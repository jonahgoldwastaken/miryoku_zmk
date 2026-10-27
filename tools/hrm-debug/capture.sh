#!/usr/bin/env bash
# Record the ZMK USB debug log of the TOTEM left half to tools/hrm-debug/logs/.
# Usage: tools/hrm-debug/capture.sh [/dev/cu.usbmodemXXXX]
#
# The debug firmware exposes two USB serial ports (the XIAO board's own one and
# the logging one), so by default this listens on every /dev/cu.usbmodem* port
# and records the one that sends ZMK log lines.
#
# WARNING: while this runs, every key press is recorded. Do not type passwords.
# Logs are git-ignored and stay on your machine unless you share them.
set -euo pipefail
exec python3 - "$(cd "$(dirname "$0")" && pwd)/logs" "$@" <<'PY'
import glob, os, select, signal, sys, time, tty

signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))

outdir = sys.argv[1]
ports = sys.argv[2:] or sorted(glob.glob('/dev/cu.usbmodem*'))
if not ports:
    sys.exit('No /dev/cu.usbmodem* device found. Plug the LEFT half (debug firmware) '
             'into this Mac via USB and try again.')

fds = {}
for p in ports:
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        tty.setraw(fd)
        fds[fd] = p
    except OSError as e:
        print(f'skipping {p}: {e}', file=sys.stderr)
if not fds:
    sys.exit('Could not open any USB serial port.')

os.makedirs(outdir, exist_ok=True)
out_path = os.path.join(outdir, time.strftime('session-%Y%m%d-%H%M%S.log'))
print(f'Listening on {", ".join(fds.values())}')
print('WARNING: every key press is recorded. Do not type passwords.')
print('Type normally; correct mistakes the way you always do. Ctrl-C to stop.')
print('Press any key on the keyboard to start the log stream...\n')

source = None          # fd that sends ZMK logs
buf = {fd: b'' for fd in fds}
out = None
decisions = keys = drops = 0
last_status = 0.0
try:
    while True:
        r, _, _ = select.select(list(fds), [], [], 1.0)
        for fd in r:
            try:
                chunk = os.read(fd, 65536)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                sys.exit(f'\n{fds[fd]} disconnected.')
            if not chunk:
                continue
            if source is None:
                buf[fd] += chunk
                if b'<dbg> zmk:' in buf[fd] or b'<inf> zmk:' in buf[fd]:
                    source = fd
                    out = open(out_path, 'wb')
                    out.write(buf[fd])
                    print(f'Recording ZMK log from {fds[fd]} -> {out_path}')
                continue
            if fd != source:
                continue
            out.write(chunk)
            out.flush()
            decisions += chunk.count(b' decided ')
            keys += chunk.count(b'Row: ') + chunk.count(b'Trigger key position')
            drops += chunk.count(b'dropped')
        now = time.time()
        if source is not None and now - last_status > 0.5:
            last_status = now
            print(f'\rkey events: {keys}  hold-tap decisions: {decisions}  drop warnings: {drops}  ',
                  end='', flush=True)
except KeyboardInterrupt:
    pass
finally:
    if out:
        out.close()
        print(f'\nSaved {out_path} ({decisions} hold-tap decisions, {drops} drop warnings)')
    else:
        print('\nNo ZMK log lines received; nothing saved. Is the debug firmware flashed on the LEFT half?')
PY
