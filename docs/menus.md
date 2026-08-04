# Tone Studio toolbar / dialog SysEx map

This file documents the toolbar buttons and dialog windows in BOSS
TONE STUDIO that are outside the EDITOR's effect-chain view, with the
captured SysEx addresses behind each settable parameter.

Captures live in `captures/menus_v3/` (dialog open snapshots) and
`captures/menus_v4/` (after-change snapshots + USBPcap of the wire
traffic).

> **Updated 2026-05-03** with corrections from the official Roland
> MIDI Implementation chart (`docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md`).
> Several addresses were mislabeled in earlier RE work:
> - `0x0000_000D` is **EXP1 HOLD**, not AUTO OFF
> - `0x0000_000F` is **AUTO OFF**
> - `0x0000_0016` is **DELETE WARNING**, not REC ACTION
> - `0x0000_0017` is **OVERWRITE WARNING**, not LOOP MODE
> - `0x0000_0018` is **FX ORDER** (BY TYPE / BY NAME — the SORT BY toggle in the EDITOR)
> - LOOP MODE/REC ACTION live at `0x0000_5000`/`0x0000_5001` in the SystemEfct region
> - User patches are at `0x2000_0000+` (not `0x6040_0000` — that was wrong)
> - All FX Parameters (knob values) are **4 nibbles** big-endian, value = display + 32768
>
> See `docs/official_xref.md` for the full cross-walk.

## Two-region split

Settings are written by Tone Studio to one of three address regions
depending on whether they are **per-patch** or **global**:

| Region | Where settings live | Examples |
|--------|--------------------|----------|
| `0x10000000`+ | Live edit buffer (per-patch) | All effect knobs, CTL/EXP per-memory assignments, MASTER block |
| `0x0000_0000`–`0x0000_4FFF` | Global system block, hardware settings | AUTO OFF, EXP HOLD |
| `0x0020_0000`+ | Editor I/O staging area | INPUT type/sens, OUTPUT SELECT, GLOBAL EQ |
| `0x0000_6000`–`0x0000_6FFF` | Persistent global settings (echoed back from `0x0020_xxxx` writes) | INPUT SETTING memories 1–10 |
| `0x7F00_0000`+ | Real-time / status registers | Tuner display stream, editor-attached flag |

When a setting in `0x0020_xxxx` is changed, the device immediately
mirrors the change into a corresponding address in `0x0000_6xxx`.
Both writes are observable.

---

## Top toolbar (left)

| Click coord (window-local) | Button | Effect |
|---------------------------|--------|--------|
| `(240, 60)` | EDITOR    | Default chain editor view |
| `(320, 60)` | LIBRARIAN | Patch-list manager (out of scope) |
| `(399, 60)` | TONE EXCHANGE | Cloud patch sharing (out of scope) |
| `(482, 60)` | TUNER     | See **Tuner** below |
| `(542, 60)` | IR LOADER | User IR upload (out of scope) |
| `(605, 60)` | MENU      | See **MENU dialog** below |

## Right-side toolbar (top of editor)

| Click coord | Button |
|-------------|--------|
| `(1145, 110)` | CTL/EXP |
| `(1270, 110)` | IN/OUT SETTINGS |
| `(1405, 110)` | WRITE (drops a 2-item menu: WRITE, INITIALIZE) |

---

## TUNER

Toolbar click at `(482, 60)` activates the device tuner. TS issues a
small handshake then receives a continuous display stream.

**Activation handshake** (capture: `captures/menus_v3/TUNER.pcap`):

| # | Direction | Cmd | Address | Payload | Meaning |
|--:|-----------|-----|---------|---------|---------|
| 1 | host→dev | RQ1 | `0x0000_0007` | size=`00 00 00 01` | Read tuner state |
| 2 | dev→host | DT1 | `0x0000_0007` | `01` | Current tuner state |
| 3 | dev→host | DT1 | `0x0000_0007` | `02` | (next state value) |
| 4 | host→dev | DT1 | `0x0000_0007` | `01` | Set tuner state = 1 |
| 5 | host→dev | DT1 | `0x0000_0006` | `00` | TUNER MODE = NORMAL (see below; not a "sub-config") |
| 6 | host→dev | DT1 | `0x7F00_0002` | `02` | Editor-attached flag = 2 (tuner mode) |
| 7 | dev→host | DT1 | `0x7F00_0002` | `02` | Echo of editor-attached |
| 8 | dev→host | DT1 | `0x7F00_0701` | `06` | Poly tuner type = 6-REG |
| 9..N | dev→host | DT1 | `0x7F00_0300` | (48-byte payload) | Real-time pitch display |

**Tuner TYPE** at `0x0000_0007` (1 byte) — confirmed via official chart
(SystemCommon offset 0x07 = TUNER TYPE):
- `0x01` = MONO
- `0x02` = POLY (default)
- `0x03` = TT MODE

**Tuner MODE** at `0x0000_0006` (1 byte) — the second display axis,
per the official chart (SystemCommon offset 0x06, `NORMAL` / `STREAM`):
- `0x00` = NORMAL
- `0x01` = STREAM

The two axes multiply: **3 types × 2 modes = 6 tuner displays.** The
GX-10 manual lists the four its own UI reaches (it never offers POLY):
*"You can turn the [SELECT] knob to switch the tuner display:
Monophonic (normal), Monophonic (streaming), True Temperament (normal),
True Temperament (streaming)."* BTS's `0x0000_0006 = 0x00` in the
handshake above is just "normal" — see `protocol.md` §3.8.1, which used
to file this register as unidentified.

**THRU excludes POLY** (owner-observed on a GX-10, 2026-08-04; absent
from the manual): with TUNER OUTPUT set to THRU the device will not show
the POLY display, leaving MONO and TT — i.e. 4 of the 6. Consistent with
POLY being a BTS-GUI extension the hardware tolerates rather than a
first-class device display.

The dialog's other sub-controls live in **SystemPitch** (`0x0000_6000`):

| Address | Field | Range |
|---------|-------|-------|
| `0x0000_6000`–`0x0000_6003` | REF. PITCH | 435–445 Hz — **binary 4-nibble big-endian**, see below |
| `0x0000_6004` | TT / POLY TUNER TYPE | 0–5: 6-REG, 6-DROP D, 7-REG, 7-DROP A, 4-B REG, 5-B REG |
| `0x0000_6005` | TT / POLY TUNER OFFSET | 11–16 (–5..–1, ----) — NOT zero-based |
| `0x0000_6006` | TUNER OUTPUT | 0=MUTE, 1=BYPASS, 2=THRU |

**REF. PITCH encoding** — binary 4-nibble big-endian (low nibble of each
byte, MSN first), the same convention as every other multi-byte field
here (`tools/encoding.py`). Established in `gaps.md` §2 against a known
on-device UI state; re-confirmed 2026-08-04 on a GX-10 (sw_rev
01.00.00.00) reading `00 01 0B 08 00 0B 00`, where the rival BCD reading
gives 218 — outside the register's own 435–445 range. `--write` on
`tools/read_tuner_settings.py` additionally round-tripped all four
fields (write → read-back → restore) on that unit, so the block is
confirmed writable, not just readable.

**Label drift on `0x6004`/`0x6005`** — three namings for the same two
registers, so don't treat any one as canonical (`gaps.md` §2 notes the
chart-vs-POLY discrepancy; the third column is the on-device menu):

| Source | Names |
|--------|-------|
| Official MIDI chart / current online GX-10 manual | `TT TYPE`, `TT OFFSET` |
| Owner's GX-10, fw 01.00.00.00 (on-device menu) | `POLY TYPE`, `POLY OFFSET` |
| BTS GUI | `POLY TUNER TYPE`, `POLY TUNER OFFSET` |

Note the values bite on BOTH the POLY and TT displays, which is why
firmware that drops POLY still needs them. A client gating them on POLY
alone would hide live controls.

Verified by clicking each tab: `captures/flows/tuner_modes.pcap`
recorded 0x02 → 0x01 → 0x02 → 0x03 transitions matching the GUI.

**Real-time pitch stream**: `0x7F00_0300`, 48-byte payload, repeats
~UI-frame rate while the tuner is active. Payload is a fixed-size
display structure (likely 6×8-byte per-string or 4×12-byte). With a
silent input, all packets in the captured window contain the same
prefix `00 01 03 08 08 00 00 01 03 08 08 00 …` — i.e. the "no signal
detected" pattern.

The TUNER UI dialog also exposes:

- **MONO / POLY / TT MODE** tab buttons (top of dialog)
- **6-string display** (E B G D A E top-to-bottom) — driven by the
  `0x7F00_0300` stream
- **REF. PITCH** dropdown: 440Hz default
- **TUNER OUTPUT** dropdown: BYPASS / MUTE
- **POLY TUNER TYPE** dropdown: 6-REG (others?)
- **POLY TUNER OFFSET** dropdown

---

## IN/OUT SETTINGS

Capture: `captures/menus_v4/IN_OUT_changes.pcap` (25 DT1 events).

Dialog has these sections:

### INPUT SETTING (a 1–10 named memory of input config)

| Parameter | Address (host) | Mirror (device) | Bytes | Notes |
|-----------|---------------|-----------------|------:|-------|
| INPUT (GUITAR / BASS) | `0x0020_0341` | `0x0000_6110` | 1 | `00`=GUITAR, `01`=BASS |
| INPUT SENS (–10 to +10 dB) | `0x0020_0342` | `0x0000_6111` | 1 | Default `0x25` (= +4 dB observed); each UP-arrow press increments by 1 |
| OUTPUT SELECT (LINE/PHONES, JC-120, KATANA, …) | `0x0020_0343` | `0x0000_6B10` | 1 | Observed `0x21..0x23`; ~14 enum values per manual |

INPUT SETTING memory 1–10: each memory holds an INPUT-section block.
The TS dialog's "INPUT SETTING:" dropdown selects which memory to
edit; the addresses above are for the active memory.

### GLOBAL EQ

| Parameter | Address | Bytes | Notes |
|-----------|---------|------:|-------|
| GLOBAL EQ ON/OFF | `0x0000_400C` | 1 | `00`=OFF, `01`=ON |
| GLOBAL EQ slot? | `0x0000_1063` | 1 | Observed once on toggle; meaning unclear |
| GLOBAL EQ LOW-MID FREQ | `0x0020_0345` (host) → `0x0000_6B12` (dev) | 1 | Observed `0x0D..0x0F` |

(Other GLOBAL EQ controls were not toggled in the capture run; their
addresses follow the same `0x0020_034x` / `0x0000_6Bxx` pattern in
order: LOW GAIN, LOW-MID FREQ, LOW-MID Q, LOW-MID GAIN, HIGH GAIN,
HIGH-MID FREQ, HIGH-MID Q, HIGH-MID GAIN, LOW CUT, HIGH CUT, LEVEL.)

---

## CTL/EXP (per-memory)

Capture: `captures/menus_v4/CTL_EXP_changes.pcap` (2 DT1 events).

CTL/EXP holds **per-memory** (per-patch) controller assignments — they
live in the live edit buffer at `0x1000_0000+`. The dialog has 4 tabs:

- **CONTROL FUNCTION** — assign footswitches to functions (DOWN, UP,
  MANUAL ▼/▲, CURNUM, CTL1/2/3, EXP1 SW, EXP1 PEDAL, EXP2)
- **ASSIGN SETTINGS** — 20 generic source→target assignments
- **KNOB SETTINGS** — assign favorite parameters to knobs [1]–[4]
- **MEMORY MIDI** — outgoing MIDI on memory change (CH, BANK MSB/LSB,
  PC#, CC#1, CC#2)

Each row has a **FUNCTION** dropdown (e.g. OFF, DOWN, UP, BANK ▼/▲,
BPM TAP, TUNER, MEMORY/MAN, …), a **MODE** column (TOGGLE/MOMENT for
some), and a **PREFERENCE** toggle (MEMORY/SYSTEM — whether the
setting is per-memory or global).

**Captured per-patch addresses**:

| Parameter | Address | Bytes | Notes |
|-----------|---------|------:|-------|
| CTL1 FUNCTION | `0x1000_001B` | 1 | 17-value enum (see below) |
| EXP1 SW FUNCTION | `0x1000_001F` | 1 | Same enum domain |

### FUNCTION enum (verified)

A full cycle of the CTL1 dropdown captured in
`captures/flows/ctl_exp_function_cycle.pcap` produced 17 distinct byte
values at `0x1000_001B`. Mapping (matched against the manual's order):

| Byte | Function |
|-----:|---------|
| `0x00` | OFF |
| `0x01` | DOWN |
| `0x02` | UP |
| `0x03` | BANK ▼ |
| `0x04` | BANK ▲ |
| `0x05` | BPM TAP |
| `0x06` | TUNER |
| `0x07` | MEMORY/MAN |
| `0x08` | TUNER/MAN |
| `0x09` | MAN/TUNER |
| `0x0A` | (reserved — not produced; depends on chain content) |
| `0x0B` | (reserved) |
| `0x0C` | WAH |
| `0x0D` | DIV CH.SEL |
| `0x0E` | SEND/RETURN |
| `0x0F` | LOOP CTL |
| `0x10` | LOOPER STOP |
| `0x11` | LOOPER CLEAR |
| `0x12` | MIDI START |

The 0x1000001x window holds the per-memory CTL/EXP assignments. By
mapping the FUNCTION enum (24 values from the manual: OFF, DOWN, UP,
BANK ▼/▲, BPM TAP, TUNER, MEMORY/MAN, TUNER/MAN, MAN/TUNER, WAH, DIV
CH.SEL, SEND/RETURN, LOOP CTL, LOOPER STOP, LOOPER CLEAR, MIDI START)
the byte values at these addresses identify the assigned function.

**Per-controller FUNCTION addresses** — corrected against the official
MemoryCommon layout. Our captures matched the right region but had some
controller labels off-by-one:

| Controller (label in TS) | Address | Region | Manual-chart name | Notes |
|--------------------------|---------|--------|-------------------|-------|
| ▼ (in MANUAL mode) | `0x1000_0017` | MemoryCommon offset 0x17 | Manual Num1 Function | (we labeled DOWN_SW) |
| ▲ (in MANUAL mode) | `0x1000_0018` | MemoryCommon offset 0x18 | Manual Num2 Function | (we labeled UP_SW) |
| **CTL1** | `0x1000_001B` | MemoryCommon offset 0x1B | Ctl1 Function | ✓ verified, full 17-value enum cycle captured |
| **CTL2** | `0x1000_001C` | MemoryCommon offset 0x1C | Ctl2 Function | (we'd captured 0x1D and labeled CTL2 — was actually CTL3) |
| **CTL3** | `0x1000_001D` | MemoryCommon offset 0x1D | Ctl3 Function | |
| **CTL4** | `0x1000_001E` | MemoryCommon offset 0x1E | Ctl4 Function | (chart has 4 CTL switches — we'd called this CTL3) |
| **EXP1 SW** | `0x1000_001F` | MemoryCommon offset 0x1F | Exp1Sw Function | ✓ verified |
| EXP1 PEDAL action | `0x1000_0020` | MemoryCommon offset 0x20 | Exp1 Function | range 0–5: OFF / FOOT VOL / PEDAL FX / FV/PEDAL FX / FV+TUNER / FV+TUNE/PFX |
| **EXP2** | `0x1000_0021` | MemoryCommon offset 0x21 | Exp2 Function | ✓ verified |
| EXP1 PEDAL (system PREF=SYSTEM) | `0x0000_1022` | SystemControl offset 0x22 | Exp1 Function (system) | When PREFERENCE = SYSTEM, the global value is at SystemControl + 0x22 |

The system-level mirror in **SystemControl** (`0x0000_1000`+) is consulted
when a controller's PREFERENCE column is set to SYSTEM. Layout (from
official chart):

| Offset | Field |
|--------|-------|
| 0x00–0x11 | per-controller PREFERENCE bits (Num1..4, BankDown/Up, CNum, Manual Num1..4, CTL1..4, Exp1Sw, Exp1, Exp2) |
| 0x12–0x21 | system FUNCTION values for each controller (same enum as MemoryCommon 0x10–0x21) |
| 0x22–0x33 | system MODE bits (TOGGLE/MOMENT) |
| 0x34 | CONTROL MODE (GX-10): 0=MEMORY, 1=MANUAL, 2=BANK/NUM, 3=MANUAL2 |
| 0x61 | INPUT SETTING (system default: 0–9 = memory 1–10) |
| 0x63 | GLOBAL EQ SW (OFF/ON) |
| 0x64 | Down & Up Function (GX-10): OFF, TUNER, DOWN, UP |
| 0x65 | Up & Ctl1 Function (GX-10): OFF, MANUAL, DOWN, UP |

---

## WRITE

Click `(1405, 110)` opens a small drop-down with two items:

- **WRITE** — opens the WRITE dialog (memory selector + name input)
- **INITIALIZE** — clears the live edit buffer back to default

### WRITE protocol

The actual save is **NOT** a bulk transfer to `0x6040_xxxx` as
originally hypothesized. Instead, it's a 2-byte trigger that tells
the device to copy its own edit buffer to a user-memory slot.

Captured at `captures/flows/write_save_v2.pcap`:

```
host → DT1 0x10000000 len=16  "EMPTY           "    # set patch name
host → DT1 0x7F000104 len=2   00 06                 # SAVE command: slot index 6
dev  → DT1 0x7F000104        00 06                  # echo
dev  → DT1 0x00000000 len=4   00 00 00 06           # patch-select register updated
host → RQ1 0x10000000 size=0x10                     # verify name
dev  → DT1 0x10000000 len=16  "EMPTY           "    # echo
host → DT1 0x7F000703 len=1   00                    # clear dirty flag
dev  → DT1 0x7F000703 len=1   01                    # echo
dev  → DT1 0x00200040 len=83  (all-0x01s)           # patch-list metadata refresh
host → RQ1 0x50000000 size=0x100                    # refresh patch name catalogue
host → RQ1 0x50000100 size=0x100
```

**Key insight**: `0x7F00_0104` is the **save trigger register**. Write
2 bytes there: `00 NN` where `NN` is the memory slot index (0–47 for
16 user banks × 3 patches per bank). The device handles the actual
copy internally.

The 16-byte ASCII patch name should be written to `0x1000_0000` first
(part of the live edit buffer); the save command just commits the
buffer's current state — name and all parameters — to the named slot.

### INITIALIZE

Click `(1413, 215)` selects INITIALIZE in the WRITE dropdown.

A confirmation popup appears (screenshot
`captures/flows/initialize_v2_dialog.png`):

> INITIALIZE
> The temporary tone setting will be initialized.
> [CANCEL]   [OK]

OK button at `(1038, 654)`. Pressing Enter or clicking OK confirms.

The captured pcap is **empty** (0 events) — INITIALIZE is purely
client-side: TS resets its local edit-buffer model to defaults but
does **not** send any MIDI to the device. The device's edit buffer is
unchanged until the user WRITEs or loads another patch.

The dialog text "**temporary** tone setting" confirms this — the
"temporary" buffer is the editor's local representation, not the
on-device live buffer.

## Patch-load flow (PRESET click)

Capture: `captures/flows/preset_load.pcap` (93 events when changing
from P02-1 to P03-1 NEO SOUL).

The exchange is:

```
host → DT1 0x00000000 = 00 00 0C 0E              # 4-byte patch select
host → RQ1 0x10000000 size=0x10                  # read patch name
dev  → DT1 0x10000000 = "EMPTY           "       # old name (still loading)
host → RQ1 0x00000000 size=0x04                  # confirm select register
dev  → DT1 0x00000000 = 00 00 0C 0E              # echo
dev  → DT1 0x00000000 = 00 00 0C 0E              # change notification
host → RQ1 0x10000000 size=0x10                  # re-read name
host → DT1 0x7F000703 = 00                       # ?
dev  → DT1 0x7F000703 = 01                       # ?
host → RQ1 0x10001100 size=0x103                 # slot 0 params (start of bulk read)
dev  → DT1 0x10000000 = "NEO SOUL        "       # new name arrives
host → RQ1 0x10001300 size=0x103                 # slot 1
host → RQ1 0x10001500 size=0x103                 # slot 2
host → RQ1 0x10001700 size=0x103                 # slot 3
host → RQ1 0x10001803 size=0x30                  # AMP slot SP_TYPE/IR sub-block
… many more RQ1s — slots 4–19 + master block + metadata …
host → RQ1 0x10000F00 size=0x3E                  # master block (62 B)
host → RQ1 0x10000069 size=0x14                  # patch metadata (20 B)
```

Total: 1 host DT1 (the patch-select) + ~50 host RQ1s. Device replies
with all bulk data.

### Patch buffer layout (inferred)

| Address | Size | Content |
|---------|------|---------|
| `0x1000_0000` | 16 B | Patch name (ASCII, space-padded) |
| `0x1000_0069` | 20 B | Patch metadata (creation date? memory# encoding?) |
| `0x1000_0F00` | 62 B | Master block (BPM, KEY, MEMORY LEVEL, INPUT SETTING, CARRYOVER, TEMPO HOLD, etc.) |
| `0x1000_1100` | 0x103 | Slot 0 params (`+0x00` = effect-type, `+0x03..` = sub-TYPE / params) |
| `0x1000_1300` | 0x103 | Slot 1 |
| `0x1000_1500` | 0x103 | Slot 2 |
| `0x1000_1700` | 0x103 | Slot 3 |
| `0x1000_1803` | 0x30 | AMP-style IR sub-block (when slot is an AMP-type effect) |
| `0x1000_1900` | 0x103 | Slot 4 |
| … | … | (24 slots total spanning 0x10001100..0x10003800) |
| `0x1000_3700` | 0x103 | Slot 19 (final) |

Slots are spaced **0x200 apart**. BTS reads each slot as two RQ1s
with request sizes `0x103` + `0x30` (a 131-B main record plus a 48-B
extension record, with a 0x80-byte gap at offsets 0x83..0x102 that
returns nothing). Slots that hold AMP-style effects (with SP_TYPE)
have an additional 0x30-byte IR sub-block at offset `+0x703` from
the slot base — these are the `0x10001803`, `0x10002003`,
`0x10002603`, `0x10002803`, `0x10002A03` reads observed in the
capture. (Note: the request sizes in BTS captures are ceilings — the
device chooses the response length; see `protocol.md` §3.1.2.)

### Patch select register `0x0000_0000`

Already documented in `docs/protocol.md`. Encoding is non-trivial; the
P03-1 (NEO SOUL) selector observed here is `00 00 0C 0E`, joining the
table of known mappings.

## INITIALIZE

Clicking WRITE → INITIALIZE clears the live patch buffer to default.
The capture in `captures/flows/initialize.pcap` is empty (0 events) —
likely because TS does the reset locally and only writes to the device
on next user action. To capture INITIALIZE wire traffic, the dialog's
confirm button needs different click coords than were attempted.

---

## MENU (hamburger, top-left)

Click `(605, 60)` opens the global MENU dialog. Sidebar tabs:

| Tab | Captured? | Dialog screenshot |
|-----|-----------|-------------------|
| HARDWARE SETTINGS | yes | `captures/menus_v3/MENU_open.png` |
| PLAY OPTION       | yes | `captures/menus_v4/menu_play_option.png` |
| MIDI SETTINGS     | yes | `captures/menus_v4/menu_midi_settings.png` |
| MIDI PROGRAM MAP  | partial | (not yet visited) |
| USB SETTINGS      | yes | `captures/menus_v4/menu_usb_settings.png` |
| OWNER'S MANUAL    | (link, no settings) | — |
| DEVICE SETTINGS   | yes | `captures/menus_v4/menu_device_settings.png` |
| VERSION           | (info only) | — |
| ALL DATA BACKUP   | (file dialog) | — |

### HARDWARE SETTINGS — official addresses (corrected)

| Parameter | Address | Range | Notes |
|-----------|---------|-------|-------|
| EXP1 HOLD | `0x0000_000D` | OFF, ON | Observed `0x01` (we mislabeled this as AUTO OFF) |
| EXP2 HOLD | `0x0000_000E` | OFF, ON | |
| **AUTO OFF** | `0x0000_000F` | OFF / 10HOURS / 5HOURS / 1HOUR / 20MIN | (5 values per official chart) |

### PLAY OPTION (tab at sidebar y=280)

Captured screenshot `captures/flows/menu_v2_play_option.png` reveals:

- **BANK** section: BANK MODE (WAIT1 / …), BANK EXTENT MIN (U01..),
  BANK EXTENT MAX (P33..)
- **LOOP** section: MODE (MONO / STEREO), REC ACTION (REC→PLAY→DUB / …)
- **WARNING** section: DELETE WARNING toggle (OFF/ON), OVERWRITE
  WARNING toggle (OFF/ON)
- **FOOTSWITCH** section: ▼&▲ assignment dropdown, ▲&CTL1 dropdown

**Addresses captured** (`captures/flows/menu_tabs_v3.pcap`) — **corrected per official chart**:

| Setting | Address | Region | Notes |
|---------|---------|--------|-------|
| BANK MODE (BANK CHANGE MODE) | `0x0000_0008` | SystemCommon | 0–2: WAIT1, WAIT2, IMMEDIATE |
| BANK EXTENT MIN | `0x0000_0019` | SystemCommon | 0–98: U01..U66, P01..P33; **pair-coalesced** with MAX (next byte) |
| BANK EXTENT MAX | `0x0000_001A` | SystemCommon | 0–98; same enum |
| **DELETE WARNING** | `0x0000_0016` | SystemCommon | OFF / ON (we previously mislabeled this REC ACTION) |
| **OVERWRITE WARNING** | `0x0000_0017` | SystemCommon | OFF / ON (we previously mislabeled this LOOP MODE) |
| FX ORDER (= EDITOR's SORT BY) | `0x0000_0018` | SystemCommon | 0 = BY TYPE, 1 = BY NAME |
| **PHRASE LOOP MODE** | `0x0000_5000` | SystemEfct | MONO / STEREO (previously labeled DELETE WARNING) |
| **PHRASE LOOP REC ACTION** | `0x0000_5001` | SystemEfct | REC>PLAY>DUB / REC>DUB>PLAY (previously labeled OVERWRITE WARNING) |

These confirm that PLAY OPTION settings live in the **global system
block** (`0x0000_0000`–`0x0000_5001`), not the per-patch buffer. They
write through immediately on toggle (no save needed).

### MIDI SETTINGS (tab at sidebar y=320)

Captured (`captures/flows/menu_midi_usb_device.pcap`):

| Setting | Address | Notes |
|---------|---------|-------|
| RX CHANNEL | `0x0000_3000` | 1 byte; CH 1..16 + OFF |
| TX CHANNEL | `0x0000_3002` | 1 byte; observed `0x10` (= 16 or "RX CH" sentinel) |
| USB IN THRU | `0x0000_3006` | 1 byte; OFF/ON |
| SYNC CLOCK / CLOCK OUT | `0x0000_400B` | 1 byte (region overlaps GLOBAL EQ block at 0x0000400C) |

The MIDI settings tab has a PAGE1 / PAGE2 internal selector — page 2
likely holds Bank Select MSB/LSB, PC#, etc. (not yet exercised).

### USB SETTINGS (tab at sidebar y=400)

Chart-documented as the `[SystemInOut]` block, size `0x0D` bytes,
starting at `0x00004000`. Verified by reading the whole block on a
GX-10 in vendor mode (2026-05-04).

| Offset | Address | Field | Range | Encoding |
|--------|---------|-------|-------|----------|
| 0x00 | `0x00004000` | **MAIN:LEVEL SELECT** | 0 / 1 | 1 byte: 0 = −10 dBu, 1 = +4 dBu |
| 0x01–02 | `0x00004001..02` | (N/A, fixed 0) | – | – |
| 0x03–04 | `0x00004003..04` | USB MAIN:EFX OUT | 0..200 % | **2 nibbles** (low nibble of each byte combine into 8-bit value) |
| 0x05–06 | `0x00004005..06` | USB MAIN:MIX LEVEL | 0..200 % | 2 nibbles |
| 0x07–08 | `0x00004007..08` | USB DRY:OUT | 0..200 % | 2 nibbles |
| 0x09–0A | `0x00004009..0A` | USB DRY:TO EFX | 0..200 % | 2 nibbles |
| 0x0B | `0x0000400B` | USB LOOPBACK | 0 / 1 | 1 byte |
| 0x0C | `0x0000400C` | AIRD OUTPUT SELECT | 0..14 | 1 byte enum |

**Encoding correction** to earlier note: the level fields are
**2 nibbles**, not 14-bit. The chart shows `0000 aaaa | 0000 bbbb`
for each pair — only the low nibble of each byte is data, so the
combined value is `(byte_hi & 0xF) << 4 | (byte_lo & 0xF)`,
range 0..200 (`0x00..0xC8`) representing 0..200 %.

Example: `04 0B` → `0x4B` = **75 %**, not 0x40B / 26 %.

`AIRD OUTPUT SELECT` enum: LINE/PHONES (RECORDING), JC-120 RETURN,
JC-120 INPUT, KATANA-100/212 RETURN, KATANA-100/212 INPUT,
KATANA-100 RETURN, KATANA-100 INPUT, TUBE COMBO 212 RETURN/INPUT,
TUBE COMBO 112 RETURN/INPUT, TUBE STACK 412 RETURN/INPUT,
BASS AMP WITH TWEETER, BASS AMP NO TWEETER.

The Setup_temp addresses `0x0020_0113` (DIRECT MONITOR) and
`0x0020_0114` (LOOP BACK) are editor-staging mirrors used by BTS;
the persistent value lives at `0x00004000+`. `DIRECT MONITOR`
specifically isn't in the chart's `[SystemInOut]` block — it's a
BTS-only UI control that toggles whether the host hears the input
signal directly through the GX-10 mix.

**Why BTS hides some of these in generic mode**: in generic USB-Audio
class mode the device exposes only stereo (the DRY channel pair isn't
present in the USB descriptor), so `USB DRY:OUT` and `USB DRY:TO EFX`
have no audible effect — BTS greys them out. `MAIN:LEVEL SELECT` is
the analog output line-level pad; BTS only surfaces it when it knows
the user is on the vendor (full-feature) driver path.

### DEVICE SETTINGS (tab at sidebar y=480)

Click cycle hit `0x0020_0340` (1 byte = `01`) — likely the INPUT
SETTING memory selector (cousin to `0x0020_0341..0x0020_0345` from
IN/OUT, which addresses memory #1's content).

Other DEVICE SETTINGS controls (LCD brightness, USB driver mode, etc.)
weren't toggled in this capture run; addresses TBD.

### MIDI PROGRAM MAP (tab at sidebar y=360)

64 program-number → memory entries per the manual. Not exercised in
captures (would need to scroll through the table). Addresses likely
follow `0x0000_30xx` stride into the global MIDI block.

---

## MASTER block (visible when WRITE drop-down is open)

The MASTER block sits between the effect chain and the editor pane
(visible only when no effect is selected). Its 6 knobs are:

| # | Name | Default | Notes |
|--:|------|---------|-------|
| 0 | MEMORY LEVEL | 100 | Per-patch level |
| 1 | BPM | 120 | Master BPM, address `0x1000_0F02` (see `bpm_encoding.md`) |
| 2 | KEY | C(Am) | For HARMONIST etc. |
| 3 | INPUT SETTING | SYSTEM | Selects which IN/OUT memory (1–10) drives this patch, or "SYSTEM" for global |
| 4 | CARRYOVER | ON | Whether delays/reverbs carry sound across patch changes |
| 5 | TEMPO HOLD | OFF | Hold BPM across patch changes |

Manual TARGET list (page 106) confirms these names.

---

## What's NOT generating USB traffic

Empirically, **opening** any of these dialogs (`captures/menus_v3/`)
sends zero MIDI to the device — TS just renders local UI state. MIDI
traffic only happens when a setting is **changed**:

- IN/OUT settings: change → DT1 to `0x0020_03xx` (host) + echo to
  `0x0000_6xxx` (dev)
- CTL/EXP per-patch: change → DT1 into the live patch buffer at
  `0x1000_001x`
- MENU global hardware: change → DT1 into the global block at
  `0x0000_000x`–`0x0000_4xxx`
- WRITE: bulk DT1 stream into a user-patch slot at `0x6040_x000`
- TUNER: handshake at `0x0000_000x` + `0x7F00_000x` plus a continuous
  display stream at `0x7F00_0300`

This split (host writes to a "staging" address, device echoes to a
"persistent" address) is unique to IN/OUT — it suggests the
`0x0020_0000+` region is an editor-staged batch that the device
re-publishes as the canonical setting in `0x0000_6000+`.
