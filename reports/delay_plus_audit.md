# DELAY+ (TYPE 0x0E) — catalog address audit

**Date:** 2026-05-10
**Method:** FxItem 1 set to TYPE 0x0E, ON, variant 0. User turned
each main knob (TIME, FEEDBACK, EFFECT LEVEL, HIGH CUT) while we
listened on the broadcast channel.

## Verified addresses (offsets relative to FxItem base)

| Offset | Knob | Display range observed | Catalog status |
|--------|------|------------------------|----------------|
| `0x23` | **TIME** (ms) | 401..435 ms | **Catalog missing this entry**. Phantom "TAP TIME" wrongly placed at `0x27`. |
| `0x27` | FEEDBACK (%) | 24..51 | catalog correct ✓ (catalog also had a phantom "TAP TIME" duplicate here — remove) |
| `0x2B` | EFFECT LEVEL (%) | 51..72 | catalog correct ✓ (catalog also had phantom "1: TIME" duplicate here — remove) |
| `0x2F` | HIGH CUT | 14..27 | catalog correct ✓ (catalog also had phantom "1: FEEDBACK" duplicate here — remove) |

## Phantom catalog entries to remove

`bts_effect_catalog.json` for TYPE 0x0E lists three duplicate-address
entries (per task #40):

- `0x10001127`: FEEDBACK + **TAP TIME** (phantom — no such knob on
  the device per user)
- `0x1000112B`: EFFECT LEVEL + **1: TIME** (phantom — there's only
  TIME, not "1: TIME")
- `0x1000112F`: HIGH CUT + **1: FEEDBACK** (phantom — there's only
  FEEDBACK, not "1: FEEDBACK")

The phantoms appear to be parser artefacts — likely the chart's
multi-tap delay sub-section text was parsed as new knobs when in
fact the device exposes only one TIME / FEEDBACK knob.

## Implications

1. **DELAY+ has TIME at offset `0x23`** — completely missing from
   the catalog. Was previously interpreted as "TAP TIME" placed
   wrongly at `0x27`. Real TIME is at `0x23`.

2. **The four main DELAY+ knobs are at consecutive +4 offsets**
   `0x23`, `0x27`, `0x2B`, `0x2F` — clean monotonic layout. The
   catalog's apparent confusion came from inventing duplicate
   entries, not from address errors per se.

3. **`build_bts_catalog.py` parser bug is the same pattern**:
   like the menu_catalog had spec-row rows mis-ingested, the BTS
   catalog generator has phantom entries from sub-section
   confusion. Worth a targeted parser-fix pass to detect "label
   appears twice within an effect" and de-duplicate.

## Open / not tested in this round

DELAY+ has 19 knobs in the catalog. We verified 4. The remaining 15
include knobs like:
- LOW CUT, MOD RATE, MOD DEPTH, PRE-DELAY, ...
- PAN params (if PAN mode active)
- Tap-tempo / sync indicators

Catalog addresses for those weren't inspected this round; same
audit method (single-knob broadcast capture) would resolve them
quickly.
