# AMP (TYPE 0x02) — catalog address audit

**Date:** 2026-05-10
**Method:** Set FxItem 0 to TYPE = 0x02 (AIRD PREAMP), variant 0
(TRANSPARENT). Write distinct ascending values 1..18 to cells
0x10001107..0x1000114B. User reads device's AMP edit screen and
reports the displayed values for each labelled knob. Matching cell
values to displayed labels gives the real address per knob.

## Confirmed correct in catalog

| Address    | Knob       | Verified |
|------------|------------|----------|
| `0x10001107` | GAIN     | ✓ (= 1)   |
| `0x1000110B` | LEVEL    | ✓ (= 2)   |
| `0x1000110F` | BASS     | ✓ (= 3)   |
| `0x10001113` | MIDDLE   | ✓ (= 4)   |
| `0x10001117` | TREBLE   | ✓ (= 5)   |
| `0x1000111B` | PRESENCE | ✓ (= 6)   |
| `0x1000111F` | GAIN SW  | ✓ (out-of-range raw=7 displayed via modulo as MIDDLE; address is right) |
| `0x10001123` | SOLO SW  | ✓ (out-of-range raw=8 displayed via modulo as OFF; address is right) |

## Catalog WRONG — corrected addresses

| Knob       | Catalog claim | Actual address  | Evidence |
|------------|---------------|-----------------|----------|
| **SP TYPE** | `0x10001103` | **`0x1000113B`** | Wrote raw=14 there → device displayed "USER 1" (= raw 14 in SP TYPE enum). Forced to raw=1 → device displayed "ORIGINAL". |
| **DIRECT MIX** | `0x1000113B` | **`0x10001137`** | Wrote raw=13 there → device displayed "13" for DIRECT MIX. |
| **MIC LEVEL** | `0x10001143` | **`0x1000114B`** | Wrote raw=18 there → device displayed "18" for MIC LEVEL. |

The new addresses also explain the catalog's duplicate-address bug:
the catalog conflated SP TYPE / DIRECT MIX / MIC TYPE all at
`0x1000113B` because the BTS sweep's stride logic placed three
different parameters at the same offset.

## Still uncertain — display-gated or address unknown

SAG, RESONANCE, BRIGHT SW, MIC TYPE, MIC POSITION, MIC DISTANCE
all displayed values that don't trivially match a single cell:

- **SAG**: display 0. Catalog `0x1000112F`. Cell verified to store
  raw=11 after our write, but display fixed at 0. Either wrong
  address, or display gated (e.g., requires a power-amp flag we
  haven't set).
- **RESONANCE**: display 0. Catalog `0x10001133`. Same situation
  as SAG.
- **BRIGHT SW**: catalog `0x10001137`, but that cell is now
  confirmed DIRECT MIX. So BRIGHT SW is at an unknown address.
- **MIC TYPE = DYN57**: enum index 1. Cell with raw=1 is `0x07`
  (GAIN). MIC TYPE address is unknown — possibly at a cell beyond
  `0x4B` we didn't write (and which retained an old value of 1) or
  at an unmapped offset. Not `0x07` (which displays GAIN=1
  correctly per the verified mapping above).
- **MIC POSITION = 5cm**: numeric. Cell with raw=5 is `0x17`
  (TREBLE). Same ambiguity as MIC TYPE.
- **MIC DISTANCE = SHORT**: enum index 1. Same.

## Hypothesis: AMP edit screen has multiple "pages" with overlapping displays

The GX-10's AMP edit UI likely paginates: one page shows the basic
amp knobs (GAIN/LEVEL/BASS/MIDDLE/TREBLE/PRESENCE), another shows
power-amp settings (SAG, RESONANCE, BRIGHT SW), another shows mic
settings (SP TYPE, MIC TYPE/POSITION/DISTANCE/LEVEL, DIRECT MIX).
The user only saw a subset depending on which page was active when
they read.

If the catalog mis-resolved several knob addresses by snapshotting
the wrong page, the wrong-address pattern follows: TREBLE display
on the basic page came from `0x17`, and the same cell `0x17` may
also be referenced by MIC POSITION on the mic page (if BTS UI
re-uses cells for unrelated parameters). This would surface as
"both knobs match cell 0x17" without either being wrong on its
own page.

## Next-step recommendations

1. **Targeted SAG / RESONANCE probe**: change AMP variant from
   TRANSPARENT (sub-type 0) to a high-power amp like JUGGERNAUT
   (sub-type 5) or BRIT STACK (sub-type 14). Power-amp simulation
   may activate, exposing SAG / RESONANCE displays.
2. **Beyond-`0x4B` probe**: extend the cell sweep to offsets
   `0x4F`..`0x7F` so MIC TYPE / POSITION / DISTANCE candidate
   addresses get distinct test values.
3. **Multi-page LCD reading**: ask the user to walk through every
   page of the AMP edit screen and note which knobs appear on
   which page — distinguishes "page-overlap" from real
   address-collision.
4. **Windows-side BTS UI re-capture for AMP**: BTS shows all knobs
   at once with proper labels and the cells their writes target.
   `tools/probe_bulk_enums.py` already supports this; rerun it
   pinned to AMP and produce a fresh per-(TYPE, sub-type) map.

## Implication for catalog confidence

The AMP catalog has at least 3 wrong addresses + 4-6 unverified
addresses. By extension, AMP_BASS (which the catalog audit at task
#40 also flagged with duplicate-address bugs) and DELAY+ (same)
likely have similar issues. Treat `bts_effect_catalog.json` as
**suspect for any effect with `dropdowns` of more than one item**
until a per-effect re-validation pass is done.

Effects already validated correct via subtype_sweep (all-y on user
smoke test):
- WAH (TYPE 0x35) — 5 knobs × 6 sub-types
- AC RESONANCE (TYPE 0x01) — 3 knobs × 3 sub-types
- (numeric-knob-only portion of AMP)

Effects flagged for re-validation:
- AIRD PREAMP (0x02) — confirmed bugs
- BASS AIRD PREAMP (0x03) — likely (same catalog pattern)
- DELAY+ (0x0E) — likely (same catalog pattern)
