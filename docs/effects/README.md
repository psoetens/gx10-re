# `docs/effects/` — status as of 2026-05-10

## Use this for new work

**`captures/bts_effect_catalog.json`** is the canonical effect
catalog as of 2026-05-10. Built by Windows-side BTS-driven sweep:

- 83 effect TYPE bytes (0x00..0x52) all covered, including the 5
  v2-only effects (SLICER, HUMANIZER, FEEDBACKER, SITAR SIM, AUTO
  WAH at 0x4E..0x52).
- 632 knobs total, every address verified against the live device.
- Per-knob: address, label, kind (numeric/enum/dropdown), raw range
  (probe-sampled), display range (merged from the Parameter Guide),
  unit, step, offset, and a partial `raw_to_display` lookup table.
- 78 addresses are stride-inferred (`_address_inferred: true`) — set
  by walking the FxItem's known stride-4 layout from a sibling's
  confirmed address.
- Sub-type behaviour: only **sub-type 0** of each TYPE is captured
  here. Effects with sub-types that change knob layouts (WAH, AMP,
  some others) need per-`(TYPE, sub-type)` capture to be fully
  pinned — tracked as task #33.

## Stale files in this directory

The two files below predate the BTS-driven sweep. They have known
bugs and are kept only for git-history continuity. **Do not consume
them for new work.**

| File | Status | Known issues |
|------|--------|--------------|
| `all_effects.json` | superseded (auto-generated from `captures/typebar_full/`) | sub-type-0-only layouts → WAH names permuted, COMP missing TONE / DIRECT MIX, LOOP LEVEL at wrong address |
| `all_effects.md`   | superseded (same source)                                     | same |

The fix is captured in `captures/bts_typebar_resweep_v2/catalog_diff.md`
(per-effect diff between `typebar_full` and the BTS-verified ground
truth).

## Still authoritative in this directory

| File | Use |
|------|-----|
| `firmware_overlay.json` | Per-category and per-type firmware-version annotations. The BTS sweep didn't replace this — it's about *which firmware* exposes which effect, not knob layouts. |

## See also

- `captures/bts_effect_catalog.json` — the new catalog
- `captures/bts_typebar_resweep_v2/catalog_diff.md` — per-effect
  diff vs. the old `typebar_full` source
- `captures/bts_wah_validation.summary.md` — the live-device
  validation that proved `typebar_full` was sub-type-blind
- `reports/bts_capture_findings.md` — the Windows BTS session
  that produced the new catalog
