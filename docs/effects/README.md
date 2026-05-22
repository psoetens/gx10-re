# `docs/effects/` — moved out

The authoritative material that used to live in this directory has
been promoted to the top-level [`catalogs/`](../../catalogs/) directory
so it's easier to find. The stale files (`all_effects.{md,json}`,
`typebar.md`, `typebar_full.md`, `knob_mapping.md`) have been deleted
— they were sub-type-0-blind and the SUPERSEDED notices they carried
kept causing confusion downstream.

## Where things went

| Old path | New path |
|----------|----------|
| `docs/effects/firmware_overlay.json` | [`catalogs/firmware_overlay.json`](../../catalogs/firmware_overlay.json) |
| `docs/effect_catalog.md` *(deleted)* | [`catalogs/bts_effect_catalog_complete.json`](../../catalogs/bts_effect_catalog_complete.json) |
| `docs/effects/all_effects.{md,json}` *(deleted)* | same |
| `docs/effects/typebar.md`, `typebar_full.md`, `knob_mapping.md` *(deleted)* | (no replacement — capture methodology lives in [`../methodology.md`](../methodology.md)) |

## What's where now

- **Effect knob catalog (ground truth):**
  `catalogs/bts_effect_catalog_complete.json` — 83 effects × 632
  knobs, merged from BTS's own `effect_parameter.js` plus our
  live-device probe captures. Schema:
  [`../bts_catalog_schema.md`](../bts_catalog_schema.md).
- **Firmware coverage overlay:** `catalogs/firmware_overlay.json`.
- **TYPE / SP TYPE / MIC TYPE enums:**
  `catalogs/per_effect_types.json`.
- **ASSIGN TARGET enum table:** `catalogs/assign_target_table.json`.
- **Build / capture methodology:** [`../methodology.md`](../methodology.md).
