# hrm-debug: tune home-row mods and layer-taps on your own typing

Records what the keyboard actually sees (every key press and release with
timestamps, and every hold-tap decision) and then:

1. finds the mistakes you corrected, without manual labeling, and explains why
   the firmware decided wrong;
2. replays your real timings under other settings and recommends the ones that
   fix the most mistakes without breaking decisions that were fine.

## 1. Build and flash the debug firmware (left half only)

```sh
gh workflow run totem-jonah-debug.yml        # or: GitHub > Actions > "Jonah's Totem (debug logging)" > Run workflow
gh run download --name totem_left            # after the run finishes
```

Flash `zmk.uf2` to the **left** half only (it is the central: it receives the
right half's keys and makes every decision). The right half keeps the normal
firmware. The debug build uses the same keymap and settings as the normal build.

## 2. Record

Plug the left half into the Mac with USB and run:

```sh
tools/hrm-debug/capture.sh
```

Then work normally: prose, code, Neovim. When a mod or layer misfires, fix it
the way you always do (Backspace, or a Neovim edit) and try again. That is how
the mistakes are found. Longer is better: aim for a few hours of real use in
total, over several sessions. Ctrl-C stops a recording. Logs go to
`tools/hrm-debug/logs/`, which git ignores.

> **Privacy:** while recording, every key press is logged. Don't type passwords.
> The analysis only uses key positions and timings.

Keystrokes go over USB instead of Bluetooth while plugged in. The hold-tap logic
is the same. If the counter shows "drop warnings", the log missed lines during
a fast burst. The analysis skips those stretches.

## 3. Analyse

```sh
python3 tools/hrm-debug/hrmlab.py report tools/hrm-debug/logs/*.log
python3 tools/hrm-debug/hrmlab.py tune   tools/hrm-debug/logs/*.log
```

`report` shows:
- **replay agreement**: how often the replay engine reproduces the firmware's
  decisions. Should be about 100%; tuning is only trustworthy if it is.
- **detected mistakes**: `missed-hold` (wanted a mod/layer, got a letter) and
  `false-hold` (wanted a letter, got a mod/layer), per behavior class.
- **why holds were missed**, taken from the firmware's own decision log:
  - `quick-tap`: pressed too soon after the previous key (`require-prior-idle-ms`);
  - `key-up`: the mod was released before the other key;
  - `other-key-up`: the positional (same-hand) rule.
- **your timing** when you mean a hold: gap before the press, and how often you
  release the mod before the other key.

`tune` tries other settings per class (`mt` = Cmd/Alt/Ctrl, `mt_shift` = Shift,
`lt` = Space/Tab/Esc/pinky layers, `lt_fast` = Enter/Backspace/Delete layers)
and prints the best ones. A score counts mistakes fixed minus 2× decisions that
were fine but would become wrong; change the weight with `--penalty`. Apply the
recommendation in `miryoku/miryoku_behaviors.dtsi`, and update `CURRENT` in
`hrmlab.py` to match.

## Files

- `capture.sh`: records the USB log.
- `hrmlab.py`: parser, replay engine (port of ZMK `behavior_hold_tap.c`),
  mistake detection and tuner.
- `selftest.py`: end-to-end test on a synthetic log in the firmware's format.
  Run it after changing `hrmlab.py`.
- `../../.github/workflows/totem-jonah-debug.yml`: debug firmware build.
