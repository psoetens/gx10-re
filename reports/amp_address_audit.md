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

## Resolved via passive broadcast capture (user-driven knob turns)

Pivot: instead of writing distinct values and decoding by display,
set editor-attach handshake and listen for unsolicited DT1
broadcasts while the user turns specific knobs. The address that
fires identifies the knob unambiguously.

| Address    | Knob (verified by broadcast)          | Catalog status       |
|------------|---------------------------------------|----------------------|
| `0x1000112F` | **SAG** (bipolar -10..+10)         | catalog correct ✓ — earlier "always 0" was just our test value clamping (raw 11/12/13 = display +11/+12/+13 → out of range → 0) |
| `0x10001133` | **RESONANCE** (bipolar -10..+10)   | catalog correct ✓ — same root cause |
| `0x1000113F` | **MIC POSITION**                   | catalog correct ✓ |
| `0x10001143` | **MIC DISTANCE**                   | catalog correct ✓ — disambiguates from the duplicate that had MIC LEVEL there |
| `0x10001137` | **DIRECT MIX** (re-confirmed)      | catalog WRONG (claimed `0x1000113B`) |
| `0x1000114B` | **MIC LEVEL** (re-confirmed)       | catalog WRONG (claimed `0x10001143`) |

## Still uncertain after this round

- **BRIGHT SW** (resolved 2026-05-10 via AMP_BASS test):
  AMP_BASS exposes BRIGHT SW; the user toggled it once and the
  broadcast fired at **offset `0x2B`** (cell `0x1000112B`). That's
  the cell catalog had as the "gap" between SOLO LEVEL and SAG.
  By symmetry, plain AMP almost certainly has BRIGHT SW at the
  same offset — just hidden on the AMP variants we tested
  (TRANSPARENT, BRIT STACK, DELUXE COMBO, DIAMOND AMP).

## Definitive AMP knob/dropdown layout (per live broadcast probe)

Captures concluded with two more single-knob broadcasts (MIC TYPE
and MIC POSITION). The full corrected layout for AMP (TYPE 0x02,
variant BRIT STACK = 14, SP TYPE = ORIGINAL = 1):

| Address      | Knob               | Notes                          |
|--------------|--------------------|--------------------------------|
| `0x10001100` | TYPE byte (1B)     | AIRD PREAMP family selector    |
| `0x10001103` | variant (4N)       | TRANSPARENT/NATURAL/.../BRIT STACK/... — 16 variants per catalog, broadcast went raw 8..20 so device may accept up to ≥20 |
| `0x10001107` | GAIN               | catalog correct                |
| `0x1000110B` | LEVEL              | catalog correct                |
| `0x1000110F` | BASS               | catalog correct                |
| `0x10001113` | MIDDLE             | catalog correct                |
| `0x10001117` | TREBLE             | catalog correct                |
| `0x1000111B` | PRESENCE           | catalog correct                |
| `0x1000111F` | GAIN SW            | catalog correct (enum 0..2)    |
| `0x10001123` | SOLO SW            | catalog correct (enum 0..1)    |
| `0x10001127` | SOLO LEVEL         | catalog correct; display gated on SOLO SW = ON |
| `0x1000112B` | (gap?)             | catalog skipped this offset    |
| `0x1000112F` | SAG                | catalog correct (bipolar -10..+10; display clamps to 0 when raw outside 0x7FF6..0x800A) |
| `0x10001133` | RESONANCE          | catalog correct (same as SAG)  |
| `0x10001137` | DIRECT MIX         | **catalog WRONG** (claimed 0x1000113B) |
| `0x1000113B` | SP TYPE            | **catalog WRONG** (claimed 0x10001103) |
| `0x1000113F` | MIC TYPE           | **catalog WRONG** (claimed 0x1000113B) |
| `0x10001143` | MIC DISTANCE       | catalog correct                |
| `0x10001147` | MIC POSITION       | **catalog WRONG** (claimed 0x1000113F) |
| `0x1000114B` | MIC LEVEL          | **catalog WRONG** (claimed 0x10001143) |
| `0x1000114F`+| (unmapped)         | possibly BRIGHT SW (variant-conditional) |

**Pattern:** the cells from `0x10001137` onward form a clean
monotonic +4 sequence (DIRECT MIX → SP TYPE → MIC TYPE → MIC DISTANCE
→ MIC POSITION → MIC LEVEL) but the catalog generator placed them
out of order — SP TYPE wrongly at the variant-selector address
`0x10001103`, and the MIC group shifted around. The order in
the catalog matches the real order; only the addresses collide
and shift.

## Methodology that worked

The **passive broadcast capture** (set editor-attach handshake,
listen, user turns one knob at a time) is dramatically more
reliable than the write-distinct-values-and-read-display approach
for catalog audits. Reasons:

1. The device tells us directly which address its knob writes to.
2. No interpretation needed for enum vs numeric vs bipolar — the
   address is unambiguous.
3. No risk of writing out-of-range values that get clamped/modulo'd
   into wrong-looking displays.
4. User just turns one knob at a time and says "done" — no need to
   read 17 displays in catalog order.

Recommend this method as the **canonical catalog-audit tool**;
deprecate the smoke-test ordinal-write approach for effects with
many enum / bipolar / range-restricted knobs.

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
