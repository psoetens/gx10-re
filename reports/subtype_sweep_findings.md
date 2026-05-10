# Sub-type knob-order smoke test findings

**Date:** 2026-05-10
**Tool:** `tools/subtype_sweep.py`
**Method:** Write distinctive ordinal values (1, 2, 3, ...) to knobs in
catalog order, for each sub-type of an effect. User watches the device
LCD and confirms y/n per sub-type.

---

## §1. WAH (TYPE 0x35) — all 6 sub-types pass

| Sub-type | Name        | User match | Notes |
|---------:|-------------|:----------:|-------|
| 0 | CRY WAH       | ✓ y | catalog matches |
| 1 | VO WAH        | ✓ y | catalog matches |
| 2 | FAT WAH       | ✓ y | catalog matches |
| 3 | LIGHT WAH     | ✓ y | catalog matches |
| 4 | 7STRING WAH   | ✓ y | catalog matches |
| 5 | RESO WAH      | ✓ y | catalog matches |

Result: `bts_effect_catalog.json` WAH layout (5 knobs at addresses
`0x10001113 EFFECT LEVEL`, `0x10001117 DIRECT MIX`, `0x10001107
PEDAL POSITION`, `0x1000110B PEDAL MIN`, `0x1000110F PEDAL MAX`) is
correct **for every WAH sub-type, not just CRY WAH (sub-type 0)**.

Captured to: `captures/subtype_sweep_results/0x35_WAH.json`.

### Earlier "WAH names permuted" was about the old catalog

The "WAH names permuted by 3 positions" finding (Linux probe + Windows
validation, ~2026-05-09) referred to the **old typebar_full-derived**
`docs/effect_catalog.md`, which was sub-type-blind in capture. The
**new** `bts_effect_catalog.json` (Windows BTS-driven sweep) was
captured at sub-type 0 (CRY WAH) — but this smoke test now confirms
its layout is correct for sub-types 1..5 too.

So the assumption motivating task #33 (sub-type capture needed) does
**not** apply to WAH. Open question: does it apply to any other
effect, or is the BTS sweep at sub-type 0 universally correct for all
sub-types?

---

## §1b. AC RESONANCE (TYPE 0x01) — all 3 sub-types pass

User smoke-tested AC RESONANCE (3 knobs × 3 sub-types). All 'y'.
Catalog matches the device for every sub-type.

## §1c. AIRD PREAMP (TYPE 0x02) — partial test, no order mismatch found

User started AMP smoke test (17 knobs × 16 sub-types) but didn't
complete all sub-types. Notable observation:

> "many 'enum' or different ranges values and these didn't match the
> raw number. but where a number was useful, it was correct."

i.e. for numeric knobs whose display range accommodates the ordinal
test values (1..17), the device displayed exactly the catalog-claimed
labels. Enum knobs and small-range knobs (raw_max < ordinal) did not
show "1, 2, 3, ..." literally because their displays use enum labels
(e.g. SOLO SW = ON/OFF) or clamp to a smaller range.

**Tool improvement landed**: `tools/subtype_sweep.py` now picks a
test value clamped to each knob's actual range and reports the
**expected display value** (with enum labels resolved from the
catalog's `raw_to_display` map). E.g.:

```
GAIN SW       = HIGH                 (raw=2, [enum])
SAG           = +10                  (raw=10)
MIC TYPE      = BLEND C               (raw=8, [enum])
```

This makes the user's y/n call clear regardless of knob kind.

## §1d. NEW catalog bug — duplicate addresses for some knobs

While running the improved sweep on AMP, surfaced **7 cells in 3
effects** where two distinct knobs claim the same address:

| TYPE | Address      | Knob A | Knob B |
|-----:|--------------|--------|--------|
| 0x02 AIRD PREAMP | 0x1000113B | DIRECT MIX | MIC TYPE |
| 0x02 AIRD PREAMP | 0x10001143 | MIC DISTANCE | MIC LEVEL |
| 0x03 BASS AIRD PREAMP | 0x10001137 | BRIGHT SW | DIRECT MIX |
| 0x03 BASS AIRD PREAMP | 0x10001143 | MIC DISTANCE | MIC LEVEL |
| 0x0E DELAY+ | 0x10001127 | FEEDBACK | TAP TIME |
| 0x0E DELAY+ | 0x1000112B | EFFECT LEVEL | 1: TIME |
| 0x0E DELAY+ | 0x1000112F | HIGH CUT | 1: FEEDBACK |

Catalog can't have two knobs at the same address. Most likely cause:
stride-inference + manual-cross-ref overlay conflict in
`tools/build_bts_catalog.py`. Tracked as task #40. Each pair needs
disambiguation via either:
- live-device probe (write distinct values to neighbouring offsets,
  see which knob the device respects), or
- a Windows BTS re-capture targeted at these effects.

Until fixed: the SECOND knob in each pair (lexically last in the
catalog's `knobs` array) shadows the first on writes, since both
hit the same address.

---

## §2. Next steps to bracket the hypothesis

To validate "BTS sweep at sub-type 0 is correct for all sub-types" as
a general claim, smoke-test a few more effects with sub-types,
prioritising small ones for quick test cycles:

| TYPE | Effect       | Knobs | Sub-types | Effort |
|-----:|--------------|------:|----------:|--------|
| 0x01 | AC RESONANCE  | 3 | 3 | small (3 prompts) |
| 0x07 | CLASSIC VIBE  | 4 | 2 | small (2 prompts) |
| 0x08 | COMPRESSOR    | 5 | 3 | small (3 prompts) |
| 0x05 | BASS CHORUS   | 7 | 2 | small (2 prompts) |
| 0x29 | FUZZ          | 7 | 3 | small (3 prompts) |
| 0x25 | OVERDRIVE     | 7 | 9 | medium (9 prompts) |
| 0x02 | AIRD PREAMP   | 17 | 16 | large (16 prompts) — biggest test of the hypothesis |

Recommended: run 0x01 (AC RESONANCE, 3 prompts) and 0x02 (AIRD PREAMP,
16 prompts) to bracket the easy and hard cases. If both pass, the
"BTS sweep is sub-type-invariant" hypothesis is strongly supported.
If 0x02 finds any 'n' entries, those specific (TYPE, sub-type) pairs
get tagged for Windows BTS re-capture.

Command:

```bash
.venv/bin/python tools/subtype_sweep.py --type 0x01
.venv/bin/python tools/subtype_sweep.py --type 0x02
```

---

## §3. Implications if hypothesis holds

If the BTS catalog at sub-type 0 turns out to be correct for all
sub-types of every effect:

1. **`bts_effect_catalog.json` is fully usable as-is** — no
   per-(TYPE, sub-type) re-capture needed.
2. **Task #33 effectively closes** without Windows-side automation
   (the script we just wrote becomes a regression-test for future
   firmware updates rather than an active capture tool).
3. **gxnarly Issue 6** (regenerate `devices/*.json` from
   `bts_effect_catalog.json`) becomes a clean port — no per-sub-type
   schema needed.

If the hypothesis fails for some effect (e.g., AIRD PREAMP with 16
sub-types finds 'n' for one):

1. That (TYPE, sub-type) pair is tagged for Windows re-capture.
2. The Linux smoke-test result lists exactly which pairs need it,
   minimising Windows-side work.
3. `bts_effect_catalog.json` gets a per-sub-type extension only for
   the affected entries.

Either outcome is informative; the smoke test is cheap.
