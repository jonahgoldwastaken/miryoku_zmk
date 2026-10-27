#!/usr/bin/env python3
"""Realistic-usage test bench for hold-tap settings.

Simulates the things you actually do (capitals, camelCase, vim normal-mode
capitals, Cmd/Ctrl/Alt shortcuts, stacked mods, layer chords, mods + layers)
in realistic contexts (right after a letter / Space / Enter / Esc / a pause,
with the previous key possibly still held), using timing measured from your
recordings. Also estimates accidental mods/layers while typing, both on the
recorded logs and on synthetic typing generated from your measured timing.

Usage:
  python3 tools/hrm-debug/scenarios.py                 # current settings
  python3 tools/hrm-debug/scenarios.py --compare       # current vs candidates
"""
import argparse
import copy
import glob
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hrmlab  # noqa: E402

# Colemak-DH positions (TOTEM)
K = dict(zip('qwfpbjluy', range(9)))
K.update(dict(zip('arstgmneio', range(10, 20))))
K.update({'z': 21, 'x': 22, 'c': 23, 'd': 24, 'v': 25, 'k': 26, 'h': 27, ',': 28, '.': 29, '/': 30})
ESC, SPC, TAB, RET, BSPC, DEL = 32, 33, 34, 35, 36, 37
A, R, S, T, N, E, I, O = (K[c] for c in 'arstneio')
LEFT_PLAIN = [K[c] for c in 'wfpbgcdv']
RIGHT_PLAIN = [K[c] for c in 'jluymkh,']

# Timing measured from recordings (ms); see `hrmlab.py report`.
LETTER_HOLD = (75, 15, 45, 128)     # median, sd, min, max
THUMB_HOLD = (85, 18, 50, 149)
GAP = (132, 60, 30, 600)            # press-to-press while typing


def clamp_norm(rng, med, sd, lo, hi):
    return min(hi, max(lo, rng.gauss(med, sd)))


def letter_hold(rng):
    return clamp_norm(rng, *LETTER_HOLD)


def thumb_hold(rng):
    return clamp_norm(rng, *THUMB_HOLD)


# Contexts: what happened right before the action. (prev key, gap range from its press)
CONTEXTS = {
    'after letter (same hand as first key)': ('same', (45, 200)),
    'after letter (other hand)':             ('other', (45, 200)),
    'after Space (rolling)':                 (SPC, (30, 160)),
    'after Enter':                           (RET, (60, 300)),
    'after Esc':                             (ESC, (60, 300)),
    'after a pause':                         ('other', (400, 1200)),
}


def prefix(rng, ctx, first_key):
    """Events before the action; the previous key may still be held (overlap)."""
    kind, (g0, g1) = CONTEXTS[ctx]
    gap = rng.uniform(g0, g1)
    if kind == 'same':
        prev = rng.choice(LEFT_PLAIN if first_key in hrmlab.LEFT + hrmlab.THUMBS_L else RIGHT_PLAIN)
    elif kind == 'other':
        prev = rng.choice(RIGHT_PLAIN if first_key in hrmlab.LEFT + hrmlab.THUMBS_L else LEFT_PLAIN)
    else:
        prev = kind
    hold = thumb_hold(rng) if prev in hrmlab.THUMBS else letter_hold(rng)
    t0 = -gap
    # an earlier key well before, so idle windows see realistic history
    ev = [(t0 - 400, K['g'], True), (t0 - 330, K['g'], False), (t0, prev, True), (t0 + hold, prev, False)]
    return ev, [(prev, t0)]


# Hold durations when you mean a mod / layer (from recordings: mods >= 175 ms,
# median ~230; thumbs >= 224 ms, median ~300). Sampled slightly wider than seen.
MOD_HOLD = (230, 60, 140, 700)
THUMB_LAYER_HOLD = (300, 70, 180, 800)


def chord(rng, holders, final, final_is_layer_key=False, thumb_holders=()):
    """holders pressed in order (first at t=0), then `final` tapped; each holder
    is held for a duration drawn from your measured hold times (but never
    released before the final key is pressed)."""
    ev, t = [], 0.0
    starts = []
    for h in holders:
        starts.append((h, t))
        t += rng.uniform(30, 120)
    d = t + rng.uniform(20, 90)
    fh = letter_hold(rng)
    ev += [(d, final, True), (d + fh, final, False)]
    for h, s in starts:
        total = clamp_norm(rng, *(THUMB_LAYER_HOLD if h in hrmlab.THUMBS else MOD_HOLD))
        ev += [(s, h, True), (max(s + total, d + 5), h, False)]
    return ev, starts, (final, d)


def mk(name, holders, final, want, contexts=None, note=''):
    return dict(name=name, holders=holders, final=final, want=want,
                contexts=contexts or list(CONTEXTS), note=note)


# want: list of (key, 'hold'|'tap'|'layer') checks.
#  'hold' -> that hold-tap must resolve as hold
#  'tap'  -> that hold-tap must resolve as tap (or not be a hold-tap at all)
#  'layer'-> key must be pressed while a layer is active (it is then a plain key)
ACTIONS = [
    # --- Shift (opposite hand)
    mk('Capital, left letter: Shift(N)+w', [N], K['w'], [(N, 'hold')]),
    mk('Capital, right letter: Shift(T)+h', [T], K['h'], [(T, 'hold')]),
    mk('Capital on a mod key: Shift(T)+o (vim O)', [T], O, [(T, 'hold'), (O, 'tap')]),
    mk('Capital on a mod key: Shift(N)+a (vim A)', [N], A, [(N, 'hold'), (A, 'tap')]),
    mk('Capital same hand: Shift(T)+s', [T], S, [(T, 'hold'), (S, 'tap')], note='same hand'),
    # --- Cmd
    mk('Cmd(O)+s/c/v (save/copy/paste, opposite hand)', [O], K['c'], [(O, 'hold')]),
    mk('Cmd(A)+l (opposite hand)', [A], K['l'], [(A, 'hold')]),
    mk('Cmd(A)+c (same hand)', [A], K['c'], [(A, 'hold')], note='same hand'),
    mk('Cmd(A)+Tab', [A], TAB, [(A, 'hold'), (TAB, 'tap')]),
    mk('Cmd(A)+Space', [A], SPC, [(A, 'hold'), (SPC, 'tap')]),
    mk('Cmd(O)+Enter', [O], RET, [(O, 'hold'), (RET, 'tap')]),
    mk('Cmd(A)+Bspc', [A], BSPC, [(A, 'hold'), (BSPC, 'tap')]),
    # --- Ctrl (terminal / vim)
    mk('Ctrl(E)+c/d/w (terminal, vim)', [E], K['d'], [(E, 'hold')]),
    mk('Ctrl(S)+u/l (vim scroll, opposite hand)', [S], K['u'], [(S, 'hold')]),
    mk('Ctrl(E)+r (vim redo; r is a mod key)', [E], R, [(E, 'hold'), (R, 'tap')]),
    # --- Alt / Shift with thumbs
    mk('Alt(R)+Bspc (delete word)', [R], BSPC, [(R, 'hold'), (BSPC, 'tap')]),
    mk('Alt(I)+Bspc (delete word)', [I], BSPC, [(I, 'hold'), (BSPC, 'tap')]),
    mk('Shift(T)+Enter', [T], RET, [(T, 'hold'), (RET, 'tap')]),
    mk('Shift(N)+Tab', [N], TAB, [(N, 'hold'), (TAB, 'tap')]),
    # --- stacked mods
    mk('Cmd(O)+Shift(N)+t (same-hand stack)', [O, N], T, [(O, 'hold'), (N, 'hold'), (T, 'tap')]),
    mk('Cmd(A)+Shift(T)+k (same-hand stack)', [A, T], K['k'], [(A, 'hold'), (T, 'hold')]),
    # --- layers
    mk('Sym: Enter-hold + ":"/"("', [RET], A, [(RET, 'hold'), (A, 'layer')]),
    mk('Num: Bspc-hold + digit', [BSPC], R, [(BSPC, 'hold'), (R, 'layer')]),
    mk('Nav: Space-hold + arrow', [SPC], K['m'], [(SPC, 'hold'), (K['m'], 'layer')]),
    mk('Mouse: Tab-hold + key', [TAB], K['m'], [(TAB, 'hold'), (K['m'], 'layer')]),
    # --- mods + layers
    mk('Shift(T)+Nav arrow (select)', [T, SPC], K['m'], [(T, 'hold'), (SPC, 'hold'), (K['m'], 'layer')]),
    mk('Alt(R)+Nav arrow (word jump)', [R, SPC], K['n'] if False else K['m'], [(R, 'hold'), (SPC, 'hold'), (K['m'], 'layer')]),
    mk('Cmd(A)+Num digit (tab switch)', [A, BSPC], R, [(A, 'hold'), (BSPC, 'hold'), (R, 'layer')]),
    mk('Num first, then Cmd (Miryoku way)', [BSPC, O], R, [(BSPC, 'hold'), (R, 'layer')]),
]


def run_action(settings, act, ctx, rng):
    pre, _ = prefix(rng, ctx, act['holders'][0])
    ev, starts, (fin, fin_t) = chord(rng, act['holders'], act['final'])
    events = sorted(pre + ev, key=lambda e: (e[0], not e[2]))
    eng = hrmlab.Engine(settings)
    # record whether a layer was active at the moment each key's binding is
    # looked up (after any due hold-tap timers, as in ZMK)
    pressed_on_layer = {}
    orig_binding = eng.binding
    cur = {}

    def binding(pos):
        pressed_on_layer[(pos, cur.get('ts'))] = bool(eng.layers)
        return orig_binding(pos)
    orig_pos_event = eng.pos_event

    def pos_event(pos, down, ts):
        cur['ts'] = ts
        return orig_pos_event(pos, down, ts)
    eng.binding = binding
    eng.pos_event = pos_event
    dec = eng.run(events)
    times = dict((h, s) for h, s in starts)
    times[fin] = fin_t
    for key, want in act['want']:
        t = times[key]
        if want == 'layer':
            if not pressed_on_layer.get((key, t)):
                return False
            continue
        d = dec.get((key, t))
        if want == 'hold' and (d is None or d['status'] == 'tap'):
            return False
        if want == 'tap' and d is not None and d['status'] != 'tap':
            return False
    return True


def typing_misfires(settings, n_keys=20000, seed=3):
    """Synthetic typing with your measured holds/gaps (independent sampling,
    so it produces MORE nested rolls than you actually type: conservative)."""
    rng = random.Random(seed)
    letters = 'etaoinsrhldcumfpgwybvk'
    weights = [12.7, 9.1, 8.2, 7.5, 7.0, 6.7, 6.3, 6.0, 6.1, 4.0, 4.3, 2.8, 2.8, 2.4, 2.2, 1.9, 2.0, 2.4, 2.0, 1.5, 1.0, 0.8]
    t, ev, busy = 0.0, [], {}
    for i in range(n_keys):
        c = ' ' if rng.random() < 0.18 else rng.choices(letters, weights)[0]
        p = SPC if c == ' ' else K[c]
        t += clamp_norm(rng, *GAP)
        if busy.get(p, -1) >= t:
            t = busy[p] + 10
        h = thumb_hold(rng) if p == SPC else letter_hold(rng)
        ev += [(t, p, True), (t + h, p, False)]
        busy[p] = t + h
    dec = hrmlab.Engine(settings).run(sorted(ev, key=lambda e: e[0]))
    bad = sum(1 for d in dec.values() if d['status'] != 'tap')
    return 1000 * bad / n_keys


def recorded_misfires(settings):
    logs = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', '*.log')))
    sessions = [hrmlab.parse_log(p) for p in logs]
    data = []
    for s in sessions:
        at, o = hrmlab.build_attempts(s)
        hrmlab.label(at, o)
        data.append((at, o))
    r = hrmlab.evaluate(sessions, data, settings, False)
    return r


def score(settings, n=200, seed=1, verbose=True):
    rng = random.Random(seed)
    results = {}
    for act in ACTIONS:
        row = {}
        for ctx in act['contexts']:
            ok = sum(run_action(settings, act, ctx, rng) for _ in range(n))
            row[ctx] = 100 * ok / n
        results[act['name']] = row
    if verbose:
        ctxs = list(CONTEXTS)
        short = ['same-hand ltr', 'other-hand ltr', 'after Space', 'after Enter', 'after Esc', 'after pause']
        print(f'{"action":48s}' + ''.join(f'{s:>15s}' for s in short))
        for name, row in results.items():
            print(f'{name:48s}' + ''.join(f'{row.get(c, float("nan")):14.0f}%' for c in ctxs))
    allv = [v for row in results.values() for v in row.values()]
    return sum(allv) / len(allv), min(allv), results


# Previous firmware (balanced + idle windows + positional), for comparison.
CANDIDATE = {
    'mt':       dict(flavor='balanced', term=220, qt=175, idle=125, on_release=True, positional=True),
    'mt_shift': dict(flavor='balanced', term=150, qt=175, idle=0, on_release=True, positional=True),
    'lt':       dict(flavor='tap-preferred', term=200, qt=175, idle=150, on_release=False, positional=False),
    'lt_fast':  dict(flavor='balanced', term=200, qt=0, idle=0, on_release=False, positional=False),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--compare', action='store_true')
    args = ap.parse_args()
    configs = {'current': hrmlab.CURRENT}
    if args.compare:
        configs['previous firmware'] = CANDIDATE
    for name, st in configs.items():
        print(f'\n===== {name}')
        avg, worst, _ = score(st)
        rec = recorded_misfires(st)
        print(f'average success {avg:.1f}%, worst cell {worst:.0f}%')
        print(f'typing: accidental mods/layers per 1000 keys (synthetic, conservative): {typing_misfires(st):.2f}')
        print(f'recorded logs: {rec["broken"]} decisions that were fine would change, '
              f'{rec["fixed"]}/{rec["labeled"]} detected mistakes fixed')


if __name__ == '__main__':
    main()
