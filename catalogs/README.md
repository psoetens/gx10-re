# `catalogs/` — authoritative reference tables

The JSON files in this directory are the **ground truth** for GX-10 /
GX-100 effect knobs, register addresses, firmware-version coverage,
per-effect TYPE/SP TYPE enums, the global TYPE-byte enum, and the
ASSIGN TARGET address table. Downstream tools and docs should read
from here.

| File | What it is | Schema / docs | Producer |
|------|------------|---------------|----------|
| `bts_effect_catalog_complete.json` | 83 effects × 632 knobs. Every TYPE byte (`0x00..0x52`), every knob's address, label, kind, raw/display range, unit, step, offset, and (where known) the raw→display lookup. Merged from BTS's own `effect_parameter.js` (Roland's parameter DB) + our live-device probe captures. | [`docs/bts_catalog_schema.md`](../docs/bts_catalog_schema.md) | `tools/merge_bts_into_catalog.py` |
| `menu_register_catalog.json` | Register map for everything that *isn't* an effect knob: SystemCommon, MENU dialogs (TUNER, CTL/EXP, IN/OUT, WRITE), per-region field offsets, encodings, ranges, enums. Complements the effect catalog — together they cover the whole device address map. | inline in the file | `tools/build_menu_catalog.py` (from `docs/manuals/`) |
| `firmware_overlay.json` | Per-category and per-type firmware-version annotations — which firmware family exposes which effect, which sub-types are v2-only, etc. Complements the catalog (the catalog is *what knobs exist*; the overlay is *which firmware exposes them*). | inline in the file | hand-maintained |
| `per_effect_types.json` | Per-effect TYPE / SP TYPE / MIC TYPE enum value lists (e.g. COMP → `["BOSS COMP", "D-COMP", "ORANGE"]`). | inline in the file | `tools/extract_per_effect_types.py` (from `docs/manuals/`); mirrored in `tools/per_effect_types.py` |
| `fx_type_enum.json` | 83-entry global MemoryFxItem TYPE byte → effect name table (`{"0": "AC GUITAR SIMULATOR", ..., "82": "AUTO WAH"}`). Hand-maintained from the MIDI chart; mirrored in `tools/fx_type_enum.py` for Python `import`. | inline in the file | hand-maintained (keep .json and .py in sync) |
| `assign_target_table.json` | The 741-entry ASSIGN TARGET enum from the official MIDI Implementation chart — maps each addressable parameter to its assign-target index. | inline in the file | `tools/extract_assign_target_table.py` (from `docs/manuals/`); mirrored in `tools/assign_target_table.py` |
| `source_names.json` | The 84-entry ASSIGN SOURCE enum — flat list where position `i` is the human-readable name of SOURCE byte value `i` (`"NUM 1", "NUM 2", ..., "INPUT", "CC#1", ..., "CC#31", "CC#64", ..., "CC#95"`). | inline in the file | hand-maintained (keep .json and `tools/source_names.py` in sync) |

## Build inputs (not ground truth)

`captures/bts_effect_catalog.json` is the probe-only intermediate that
feeds `tools/merge_bts_into_catalog.py`. It lives in `captures/`
because it's a build artifact, not an authoritative end product.
Don't consume it directly — use `bts_effect_catalog_complete.json`.
