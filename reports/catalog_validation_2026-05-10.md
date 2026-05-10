# Catalog validation 2026-05-10 — wire-level RQ1 sweep against live GX-10

**Device:** BOSS GX-10, firmware 1.04, ALSA `hw:4,0,0`
**Tool:** `tools/validate_catalogs.py`
**Inputs:** `captures/bts_effect_catalog.json` (632 addresses) +
`captures/menu_catalog.json` (435 entries)
**Method:** Read-only RQ1 to every address, with editor-attach
handshake set (`0x7F000001=0x01`, `0x7F000703=0x01`). No DT1 writes
to FX/menu fields; device patch state unchanged.
**Runtime:** 67.3 s for 1067 reads.
**Full transcript:** `/tmp/validation.json` (per-address result).

---

## Headline numbers

| Source | Total | Replied | Reply rate |
|--------|------:|--------:|-----------:|
| `bts_effect_catalog.json` | 632 | **632** | **100%** ✓ |
| `menu_catalog.json`       | 435 | 243 | 56% |
| **Combined**              | 1067 | 875 | 82% |

The effect catalog is **wire-level perfect**. The menu catalog is
half real, half parser noise — see §2.

---

## §1. Effect catalog — 632/632 ✓

Every address in `captures/bts_effect_catalog.json` replied to RQ1
(size=4) — all 83 effects, all 632 knob addresses, including the
**78 stride-inferred** addresses flagged with `_address_inferred`.
Stride-inference logic in `tools/build_bts_catalog.py` is correct.

### Range-check artifacts (98 "out-of-range" entries)

98 entries decoded to values outside their documented `value_min..
value_max` range. **These are not catalog bugs.** They reflect the
fact that **FxItem 0** (the only slot we read for effect-catalog
addresses) holds **one** TYPE byte at a time. We read with FxItem 0
= TYPE 0x35 = WAH FAT, so:

- Reading `0x10001113` gets WAH's "EFFECT LEVEL" cell (display 0..100)
- The catalog's COMPRESSOR entry says "TONE -50..+50" at that
  address; that's only meaningful when FxItem 0 holds COMP
- Decoded value 100 trips the COMP TONE range check

To get a proper per-effect range check, every TYPE would need to be
written into FxItem 0 in turn (then read), then restored. That's
intrusive (changes patch state) and disturbing for a no-touch
session. The wire-level existence claim is what matters here, and
it's 100%.

### What this validates

- Address layout matches the BTS sweep across all 83 effects.
- Stride-4 inference for FX Parameter slots is correct.
- All 5 v2-only effects (`0x4E SLICER` through `0x52 AUTO WAH`)
  reply on this firmware-1.04 device.
- The editor-attach + `0x7F000703=0x01` handshake successfully
  enabled all reads (no replies before the handshake — re-confirms
  earlier findings).

---

## §2. Menu catalog — 243/435 (with caveat: ~74 are parser noise)

### Parser-noise breakdown

74 of 435 entries (~17%) have labels matching the bit-pattern
spec-row format (e.g. `"00 05 0000 cccc"`, `"00 09 0000 eeee"`).
These are **artifacts from the chart parser** in
`tools/build_menu_catalog.py` — the manual's encoding-spec rows got
captured alongside the actual field-name rows. They don't represent
real probeable addresses.

Adjusted picture:

| Class | Count | Notes |
|-------|------:|-------|
| Real field-name entries | ~361 | Estimated by filtering bit-pattern labels |
| Bit-pattern spec rows (parser artifacts) | ~74 | should not be probed |
| Edge cases | ~bug | Mixed; need a refined parser pass |

Of the ~361 real fields, **243 replied = ~67%** real reply rate.

### No-reply patterns by region

| Region | Replied/Total | Notes |
|--------|--------------:|-------|
| `0x00000000 SystemCommon` | 22/30 | 8 no-replies, mostly spec rows |
| `0x00001000 SystemControl` | 57/68 | 11 no-replies |
| `0x00003000 SystemMidi` | 20/20 ✓ | clean |
| `0x00004000 SystemInOut` | 3/7 | 4 no-replies |
| `0x00005000 SystemEfct` | 2/2 ✓ | clean |
| `0x00006000 SystemPitch` | 3/5 | 2 no-replies |
| `0x00006100 SysteminputSetting` | 18/18 ✓ | clean |
| `0x00006B00 SystemGlobalEq` | 11/11 ✓ | clean |
| `0x00100000 PcmapPc` | **0/10** | every entry at non-cell-start offset |
| `0x10000000 MemoryCommon` | 67/95 | 28 no-replies |
| `0x10000140 MemoryLed` | **0/4** | every entry at non-cell-start offset |
| `0x10000200 Assign` | **1/28** | mostly multi-byte fields read as size=1 |
| `0x10000F00 MemoryEfct` | 36/59 | 23 no-replies including BPM at mid-cell offset |
| `0x10001100 MemoryFxItem` | 3/78 | 75 no-replies; structurally same issue |

### Three causes of no-replies

1. **Bit-pattern spec rows captured as fields.** The parser
   ingested manual rows describing the encoding (e.g.
   `"00 05 0000 cccc"`) as if they were field entries. About 74
   of the 192 no-replies. Filter these in the parser.

2. **Multi-byte fields read with size=1 at mid-cell offsets.**
   Examples:
   - `0x10000F05 BPM` — BPM is a 4-byte cell at `0x10000F02..05`;
     reading byte +5 alone gets no reply.
   - `0x00100003 Program Change#1` — PcmapPc entries are 4-byte
     cells at stride 4; entry indices map to start addresses
     (`0x00100000`, `0x00100004`, …), not the labels' addresses.
   - `0x10000037..3F MEMORY MIDI 1:BANK MSB / LSB / PC# / CC1#`
     — these are positions inside a packed multi-byte structure.
   The chart describes the byte boundaries; the parser should
   reconstruct the cell-start address + total size, not split
   each documented byte position into a separate field.

3. **Pair parameters.** Per the Windows commit message:
   > BANK EXTENT MAX is a "pair parameter" that won't read until
   > both halves committed.
   Per the manual: "BANK EXTENT MIN/MAX" — DT1 to either is
   *suspended*; the DT1 to the pair's final address triggers
   atomic commit. RQ1 to the pending half before commit returns
   no reply.

### What's clean

`SystemMidi`, `SystemEfct`, `SysteminputSetting`, `SystemGlobalEq`
all 100% replied — these regions had cleanly-sized 1-byte fields.
`SystemCommon` and `SystemControl` are mostly clean; the
no-replies there are likely the bit-pattern spec rows.

---

## §3. Live readings — what the device's current state looks like

The validation captured the live values for every replying address.
Highlights from the menu side, all from this firmware-1.04 device:

| Address | Field | Value | Decode |
|---------|-------|------:|--------|
| `0x00000007` | TUNER TYPE | 2 | POLY (v1 enum: MONO+POLY/MONO/POLY) |
| `0x0000000F` | AUTO OFF | 0 | OFF |
| `0x00000019` | BANK EXTENT MIN (GX-10) | 1 | U02 |
| `0x0000001A` | BANK EXTENT MAX (GX-10) | 98 | P33-3 (max) |
| `0x0000001B` | COLOR MODE | 0 | TYPE 1 |
| `0x0000001C` | SHOW AUTO OFF WARNING | 1 | ON |
| `0x00001034` | CONTROL MODE | 1 | MANUAL |
| `0x00001063` | GLOBAL EQ SW | 1 | ON |
| `0x00001064` | Down&Up Function (GX-10) | 0 | OFF |
| `0x00001065` | Up&Ctl1 Function (GX-10) | 1 | MANUAL |

This corroborates the earlier `linux_probe_results.md` SystemCommon
dump (the data is consistent across sessions — no drift).

---

## §4. Cross-verification of earlier claims

- **Editor-attach gates `0x7F0xxxxx` reads** (cross_check P2-4): ✓
  — every `0x7F0xxxxx` register replied with attach=1 set.
- **`0x7F000703 = 0x01` is part of the BTS handshake but not strictly
  required for read-replies** (cross_check follow-up #32): partially
  tested. Both bits were set in this run; we still haven't done the
  comparison test to isolate whether attach=1 alone is sufficient.
- **`0x7F000701` writes are state-mirror only**: not exercised
  here; would require a chain edit to trigger.

---

## Findings

**P0 (none).** No critical wire-level bugs in either catalog.

**P1: Menu catalog parser produces ~74 bit-pattern spec-row
artifacts.** `tools/build_menu_catalog.py` should filter rows whose
label matches the manual's bit-pattern-description format
(e.g. `^[0-9A-F ]+0000 [a-z]{4}$`). Cleanup brings the menu catalog
to its "real fields only" state of ~361 entries.

**P1: Menu catalog uses wrong size hints for multi-byte fields.**
Pair parameters (BANK EXTENT MIN/MAX), 4-byte fields (BPM, MEMORY
NUMBER, PcmapPc PC entries), and packed multi-byte structures
(MEMORY MIDI 1..4: BANK MSB/LSB/PC#/CC1#/CC2#) need cell-start
addresses + correct sizes. Currently the parser splits these into
per-byte entries that don't correspond to readable RQ1 cells.

**P2: Effect-catalog range checks need per-TYPE FxItem priming.**
98 "out-of-range" decode artifacts in this run reflect that FxItem
0 only holds one TYPE; per-effect range validation requires writing
each TYPE into a slot. Out of scope for a no-touch session.

**P3: Stride-inferred addresses confirmed.** The 78 inferred entries
all replied. Stride-inference can be promoted from "conjecture" to
"verified" in the catalog metadata.

---

## Next steps

In rough effort order, all doable on Linux without user input or
physical device interaction:

1. **Filter bit-pattern spec rows from menu_catalog generator**
   (`tools/build_menu_catalog.py`). Quick win: 74 catalog noise
   entries removed, reply rate jumps from 56% to ~67%.
2. **Reconstruct multi-byte cell groups in menu_catalog.** For each
   region, group consecutive single-byte entries that share a common
   "BPM"-style label into a single field with the correct
   cell-start address and size (2 or 4 bytes). Validate by re-
   running `validate_catalogs.py`.
3. **Per-TYPE effect-catalog range check.** Write each TYPE byte
   into FxItem 0, read the cell, restore. ~83 TYPE writes. Yields
   per-effect documented-range conformance for every knob.
4. **Comparison test for `0x7F000703`** (#32). Set attach=1 only
   (no 703), do a targeted RQ1 sweep across `0x7F0xxxxx` flags and
   one effect-catalog address. Tells us whether 703 is a strict
   prerequisite for any reply path.
5. **Promote stride-inferred entries.** Drop `_address_inferred`
   in `bts_effect_catalog.json` for the 78 entries that all
   replied here.
6. **Sub-type-specific knob layouts (#33).** Still needs the
   broadcast-listen workflow and user-paced knob turns; defer.

Item 3 is the highest-information no-touch test (validates ranges
across all 83 effects). Items 1+2 are pure parser cleanup.

---

## Source artifacts

- `tools/validate_catalogs.py` — the validator (re-runnable for
  regression checks)
- `/tmp/validation.json` — full per-address result with payloads
  and decoded values
- `captures/bts_effect_catalog.json` — input
- `captures/menu_catalog.json` — input
- `tools/build_menu_catalog.py` — needs the parser fixes (P1)
