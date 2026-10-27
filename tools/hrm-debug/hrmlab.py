#!/usr/bin/env python3
"""hrmlab - learn home-row-mod / layer-tap settings from your own typing.

Reads ZMK USB debug logs recorded with capture.sh (debug firmware from
.github/workflows/totem-jonah-debug.yml) and:

  report  - finds hold-tap mistakes from how you corrected them, explains why
            the firmware decided the way it did, and checks that the replay
            engine reproduces the firmware's decisions.
  tune    - replays your real key timings under alternative settings and ranks
            them by mistakes fixed vs. new mistakes introduced.

Mistake detection (no manual labelling needed):
  missed hold : a hold-tap pressed together with key Q resolved as a tap, and
                within a few seconds you pressed the same hold-tap + Q again
                and it resolved as a hold (e.g. wanted Shift+T, got "nt", fixed
                it, tried again). Marked "strong" when a correction (Backspace,
                Delete, Esc / vim edit) happened in between.
  false hold  : a hold-tap resolved as a hold with key Q, then after a
                correction you typed the same two keys again as plain letters.

The replay engine is a port of ZMK app/src/behaviors/behavior_hold_tap.c (main).
Layout constants below describe the TOTEM + Miryoku setup in this repo; keep
CURRENT in sync with miryoku/miryoku_behaviors.dtsi.
"""
import argparse
import collections
import itertools
import math
import re
import sys
from dataclasses import dataclass, field

# ----------------------------------------------------------------------------
# Layout (TOTEM, Miryoku). Positions: 0-9 top row, 10-19 home row,
# 20-31 bottom row (20/31 are the outer pinky keys), 32-37 thumbs.
LEFT = [0, 1, 2, 3, 4, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 25]
RIGHT = [5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 26, 27, 28, 29, 30, 31]
THUMBS_L = [32, 33, 34]
THUMBS_R = [35, 36, 37]
THUMBS = THUMBS_L + THUMBS_R

# Base-layer hold-taps: position -> (behavior class, hand)
HOLDTAPS = {
    10: ('mt', 'L'), 11: ('mt', 'L'), 12: ('mt', 'L'), 13: ('mt_shift', 'L'), 22: ('mt', 'L'),
    16: ('mt_shift', 'R'), 17: ('mt', 'R'), 18: ('mt', 'R'), 19: ('mt', 'R'), 29: ('mt', 'R'),
    21: ('lt', 'L'), 30: ('lt', 'R'),
    32: ('lt', 'L'), 33: ('lt', 'L'), 34: ('lt', 'L'),
    35: ('lt_fast', 'R'), 36: ('lt_fast', 'R'), 37: ('lt_fast', 'R'),
}
# Human readable names (Colemak-DH base / Miryoku thumbs).
NAMES = {
    0: 'q', 1: 'w', 2: 'f', 3: 'p', 4: 'b', 5: 'j', 6: 'l', 7: 'u', 8: 'y', 9: "'",
    10: 'a/Cmd', 11: 'r/Alt', 12: 's/Ctrl', 13: 't/Shift', 14: 'g', 15: 'm',
    16: 'n/Shift', 17: 'e/Ctrl', 18: 'i/Alt', 19: 'o/Cmd',
    20: 'q(outer)', 21: 'z/Button', 22: 'x/AltGr', 23: 'c', 24: 'd', 25: 'v',
    26: 'k', 27: 'h', 28: ',', 29: './AltGr', 30: '//Button', 31: "'(outer)",
    32: 'Esc/Media', 33: 'Space/Nav', 34: 'Tab/Mouse', 35: 'Enter/Sym', 36: 'Bspc/Num', 37: 'Del/Fun',
}
CORRECTION_KEYS = {36, 37, 32}  # Backspace, Delete, Esc (vim edits start with Esc)

# Current firmware settings (miryoku/miryoku_behaviors.dtsi).
CURRENT = {
    'mt':       dict(flavor='tap-preferred', term=150, qt=175, idle=0, on_release=False, positional=False),
    'mt_shift': dict(flavor='tap-preferred', term=150, qt=175, idle=0, on_release=False, positional=False),
    'lt':       dict(flavor='tap-preferred', term=180, qt=0, idle=0, on_release=False, positional=False),
    'lt_fast':  dict(flavor='tap-preferred', term=180, qt=0, idle=0, on_release=False, positional=False),
}


def trigger_positions(cls, hand, cfg):
    if not cfg.get('positional'):
        return []
    if cls in ('mt', 'mt_shift'):
        return (RIGHT if hand == 'L' else LEFT) + THUMBS
    return []


def layer_mod_positions(layer_pos):
    """Positions that are plain modifiers while a layer key is held."""
    if layer_pos in THUMBS_L:
        return {10, 11, 12, 13}
    if layer_pos in THUMBS_R:
        return {16, 17, 18, 19}
    return {10, 11, 12, 13, 16, 17, 18, 19}


# ----------------------------------------------------------------------------
# Log parsing
ANSI = re.compile(r'\x1b\[[0-9;]*m')
TS = re.compile(r'\[(\d+):(\d+):(\d+)\.(\d+),(\d+)\]')
RE_LOCAL = re.compile(r'Row: \d+, col: \d+, position: (\d+), pressed: (true|false)')
RE_NOTIFY_DATA = re.compile(r'split_central_notify_func: data\s*$')
RE_HEX = re.compile(r'^\s+((?:[0-9a-f]{2}\s+){1,16})\s*\|')
RE_DECIDED = re.compile(r'(\d+) decided (tap|hold-timer|hold-interrupt) \((\S+) decision moment (\S+)\)')
RE_DROPPED = re.compile(r'messages? dropped')


@dataclass
class Session:
    name: str
    events: list = field(default_factory=list)      # (ts, pos, pressed)
    decisions: list = field(default_factory=list)   # (ts_logged, pos, status, flavor, moment)
    dropped: list = field(default_factory=list)     # ts of drop warnings


def parse_ts(line):
    m = TS.search(line)
    if not m:
        return None
    h, mi, s, ms, us = map(int, m.groups())
    # hold-tap compares k_uptime_get() milliseconds, so drop the microseconds
    return float(((h * 60 + mi) * 60 + s) * 1000 + ms)


def parse_log(path):
    sess = Session(path)
    peripheral_state = None
    pending_hex_ts = None
    hex_bytes = []
    last_ts = 0.0

    def flush_hex():
        nonlocal peripheral_state, hex_bytes, pending_hex_ts
        if pending_hex_ts is None:
            return
        state = hex_bytes
        if peripheral_state is None:
            peripheral_state = [0] * len(state)
            # first notification: everything set is a press
        for i, byte in enumerate(state):
            old = peripheral_state[i] if i < len(peripheral_state) else 0
            changed = byte ^ old
            for bit in range(8):
                if changed & (1 << bit):
                    sess.events.append((pending_hex_ts, i * 8 + bit, bool(byte & (1 << bit))))
        peripheral_state = state
        pending_hex_ts = None
        hex_bytes = []

    with open(path, errors='replace') as f:
        for raw in f:
            line = ANSI.sub('', raw.rstrip('\r\n'))
            if pending_hex_ts is not None:
                m = RE_HEX.match(line)
                if m:
                    hex_bytes += [int(x, 16) for x in m.group(1).split()]
                    continue
                flush_hex()
            ts = parse_ts(line)
            if ts is not None:
                if ts + 1000 < last_ts:  # keyboard rebooted: timestamps restart
                    sess.dropped.append(last_ts)
                    peripheral_state = None
                last_ts = ts
            if RE_DROPPED.search(line):
                sess.dropped.append(last_ts)
                continue
            m = RE_LOCAL.search(line)
            if m and ts is not None:
                sess.events.append((ts, int(m.group(1)), m.group(2) == 'true'))
                continue
            if RE_NOTIFY_DATA.search(line) and ts is not None:
                pending_hex_ts = ts
                hex_bytes = []
                continue
            m = RE_DECIDED.search(line)
            if m and ts is not None:
                sess.decisions.append((ts, int(m.group(1)), m.group(2), m.group(3), m.group(4)))
    flush_hex()
    sess.events.sort(key=lambda e: e[0])
    return sess


# ----------------------------------------------------------------------------
# Replay engine (port of ZMK behavior_hold_tap.c)
class Engine:
    def __init__(self, settings):
        self.settings = settings
        self.layers = []                 # stack of layer-key positions currently held as layers
        self.held = {}                   # pos -> binding pressed ('ht', ht) / ('kp', is_mod)
        self.last = dict(pos=None, ts=-1e12)
        self.und = None
        self.cap = []
        self.decisions = {}              # (pos, press_ts) -> dict(status, moment)

    def binding(self, pos):
        if self.layers:
            lp = self.layers[-1]
            return ('kp', pos in layer_mod_positions(lp))
        if pos in HOLDTAPS:
            cls, hand = HOLDTAPS[pos]
            cfg = self.settings[cls]
            return ('ht', dict(cfg, cls=cls, trig=trigger_positions(cls, hand, cfg),
                              is_layer=cls.startswith('lt')))
        return ('kp', False)

    def store_last(self, ts):
        if ts > self.last['ts']:
            self.last = dict(pos=None, ts=ts)

    def decide(self, ht, moment):
        if ht['status'] != 'U' or ht is not self.und:
            return
        f = ht['cfg']['flavor']
        table = {
            'balanced': {'key-up': 'tap', 'other-key-up': 'hold-interrupt', 'timer': 'hold-timer', 'quick-tap': 'tap'},
            'tap-preferred': {'key-up': 'tap', 'timer': 'hold-timer', 'quick-tap': 'tap'},
            'hold-preferred': {'key-up': 'tap', 'other-key-down': 'hold-interrupt', 'timer': 'hold-timer', 'quick-tap': 'tap'},
            'tap-unless-interrupted': {'key-up': 'tap', 'other-key-down': 'hold-interrupt', 'timer': 'tap', 'quick-tap': 'tap'},
        }[f]
        st = table.get(moment)
        if st is None:
            return
        trig = ht['cfg']['trig']
        if trig and ht['first'] is not None and ht['first'] not in trig:
            st = 'tap'
        ht['status'] = st
        self.und = None
        self.decisions[(ht['pos'], ht['ts'])] = dict(status=st, moment=moment)
        if st == 'tap':
            # store_last_hold_tapped(): unconditional
            self.last = dict(pos=ht['pos'], ts=ht['ts'])
        elif ht['cfg']['is_layer']:
            self.layers.append(ht['pos'])
        caps, self.cap = self.cap, []
        for e in caps:
            self.pos_event(*e)

    def ht_press(self, pos, cfg, ts):
        ht = dict(pos=pos, cfg=cfg, ts=ts, status='U', first=None)
        self.held[pos] = ('ht', ht)
        self.und = ht
        if (self.last['ts'] + cfg['idle'] > ts) or (self.last['pos'] == pos and self.last['ts'] + cfg['qt'] > ts):
            self.decide(ht, 'quick-tap')
        return ht

    def ht_release(self, ht, ts):
        if ts > ht['ts'] + ht['cfg']['term']:
            self.decide(ht, 'timer')
        self.decide(ht, 'key-up')
        if ht['status'] != 'tap' and ht['cfg']['is_layer'] and ht['pos'] in self.layers:
            self.layers.remove(ht['pos'])

    def pos_event(self, pos, down, ts):
        u = self.und
        if u is not None:
            if u['cfg']['on_release'] != down and u['first'] is None:
                u['first'] = pos
            if not (u['pos'] == pos and not down):
                if ts > u['ts'] + u['cfg']['term']:
                    self.decide(u, 'timer')
                u = self.und
                if u is not None:
                    if down or any(c[0] == pos and c[1] for c in self.cap):
                        self.cap.append((pos, down, ts))
                        self.decide(u, 'other-key-down' if down else 'other-key-up')
                        return
        if down:
            if pos in self.held:
                return  # duplicate press (log glitch)
            kind, data = self.binding(pos)
            if kind == 'ht':
                self.ht_press(pos, data, ts)
            else:
                self.held[pos] = ('kp', data)
                if not data:
                    self.store_last(ts)
        else:
            b = self.held.pop(pos, None)
            if b and b[0] == 'ht':
                self.ht_release(b[1], ts)

    def run(self, events):
        for ts, pos, down in events:
            u = self.und
            if u and ts >= u['ts'] + u['cfg']['term']:
                self.decide(u, 'timer')
            self.pos_event(pos, down, ts)
        if self.und:
            self.decide(self.und, 'timer')
        return self.decisions


def segments(sess):
    """Split the event stream at log drops / reboots: replay is only valid on gap-free stretches."""
    cuts = sorted(sess.dropped)
    segs, cur, ci = [], [], 0
    for e in sess.events:
        while ci < len(cuts) and e[0] > cuts[ci]:
            if cur:
                segs.append(cur)
            cur, ci = [], ci + 1
        cur.append(e)
    if cur:
        segs.append(cur)
    return segs


def replay(sess, settings):
    out = {}
    for seg in segments(sess):
        out.update(Engine(settings).run(seg))
    return out


# ----------------------------------------------------------------------------
# Attempts and labels
@dataclass
class Attempt:
    pos: int
    t_press: float
    t_release: float
    partner: int          # first other key pressed while held (or None)
    partner_release: float
    prev_gap: float       # ms since previous key press
    fw_status: str        # firmware decision
    fw_moment: str
    label: str = ''       # '', 'missed-hold', 'false-hold'
    strength: str = ''
    retry_idx: int = -1


def build_attempts(sess):
    """Pair each firmware decision with the physical press it belongs to."""
    presses = collections.defaultdict(list)   # pos -> [(t_press, t_release)]
    open_ = {}
    order = []
    for ts, pos, down in sess.events:
        if down:
            open_[pos] = ts
            order.append((ts, pos))
        elif pos in open_:
            presses[pos].append((open_.pop(pos), ts))
    rel = {(p, a): b for p, lst in presses.items() for a, b in lst}
    press_times = [t for t, _ in order]

    attempts = []
    used = set()
    for dts, pos, status, flavor, moment in sess.decisions:
        if pos not in HOLDTAPS:
            continue
        # the press is the latest press of pos at or before the decision log time
        cands = [(a, b) for a, b in presses.get(pos, []) if a <= dts + 2 and (pos, a) not in used]
        if not cands:
            continue
        a, b = cands[-1]
        used.add((pos, a))
        # partner: first other key pressed after a, before release b
        partner, prel = None, None
        for t, p in order:
            if t > a and t < b and p != pos:
                partner = p
                prel = next((rb for (ra, rb) in presses.get(p, []) if ra == t), None)
                break
        i = _bisect_left(press_times, a)
        gap = a - press_times[i - 1] if i > 0 else 1e9
        attempts.append(Attempt(pos, a, b, partner, prel if prel is not None else math.nan, gap,
                                'tap' if status == 'tap' else 'hold', moment))
    attempts.sort(key=lambda x: x.t_press)
    return attempts, order


def _bisect_left(arr, x):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _bisect(arr, x):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def label(attempts, order, correction_ms=2500, correction_keys=10, retry_ms=4000, weak_retry_ms=3000):
    """Mark attempts that you visibly corrected.

    A correction (Backspace / Delete / Esc) must start within correction_ms and
    correction_keys presses after the attempt, and the retry must follow the
    correction within retry_ms. Without a correction, an immediate retry of the
    same hold-tap + key that now resolves as a hold is a "weak" missed hold.
    """
    press_times = [t for t, _ in order]
    for i, at in enumerate(attempts):
        if at.partner is None:
            continue
        k0 = _bisect(press_times, at.t_release)
        corr = None
        for t, p in order[k0:k0 + correction_keys]:
            if t - at.t_release > correction_ms:
                break
            if p in CORRECTION_KEYS:
                corr = t
                break
        for j in range(i + 1, len(attempts)):
            nx = attempts[j]
            limit = (corr + retry_ms) if corr is not None else (at.t_release + weak_retry_ms)
            if nx.t_press > limit:
                break
            if corr is not None and nx.t_press < corr:
                continue
            if at.fw_status == 'tap' and nx.pos == at.pos and nx.partner == at.partner and nx.fw_status == 'hold':
                at.label, at.strength, at.retry_idx = 'missed-hold', 'strong' if corr is not None else 'weak', j
                break
            if at.fw_status == 'hold' and corr is not None and nx.pos == at.pos and nx.fw_status == 'tap':
                k = _bisect(press_times, nx.t_press)
                if k < len(order) and order[k][1] == at.partner:
                    at.label, at.strength, at.retry_idx = 'false-hold', 'strong', j
                    break
    return attempts


CAUSE = {
    'quick-tap': 'pressed too soon after the previous key (require-prior-idle / quick-tap)',
    'key-up': 'released before the tapping term (and, for balanced, before the other key)',
    'other-key-up': 'positional rule: first key released was on the same hand',
    'other-key-down': 'positional rule',
    'timer': 'timer',
}


def explain(at):
    if at.label == 'missed-hold':
        c = CAUSE.get(at.fw_moment, at.fw_moment)
        if at.fw_moment == 'key-up' and not (at.t_release < at.partner_release):
            c = 'other key released while held, but balanced still saw key-up first (check log)'
        return c
    if at.label == 'false-hold':
        return f'resolved as hold ({at.fw_moment}) while typing'
    return ''


# ----------------------------------------------------------------------------
def intended(at, include_weak):
    if at.label and (at.strength == 'strong' or include_weak):
        return 'hold' if at.label == 'missed-hold' else 'tap'
    return at.fw_status


def evaluate(sessions, data, settings, include_weak):
    fixed = broken = still = total_labeled = 0
    per_cls = collections.Counter()
    for sess, (attempts, _) in zip(sessions, data):
        dec = replay(sess, settings)
        for at in attempts:
            d = dec.get((at.pos, at.t_press))
            if d is None:
                continue
            sim = 'tap' if d['status'] == 'tap' else 'hold'
            want = intended(at, include_weak)
            if want != at.fw_status:
                total_labeled += 1
                if sim == want:
                    fixed += 1
                else:
                    still += 1
            elif sim != want:
                broken += 1
                per_cls[HOLDTAPS[at.pos][0]] += 1
    return dict(fixed=fixed, still=still, broken=broken, labeled=total_labeled, broken_by_cls=dict(per_cls))


def validate(sess, attempts, settings=None):
    dec = replay(sess, settings or CURRENT)
    agree = n = 0
    mism = []
    for at in attempts:
        d = dec.get((at.pos, at.t_press))
        if d is None:
            continue
        n += 1
        sim = 'tap' if d['status'] == 'tap' else 'hold'
        if sim == at.fw_status:
            agree += 1
        else:
            mism.append((at, d))
    return agree, n, mism


def fmt_t(ms):
    return f'{ms / 1000:9.3f}s'


def cmd_report(args):
    sessions = [parse_log(p) for p in args.logs]
    for sess in sessions:
        attempts, order = build_attempts(sess)
        label(attempts, order)
        print(f'== {sess.name}')
        print(f'   {len(sess.events)} key events, {len(sess.decisions)} hold-tap decisions, '
              f'{len(sess.dropped)} log gaps')
        if not sess.events:
            print('   no key events found: is this a log from the debug firmware on the LEFT half?')
            continue
        agree, n, mism = validate(sess, attempts)
        print(f'   replay engine agrees with firmware on {agree}/{n} decisions'
              + ('' if n == 0 else f' ({100 * agree / n:.1f}%)'))
        for at, d in mism[:args.show]:
            print(f'     mismatch {fmt_t(at.t_press)} {NAMES.get(at.pos, at.pos)}: firmware {at.fw_status} '
                  f'({at.fw_moment}), replay {d["status"]} ({d["moment"]})')
        lab = [a for a in attempts if a.label]
        by = collections.Counter((a.label, a.strength, HOLDTAPS[a.pos][0]) for a in lab)
        print('   detected mistakes:')
        for (l, s, c), k in sorted(by.items()):
            print(f'     {l:12s} {s:6s} {c:9s} {k}')
        causes = collections.Counter((HOLDTAPS[a.pos][0], explain(a)) for a in lab if a.label == 'missed-hold')
        if causes:
            print('   why holds were missed:')
            for (c, why), k in causes.most_common():
                print(f'     {k:4d}  {c:9s} {why}')
        for a in lab[:args.show]:
            partner = NAMES.get(a.partner, a.partner)
            print(f'     {fmt_t(a.t_press)} {a.label:11s} {NAMES.get(a.pos, a.pos)} + {partner}: '
                  f'gap-before {a.prev_gap:.0f}ms, held {a.t_release - a.t_press:.0f}ms, '
                  f'partner +{(next((t for t, p in order if p == a.partner and t > a.t_press), a.t_press) - a.t_press):.0f}ms, '
                  f'released {"before" if a.t_release < a.partner_release else "after"} partner '
                  f'-> firmware {a.fw_moment}')
        # timing profile of intended holds (labelled + firmware holds with partner)
        prof = collections.defaultdict(list)
        for a in attempts:
            if intended(a, True) == 'hold' and a.partner is not None and not math.isnan(a.partner_release):
                prof[HOLDTAPS[a.pos][0]].append(a)
        if prof:
            print('   your timing when you mean a hold (median / 10th percentile):')
            for c, lst in prof.items():
                gaps = sorted(min(a.prev_gap, 5000) for a in lst)
                early = sum(a.t_release < a.partner_release for a in lst)
                print(f'     {c:9s} n={len(lst):4d}  gap before press {pct(gaps, 50):.0f}/{pct(gaps, 10):.0f}ms  '
                      f'released before other key: {100 * early / len(lst):.0f}%')


def pct(sorted_vals, p):
    if not sorted_vals:
        return float('nan')
    k = (len(sorted_vals) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


GRID = {
    'mt':       dict(flavor=['tap-preferred', 'balanced'], idle=[0, 50, 125], term=[130, 140, 150, 160, 170, 180, 200]),
    'mt_shift': dict(flavor=['tap-preferred', 'balanced'], idle=[0, 50, 75], term=[130, 140, 150, 160, 170, 180, 200]),
    'lt':       dict(flavor=['tap-preferred', 'balanced'], idle=[0, 50, 150], term=[160, 170, 180, 190, 200, 220]),
    'lt_fast':  dict(flavor=['tap-preferred', 'balanced'], idle=[0, 50], term=[160, 170, 180, 190, 200, 220]),
}


def cmd_tune(args):
    sessions = [parse_log(p) for p in args.logs]
    data = []
    for s in sessions:
        at, order = build_attempts(s)
        label(at, order)
        data.append((at, order))
    base = evaluate(sessions, data, CURRENT, args.weak)
    print(f'current settings: {base["labeled"]} detected mistakes, replay fixes {base["fixed"]} '
          f'and changes {base["broken"]} other decisions (both 0 when CURRENT matches the firmware that recorded the logs)')
    best = {k: dict(v) for k, v in CURRENT.items()}
    for cls, grid in GRID.items():
        keys = list(grid)
        r0 = evaluate(sessions, data, best, args.weak)
        base_score = r0['fixed'] - args.penalty * r0['broken']
        rows = []
        for combo in itertools.product(*(grid[k] for k in keys)):
            s = {k: dict(v) for k, v in best.items()}
            s[cls].update(dict(zip(keys, combo)))
            r = evaluate(sessions, data, s, args.weak)
            score = r['fixed'] - args.penalty * r['broken']
            n_changed = sum(best[cls].get(k) != v for k, v in zip(keys, combo))
            rows.append((score, n_changed, combo, r))
        # best score first; on ties prefer the fewest changes from the current values
        rows.sort(key=lambda x: (-x[0], x[1]))
        print(f'\n[{cls}] top settings (score = fixed - {args.penalty} x newly-wrong; current scores {base_score:.1f}):')
        for score, _, combo, r in rows[:args.top]:
            desc = ', '.join(f'{k}={v}' for k, v in zip(keys, combo))
            print(f'   {score:6.1f}  fixed {r["fixed"]:4d}/{r["labeled"]:<4d} newly-wrong {r["broken"]:4d}   {desc}')
        if rows and rows[0][0] > base_score:
            best[cls].update(dict(zip(keys, rows[0][2])))
    final = evaluate(sessions, data, best, args.weak)
    print('\nrecommended settings:')
    for cls, cfg in best.items():
        diff = {k: v for k, v in cfg.items() if CURRENT[cls].get(k) != v}
        print(f'   {cls:9s} {diff if diff else "(unchanged)"}')
    print(f'combined: fixes {final["fixed"]}/{final["labeled"]} detected mistakes, '
          f'{final["broken"]} decisions that were fine become wrong {final["broken_by_cls"]}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('report', help='find mistakes and explain them')
    r.add_argument('logs', nargs='+')
    r.add_argument('--show', type=int, default=15, help='examples to print')
    r.set_defaults(func=cmd_report)
    t = sub.add_parser('tune', help='rank alternative settings on your recorded timing')
    t.add_argument('logs', nargs='+')
    t.add_argument('--penalty', type=float, default=2.0,
                   help='cost of breaking a decision that was fine, relative to fixing a mistake (default 2)')
    t.add_argument('--weak', action='store_true', help='also count weak (no correction seen) mistakes')
    t.add_argument('--top', type=int, default=5)
    t.set_defaults(func=cmd_tune)
    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
