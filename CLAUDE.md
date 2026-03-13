# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Miryoku ZMK is the [ZMK firmware](https://zmkfirmware.dev/) implementation of the [Miryoku](https://github.com/manna-harbour/miryoku/) ergonomic keyboard layout. It is a configuration repo (not application code) — there is no build system, test runner, or linter to run locally. Builds happen via GitHub Actions workflows or by setting `ZMK_CONFIG` to the `config/` directory in a local ZMK build environment.

## Build System

**Workflow builds (primary method):** Push to trigger `.github/workflows/totem-jonah.yml`, which calls the reusable `main.yml` workflow. Firmware artifacts (`.uf2`/`.bin`/`.hex`) are uploaded as GitHub Actions artifacts.

**Local builds:** Set up a ZMK build environment per [ZMK docs](https://zmk.dev/docs/development/setup), then build with `ZMK_CONFIG` pointing to the absolute path of the `config/` subdirectory.

There are no tests or lint commands to run locally.

## Architecture

### Keyboard keymap composition

Each keyboard's keymap file in `config/` follows the same 3-line pattern:
```c
#include "../miryoku/custom_config.h"    // user configuration options
#include "../miryoku/mapping/NN/name.h"  // physical layout mapping
#include "../miryoku/miryoku.dtsi"       // the Miryoku keymap itself
```

### Key directories

- **`config/`** — Per-keyboard `.keymap` files (and optional `.conf` for Kconfig). Each keymap is a thin wrapper that selects a mapping and includes the shared Miryoku keymap.
- **`miryoku/`** — Shared keymap logic:
  - `custom_config.h` — User config (`#define MIRYOKU_*` options). Empty by default; populated by CI from workflow inputs.
  - `miryoku.dtsi` / `miryoku.h` — Main keymap and macro definitions.
  - `miryoku_babel/` — Auto-generated layer data from [Miryoku Babel](https://github.com/manna-harbour/miryoku_babel). Layer alternatives, selection, and listing.
  - `mapping/` — Physical layout mappings organized by key count (`30/`, `34/`, `36/`, `38/`, etc.). Each mapping defines a `MIRYOKU_MAPPING` macro that maps the logical 3×5+3 Miryoku layout onto the physical keyboard.
  - `miryoku_kludge_*.dtsi` — Workarounds (thumb combos, top/bottom row combos, tap delay).
  - `miryoku_behaviors.dtsi`, `miryoku_shift_functions.dtsi`, `miryoku_mousekeys.dtsi` — ZMK behavior definitions.
- **`.github/workflows/`** — CI workflows. `main.yml` is the reusable build workflow. `build-example-*.yml` are example workflows. `test-*.yml` test combinations. `outboards/` contains metadata for out-of-tree keyboards.

### Configuration options

Options are `#define` macros in `custom_config.h` using the pattern `MIRYOKU_OPTION_VALUE`:
- `MIRYOKU_ALPHAS_*` — Alpha layout (default: Colemak-DH; alternatives: QWERTY, DVORAK, HALMAK, etc.)
- `MIRYOKU_NAV_*` — Nav layout (VI, INVERTEDT)
- `MIRYOKU_LAYERS_*` — Layer arrangement (FLIP)
- `MIRYOKU_CLIPBOARD_*` — Clipboard bindings (MAC, WIN)
- `MIRYOKU_MAPPING_*` — Physical mapping variant (EXTENDED_THUMBS, PINKIE_STAGGER, 2X2U)
- `MIRYOKU_EXTRA_*` / `MIRYOKU_TAP_*` — Alternative alphas for Extra/Tap layers
- `MIRYOKU_KLUDGE_*` — Workaround flags (SOFT_OFF, TAPDELAY, DOUBLETAPBOOT)

### Jonah's personal build

The `totem-jonah.yml` workflow builds for a TOTEM keyboard (38-key split) with seeeduino_xiao_ble controllers. Current config: Colemak-DH alphas, QWERTY extra layer, Vi nav, Mac clipboard, soft off enabled, Bluetooth high power, display enabled.
