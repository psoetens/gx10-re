# MIDI implementation diff: GX-100 v1 vs GX-100/GX-10 v2

A code-ready reference for branching firmware behaviour between the two
published Roland MIDI Implementation documents.

| | v1 | v2 |
|---|---|---|
| File | `docs/manuals/GX-100_MIDI_Imple_eng01_W.md` | `docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md` |
| Model | GX-100 | GX-100 / GX-10 |
| Date | March 3rd, 2022 | March 1st, 2026 |
| Version | GX-100 ver1.10 | GX-100 ver.2.04 / GX-10 ver.1.05 |
| Embedded chart date | — | September 19th, 2024 (GX-100 v2.00 / GX-10 v1.00) |

The Manufacturer ID (`41`) and 5-byte Model ID (`00 00 00 00 0B`) are
**identical** between v1 and v2 and between GX-100 and GX-10 — neither
identifies the product or firmware version on its own.

---

## 1. Detecting product and firmware version

### 1.1 Identity Reply layout

Both docs describe the Identity Reply with the same skeleton:

```
F0 7E dev 06 02 41 0B 04 00 00 nn 00 vv 00 F7
                  └──┬──┘ └─┬─┘ └─────┬─────┘
              dev family   number    sw rev #1..#4
              code         code      (4 bytes)
```

`nnH` is `Software revision level #1` (byte 10 of the payload after
`F0`). `vvH` is `Software revision level #3` (byte 12). Bytes #2 and #4
are documented as `00H`.

### 1.2 Conflicting interpretations of `nnH`

The v2 manual annotates byte 10 as a **product discriminator**:

> `nnH: Software revision level # 1 (GX-100:0 / GX-10:1)`
> *(GX-100_GX-10_MIDI_Imple_eng02_W.md, line 222)*

The v1 manual leaves byte 10 unannotated:

> `nnH: Software revision level # 1`
> *(GX-100_MIDI_Imple_eng01_W.md, line 222)*

This **conflicts** with `docs/firmware_versions.md`, which treats the
first sw-rev byte as the **major version number**:

```
01 00 ... -> firmware 1.0
01 05 ... -> firmware 1.05
02 00 ... -> firmware 2.0
02 04 ... -> firmware 2.04
```

Both readings happen to agree on GX-100 v2.04 (`nn=02`, major=2) and on
GX-10 v1.05 (`nn=01`, major=1) only because the major version *coincides*
with the product-id Roland chose. They diverge for any GX-100 firmware
with major !=2 (e.g. GX-100 v1.10 should report `nn=01` on the
"product" reading but `nn=01` only by coincidence — the v2 doc was
written when that firmware was already obsolete).

**Recommendation for code:** treat `(nn, byte11, vv, byte13)` as
`(major, minor, patch, build)` per `firmware_versions.md`, and derive
product from the **combination** of `(family_code=0x040B, major_version)`
plus a probe write/read to a v2-only address (e.g. RQ1 to
`[SystemCommon] 0x1B COLOR MODE` returns non-zero on v2). Do not rely
on byte 10 as a product flag alone.

### 1.3 Detection booleans

```
is_v2     := sw_rev_major >= 2 || (gx10_marker_seen)
is_gx10   := product_string contains "GX-10" (from device probe)
is_v1     := !is_v2

// Probe-based fallback if Identity Reply is ambiguous:
// RQ1 to 00 00 00 1B (1 byte). If COLOR MODE is non-trivially enumerated,
// the device is on v2 firmware. v1 firmware will return 0 (N/A fixed slot).
```

---

## 2. Removed `Setup*` region (entire `00 20 xx xx` bank)

Five sub-blocks present in v1, **removed** in v2. The v2 Address Map
jumps from `00 10 08 00 [PcmapPc bank3]` directly to
`10 00 00 00 [Memory (temporary)]`.

| Address      | Block name    | Total size | Notes                              |
|--------------|---------------|------------|------------------------------------|
| `00 20 00 00` | `[SetupTemp]`  | `0x05`    | Slot reserves 64 bytes             |
| `00 20 00 40` | `[SetupTemp2]` | `0x4E`    | FxItemResource 1..78               |
| `00 20 01 40` | `[SetupTemp3]` | `0x16A`   | FxItemResourceA/B/C 1..78          |
| `00 20 03 40` | `[SetupEfct]`  | `0x0D`    | LEVEL SELECT, USB MIX, AIRD        |
| `00 20 04 40` | `[SetupComm]`  | `0x12`    | INPUT/EQ/BPM                       |

**v2 firmware response is unspecified** — the doc is silent on what RQ1
to a deleted address returns. Most likely outcomes: silent drop or
out-of-range error. Code must gate all `00 20 xx xx` access on `is_v1`.

---

## 3. `[SystemCommon]` repurposed slots (base `00 00 00 00`, total size `0x2D` — unchanged)

In-place repurposing — no offset shift, no insertion. v1 firmware sees
zero in these slots; v2 firmware uses them.

| Offset | v1 name      | v1 bits      | v1 range | v2 name                              | v2 bits      | v2 range / enum                                 |
|--------|--------------|--------------|----------|---------------------------------------|--------------|--------------------------------------------------|
| `0x19` | N/A (fixed)  | `000a aaaa`  | `(0)`   | `BANK EXTENT MIN(GX-10)`              | `0aaa aaaa`  | `0..98` ; `U01..U66, P01..P33`                  |
| `0x1A` | N/A (fixed)  | `000a aaaa`  | `(0)`   | `BANK EXTENT MAX(GX-10)`              | `0aaa aaaa`  | `0..98` ; `U01..U66, P01..P33`                  |
| `0x1B` | N/A (fixed)  | `000a aaaa`  | `(0)`   | `COLOR MODE`                          | `0000 000a`  | `0..1` ; `TYPE 1, TYPE 2`                       |
| `0x1C` | N/A (fixed)  | `000a aaaa`  | `(0)`   | `SHOW AUTO OFF WARNING AT STARTUP`    | `0000 000a`  | `0..1` ; `ON(SHOW), OFF(HIDE)`                  |

Bit-mask: read 0x19/0x1A as 7-bit on v2, 5-bit on v1.

`BANK EXTENT MIN(GX-10)` / `BANK EXTENT MAX(GX-10)` are **pair
parameters** with deferred commit (same contract as the existing GX-100
pair at `0x09` / `0x0A`):

> The DT1 to each parameter is temporarily suspended, and the DT1 to
> the pair parameter final address automatically checks the pending
> parameters, and if there is no problem, the value is set. If the
> value is incomplete it will not be set.

---

## 4. `[SystemCommon]` enum changes at existing offsets

### 4.1 `0x07` TUNER TYPE — non-contiguous valid set on v2

```
v1: TUNER TYPE (0..2)   bits 0000 00aa   MONO+POLY, MONO, POLY
v2: TUNER TYPE (1, 3)   bits 0000 00aa   MONO, TT
```

v2 valid raw bytes are **{1, 3} only**. Value `0` (was MONO+POLY) and
value `2` (was POLY) are invalid on v2 firmware. Value `3` is invalid
on v1.

### 4.2 `0x0F` AUTO OFF — bit-width grew 1→3

```
v1: AUTO OFF (0..1)   bits 0000 000a   OFF, ON
v2: AUTO OFF (0..4)   bits 0000 0aaa   OFF, 10HOURS, 5HOURS, 1HOUR, 20MIN
```

A v1 client writing `1` (= "ON") to v2 firmware will set "10HOURS",
which is the v2 default-behaviour equivalent — coincidentally compatible.

### 4.3 Memory Number / BANK EXTENT (raw range `0..299`, semantics differ per product)

v2 description, **verbatim** (`GX-100_GX-10_MIDI_Imple_eng02_W.md`,
`[SystemCommon]` 0x00..0x03 and `[PcmapPc]` Program Change#N):

```
Memory Number (0 - 299)
  0.. 197, 198, 199, 200.. 298, 299
  GX-100:U01-1..U50-2,U50-3,U50-4,P01-1..P25-3,P25-4
  GX-10 :U01-1..U66-3, NIU, NIU,P01-1..P33-3, NIU
  * NIU : not in use
```

**GX-100 mapping** (50 user banks × 4 patches + 25 preset banks × 4 = 300):

```
raw 0..199    -> U01-1 .. U50-4   (200 user slots, 4 per bank)
raw 200..299  -> P01-1 .. P25-4   (100 preset slots, 4 per bank)
```

Decode:
```
if raw < 200: ("U", raw/4 + 1, raw%4 + 1)
else:         ("P", (raw-200)/4 + 1, (raw-200)%4 + 1)
```

**GX-10 mapping** (66 user banks × 3 patches + 33 preset banks × 3 = 297
in-use, with 3 NIU holes at raw 198, 199, 299):

```
raw 0..197    -> U01-1 .. U66-3   (198 user slots, 3 per bank)
raw 198, 199  -> NIU
raw 200..298  -> P01-1 .. P33-3   (99 preset slots, 3 per bank)
raw 299       -> NIU
```

Decode:
```
if raw == 198 or raw == 199 or raw == 299: NIU
if raw < 198: ("U", raw/3 + 1, raw%3 + 1)
else:         ("P", (raw-200)/3 + 1, (raw-200)%3 + 1)
```

`v1 Memory Number` description text differs from the above only
cosmetically; v2 GX-100 mapping should be treated as authoritative for
both v1 and v2 GX-100 firmware.

### 4.4 `BANK EXTENT MIN`/`MAX` ranges per product

| Variant         | Min addr  | Max addr  | Range  | Slot vocabulary                |
|-----------------|-----------|-----------|--------|--------------------------------|
| v1 / v2-GX-100  | `0x09`   | `0x0A`   | `0..74` | `U01..U50, P01..P25`           |
| v2-GX-10        | `0x19`   | `0x1A`   | `0..98` | `U01..U66, P01..P33`           |

GX-10 firmware ignores writes to `0x09`/`0x0A`; GX-100 ignores writes
to `0x19`/`0x1A`. Code should write the appropriate pair based on
detected product.

---

## 5. `[SystemControl]` (base `00 00 10 00`)

### 5.1 Total size

| Version | Size  |
|---------|-------|
| v1      | `0x64` |
| v2      | `0x66` (+2 bytes appended at offsets 0x64, 0x65) |

No internal shift; existing offsets 0x00..0x63 are byte-identical.

### 5.2 New params at end

| Offset | Name (v2)                    | Bits        | Range  | Enum                          |
|--------|------------------------------|-------------|--------|-------------------------------|
| `0x64` | `Down & Up Function(GX-10)`  | `0000 00aa` | `0..3` | `OFF, TUNER, DOWN, UP`        |
| `0x65` | `Up & Ctl1 Function(GX-10)`  | `0000 00aa` | `0..3` | `OFF, MANUAL, DOWN, UP`       |

GX-100 firmware presumably accepts but ignores writes here (doc does
not specify).

### 5.3 `0x34` CONTROL MODE — bit-width grew 1→2, range product-gated

```
v1:        CONTROL MODE (0..1)                       bits 0000 000a   MEMORY, MANUAL
v2-GX-100: CONTROL MODE (GX-100:0..1)                bits 0000 00aa   MEMORY, MANUAL
v2-GX-10:  CONTROL MODE (GX-10:0..3)                 bits 0000 00aa   MEMORY, MANUAL, BANK/NUM, MANUAL2
```

Raw byte `2` (BANK/NUM) and `3` (MANUAL2) are GX-10 only; GX-100
firmware on v2 still rejects them.

### 5.4 BANK arrow → BANK DOWN / UP rename (label only)

The byte values are unchanged; only the rendered string differs.

v1 source contains literal escape bytes `0x1B` (ESC) and `0x1A` (SUB)
as triangle-glyph placeholders:

```
v1 [SystemControl] 0x16: BankDown Function ... OFF, BANK \x1b, MEMORY -1, ...
v1 [SystemControl] 0x17: BankUp Function   ... OFF, BANK \x1a, MEMORY -1, ...
v2 [SystemControl] 0x16: BankDown Function ... OFF, BANK DOWN, MEMORY -1, ...
v2 [SystemControl] 0x17: BankUp Function   ... OFF, BANK UP,   MEMORY -1, ...
```

Same rename applies to enum index `1` and `2` of the Function lists at:

- `[SystemControl]` `0x16` (BankDown), `0x17` (BankUp), `0x1D..0x21` (Ctl1..Ctl4, Exp1Sw)
- `[MemoryCommon]`  `0x14`, `0x15`, `0x1B..0x1F` (Bank Down/Up + Ctl1..Ctl4, Exp1Sw)

**Not renamed in v2** (still uses `BANK\x1B` / `BANK\x1A` raw escapes
in the v2 doc text):

- `[SystemMidi]` `0x0C` `BANK\x1B CC#`
- `[SystemMidi]` `0x0D` `BANK\x1A CC#`

This is a doc inconsistency; the byte slots and semantics are unchanged.

---

## 6. `[SystemMidi]` (base `00 00 30 00`, total size `0x15` — unchanged)

Two fields gain a `(GX-100)` qualifier in v2 — they are **GX-100 only**;
GX-10 firmware ignores writes and is undefined on read:

| Offset | v2 name              | Range | Enum                                  |
|--------|----------------------|-------|---------------------------------------|
| `0x03` | `SYNC CLOCK(GX-100)` | `0..3` | `AUTO, INTERNAL, MIDI(AUTO), USB(AUTO)` |
| `0x05` | `USB IN THRU(GX-100)` | `0..3` | `OFF, MIDI OUT, USB OUT, USB & MIDI`   |

All other offsets (RX/TX CHANNEL, MIDI IN THRU, CLOCK OUT, MAP SELECT,
NUM1..4 CC#, BANK CCs, CTL1..4 CC#, EXP1 SW CC#, EXP1 CC#, EXP2 CC#)
are byte-identical between v1 and v2.

---

## 7. Effect TYPE enum — `[MemoryFxItem]` offset `0x00`, bits `0aaa aaaa`

v1: `TYPE (0..77)`. v2: `TYPE (0..82)`. Indices `0..77` are **byte- and
string-identical** between v1 and v2 (no reorderings).

v2 new entries (indices in append order):

| Raw | Effect name   |
|-----|---------------|
| 78  | `SLICER`     |
| 79  | `HUMANIZER`  |
| 80  | `FEEDBACKER` |
| 81  | `SITAR SIM`  |
| 82  | `AUTO WAH`   |

---

## 8. Knob / Assign TARGET tables — extension to 740

Two adjacent tables share the same target-id space. v1 range `0..701`,
v2 range `0..740`. The two tables **disagree** on indices `700`,
`701`; they agree on `0..699` and on `702..740`.

### 8.1 Knob target table (`[MemoryCommon]` `KNOB1..4 SETTING`, range `0..740`)

| Raw | Block | Param |
|-----|-------|-------|
| 700 | N/A | N/A |
| 701 | N/A | N/A |

### 8.2 Assign target table (`[Assign]` `TARGET`, range `0..740`)

| Raw | Block | Param |
|-----|-------|-------|
| 700 | MIDI | MIDI CC# |
| 701 | MIDI | MIDI PC# |

### 8.3 New entries `702..740` (identical in both tables)

| Raw | Block       | Param          |
|-----|-------------|----------------|
| 702 | SLICER      | PATTERN        |
| 703 | SLICER      | RATE           |
| 704 | SLICER      | TRIGGER        |
| 705 | SLICER      | EFFECT LEVEL   |
| 706 | SLICER      | ATTACK         |
| 707 | SLICER      | DUTY           |
| 708 | SLICER      | DIRECT MIX     |
| 709 | HUMANIZER   | MODE           |
| 710 | HUMANIZER   | VOWEL1         |
| 711 | HUMANIZER   | VOWEL2         |
| 712 | HUMANIZER   | SENS           |
| 713 | HUMANIZER   | RATE           |
| 714 | HUMANIZER   | DEPTH          |
| 715 | HUMANIZER   | MANUAL         |
| 716 | HUMANIZER   | LEVEL          |
| 717 | FEEDBACKER  | MODE           |
| 718 | FEEDBACKER  | TRIGGER        |
| 719 | FEEDBACKER  | DEPTH          |
| 720 | FEEDBACKER  | RISE TIME      |
| 721 | FEEDBACKER  | OCT RISE TIME  |
| 722 | FEEDBACKER  | FEEDBACK       |
| 723 | FEEDBACKER  | OCT FEEDBACK   |
| 724 | FEEDBACKER  | VIB RATE       |
| 725 | FEEDBACKER  | VIB DEPTH      |
| 726 | SITAR SIM   | SENS           |
| 727 | SITAR SIM   | DEPTH          |
| 728 | SITAR SIM   | TONE           |
| 729 | SITAR SIM   | EFFECT LEVEL   |
| 730 | SITAR SIM   | RESONANCE      |
| 731 | SITAR SIM   | BUZZ           |
| 732 | SITAR SIM   | DIRECT MIX     |
| 733 | AUTO WAH    | FILTER MODE    |
| 734 | AUTO WAH    | RATE           |
| 735 | AUTO WAH    | DEPTH          |
| 736 | AUTO WAH    | EFFECT LEVEL   |
| 737 | AUTO WAH    | FREQUENCY      |
| 738 | AUTO WAH    | RESONANCE      |
| 739 | AUTO WAH    | WAVEFORM       |
| 740 | AUTO WAH    | DIRECT MIX     |

### 8.4 Pre-existing knob/assign-table inconsistencies (v1 and v2 both)

These are **not v1→v2 changes** — they exist in both — but matter
for code that auto-derives strings from one table into the other:

| Raw | Knob table label                    | Assign table label                          |
|-----|-------------------------------------|----------------------------------------------|
| 644 | `RING MOD INTELLIGENT`             | `RING MODULATOR INTELLIGENT`                |
| 645 | `RING MOD FREQUENCY`               | `RING MODULATOR FREQUENCY`                  |
| 646 | `RING MOD MOD RATE`                | `RING MODULATOR MOD RATE`                   |
| 647 | `RING MOD MOD DEPTH`               | `RING MODULATOR MOD DEPTH`                  |
| 648 | `RING MOD EFFECT LEVEL`            | `RING MODULATOR EFFECT LEVEL`               |
| 649 | `RING MOD DIRECT MIX`              | `RING MODULATOR DIRECT MIX`                 |
| 690 | `SEND/RETURN RET LEVEL`            | `SEND/RETURN RETURN LEVEL`                  |
| 672–678 | `PRIME VIBARTO ...` (typo)     | `PRIME VIBARTO ...` (typo persists in v2)  |

Recommend canonical form `RING MODULATOR` and `SEND/RETURN RETURN
LEVEL` in any normalised internal representation.

---

## 9. Blocks unchanged between v1 and v2 (size and layout)

These can share a single struct definition across versions:

- `[SystemCommon]` size `0x2D` (only enum/repurpose changes; layout same)
- `[SystemMidi]` size `0x15`
- `[SystemEfct]` size `0x02`
- `[SystemInOut]` size `0x0D`
- `[SystemPitch]` size `0x07`
- `[SystemGlobalEq]` size `0x1B`
- `[SystemInputSetting]` size `0x12`
- `[PcmapPc]` size `0x400` (unchanged across all 3 banks)
- `[Memory]` outer layout
- `[MemoryEfct]` size `0x3E`
- `[MemoryFxItem]` size `0x133` (only the TYPE enum extends)
- `[MemoryLed]` size `0x1C`
- `[Assign]` size `0x2D` (only TARGET range extends)

---

## 10. Embedded MIDI Implementation Chart

End-of-doc summary chart is byte-identical between v1 and v2 except for
the model/version strings. CC ranges, PC ranges, sysex-enable flag,
and clock handling rows are all unchanged.

The v2 chart still carries date `September 19, 2024` and version
`GX-100 v2.00 / GX-10 v1.00` even though the doc body claims `2.04 /
1.05` from `March 1st, 2026` — the chart wasn't refreshed for the
2.04/1.05 errata. Treat the chart as accurate for the v2.00/v1.00
baseline only.

---

## 11. Code-branching reference

```c
/* Version booleans, derived per §1.3 */
bool is_v2;       /* firmware ver >= 2.0 (GX-100) or >= 1.0 (GX-10) */
bool is_gx10;     /* product is GX-10 */

/* === SystemCommon === */
const u32 SC_BASE = 0x00000000;

/* BANK EXTENT pair address */
u32 bank_extent_min = (is_v2 && is_gx10) ? SC_BASE + 0x19 : SC_BASE + 0x09;
u32 bank_extent_max = (is_v2 && is_gx10) ? SC_BASE + 0x1A : SC_BASE + 0x0A;
u8  bank_extent_max_value = (is_v2 && is_gx10) ? 98 : 74;

/* AUTO OFF */
u8 auto_off_max  = is_v2 ? 4 : 1;
u8 auto_off_bits = is_v2 ? 3 : 1;

/* TUNER TYPE valid set (non-contiguous on v2) */
const u8 tuner_v1[] = {0,1,2};        /* MONO+POLY, MONO, POLY */
const u8 tuner_v2[] = {1,3};          /* MONO, TT */

/* v2-only fields */
bool color_mode_present       = is_v2;     /* SC_BASE + 0x1B */
bool auto_off_warn_present    = is_v2;     /* SC_BASE + 0x1C */

/* Memory Number decode -> see §4.3 */

/* === SystemControl === */
const u32 SCTL_BASE = 0x00001000;
u8 sysctrl_size = is_v2 ? 0x66 : 0x64;

/* CONTROL MODE */
u8 control_mode_max = is_v2 ? (is_gx10 ? 3 : 1) : 1;
u8 control_mode_bits = is_v2 ? 2 : 1;

/* GX-10-only footswitch fns */
bool down_up_fn_present  = is_v2 && is_gx10;   /* SCTL_BASE + 0x64 */
bool up_ctl1_fn_present  = is_v2 && is_gx10;   /* SCTL_BASE + 0x65 */

/* === SystemMidi === */
bool sync_clock_writable = !(is_v2 && is_gx10);   /* GX-100 only on v2 */
bool usb_in_thru_writable = !(is_v2 && is_gx10);

/* === Setup region (00 20 xx xx) === */
bool setup_region_present = !is_v2;   /* gone entirely in v2 */

/* === Effect TYPE enum === */
u8 fx_type_max = is_v2 ? 82 : 77;     /* 78..82 = SLICER, HUMANIZER, FEEDBACKER, SITAR SIM, AUTO WAH */

/* === Knob / Assign TARGET === */
u16 target_max = is_v2 ? 740 : 701;
/* On v2: knob_target[700,701] = N/A; assign_target[700]=MIDI CC#, [701]=MIDI PC#; both share 702..740 */

/* === Bank-arrow strings (display only) === */
const char *bank_down_label = is_v2 ? "BANK DOWN" : "BANK \x1b";
const char *bank_up_label   = is_v2 ? "BANK UP"   : "BANK \x1a";
```

---

## 12. Source files

- `docs/manuals/GX-100_MIDI_Imple_eng01_W.md` — v1 (GX-100 ver1.10, 2022-03-03)
- `docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md` — v2 (GX-100 ver.2.04 / GX-10 ver.1.05, 2026-03-01)
- `docs/firmware_versions.md` — host-side version detection convention (Identity Reply parsing, `min_firmware` per-parameter tagging)
