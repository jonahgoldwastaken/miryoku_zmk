#!/usr/bin/env bash
# Record the ZMK USB debug log of the TOTEM left half to tools/hrm-debug/logs/.
# Usage: tools/hrm-debug/capture.sh [/dev/cu.usbmodemXXXX]
#
# WARNING: while this runs, every key press is recorded. Do not type passwords.
# Logs are git-ignored and stay on your machine unless you share them.
set -euo pipefail

dev="${1:-}"
if [ -z "$dev" ]; then
  dev="$(ls /dev/cu.usbmodem* 2>/dev/null | head -n 1 || true)"
fi
if [ -z "$dev" ] || [ ! -e "$dev" ]; then
  echo "No /dev/cu.usbmodem* device found." >&2
  echo "Plug the LEFT half (debug firmware) into this Mac via USB and try again." >&2
  exit 1
fi

outdir="$(cd "$(dirname "$0")" && pwd)/logs"
mkdir -p "$outdir"
out="$outdir/session-$(date +%Y%m%d-%H%M%S).log"

stty -f "$dev" 115200 raw -echo 2>/dev/null || true

echo "Recording $dev -> $out"
echo "WARNING: every key press is recorded. Do not type passwords."
echo "Type normally; just correct mistakes the way you always do. Ctrl-C to stop."
echo

# Show a live counter of hold-tap decisions so you can see it is working.
count=0
dropped=0
trap 'echo; echo "Saved $out ($count hold-tap decisions, $dropped drop warnings)"; exit 0' INT
while IFS= read -r line; do
  printf '%s\n' "$line" >> "$out"
  case "$line" in
    *" decided "*) count=$((count + 1)); printf '\rhold-tap decisions: %d  drop warnings: %d' "$count" "$dropped" ;;
    *"dropped"*) dropped=$((dropped + 1)); printf '\rhold-tap decisions: %d  drop warnings: %d' "$count" "$dropped" ;;
  esac
done < "$dev"
