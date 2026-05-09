# Live WAH name→address validation — typebar_full mapping is permuted by 3 positions

User performed a write/read validation on the live device. Result:
**typebar_full has every WAH knob name in the wrong slot.**

## Test

I wrote five distinctive values via DT1 (one per FX Param slot of WAH
on FxItem #0):

| Address | typebar_full claimed name | Value written |
|---------|---------------------------|---------------|
| `0x1000110B` | EFFECT LEVEL | 1 |
| `0x1000110F` | DIRECT MIX | 2 |
| `0x10001113` | PEDAL POSITION | 3 |
| `0x10001117` | PEDAL MIN | 4 |
| `0x1000111B` | (not in typebar_full — guessed PEDAL MAX) | 5 |

User then read the device's labelled knob values in the order
EFFECT LEVEL / DIRECT MIX / PEDAL POSITION / PEDAL MIN / PEDAL MAX:

```
EFFECT LEVEL    = 3
DIRECT MIX      = 4
PEDAL POSITION  = 70   ← original snapshot value, not written this run
PEDAL MIN       = 1
PEDAL MAX       = 2
```

## Decode

The values that came back match writes I made to *different* addresses
than typebar_full claimed:

| Real label  | Real address | typebar_full address | typebar_full label   |
|-------------|--------------|----------------------|----------------------|
| WAH TYPE (sub-type) | `0x10001103` (Param 1) | `0x10001103` | type_address ✓ |
| **PEDAL POSITION**  | `0x10001107` (Param 2) | `0x10001107` | WAH TYPE ✗ |
| **PEDAL MIN**       | `0x1000110B` (Param 3) | `0x1000110B` | EFFECT LEVEL ✗ |
| **PEDAL MAX**       | `0x1000110F` (Param 4) | `0x1000110F` | DIRECT MIX ✗ |
| **EFFECT LEVEL**    | `0x10001113` (Param 5) | `0x10001113` | PEDAL POSITION ✗ |
| **DIRECT MIX**      | `0x10001117` (Param 6) | `0x10001117` | PEDAL MIN ✗ |
| (no visible label)  | `0x1000111B` (Param 7) | not in typebar_full | — |

In words: every WAH knob name in typebar_full is shifted by **3
positions** relative to its true address. typebar_full's "WAH TYPE
knob" is actually PEDAL POSITION on the device; typebar_full's
"PEDAL POSITION" is actually EFFECT LEVEL; etc.

## Why typebar_full was wrong

`captures/typebar_full/page1/23_WAH/summary.json` was extracted from
BTS's UI screenshot at the moment WAH was dragged into slot 0 — and
BTS at that moment showed sub-type 0 (the default for a fresh drag).
The user's session was at sub-type 2 (Param 1 = 2 in the snapshot
header). **Sub-types of WAH have different knob layouts**, but the
typebar_full pipeline only captured one snapshot per category, not
per sub-type. So typebar_full's WAH knob list reflects sub-type 0,
which apparently has names in a different order than sub-type 2.

This explains both the Linux finding (commit `4052c1d`: "WAH catalog
bug") and the missing PEDAL MAX entry (it's a sub-type 2 knob the
sub-type 0 layout didn't have).

## Open: what's at `0x1000111B` (Param 7)?

I wrote `5` to this slot and the user didn't see any labelled knob
with value 5. The original snapshot had display=0 there. Possible:

- A boolean / switch parameter (on/off, not shown as a numeric knob
  on the device LCD).
- A sub-page knob the device's main view doesn't show.
- A genuinely unused slot the device accepts writes to but doesn't
  expose.

Worth a follow-up: write 0 vs 1 vs 100 to this slot, watch for any
audible/visible effect.

## Implications for the catalog

The two known catalog bugs are both real:

1. **WAH names-permuted** (this finding) — every knob name is in the
   wrong slot for sub-type 2. typebar_full needs per-sub-type
   captures, not per-category.
2. **COMP catalog-incomplete** (Linux finding `bccde3e`) — TONE and
   DIRECT MIX visible on device but not in catalog.

Pattern: the typebar_full pipeline took **one snapshot per category**
(default sub-type at drag time), but effect categories that have
sub-types (TYPE/SP TYPE byte at 0x10001103) can change knob count
AND knob name AND knob position when the sub-type changes. The
catalog needs to be regenerated **per (TYPE, sub-type) pair**.

## Next test recommendations

1. For WAH: cycle through sub-types 0..5, capture the device's
   labelled knob list at each. That gives the full WAH knob matrix.
2. For COMP: same cycle (type_max=2 per typebar_full, so 3 sub-types).
3. For every effect with `type_max > 0` in typebar_full's per-effect
   summary.json: same.

The Linux side could automate this with the device-broadcast finding:
write each TYPE+sub-type byte, ask user to nudge each visible knob
slightly, capture broadcast addresses to identify which slots are
"live" (= visible knobs) for that sub-type combination.

## Tools used

- `tools/write_wah_test.py` — wrote the 5 test values (at
  typebar_full-claimed addresses).
- `tools/restore_fxitem0.py` — restored the user's WAH (TYPE 0x35,
  sub-type 2) snapshot byte-for-byte.

## Status

User's slot-0 patch was restored byte-for-byte after the test.
