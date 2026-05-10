# Windows BTS hand-off — automated cross-validation needed

**Date:** 2026-05-10
**For:** Windows-side Claude executor, with BTS + GX-10 attached.
**Prereq:** `git pull` on `firmware-versions` (or `windows-bts-captures`),
then `pip install -r` your usual env.

The Linux side has gone as far as it can without device-touching:
verified the broadcast-capture catalog-audit method works, manually
audited AMP / AMP_BASS / DELAY+ knob addresses, applied corrections to
`captures/bts_effect_catalog.json`, and stopped. Manual user-driven
knob turning is too slow and error-prone to scale to all 83 effects.
**Windows BTS is the right tool for the rest** — UIA/screen reads
give knob labels for free, and you can drive BTS knobs
programmatically.

## What's already in the catalog

`captures/bts_effect_catalog.json` is now post-corrections:
- 83 effect TYPE bytes (0x00..0x52)
- 629 knobs (down from 632 after phantom de-dup)
- All addresses corrected for the verified subset
- `_address_verified_2026_05_10: true` flag on knobs we've live-verified

`captures/effect_catalog_corrections.json` is the overlay the Linux
side applied. Keep it as the audit trail.

## What needs Windows automation

### Priority 1 — generator-side de-dup

`tools/build_bts_catalog.py` was the source of phantom duplicate
knob entries (TAP TIME, 1: TIME, 1: FEEDBACK on DELAY+; same pattern
for AMP/AMP_BASS earlier). The phantoms come from BTS UI sweep
mis-attributing sub-section labels.

Fix the generator so it doesn't emit duplicates in the first place:

1. After building `knobs_out` per effect, group by address.
2. Within each address-group, keep the entry whose label is shortest
   / has no "1: " / "2: " / "TAP " / "<sub-section>: " prefix.
3. Re-emit `bts_effect_catalog.json`.
4. Re-run `tools/apply_catalog_corrections.py` on the regenerated
   catalog (the corrections file remains the verified-overlay source
   of truth).

### Priority 2 — full per-effect address audit (BTS-driven)

Reproduce the Linux-side broadcast-capture method, but BTS-driven
instead of user-driven. Each effect:

1. Set `FxItem 0` to TYPE = T, variant = 0.
2. Open BTS to the effect's edit panel.
3. For each knob the panel exposes:
   a. Programmatically click + drag the knob a small amount.
   b. Capture the broadcast DT1 address.
   c. Map BTS UI label → cell address.
4. Compare against `bts_effect_catalog.json`.
5. For mismatches: append to a corrections-overlay JSON (same schema
   as `captures/effect_catalog_corrections.json`).
6. Repeat for each sub-type variant (raw 0..max) — only for effects
   that show layout differences across variants. WAH (6 variants),
   AC RES (3), and AMP family preliminary checks suggest layouts
   are sub-type-INVARIANT. The `subtype_sweep.py` smoke-test with
   the user as visual oracle showed all-y for WAH and AC RES and
   numeric-knob-OK for AMP — but BTS UIA can confirm conclusively.

Pseudocode for one effect:

```
attach=1
listen_start
for each knob in BTS_panel(effect=T):
  bts_click_drag(knob)
  events = listen_collect(timeout=2s)
  addr = events[0].address  # first DT1 fired
  record_mapping(T, knob.label, addr)
listen_stop
```

### Priority 3 — bipolar knob test methodology

Bipolar knobs (-N..+N) clamp out-of-range writes to 0, which broke
our naive 1..N ordinal write test (all writes appeared as 0 on
display). Fix in any future write-then-read tools: use
`encode_fx_param(0)` or a value within the documented range. The
Linux side's `tools/per_type_range_check.py` already has the
display-conversion logic; fold that into the BTS-side validator.

### Priority 4 — sub-type knob layout claim

Linux smoke test (`tools/subtype_sweep.py`) had user confirm WAH
all-y across 6 sub-types and AC RES all-y across 3. BTS-side can
verify this exhaustively using UIA reads of knob labels per
sub-type. If all sub-types share the same label↔address mapping
for an effect, that effect's catalog needs only one entry. If
they differ, per-(TYPE, sub-type) entries are needed.

## Linux-side artefacts to consume

| File | Use |
|------|-----|
| `captures/bts_effect_catalog.json` | post-corrections catalog (current canonical) |
| `captures/bts_effect_catalog.json.bak` | pre-corrections catalog (for diff) |
| `captures/effect_catalog_corrections.json` | verified overlay |
| `tools/apply_catalog_corrections.py` | re-runs the overlay (idempotent) |
| `reports/amp_address_audit.md` | full AMP findings + methodology |
| `reports/delay_plus_audit.md` | DELAY+ findings + phantom-knob diagnosis |
| `reports/catalog_validation_2026-05-10.md` | wire-level validation methodology |
| `tools/validate_catalogs.py` | regression-test: 88.2% wire-level reply rate baseline |
| `tools/encoding.py` | 4-nibble offset binary encoder/decoder (use this everywhere) |
| `tools/midi_io_linux.py` (Linux) / equivalent on Windows | MIDI I/O wrapper |
| `tools/subtype_sweep.py` | smoke-test for sub-type layout invariance |

## Linux-side known-correct subset

These are the entries we've verified live and/or by spot-check,
flagged with `_address_verified_2026_05_10: true` in the catalog:

- 0x01 AC RESONANCE (3/3 sub-types verified knob layout)
- 0x02 AIRD PREAMP — 12 of 17 knobs verified (BRIGHT SW newly added)
- 0x03 BASS AIRD PREAMP — 6 knobs verified
- 0x08 COMPRESSOR (5/5 knobs)
- 0x0E DELAY+ — 4 of 16 knobs verified; phantom knobs removed
- 0x35 WAH (5/5 knobs across 6/6 sub-types)

The remaining ~570 knob entries are catalog-claimed but not
live-verified. BTS-driven audit closes the loop.

## Hand-off acknowledgment

When the Windows side has completed Priority 1 + 2, the
`firmware-versions` branch should have:

- `tools/build_bts_catalog.py` patched to de-dup phantoms
- `captures/bts_effect_catalog.json` re-emitted
- `captures/effect_catalog_corrections.json` updated with all newly-
  verified entries (the union of Linux + Windows findings)
- `_address_verified_2026_05_10: true` (or a 2026-05-11+ flag) on
  every audited entry
- A regression-test note that `validate_catalogs.py` reply-rate
  target is now ~95%+ (was 88.2%)

Ping back when done; Linux side will pull and integrate.
