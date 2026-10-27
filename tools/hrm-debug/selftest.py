#!/usr/bin/env python3
"""Self-test for hrmlab: writes a synthetic ZMK debug log (same format as the
real firmware, including right-half state dumps), containing typing plus
"wanted Shift, got a letter -> backspace -> retry" mistakes, then checks that
hrmlab parses it, reproduces the decisions, detects and explains the mistakes,
and that tuning finds settings that fix them.

Usage: python3 tools/hrm-debug/selftest.py
"""
import math
import os
import random
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hrmlab  # noqa: E402
import copy  # noqa: E402

# Fixed settings for the synthetic firmware, independent of the real CURRENT
# values, so the test always has mistakes to find.
TEST = {
    'mt':       dict(flavor='balanced', term=220, qt=175, idle=125, on_release=True, positional=True),
    'mt_shift': dict(flavor='balanced', term=220, qt=175, idle=75, on_release=True, positional=True),
    'lt':       dict(flavor='tap-preferred', term=200, qt=175, idle=150, on_release=False, positional=False),
    'lt_fast':  dict(flavor='balanced', term=200, qt=0, idle=0, on_release=False, positional=False),
}

P = dict(zip('qwfpbjluy', range(9)))
P.update(dict(zip('arstgmneio', range(10, 20))))
P.update({'z': 21, 'x': 22, 'c': 23, 'd': 24, 'v': 25, 'k': 26, 'h': 27, ',': 28, '.': 29, ' ': 33})
WORDS = 'the of and to in is you that it was for on are as with they at be this have from or one had by word'.split()


def lognorm(mean, sd, rng):
    s2 = math.log(1 + (sd / mean) ** 2)
    return rng.lognormvariate(math.log(mean) - s2 / 2, s2 ** 0.5)


def tap(events, pos, t, hold):
    events += [(t, pos, True), (t + hold, pos, False)]


def make_session(rng, n_sentences=60):
    ev, t = [], 1000.0
    expected_mistakes = 0
    for _ in range(n_sentences):
        for w in [rng.choice(WORDS) for _ in range(6)]:
            for ch in w + ' ':
                tap(ev, P[ch], t, max(40, lognorm(110 if ch == ' ' else 95, 25, rng)))
                t += max(60, lognorm(130, 40, rng))
        tap(ev, P['.'], t, 90); t += 120
        tap(ev, P[' '], t, 100)
        # capital after ". ": Shift(N) + t, pressed soon after the space
        gap = rng.uniform(40, 140)
        t += gap
        if gap < TEST['mt_shift']['idle']:
            expected_mistakes += 1
            ev += [(t, 16, True), (t + 60, 13, True), (t + 120, 13, False), (t + 150, 16, False)]  # -> "nt"
            t += 450
            tap(ev, 36, t, 80); t += 220
            tap(ev, 36, t, 80); t += 600                                                      # backspace x2
            ev += [(t, 16, True), (t + 70, 13, True), (t + 130, 13, False), (t + 200, 16, False)]  # retry -> "T"
        else:
            ev += [(t, 16, True), (t + 60, 13, True), (t + 120, 13, False), (t + 160, 16, False)]
        t += 300
    ev = sorted(((float(int(t)), p, d) for t, p, d in ev), key=lambda e: e[0])
    return ev, expected_mistakes


def ts_str(ms):
    s, ms_ = divmod(ms, 1000)
    us = int((ms_ - int(ms_)) * 1000)
    h, s = divmod(int(s), 3600)
    m, s = divmod(s, 60)
    return f'[{h:02d}:{m:02d}:{s:02d}.{int(ms_):03d},{us:03d}]'


def write_log(path, events):
    dec = hrmlab.Engine(TEST).run(events)
    lines = []
    state = [0] * 6
    for t, pos, down in events:
        if pos in hrmlab.RIGHT or pos in hrmlab.THUMBS_R:
            byte, bit = divmod(pos, 8)
            state[byte] = state[byte] | (1 << bit) if down else state[byte] & ~(1 << bit)
            hexs = ' '.join(f'{b:02x}' for b in state)
            lines.append((t, f'{ts_str(t)} <dbg> zmk: split_central_notify_func: [NOTIFICATION] data 0x20003a10 length 6'))
            lines.append((t, f'\x1b[1;34m{ts_str(t)} <dbg> zmk: split_central_notify_func: data\x1b[0m\n'
                             f'                                   {hexs}{" " * 33}|......'))
        else:
            lines.append((t, f'{ts_str(t)} <dbg> zmk: zmk_physical_layouts_kscan_process_msgq: '
                             f'Row: 1, col: 3, position: {pos}, pressed: {"true" if down else "false"}'))
    for (pos, t), d in dec.items():
        cls = hrmlab.HOLDTAPS[pos][0]
        lines.append((t + 0.5, f'{ts_str(t + 0.5)} <dbg> zmk: decide_hold_tap: {pos} decided {d["status"]} '
                               f'({TEST[cls]["flavor"]} decision moment {d["moment"]})'))
    lines.sort(key=lambda x: x[0])
    with open(path, 'w') as f:
        for _, l in lines:
            f.write(l + '\n')


def main():
    rng = random.Random(4)
    events, expected = make_session(rng)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'session-test.log')
        write_log(path, events)
        sess = hrmlab.parse_log(path)
        assert sorted(sess.events) == sorted(events), 'parser did not reconstruct the key events'
        attempts, order = hrmlab.build_attempts(sess)
        hrmlab.label(attempts, order)
        agree, n, _ = hrmlab.validate(sess, attempts, TEST)
        assert agree == n and n > 0, f'replay mismatch {agree}/{n}'
        found = [a for a in attempts if a.label == 'missed-hold' and a.strength == 'strong']
        assert expected > 0 and len(found) == expected, f'expected {expected} missed holds, found {len(found)}'
        assert all(a.fw_moment == 'quick-tap' for a in found)
        false = [a for a in attempts if a.label == 'false-hold']
        assert not false, f'unexpected false holds {len(false)}'
        better = copy.deepcopy(TEST)
        better['mt_shift']['idle'] = 0
        r = hrmlab.evaluate([sess], [(attempts, order)], better, False)
        assert r['fixed'] == expected, r
        print(f'ok: {len(events)} events parsed, replay agrees {agree}/{n}, '
              f'{len(found)}/{expected} missed Shift holds found (cause: quick-tap), '
              f'mt_shift idle=0 fixes {r["fixed"]} and changes {r["broken"]} other decisions')
        if '-v' in sys.argv:
            subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), 'hrmlab.py'), 'report', path, '--show', '3'])
            subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), 'hrmlab.py'), 'tune', path, '--top', '3'])


if __name__ == '__main__':
    main()
