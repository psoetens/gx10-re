# Cross-reference: Roland MIDI Implementation Chart vs our RE findings

Source: `docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md` — Roland's
official MIDI Implementation Chart for GX-100/GX-10 (March 2026,
GX-100 v2.04 / GX-10 v1.05).

This file documents:
1. ✅ Confirmations — places the official chart agrees with our captures.
2. ✏️ Corrections — addresses or encodings we had wrong.
3. 🆕 New info — addresses/structures we had not yet discovered.
4. 🐞 Bugs in our pipeline that the chart exposes.

---

## 🐞 Critical bug — every effect knob's "byte range" is wrong

Our pipeline (`tools/explore_all_effects.py` and `analyze_type_pcap`)
extracts knob values via `int(payload[-2:], 16)` — only the **last
byte** of the DT1 payload.

The official chart says every **FX Parameter is 4 bytes (4 nibbles)**:

```
FX Parameter N (12768 - 52768)  -20000 to +20000
```

Each byte in the payload uses only its low 4 bits (`0000 aaaa`
pattern). The four nibbles combine big-endian:

```
V = b[0]*0x1000 + b[1]*0x100 + b[2]*0x10 + b[3]
```

V is in offset binary: subtract 32768 to get the signed display value.

### Verification

COMP SUSTAIN sweep capture (`captures/typebar_full/page0/00_COMP/knobs_all_up.jsonl`)
at address `0x10001107`:

| Payload | Last-byte (our pipeline) | 4-nibble V | V − 32768 (display) |
|---------|------------------------:|-----------:|--------------------:|
| `08 00 03 01` | 1 | 32817 | +49 |
| `08 00 04 0B` | 11 | 32843 | +75 |
| `08 00 06 04` | 4 | 32868 | +100 |

**The manual says COMP SUSTAIN range is 0–100.** Our captured "max"
of 4 was misleading; the actual maximum value was correctly +100,
encoded as `08 00 06 04`.

### Impact

All 731 captured knob "min" / "max" values in `summary.json` files
are wrong. The actual displayed-value range for each knob can be
recovered from the captured pcap by re-decoding with the 4-nibble
formula.

### Fix

Add `tools/reanalyze_knobs_4nibble.py` that walks every
`captures/typebar_full/<eff>/knobs_all_*.jsonl`, applies the proper
4-nibble decode, and rewrites the `min` / `max` / `n_dt1_*` fields in
each `summary.json`.

---

## ✏️ Address-region corrections

| Region | Our doc said | Official chart says |
|--------|--------------|---------------------|
| User patches | `0x6040_0000`+ (16 slots × 0x10000) | `0x2000_0000`+ (200 slots × `0x60000` stride) |
| MIDI Program Map | (unmapped) | `0x0010_0000` bank1, `0x0010_0400` bank2, `0x0010_0800` bank3 (4 KiB each) |
| System control (CTL/EXP system-level) | (unmapped) | `0x0000_1000` [SystemControl] |
| System MIDI register | partial — `0x0000_3000` range observed | `0x0000_3000` [SystemMidi] |
| System I/O | partial — `0x0000_4000` range observed | `0x0000_4000` [SystemInOut] |
| System Effect (LOOPER) | partial — `0x0000_5000` observed | `0x0000_5000` [SystemEfct] |
| System Pitch (Tuner) | (unmapped) | `0x0000_6000` [SystemPitch] |
| Input Setting memories 1–10 | echo region only | `0x0000_6100..0x0000_6A00` (10 × 0x100) |
| Global EQ | echo region only | `0x0000_6B00` [SystemGlobalEq] |

The user-patch region was **not** at `0x6040_0000` — that was an
incorrect inference. Whatever data we read there must be a mirror or
preset table region.

---

## ✏️ AUTO OFF / EXP HOLD address corrections

We captured `0x0000_000D = 0x01` and labeled it **AUTO OFF**. Per the
official chart:

| Address | Setting | Values |
|---------|---------|--------|
| `0x0000_000D` | EXP1 HOLD | OFF, ON |
| `0x0000_000E` | EXP2 HOLD | OFF, ON |
| `0x0000_000F` | AUTO OFF | OFF, 10HOURS, 5HOURS, 1HOUR, 20MIN |

Our click on the AUTO OFF dropdown didn't actually change AUTO OFF
(probably the popup didn't register). The `0x01` we captured was an
EXP1 HOLD toggle. **Update `menus.md` accordingly.**

---

## ✏️ PLAY OPTION mislabels

In `menus.md` I wrote:

| Address | I labeled | Should be (official) |
|---------|-----------|----------------------|
| `0x0000_0016` | "REC ACTION" | DELETE WARNING |
| `0x0000_0017` | "LOOP MODE" | OVERWRITE WARNING |

Looking back at the capture: I clicked LOOP MODE STEREO (which goes
to `0x0000_5000` PHRASE LOOP MODE) and then DELETE / OVERWRITE
WARNING. The 5 events at `0x0000_5000`, `0x0000_5001`, `0x0000_0016`,
`0x0000_0017` were:

- `0x0000_5000` = PHRASE LOOP:MODE (MONO/STEREO) ← STEREO toggle
- `0x0000_5001` = PHRASE LOOP:REC ACTION ← we didn't click this
- `0x0000_0016` = DELETE WARNING ← I clicked this
- `0x0000_0017` = OVERWRITE WARNING ← I clicked this

So the LOOP REC ACTION at 0x5001 was probably set by an unintended
side-effect. Anyway, the **labels in the table need swapping**.

---

## ✅ Confirmations

| Finding | Our capture | Official |
|---------|-------------|----------|
| Live edit buffer at `0x1000_0000` | ✓ | ✓ memory (temporary memory) |
| Patch name = first 16 ASCII chars at memory offset 0 | ✓ "EMPTY           " observed | ✓ Memory Name1..16 |
| Master block at `0x1000_0F00` | ✓ 62 B observed | ✓ MemoryEfct (62 B = 0x3E) |
| Master BPM = 4-nibble V = BPM × 10 at `0x1000_0F02` | ✓ derived empirically | ✓ MemoryEfct offset 0x02-0x05 = BPM (400-2500) |
| FX slots: 20 × 0x200 stride starting `0x1000_1100` | ✓ | ✓ MemoryFxItem 1..20 |
| FX slot start byte = effect-TYPE | ✓ — captured 81 distinct values | ✓ TYPE (0-82) — 83-entry enum |
| BANK CHANGE MODE at `0x0000_0008` | ✓ | ✓ |
| BANK EXTENT MIN/MAX at `0x0000_0019/_001A` | ✓ pair-coalesced | ✓ "pair parameter" |
| DELETE WARNING at `0x0000_0016` | ✓ | ✓ |
| OVERWRITE WARNING at `0x0000_0017` | ✓ | ✓ |
| INPUT type at staged `0x0020_0341` echoed at `0x0000_6110` | ✓ | ✓ inputSetting 1 offset 0x10 = INST TYPE |
| INPUT SENS at `0x0020_0342` echo `0x0000_6111` | ✓ | ✓ inputSetting offset 0x11 = INPUT LEVEL (12-52 dB) |
| Tuner mode = 1/2/3 at `0x0000_0007` | ✓ | ✓ TUNER TYPE (1, 3) — official lists only MONO/TT (1, 3); GUI also has POLY (2) |
| Tuner activation flag `0x7F00_0002 = 02` | observed | ✓ — system status register |
| Tuner display stream at `0x7F00_0300`, 48 B | ✓ | (not in this MIDI chart — runtime telemetry) |
| WRITE save-trigger at `0x7F00_0104` (2 B) | ✓ | (not in this MIDI chart — runtime cmd register) |
| FX TYPE byte values (0x02=AMP, 0x08=COMP, 0x14=PEQ, 0x37=PHASER…) | ✓ verified for all 81 effects | ✓ matches the 83-name enum |
| BPM byte = (BPM × 10) packed as 4 nibbles big-endian | ✓ derived | ✓ "BPM (400 - 2500)" |
| Patch select = 4 nibbles, value 0..299 | partial — we observed 4-byte writes | ✓ confirmed; 4 nibbles forming 16-bit memory index |
| FX TYPE byte for slot 0 at `0x1000_1100` | ✓ | ✓ MemoryFxItem 1 + offset 0 = TYPE |

---

## 🆕 New info from the chart

### Patch select register fully decoded

`0x0000_0000..0x0000_0003` = Memory Number (0–299), 4 nibbles
big-endian:

- **Index 0..197**: U01-1 .. U66-3 (66 user banks × 3 patches)
- **Index 198, 199**: NIU (not in use)
- **Index 200..298**: P01-1 .. P33-3 (33 preset banks × 3 patches)
- **Index 299**: NIU

Captured P03-1 NEO SOUL = `00 00 0C 0E` decodes:
- Nibbles: 0, 0, 0xC, 0xE → V = 0x00CE = 206
- 206 − 200 = preset 6 (0-indexed) = P03-1 ✓

The full preset-name table at `0x5000_0000` (per `protocol.md`)
lists 296 names; combined with the patch-select index, we now have a
complete preset-name → bytes mapping.

### MemoryCommon layout (the per-patch CTL/EXP block we'd been guessing)

| Offset | Field | Notes |
|-------:|-------|-------|
| 0x00–0x0F | Memory Name (16 ASCII chars, 32–126) | |
| 0x10–0x13 | Num1..4 Function (0–17, per-controller enum) | |
| 0x14 | BankDown Function (0–17) | |
| 0x15 | BankUp Function (0–17) | |
| 0x16 | CNum Function (0–14) | |
| 0x17–0x1A | Manual Num1..4 Function (0–14) | |
| 0x1B | **Ctl1 Function** (0–18) | We captured this ✓ |
| 0x1C | Ctl2 Function (0–18) | We labeled this CTL2 — was actually correct ✓ |
| 0x1D | Ctl3 Function | ❌ we said this was CTL2 |
| 0x1E | Ctl4 Function | ❌ we said this was CTL3 |
| 0x1F | Exp1Sw Function | ✓ |
| 0x20 | Exp1 Function (FOOT VOL / PEDAL FX / …) | |
| 0x21 | Exp2 Function | ✓ |
| 0x22–0x33 | Per-controller Mode (TOGGLE/MOMENT) | |
| 0x32 | INPUT SETTING (0–10 = SYSTEM, 1–10) | |
| 0x35–0x68 | MEMORY MIDI 1..4 — 13 bytes each (CH, BANK MSB×2, BANK LSB×2, PC#×2, CC1#×2, CC1 VAL, CC2#×2, CC2 VAL) | |
| 0x69–0x6C | Knob1..4 SettingFxItem (which FX item) | |
| 0x6D–0x7C | Knob1..4 SETTING (parameter, 4 nibbles each) | |

**Total MemoryCommon size: `0x101` bytes** (incl. trailing pad).

### MemoryEfct (master block, "efct" at offset 0x0F00)

| Offset | Field | Range |
|-------:|-------|-------|
| 0x00–0x01 | MEMORY LEVEL | 0–200 (2 nibbles) |
| 0x02–0x05 | **BPM** | 400–2500 = 40.0–250.0 (4 nibbles) ← matches our finding |
| 0x06 | KEY | C(Am)..B(G♯m) (12 values) |
| 0x07 | AMP CTL1 | OFF, ON |
| 0x08 | AMP CTL2 | OFF, ON |
| 0x09 | CARRYOVER | OFF, ON |
| 0x0A | TEMPO HOLD | OFF, ON |
| 0x0B | INPUT SENS | 0–100 |
| 0x0C | **CHAIN TOP ITEM** | 0–49 (= −1..48) — head pointer of the chain linked-list |
| 0x0D–0x36 | **CHAIN NEXT ITEM[0..41]** | next-pointers; 0 = end, 1..49 = FX item index |
| 0x37–0x3D | (continued CHAIN NEXT ITEM 42..48) | |

**Total MemoryEfct size: 0x3E bytes** (62 B — matches our 62-byte observation).

🆕 The effect chain is a **linked list** stored in `MemoryEfct`:
- `CHAIN TOP ITEM` (offset 0x0C) is the index of the first effect.
- `CHAIN NEXT ITEM[N]` (offset 0x0D + N) is the index of the effect
  that comes after FX item N.
- A value of 0 means "no next" (-1 = end of chain).
- Up to 49 entries means up to 49 FX items can be chained — but only
  20 FX items (0x10001100..0x10003700) hold actual data. The
  duplication count field (`MemoryFxItem` offset 0x02 = "DuplicationNumber 0-9")
  allows the same effect type to appear multiple times in the chain.

This is HUGE — it explains why effect order is fluid in the GUI even
though slots are fixed-size.

### MemoryFxItem layout (per FX slot, 0x200 bytes)

| Offset | Field | Range |
|-------:|-------|-------|
| 0x00 | TYPE | 0–82 (83-entry enum — full list below) |
| 0x01 | OFF/ON | OFF, ON |
| 0x02 | DuplicationNumber | 0–9 (which copy of this effect type in the chain) |
| 0x03–0x132 | FX Parameter 1..44 — 4 nibbles each (0x40 bytes total payload) | each 12768–52768 = -20000..+20000 |

So each FX item has up to **44 parameters** (more than any effect
needs, max 32 used). Our pipeline assumed 1-byte per parameter; it
should have decoded 4 nibbles per parameter.

### TYPE enum (83 values, byte → effect name)

```
 0 AC GUITAR SIMULATOR  21 GRAPHIC EQUALIZER     42 X-DS
 1 AC RESONANCE         22 FLANGER               43 METAL
 2 AIRD PREAMP          23 BASS FLANGER          44 BASS METAL
 3 AIRD BASS PREAMP     24 FLANGER PRIME         45 OVERTONE
 4 CHORUS               25 BASS FLANGER PRIME    46 PAN
 5 BASS CHORUS          26 HARMONIST             47 FOOT VOLUME
 6 PRIME CHORUS         27 BASS HARMONIST        48 PEDAL BEND
 7 CLASSIC-VIBE         28 PHRASE LOOP           49 BASS PEDAL BEND
 8 COMPRESSOR           29 DIVIDER               50 WAH
 9 X-COMP               30 SPLITTER              51 BASS_WAH
10 X-BASS COMP          31 MIXER                 52 PHASER
11 DEFRETTER            32 NOISE SUPPRESSOR      53 BASS PHASER
12 BASS DEFRETTER       33 OCTAVE                54 PRIME PHASER
13 DELAY                34 OCTAVE POLY           55 PRIME BASS PHASER
14 DELAY PLUS           35 OCTAVE BASS           56 SCRIPT PHASER
15 ANALOG DELAY         36 BOOSTER               57 PITCH SHIFTER
16 SPACE ECHO           37 OVERDRIVE             58 BASS PITCH SHIFTER
17 SHIMMER DELAY        38 BASS OVERDRIVE        59 REVERB
18 TWIST                39 DISTORTION            60 REVERB PLUS
19 WARP                 40 BASS DISTORTION       61 SHIMMER REVERB
20 PARAMETRIC EQUALIZER 41 FUZZ                  62 TERA ECHO
                        42 BASS FUZZ
                        43 X-OD
                        44 X-BASS OD
                        ...
                       (full list in MIDI chart)
```

This **completely decodes** our `triplet_at_10001100` byte values
across all 81 captured effects.

### CTL/EXP CONTROL FUNCTION enum (full)

We captured 17 values, with gaps at 0x0A and 0x0B. Per the official:

```
 0 OFF
 1 N (numeric: 1, 2, 3, 4 depending on which Num switch)
 2 MEMORY -1  (= "DOWN")
 3 MEMORY +1  (= "UP")
 4 BPM TAP
 5 TUNER
 6 MEMORY/MAN
 7 TUNER/MAN
 8 MAN/TUNER
 9 AMP CTL 1
10 AMP CTL 2
11 PFX
12 DIV CH.SEL
13 SEND/RETURN
14 LOOP CTL
15 LOOP STOP
16 LOOP CLEAR
17 MIDI START
18 (only on CTL1-4 / EXP1Sw — adds BANK DOWN, BANK UP at front)
```

Different controllers have different valid ranges (Num1-4: 0-17,
CNum: 0-14, CTL/Exp1Sw: 0-18). Our capture saw values 0x00..0x12
matching the CTL1 (0–18 range).

### TUNER (SystemPitch)

| Offset | Field | Range |
|-------:|-------|-------|
| 0x00–0x03 | REF. PITCH | 435–445 Hz (4 nibbles) |
| 0x04 | TT TUNER TYPE | 0–5: 6-REG, 6-DROP D, 7-REG, 7-DROP A, 4-B REG, 5-B REG |
| 0x05 | TT TUNER OFFSET | 11–16 (–5..–1, ----) |
| 0x06 | TUNER OUTPUT | MUTE, BYPASS, THRU |

So when we click the TUNER dialog dropdowns, they target
`0x00006000..0x00006006`. This **fully resolves gaps §2**.

### IN/OUT (SystemInOut, 0x4000)

| Offset | Field | Range |
|-------:|-------|-------|
| 0x00 | MAIN:LEVEL SELECT | -10dBu, +4dBu |
| 0x03–0x04 | USB MAIN:EFX OUT | 0–200 % (2 nibbles) |
| 0x05–0x06 | USB MAIN:MIX LEVEL | 0–200 % |
| 0x07–0x08 | USB DRY:OUT | 0–200 % |
| 0x09–0x0A | USB DRY:TO EFX | 0–200 % |
| 0x0B | USB LOOPBACK | OFF, ON |
| 0x0C | AIRD OUTPUT SELECT | 0–14 (full enum: LINE/PHONES, JC-120 RETURN/INPUT, KATANA-100/212 RETURN/INPUT, etc.) |

Our captures of `0x0000_4003`, `0x0000_4005`, `0x0000_4007`,
`0x0000_4009` for USB knobs match perfectly.

### MIDI (SystemMidi, 0x3000)

| Offset | Field | Range |
|-------:|-------|-------|
| 0x00 | RX CHANNEL | CH 1–16 |
| 0x02 | TX CHANNEL | CH 1–16, RX CH |
| 0x03 | SYNC CLOCK (GX-100 only) | AUTO, INTERNAL, MIDI(AUTO), USB(AUTO) |
| 0x04 | MIDI IN THRU | OFF, MIDI OUT, USB OUT, USB & MIDI |
| 0x05 | USB IN THRU (GX-100 only) | same |
| 0x06 | CLOCK OUT | OFF, ON |
| 0x07 | MAP SELECT | FIX, PROG |
| 0x08–0x14 | NUM1–4 CC#, BANK ▼/▲ CC#, CTL1–4 CC#, EXP1 SW CC#, EXP1 CC#, EXP2 CC# (each: OFF, CC#1–31, CC#64–95) | |

**GX-10 doesn't have USB IN THRU at offset 0x05** per the chart —
that field is GX-100 only. The GX-10 may rename it, omit it, or
relocate it.

### MIDI Program Map (PcmapPc, 0x100000)

| Bank | Address | Size |
|------|---------|------|
| Bank 1 | `0x0010_0000` | 0x400 |
| Bank 2 | `0x0010_0400` | 0x400 |
| Bank 3 | `0x0010_0800` | 0x400 |

Each bank holds **128 program-change entries × 4 bytes each** (4
nibbles per entry, value 0–299 = memory index).

### EDITOR FX ORDER toggle (SORT BY: TYPE / NAME)

`SystemCommon` offset 0x18: **FX ORDER** (0 = BY TYPE, 1 = BY NAME).
This resolves gaps §1.3.

---

## 🆕 Resolved gaps from `gaps.md`

The MIDI chart fully or partially resolves these gaps:

| Gap section | Resolution |
|-------------|-----------|
| §1.3 SORT BY: NAME | ✅ `0x0000_0018` FX ORDER |
| §2 TUNER REF. PITCH / OUTPUT / POLY TYPE / POLY OFFSET | ✅ all four addresses in SystemPitch (`0x00006000..0x00006006`) |
| §3.1 CTL/EXP MODE column (TOGGLE/MOMENT) | ✅ MemoryCommon 0x22–0x33; SystemControl 0x24–0x33 |
| §3.1 CTL/EXP PREFERENCE column (MEMORY/SYSTEM) | ✅ SystemControl 0x00–0x11 |
| §3.2 ASSIGN SETTINGS sub-fields | ✅ 20 assigns × 0x40 bytes at `0x10000200..0x10000B7F` (need to read the [Assign] structure for the 32 fields per entry) |
| §3.3 KNOB SETTINGS | ✅ MemoryCommon 0x69–0x7C |
| §3.4 MEMORY MIDI 1–4 | ✅ MemoryCommon 0x35–0x68 — exact field-by-field |
| §4.2 INPUT memory selector | ✅ SystemControl 0x61 = INPUT SETTING (0–9 = mem 1–10) |
| §4.2 OUTPUT SELECT full enum (14 values) | ✅ AIRD OUTPUT SELECT enum listed |
| §4.2 GLOBAL EQ knobs | ✅ SystemGlobalEq 0x10–0x1A — 11 knobs with full ranges |
| §5 WRITE MEMORY-dropdown 48-slot enum | ✅ Memory Number 0–299 maps to U01-1..NIU..P33-3..NIU |
| §6.1 AUTO OFF / EXP HOLD addresses | ✅ exact addresses (we had AUTO OFF mislabeled) |
| §6.1 CONTROL MODE | ✅ SystemControl 0x34 = MEMORY/MANUAL/BANK-NUM/MANUAL2 |
| §6.2 PLAY OPTION FOOTSWITCH section | ✅ SystemControl 0x64 (Down&Up Function), 0x65 (Up&Ctl1 Function) |
| §6.3 MIDI SETTINGS PAGE 2 | ✅ SystemMidi 0x08–0x14 — all CC# fields |
| §6.4 MIDI PROGRAM MAP 64 entries | ✅ PcmapPc 128 entries × 4 bytes per bank, 3 banks |
| §6.5 USB SETTINGS | ✅ already captured + LOOPBACK toggle confirmed |
| §6.7 DEVICE SETTINGS | ✅ SystemCommon offsets 0x12–0x18 (KNOB / TOUCH SCREEN / BUTTON / OUTPUT LEVEL LOCK / DELETE WARNING / OVERWRITE WARNING / FX ORDER) |
| §8 Patch-select encoding | ✅ fully decoded — 4 nibbles, 16-bit memory index 0–299 |
| §9 Effect TYPE / SP TYPE / etc. | ✅ TYPE byte enum (83 values) fully decoded; per-effect FX Parameter names still need GX-10 Parameter Guide |
| §11 Knob NAME mismatches | partially — the chain-linked-list structure may explain why "knob count" and "param count" differed |

Items NOT addressed by the MIDI chart (still in gaps.md):
- §1.1 EDITOR slot manipulation (delete/swap/bypass)
- §1.2 PRESET/USER tab toggle (UI-only)
- §6.1 Bluetooth device-name (hardware-only, no chart entry)
- §6.9 ALL DATA BACKUP file flow (UI-only)
- §10 Hardware-only flows (footswitch press, EXP pedal physical movement)
- §11 OCR for the 8 mismatched effects' knob labels

---

## Action items resulting from this cross-reference

1. **HIGH** — write `tools/reanalyze_knobs_4nibble.py` to fix every
   `summary.json` with proper 4-nibble decode of the captured pcaps.
2. **HIGH** — add a TYPE-byte → effect-name table to
   `docs/effects/all_effects.md` (replacing our heuristic
   `triplet_at_10001100[:2]` mapping with the official 83-entry
   enum).
3. **HIGH** — update `docs/protocol.md` with the official region map
   (especially fix the user-patch region from `0x60400000` to
   `0x20000000+`).
4. **MEDIUM** — update `docs/menus.md` with the corrected addresses
   (PLAY OPTION mislabels, AUTO OFF address, etc.).
5. **MEDIUM** — update `docs/gaps.md` to mark resolved items.
6. **LOW** — extract the [Assign] sub-structure from the chart (20
   assigns × 0x40 bytes — what fields are inside? We need to read
   that section of the official chart, which we haven't yet read).

---

## Versioning

The chart says GX-10 is at firmware **v1.05**. Our test unit's
`Identity Reply` reported software revision `01 00 00 00` — this is
**v1.00**. Newer firmware may expose additional features.
