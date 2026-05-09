# Programmatic full TYPE sweep — fills gaps in typebar_full

Source: `captures/bts_full_sweep/sweep.jsonl` (128 records),
`captures/bts_full_sweep/per_type.json` (analyzed),
`captures/bts_full_sweep/per_type_table.md` (human-readable).

## Method

No BTS UI automation, no USBPcap. Programmatic SysEx round-trips:

1. Snapshot FxItem #0 (RQ1 0x10001100 size=0x140 → device returns 179
   bytes covering the full FxItem block).
2. Set editor-attach handshake (DT1 0x7F000001 = 0x01 ×2).
3. For TYPE byte = 0x00..0x7F:
   - DT1 0x10001100 = TYPE
   - Wait 80 ms
   - RQ1 0x10001100 size=0x140 → record device's reply
4. Restore by writing each FxItem header byte + each FX-Param 4-byte
   slot individually (bulk DT1 of the snapshot is silently rejected
   past the first byte).
5. Verify: re-read FxItem #0, byte-for-byte match with snapshot. ✓
6. Clear editor-attach (DT1 0x7F000001 = 0x00).

Total time: ~17 seconds for 128 TYPE writes + restore. No BTS, no
USBPcap, no UI clicks.

Tools: `tools/sweep_all_types.py`, `tools/restore_fxitem0.py`,
`tools/verify_fxitem0.py`, `tools/analyze_sweep_v2.py`.

## Findings

### 1. TYPE byte clamps at 0x52

Writing TYPE bytes 0x53..0x7F all stored as **0x52**. The valid
effect TYPE range is **0x00..0x52** = **83 effects**.

```
TYPE 0x52: actual=0x52 head=52000008000001080003020800030208  ← A_WAH
TYPE 0x53: actual=0x52 head=52000008000001080003020800030208  ← clamp
TYPE 0x54: actual=0x52 head=52000008000001080003020800030208  ← clamp
... (all the way to 0x7F)
```

This is information neither typebar_full (which only covers
0x00..0x52) nor protocol.md previously documented. Useful for any
client that wants to enumerate effects without trusting an
out-of-band table.

### 2. Two effects missing from typebar_full

The May-6 BTS UI sweep (`captures/typebar_full`) captured 81 effects.
Our SysEx sweep finds 83 valid TYPEs in the device. The two missing
ones:

| TYPE | Block first 16 bytes | Tail pattern |
|------|----------------------|--------------|
| `0x1E` | `1e 00 00 08 00 00 00 08 00 04 06 08 00 01 09 08` | NO div-mix tail; only 6 params non-zero |
| `0x1F` | `1f 00 00 08 00 00 00 08 00 06 04 08 00 06 04 08` | div-mix tail (matches 0x1D) |

Best guess based on default-value patterns:

- **TYPE 0x1F**: probably `DIV_MIX_BASS`. Its trailing-byte pattern
  (offsets 0x1B..0x3F) is identical to TYPE 0x1D = DIV_MIX, suggesting
  the same memory-layout family. The typebar lists DIV_MIX without a
  _BASS variant; the bass version may be a hidden TYPE only reachable
  via direct SysEx.
- **TYPE 0x1E**: harder to identify. Only 6 active params with
  defaults (P1=0, P2=70, P3=25, P4=70, P5=76, P6=32) and a clean
  trailing zero-fill. Could be a tuner/util effect or a deprecated
  slot. Worth a focused probe: set TYPE 0x1E from BTS chain, screenshot
  the effect name.

These are NEW protocol-RE findings — the typebar UI either skipped
them (paginated in a way the May-6 automation didn't cover) or BTS
hides them entirely from its drag bar.

### 3. All effects expose the same 44 4-byte param slots

The device returns 179 bytes per FxItem, structured as:

```
offset 0x00      = FX TYPE byte
offset 0x01      = ON/OFF
offset 0x02      = DuplicationNumber
offset 0x03+N*4  = FX Param N+1 (4-byte 4-nibble offset binary)
```

All 44 param slots reply with `08 00 ?? ??` defaults — even for
effects that visually only have 4 knobs. Unused slots default to
`08 00 00 00` (display 0). To find the **active** knob count for an
effect, see `captures/typebar_full/page*/<idx>_<NAME>/summary.json`,
which has BTS's UI-knob count and the manual's parameter names.

Address byte 4 must be ≤ 0x7F (Roland 7-bit-per-byte rule), so FX
Params **1..32** are reachable in segment 0 (offsets 0x03..0x7F = 32
slots). Effects in this catalog use ≤21 params (max observed offset
= 0x53), so segment 2 (0x10001200..0x1000127F = "Param 33..44"
addressing) appears unused in practice.

### 4. The catalog-incomplete bug from Linux side is reaffirmed

The Linux probe (`reports/linux_probe_results.md`, commit `bccde3e`)
flagged a "catalog-incomplete" bug in `docs/effect_catalog.md` for
COMP — the catalog under-reports knob count (only 3 of 5 visible
COMP knobs were named). Our sweep gives the **address truth** for
every effect, complementing the manual-name lookup the catalog
generator was using. Combining the two:

- Catalog: knob NAMES per effect (from manual)
- This sweep: knob ADDRESSES + active-slot count per effect

A proper effect_catalog regeneration should fuse both.

## Per-TYPE table

See `captures/bts_full_sweep/per_type_table.md`. Excerpt:

```
| TYPE   | Effect       | Knobs | First addresses                              |
|--------|--------------|------:|----------------------------------------------|
| 0x00   | AC_SIM       |     4 | 0x10001107, 0x1000110B, 0x1000110F, 0x10001113|
| 0x01   | AC_RESO      |     3 | 0x10001107, 0x1000110B, 0x1000110F           |
| 0x08   | COMP         |     5 | 0x10001107, 0x1000110B, 0x1000110F, 0x10001113|
| 0x35   | WAH          |     5 | 0x10001107, 0x1000110B, 0x1000110F, 0x10001113|
| 0x52   | A_WAH        |     8 | 0x10001107, 0x1000110B, 0x1000110F, ...       |
| 0x1E   | (missing)    |     ? | 6 active param slots; needs BTS UI to name    |
| 0x1F   | (missing)    |     ? | DIV_MIX-tail pattern; likely DIV_MIX_BASS     |
```

Per-effect addresses are stride 4 starting at 0x10001107 (FxItem 0,
Param 2). For a different FxItem N, add `N * 0x200` to each address.

## What this changes for the catalog

`docs/effect_catalog.md` should be updated:

1. Add TYPE 0x1E and 0x1F to the enumeration. Mark them
   "needs name verification" until someone screenshots BTS with
   those TYPEs set.
2. Note the firmware-side TYPE clamp at 0x52 — useful for any
   parameter-validation logic.
3. Confirm the FxItem block returns 179 bytes ÷ 4 ≈ 44 param slots,
   even when only a few are knobs.

## Restore safety

The user's slot-0 patch was a WAH (TYPE 0x35) with specific knob
values. After the sweep, the restore phase wrote each parameter back
individually (32 × 4-byte DT1s) and verified byte-for-byte against
the pre-sweep snapshot. **Restore status: VERIFIED ✓.**

The session also confirmed that **bulk DT1 with a multi-byte payload
spanning the FxItem block is silently rejected past the first byte**
— per-parameter writes are required for any FxItem block restore.
This is a useful protocol detail not previously documented.
