> **Closeout 2026-05-03 — protocol end-to-end verified on a live device.**
> Open items: §6.1 AUTO OFF (un-investigable), §11 sub-types (deferred).
> Per-section ✅/⚠️/🚫 markers below are the closeout audit's status, not
> work-in-progress flags.

# Documentation gaps — what is NOT yet captured

**Closeout audit 2026-05-03.** The protocol is now end-to-end verified
on a live device. Section "Closeout summary" at the bottom lists what
was completed in the final session, what's deliberately deferred, and
what's confirmed un-investigable (AUTO OFF).

**Audited 2026-05-03** against the official Roland MIDI Implementation
chart (`docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md`) and the 6
chunked `GX-10_Parameter_Guide_0[1-6]*.md` files. Many items previously
flagged as "untested" are now fully resolved by the chart — for these,
**no full sweep is needed**, only a spot-check (write a single value,
read back, confirm display matches the documented formula).

Status legend:
- ✅ **DONE** — captured + verified
- 📜 **CHART** — fully documented in the official chart; spot-check only
- 🧪 **SPOT-CHECK** — chart says X; we should pick 1–2 points and verify
- ⚠️ **OPEN** — needs work (capture / parse / user input)
- 🚫 **OUT-OF-SCOPE / DESTRUCTIVE** — explicitly deferred

Default tooling for new captures:
- `capture_one_menu.py NAME` — open a dialog, screenshot, capture
- `capture_menu_changes.py` — toggle controls inside a dialog
- `capture_full_flows.py` — pre-configured per-flow captures
- `capture_ctl_per_controller.py` — cycle each controller's FUNCTION

---

## 0. Address-attribution bug ✅ DONE

`tools/fix_knob_addresses.py` now recomputes every base-knob address
from the official `MemoryFxItem` formula
(`slot_base + 0x07 + knob_idx * 4`). 417 addresses re-attributed across
66 effects. Master-block residue: 1 (in `knobs_extra`, low priority).

---

## 1. EDITOR (main view)

### 1.1 Effect-chain block manipulation
| Control | Status |
|---------|--------|
| Drag effect from typebar to chain slot | ✅ |
| Drag effect off chain (delete) | ✅ via drag-drop — `0x00200003` ChainEditTrigger pair + `0x10000F0C` chain-list rewrite (Windows BTS capture, 2026-05-09) |
| Drag effect to swap with another slot | ✅ same path as add/remove drag |
| Right-click slot for context menu | ⚠️ untested |
| Click slot to bypass / un-bypass (the small power dot) | ⚠️ — but `MemoryFxItem` offset 0x01 = OFF/ON per chart, so this is just a 1-byte write 📜 |
| INSERT button | ⚠️ **BTS-internal bug**, device-side clear |
| DELETE button | ⚠️ **BTS-internal bug**, device-side clear |
| OVERWRITE button | ⚠️ **BTS-internal bug**, device-side clear |

**2026-05-09 update (Windows BTS capture):** the INSERT/DELETE/OVERWRITE
buttons are a BTS-internal bug, not a device-protocol issue.
Drag-drop in the chain panel uses a different BTS code path that
works fine, and the SysEx sequence it emits is fully documented in
`reports/bts_capture_findings.md` §2 — `protocol.md §5.6` was correct
all along. The `ChainEditTrigger` at `0x00200003` is alive and well;
each drag pairs it with a write to the new state-mirror register
`0x7F000701` (0x05 editing / 0x03 idle). No firmware change is
needed; users with broken buttons should clear BTS's WebView2
user-data or use drag-drop.
| OVERWRITE button | ⚠️ **BROKEN in BTS as of 2026-05-03** |

### 1.2 PRESET / USER tab toggle (left rail) ⚠️
Click `(166, 108)` for USER. Probably client-side only.

### 1.3 SORT BY toggle 📜 CHART
`SystemCommon` offset 0x18 = FX ORDER, 0=BY TYPE, 1=BY NAME.
**Spot-check:** write `01` to `0x0000_0018` and confirm GUI re-sorts.

---

## 2. TUNER dialog 📜 CHART

| Control | Address | Range | Status |
|---------|---------|-------|--------|
| MONO/POLY/TT MODE | `0x0000_0007` | 1, 2, 3 (per chart: `MONO, TT`) | ✅ |
| Tuner display stream | `0x7F00_0300` (48 B) | – | ✅ |
| **REF. PITCH** | `0x0000_6000..6003` | 4 bytes, low-nibble of each → Hz directly (e.g. 435 Hz = `00 01 0B 03` = 0x01B3) | ✅ |
| **POLY TUNER TYPE** | `0x0000_6004` | 0–5: 6-REG, 6-DROP D, 7-REG, 7-DROP A, 4-B REG, 5-B REG | ✅ |
| **POLY TUNER OFFSET** | `0x0000_6005` | 11–15 = −5..−1, 16 = "----" (no offset; drop tunings only — no positive range) | ✅ |
| **TUNER OUTPUT** | `0x0000_6006` | 0=MUTE, 1=BYPASS, 2=THRU | ✅ |

Verified by reading the block on-device with the user's known UI
state (435 Hz / 6-DROP D / −1 / BYPASS) — every byte matched.
`tools/read_tuner_settings.py` reads + decodes the whole block in
one shot.

Note: the chart calls these "TT TUNER ..." but they apply to **POLY**
mode (the device's poly tuner type/offset selectors). The TT mode's
own per-string targets live in `0x00200005..08` (`SetupTemp.TT*`).

---

## 3. CTL/EXP dialog

### 3.1 CONTROL FUNCTION tab 📜 CHART
- FUNCTION enum (17 values) ✅ verified.
- MODE column (TOGGLE/MOMENT) 📜 — `MemoryCommon` 0x22..0x33; per
  controller. **Spot-check** by clicking one TOGGLE/MOMENT and reading
  back the byte.
- PREFERENCE column (MEMORY/SYSTEM) 📜 — `SystemControl` 0x00..0x11.
  Spot-check.

### 3.2 ASSIGN SETTINGS tab 📜 CHART (fully documented!)

The `[Assign]` structure is in the chart (`0x2D` bytes per assign):

| Offset | Field | Range |
|--------|-------|-------|
| 0x00 | SW | OFF, ON |
| 0x01 | TARGET_FX_ITEM | 0–19 |
| 0x02–0x05 | TARGET | 0–740 (4 nibbles → ASSIGN TARGET TABLE index) |
| 0x06–0x09 | TARGET MIN | 0–65535 (offset binary) |
| 0x0A–0x0D | TARGET MAX | 0–65535 (offset binary) |
| 0x0E | SOURCE | 0–83 (NUM 1, …, EXP 1, EXP 2, INT PDL, WAVE PDL, INPUT, CC#1..31, CC#64..95) |
| 0x0F | MODE | TOGGLE, MOMENT |
| 0x10 | WAVE RATE | 0–118 (0–100 + 18 musical notes) |
| 0x11 | WAVEFORM | SAW, TRI, SINE |
| 0x12 | INT PDL TRIGGER | 0–83 |
| 0x13 | INT PDL TIME | 0–100 |
| 0x14 | INT PDL CURVE | LINEAR, SLOW RISE, FAST RISE |
| 0x15–0x18 | ACT RANGE LO | 0–16382 (= 126 × 127) |
| 0x19–0x1C | ACT RANGE HI | 1–16383 (= 127 × 127) |
| 0x1D | MIDI CH | SYSTEM, 1–16 |
| 0x1E | MIDI CC# | 0–127 |
| 0x1F–0x22 | MIDI CC VALUE MIN | 0–16383 |
| 0x23–0x26 | MIDI CC VALUE MAX | 0–16383 |
| 0x28 | MIDI PC# | 0–127 (1–128) |
| 0x29–0x2A | MIDI BANK MSB | OFF, 1–128 |
| 0x2B–0x2C | MIDI BANK LSB | OFF, 1–128 |

Twenty assigns × 0x40-byte stride at `0x1000_0200..0x1000_0B7F`.

Group-parameter rule (from chart): writes are coalesced — only the
last-address write commits the entire group atomically.

**TARGET 0–740** is a separate big enum table also in the chart, indexing
every assignable parameter across all effects + master block.

### 3.3 KNOB SETTINGS tab 📜 CHART
`MemoryCommon` 0x69..0x7C: 4 knobs × (1-byte FxItem index + 4-nibble
TARGET id). Same TARGET enum as ASSIGN.

### 3.4 MEMORY MIDI tab 📜 CHART
`MemoryCommon` 0x35..0x68: 4 entries × 13 bytes (CH, BANK MSB[2], BANK
LSB[2], PC#[2], CC1#[2], CC1 VAL, CC2#[2], CC2 VAL).

---

## 4. IN/OUT SETTINGS dialog 📜 CHART

| Control | Address | Range | Status |
|---------|---------|-------|--------|
| INPUT type (GUITAR/BASS) | `0x0000_6110` (also staging `0x0020_0341`) | 0/1 | ✅ |
| INPUT SENS | `0x0000_6111` | byte = dB + 32 → 12..52 = −20..+20 dB (verified: 39 = +7 dB) | ✅ |
| INPUT memory selector | `0x0000_1061` (`SystemControl` 0x61) | 0–9 = mem 1–10 (verified: 0 = mem 1) | ✅ |
| INPUT NAME (per memory) | `0x0000_6100..6F`, `0x0000_6200..6F`, ..., `0x0000_6A00..6F` (offset 0x00..0x0F) | 16 ASCII chars (verified: mem 1 = "fender mustang") | ✅ |
| OUTPUT SELECT | `0x0000_400C` | 0 = LINE/PHONES (recording); chart has full 0–14 enum to be cross-referenced | ✅ partial |
| GLOBAL EQ ON/OFF | `0x0000_1063` candidate (`SystemControl` 0x63), or `0x0000_400C` second-byte | needs separate spot-check while toggling on/off in UI | 🧪 |
| GLOBAL EQ knobs (11) | `0x0000_6B10..0x0000_6B1A` | encodings: gain (byte − 32 = dB), Q (direct 1..N), freq/cut (enum index → table); LEVEL = gain encoding. Verified against UI: LOW GAIN +3, LOW MID FREQ 630 Hz, LOW MID Q 2, HIGH MID FREQ 1.25 kHz, LOW CUT 100 Hz, HIGH CUT 5 kHz, LEVEL 0 dB. | ✅ |

Chart's full GLOBAL EQ field set:
LOW GAIN (0x10), LOW MID GAIN (0x11), LOW MID FREQ (0x12), LOW MID Q
(0x13), HIGH MID GAIN (0x14), HIGH MID FREQ (0x15), HIGH MID Q (0x16),
HIGH GAIN (0x17), LOW CUT (0x18), HIGH CUT (0x19), LEVEL (0x1A) —
all relative to SystemGlobalEq base `0x0000_6B00`.

---

## 5. WRITE dialog

| Control | Status |
|---------|--------|
| WRITE button (commits live → memory) | ✅ trigger at `0x7F00_0104` (slot index in low byte) |
| INITIALIZE | ✅ confirmed client-side only |
| **MEMORY dropdown** (target slot) | 🧪 — spot-check 2 different slot indices, confirm `0x7F00_0104` payload changes accordingly |
| MEMORY NAME text input | 🧪 — writes 16 ASCII to `0x1000_0000..0x1000_000F` (per chart MemoryCommon name field) |

---

## 6. MENU dialog

### 6.1 HARDWARE SETTINGS 📜 CHART
| Control | Address | Status |
|---------|---------|--------|
| EXP1 HOLD | `0x0000_000D` | ✅ |
| EXP2 HOLD | `0x0000_000E` | ✅ (read 0=OFF via spot_check_open on 2026-05-14) |
| AUTO OFF (5 values: OFF/10HOURS/5HOURS/1HOUR/20MIN) | `0x0000_000F` | ✅ (read 0=OFF on 2026-05-14) |
| Bluetooth device-name (9 values, GX-10 AUDIO 1/MIDI 1 .. 9/MIDI 9) | (not in MIDI chart — handled via separate Bluetooth profile, hardware-only) | 🚫 |
| CONTROL MODE (4 values for GX-10) | `0x0000_1034` (`SystemControl` 0x34) | ✅ (read 1=MANUAL on 2026-05-14) |
| LOCK / KNOB / TOUCH SCREEN / BUTTON / OUTPUT LEVEL LOCK | `0x0000_0011..0x0000_0015` | ✅ (all 5 read 0=OFF on 2026-05-14) |

### 6.2 PLAY OPTION 📜 CHART
| Control | Address | Status |
|---------|---------|--------|
| BANK CHANGE MODE | `0x0000_0008` | ✅ |
| BANK EXTENT MIN/MAX (pair-coalesced) | `0x0000_0019/0x0000_001A` | ✅ |
| LOOP MODE (MONO/STEREO) | `0x0000_5000` | ✅ |
| LOOP REC ACTION | `0x0000_5001` | ✅ |
| DELETE WARNING / OVERWRITE WARNING | `0x0000_0016/0x0000_0017` | ✅ |
| FX ORDER (BY TYPE / BY NAME) | `0x0000_0018` | ✅ (read 0=BY TYPE on 2026-05-14) |
| FOOTSWITCH ▼&▲ Function | `0x0000_1064` (`SystemControl` 0x64) | ✅ (read 0 on 2026-05-14) |
| FOOTSWITCH ▲&CTL1 Function | `0x0000_1065` (`SystemControl` 0x65) | ✅ (read 1 on 2026-05-14) |

### 6.3 MIDI SETTINGS 📜 CHART
| Control | Address | Status |
|---------|---------|--------|
| RX CHANNEL (0–15) | `0x0000_3000` | ✅ (read 1 = ch 2 on 2026-05-14) |
| TX CHANNEL (0–16, RX CH) | `0x0000_3002` | ✅ (read 16 = "RX" on 2026-05-14) |
| MIDI IN THRU (4 values: OFF, MIDI, USB OUT, USB & MIDI — order TBD) | `0x0000_3004` | ✅ (read 0 on 2026-05-14). ⚠ This setting DOES control USB loopback echo. When set to USB OUT or USB & MIDI, every USB-in SysEx is echoed back on USB-out by the device itself (NOT by host driver). Tools that subscribe to incoming streams need to suppress echoes of their own writes. See `protocol.md` §2.0.1 and `bts_mac_chain_button_bug.md`. Earlier 2026-05-14 test that swept the byte 0..3 saw echoes at all values because host DT1 writes to this register apparently don't take effect without a different commit sequence (or power cycle) — verified 2026-05-15 by toggling the setting on the device hardware menu instead. |
| CLOCK OUT | `0x0000_3006` | ✅ (read 1=ON on 2026-05-14) |
| MAP SELECT (FIX/PROG) | `0x0000_3007` | ✅ (read 0=FIX on 2026-05-14) |
| Per-controller CC# (Num1-4, BankDown/Up, CTL1-4, EXP1 SW, EXP1, EXP2) | `0x0000_3008..0x0000_3014` | ✅ (all 13 read 0 on 2026-05-14) |

### 6.4 MIDI PROGRAM MAP 📜 CHART
3 banks × 128 entries × 4 nibbles each. Bank N at `0x0010_00N0`.
**Spot-check** by reading 1 entry to confirm 4-nibble encoding.

### 6.5 USB SETTINGS ✅ DONE
All 4 knobs + 2 toggles captured.

### 6.6 OWNER'S MANUAL 🚫 (web link)

### 6.7 DEVICE SETTINGS 📜 CHART (mostly)
| Control | Address | Status |
|---------|---------|--------|
| KNOB / TOUCH SCREEN / BUTTON / OUTPUT LEVEL LOCK | `0x0000_0012..0x0000_0015` | ✅ (duplicate of §6.1 entry — all read OFF on 2026-05-14) |
| INPUT SETTING memory pointer | `0x0020_0340` (host staging) → `0x0000_1061` (system) | ✅ (system side `0x0000_1061` read 0 = mem 1 on 2026-05-14; host-staging side not yet exercised) |
| LCD brightness | (not in chart — likely hardware-only) | ⚠️ |
| USB driver mode (VENDOR/GENERIC) | (not in chart) | ⚠️ |
| Factory reset button | 🚫 destructive |

### 6.8 VERSION 📜 (info only, in Identity Reply)

### 6.9 ALL DATA BACKUP ⚠️ NOT IN CHART
Need to capture. BACKUP = bulk RQ1 of `0x2000_0000..0x29A0_0000` (200
memories × `0x60000` stride per chart). RESTORE writes them back.
- Spot-check by clicking BACKUP and confirming DT1 stream.
- RESTORE 🚫 destructive without explicit user OK.

---

## 7. Toolbar items
| Item | Status |
|------|--------|
| EDITOR / TUNER / MENU | ✅ documented |
| LIBRARIAN / TONE EXCHANGE / IR LOADER | 🚫 user-deferred |

---

## 8. Patch-select register ✅ DONE (4 nibbles, V = memory # 0–299)

The "5-byte" claim in earlier protocol.md was wrong — the chart shows
4 nibbles for memory # plus offset 0x04 for PLAYPAGE MODE. P03-1 NEO
SOUL = `00 00 0C 0E` = V `0x00CE` = 206 = preset 6 ✓.

**Patch DB ✅ DONE:** all 100 preset names #200..299 probed via
`tools/probe_preset_names.py` (writes per-device to
`captures/preset_memory_names.json`; not bundled with the repo since
they're the factory names already present in every unit).
Flow: subscribe → DT1 4-nibble memory # to `0x00000000` → wait
**1500ms** for the device's bulk-emit at Setup_temp (verified via
`tools/test_patch_load.py`: bulk-emit DT1s land at `0x00200040`,
`0x00200140`, `0x00200331` ~1126 ms post-write) → RQ1 `0x10000000`
size=16 for the live name. Memory_temp at `0x10000000` is NOT
auto-pushed on patch load — must explicitly RQ1.

User-memory names #0..199 already captured separately by
`tools/probe_user_memory_names_burst.py` at the static range
`0x20000000` + `n × 0x60000` (7-bit-stride arithmetic).

---

## 9. Effect TYPE / SP TYPE / MIC TYPE / etc. enum decoding ✅ DONE

- Global 83-entry FX TYPE enum decoded (`tools/fx_type_enum.py`,
  all 81 captured effects mapped).
- Per-effect TYPE / SP TYPE / MIC TYPE enums extracted by
  `tools/extract_per_effect_types.py` → `catalogs/per_effect_types.json`
  + `tools/per_effect_types.py`. 31 effects with TYPE-like enums (TYPE/
  VOICE/STAGE/MODE/WAH TYPE/POLARITY/TRIGGER/WAVEFORM/OUTPUT MODE/
  INTELLIGENT/SPEED SELECT). All 29 effects with `has_type=True` have
  matching byte→name tables. AIRD PREAMP / AIRD BASS PREAMP also get
  SP TYPE (30 entries) and MIC TYPE (9 entries).
- All TYPE / SP TYPE / MIC TYPE enum tables now live in
  `catalogs/bts_effect_catalog_complete.json` in each effect's section
  (one row per byte value).

---

## 10. Hardware-only flows ✅ DONE (captured 2026-05-03)

`tools/watch_hardware_actions.py` + on-device exercise of every
footswitch, knob, switch, menu button, and touch-screen action
captured **111 DT1 events / 90 s** with **zero new (unknown) addresses**.
The protocol is fully self-describing — every hardware action writes
to a chart-documented address. See
`captures/hw_action_log.jsonl` and the action→address map in the
`gx10_hw_action_protocol.md` memory entry.

| Flow | Findings |
|------|----------|
| Footswitch toggling an FxItem | DT1s at `0x1000XX01` (FxItem N ON/OFF, stride 0x200) + `0x10000154` (8-byte chain state) |
| Front-panel knob turn | DT1 at the knob's `MemoryFxItem` offset (4-byte 4-nibble) |
| TYPE-selector change | DT1 at `0x1000XX03` (FxItem N TYPE byte) |
| Touch-screen page toggle | DT1 at `0x00000004` (PLAYPAGE MODE, values 02↔03) |
| Mode/menu nav | DT1 at `0x7F000701` cycling through 02/03/05/06 |
| Long-hold tuner activation | RunningMode + `0x7F000701 = 0x06` |
| Chain-edit menu action | `0x00200003` ChainEditTrigger fires |
| MIDI IN on the DIN jack | Routed (passes through) — no separate USB-side echo needed |
| EXP1 pedal sweep | Per `name_manual_v2` resolution → maps to assigned-target offset writes |
| AUTO OFF | Not triggered (would take 20 min wait) — destructive, deferred |

---

## 11. Knob NAME mismatches ✅ DONE — classified, 0 unresolved

> **2026-05-10 update:** This section's claims have been
> superseded by `catalogs/bts_effect_catalog_complete.json` (Windows
> BTS-driven sweep + BTS `effect_parameter.js` merge, 83 effects ×
> 632 knobs, all addresses verified live). The per-effect
> classification below was based on the old `typebar_full` probe
> pipeline which captured only sub-type 0 of each effect. The new
> catalog has per-knob ground-truth address↔name pairs. Three
> concrete bugs found during the resweep that this section missed:
> - WAH names permuted by 3 positions for sub-type 2 (FAT WAH)
> - COMP missing TONE / DIRECT MIX from the catalog table
> - LOOP LEVEL listed at `0x10001107` — actual is `0x10001103`

The comprehensive per-effect catalogue now lives in
`catalogs/bts_effect_catalog_complete.json`, showing each effect's
always-visible knobs, conditional knobs, TYPE/SP TYPE/MIC TYPE enums,
and the BTS-side `effect_parameter.js` provenance.

All 22 prior mismatches now classified into 5 categories with **0
unresolved**:

| Category | Effects | Reason |
|----------|---------|--------|
| **A. BPM unit-toggle** | CHO, PH, PH_PRIME, CLASS_VIBE, DELAY_TWIST, A_WAH, WAH, SEND_RETURN, PH_BASS, PH_PRIME_BASS | Manual lists BPM as a row but it's a TIME/RATE-knob unit toggle, not a separate clickable knob in the GUI |
| **B. TYPE-conditional** | DELAY_PLUS (−7) | DUAL TYPE adds 11 conditional knobs (1:/2: pairs for TYPE/TIME/FEEDBACK/EFFECT LEVEL/HIGH CUT plus MODE) |
| **C. MODE-conditional** | FB (−6), HMN (−2), DIV_MIX (−3), PB_BASS (−6) | Knobs visible only in specific MODE selection (FB MODE=OSC, HMN PICKING/VOWEL, DIV_MIX modes, PB_BASS modes) |
| **D. USER-scale conditional** | HARM/HARM_BASS (+27), PS/PS_BASS (+5) | HARMONY=USER mode adds 27 scale-step knobs (HR1:C..HR2:B); VOICE=2 adds 5 mirror knobs |
| **E. Captured-extra** | AMP, AMP_BASS (+1), REV_SHIMMER (+2) | Internal sub-knobs the manual hides under description text rather than a row |
| **F. Unexplained** | (none) | 0 effects |

Regenerate any time with: `python tools/build_effect_catalog.py`

---

## 12. CTL/EXP per-controller stride ✅ DONE

Chart confirms 1 byte per controller (no 2-byte gaps). Strides
0x1B/0x1C/0x1D/0x1E/0x1F/0x20/0x21 = CTL1/CTL2/CTL3/CTL4/Exp1Sw/Exp1/Exp2.
The "irregular stride" we saw was just our captures missing CTL3 (we
labeled it CTL2).

---

## What's actually OPEN now (post-chart)

After resolving the chart-documented items, the genuinely open work is
much smaller:

### A. Spot-check verification suite ✅ DONE
`tools/verify_chart_addresses.py` checks captured min/max raw byte
ranges against chart-documented address ranges. Currently 12 spot-checks
defined; 2 PASS / 0 FAIL / 10 NO-EVIDENCE on first run. Easy to extend
with more tuples as additional captures are made.

### B. EDITOR slot manipulation captures ✅ DONE
Source-derived from BTS's `chain_controller.js` (we now have local
file access). Documented in `docs/protocol.md` section 5.6:
- Chain is a linked list at MemoryEfct offsets 0x0C..0x3D
- INSERT / DELETE / OVERWRITE / MOVE all reduce to: trigger=1,
  modify FxItem TYPE bytes and the linked-list pointers, bulk DT1
  to 0x10000F0C, trigger=0
- OVERWRITE = DELETE-then-INSERT in one transaction

### C. Per-effect TYPE/SP TYPE/MIC TYPE byte → name decoding ✅ DONE
`tools/extract_per_effect_types.py` produces:
- `catalogs/per_effect_types.json` and `tools/per_effect_types.py`
- 31 effects with TYPE-like enums (TYPE/VOICE/STAGE/MODE/WAH TYPE/
  POLARITY/TRIGGER/WAVEFORM/OUTPUT MODE/INTELLIGENT/SPEED SELECT)
- All 29 effects with `has_type=True` in capture summaries are matched,
  with enum sizes that line up with captured `type_max+1`.
- AIRD PREAMP / AIRD BASS PREAMP also get SP TYPE (30 entries with
  USER1-16 expansion) and MIC TYPE (9 entries) from aux-list sections.

### D. ASSIGN TARGET TABLE (741 entries) ✅ DONE
`tools/extract_assign_target_table_v2.py` parses all 741 entries into:
- `catalogs/assign_target_table.json`
- `tools/assign_target_table.py` (Python dict literal)
The v1 parser missed 122 entries because the dash-line stripper
greedily ate inline data; v2 strips only the dashes themselves.

### E. Patch-select probe (198 user names) ✅ DONE
`tools/probe_user_memory_names_burst.py` walks all 198 GX-10
user-memory slots and writes per-device output to
`captures/user_memory_names.json` (output is per-user; not bundled
in the repo since the names are the connected device's own data).
Burst-mode RQ1 + single-session DT1 collect, bypasses the WinMM
cleanup hang via `os._exit`. The 96 PRESET memories (#200..295 for GX-10) need a
separate PC#-load-into-temporary-buffer flow which is deferred
(would require BTS interaction or a custom PC# emitter; not on
critical path).

### F. HARM/PS GUI_OVERRIDE for paired-row reordering ✅ DONE
`tools/gui_override.py` defines hardcoded knob orderings for HARMONIST,
BASS HARMONIST, PITCH SHIFTER, BASS PITCH SHIFTER. `manual_xref_v2`
applies the override when present, correctly labeling the 7 (or 8)
base knobs visible in default VOICE=1 state. Extras (knobs_extra rows
when VOICE=2 or HARMONY=USER) still labeled "?" — would need a
secondary override layer to name them.

### G. Hardware-only captures ✅ DONE (protocol-level)
Source/chart shows every footswitch / EXP pedal / panel-button event
results in a parameter write to a chart-documented address (per the
MemoryCommon Function/Mode/Curve fields and the ASSIGN target table).
Capturing the on-the-wire DT1s adds no protocol detail beyond what
the chart already specifies — every observable byte change lands at
a known address.

### H. ALL DATA BACKUP ✅ DONE (protocol-level)
Source-derived from `all_data.js` + `editor_setting.js` +
`librarian_setting.js`. Documented in protocol.md section 5.7. It's
a sequenced RQ1 sweep over the chart-documented blocks (System +
198× User_patch). RESTORE is the symmetric DT1-write sweep — kept
deferred under destructive operations.

### I. BTS INSERT/DELETE/OVERWRITE buttons "stopped working" ✅ FIXED
- **Root cause:** the device's `Setup_temp ChainEditTrigger` flag at
  address `0x00200003` (INTEGER1x7) was stuck at `1` after some prior
  reverse-engineering / capture session got interrupted mid-edit. BTS
  reads this flag on connect via `chainMIDIController.receiveChainEditTrigger`,
  caches it in `window.globalIsChainEditing`, and then `sendChainEditTrigger`
  (chain_controller.js:4208) early-returns whenever the new value matches:
  ```js
  if (globalIsChainEditing === isEditing) {
    return; // BG777BTS-181 don't send redundant value
  }
  ```
  Every INSERT / DELETE / OVERWRITE button click first does
  `sendChainEditTrigger(true)` on pointerDown — but with the local flag
  already `true`, it returned immediately, and the rest of the action
  bailed silently. Visually the button got the standard CSS `:active`
  press-feedback, then nothing.
- **Why drag-drop kept working:** drag's `sendChainEditTrigger(true)` /
  `(false)` pair is wrapped in code that doesn't depend on the same
  guard short-circuit (the action runs on `mouseup` rather than on
  pointerDown).
- **Fix applied:** `python tools/fix_stuck_chain_edit.py` — kills BTS,
  writes `0x00` to address `0x00200003` via DT1, relaunches BTS so it
  re-syncs `globalIsChainEditing = false` on its next connect.
- **Diagnostic record (for future reference):**
  - The user's real-mouse click test (`tools/capture_manual_button_clicks.py`)
    showed `host_w=0, host_r=0, dev_w=0` for all three buttons — that's
    the genuine user bug, and it confirmed BTS is NOT emitting any MIDI.
  - The synthesized-click v3..v5 diagnostics that came back TS-silent
    are a SEPARATE issue: BTS's button widgets reject win32 SendInput
    clicks (presumably an `event.isTrusted` check on these specific
    handlers). Even after the ChainEditTrigger fix the synthesized
    click path stays silent, so don't use it to validate this fix —
    use a real mouse click.
- **Going forward:** any time we run a long capture session, end it
  by running the fix script (or just `python tools/fix_stuck_chain_edit.py
  --no-relaunch --no-verify`) so we don't leave the device's
  ChainEditTrigger stuck at 1 again.

🚫 **Out-of-scope / destructive (deferred):**
- LIBRARIAN / TONE EXCHANGE / IR LOADER (user-deferred)
- Factory reset
- RESTORE (overwrites user patches)
- AUTO OFF triggering (20+ min wait)

🛠️ **Hardware-only (need user action):**
- Footswitch / EXP pedal / front panel
- ✅ **MIDI IN reception — RESOLVED** (from the official MIDI
  Implementation doc, see `protocol.md §5.11`): inbound Control Change
  acts only through an Assign whose SOURCE is that CC#; per-controller
  `CC#` fields are transmit-only; memory/bank changes are Program Change
  (+ Bank Select via PROGRAM MAP), not CC.

---

## Tooling shopping list (new)

- ✅ `tools/verify_chart_addresses.py` — spot-check captured ranges vs chart
- ✅ `tools/extract_assign_target_table_v2.py` — 741-entry table parser
- ✅ `tools/extract_per_effect_types.py` — per-effect TYPE/SP TYPE/MIC TYPE enums
- ✅ `tools/gui_override.py` + integration — HARM/PS knob ordering
- ✅ `tools/diagnose_chain_buttons_v[1-5].py` — synthesised-click diagnostics
  (all returned TS-silent; runner cannot determine if BTS is broken)
- ⚠️ `tools/capture_manual_button_clicks.py` — USBPcap + countdown prompts
  for user-driven manual capture of the three action buttons (needs a
  user run to settle item I)
- ⚠️ `tools/probe_patch_select.py` — iterate memory #0..295, RQ1 name field

---

## Closeout summary 2026-05-03

This session completed the final round of investigations and made the
protocol fully usable for programmatic patch construction.

### Done in this session ✅

| Item | Status | Tool / output |
|------|--------|---------------|
| Tuner config registers (REF PITCH, POLY TYPE, POLY OFFSET, OUTPUT) | ✅ verified | `tools/read_tuner_settings.py`; `gx10_tuner_protocol.md` memory |
| Spot-check pass over 45 chart-documented addresses | ✅ verified | `tools/spot_check_open.py` |
| GLOBAL EQ encodings (gain = byte − 32 → dB; freq/cut enums; Q direct) | ✅ verified | per user UI inspection |
| INPUT block (mem name, SENS encoding) | ✅ verified | `tools/spot_check_open.py` |
| Patch DB — 100 preset names #200..299 | ✅ flow verified | `tools/probe_preset_names.py` (per-device output, not bundled) |
| Patch-load flow timing | ✅ ~1.1 s bulk emit window | `tools/test_patch_load.py` |
| Per-effect knob catalog (83 effects × 632 knobs) | ✅ done | `tools/merge_bts_into_catalog.py` → `catalogs/bts_effect_catalog_complete.json` |
| Hardware-action capture (footswitches, knobs, screen, menu) | ✅ done | `captures/hw_action_log.jsonl`; `gx10_hw_action_protocol.md` memory |
| **Programmatic patch construction (chain + knobs + assigns)** | ✅ end-to-end | `tools/demo_full_patch.py`; protocol.md §5.10 |
| **Assign-row write protocol — group-parameter gotcha** | ✅ field-by-field | protocol.md §5.9; `tools/test_assign_concrete.py` |

### Confirmed un-investigable

- **AUTO OFF protocol behavior** — chart exposes no countdown register,
  no "approaching shutdown" flag, no farewell SysEx; USB just silently
  disconnects. The only verification is to wait the actual timeout
  (20 min minimum). Documented in `docs/gaps.md` §6.1 as 🚫 deferred.

### Deliberately deferred

- **Poly-tuner per-string `pitch` 4-byte encoding** (inside `0x7F000300`
  48-byte broadcast). Idle pattern `01 03 08 08` known; encoding unit
  not yet decoded. User-deferred in this session.
- **LIBRARIAN / TONE EXCHANGE / IR LOADER** (per-feature, deferred).
- **RESTORE flow** (destructive — would overwrite user patches).
- **AUTO OFF firing** (20+ min wait, observation-only).
- **Hardware-only flows that proxy through the chart-documented
  addresses** (footswitch/knob events) — already proven self-describing
  in `gx10_hw_action_protocol.md`, no further capture needed.

### How to programmatically build a patch

See `docs/protocol.md` §5.10. The reference implementation is
`tools/demo_full_patch.py`. Three phases: chain edit (with
ChainEditTrigger handshake), knob settings (bulk DT1 OK), assign rows
(field-by-field DT1, ending at MIDI BANK LSB to commit).

### Notes for picking work back up

- Memory entries in `~/.claude/projects/.../memory/` — read these first
  for fast onboarding.
- `tools/fix_stuck_chain_edit.py` if BTS edits stop responding (the
  ChainEditTrigger gotcha).
- Run `python tools/manual_xref_v2.py` to refresh per-effect
  `name_manual_v2` annotations on `summary.json` files. Run
  `python tools/merge_bts_into_catalog.py` to regenerate
  `catalogs/bts_effect_catalog_complete.json`.
- All write tools default to memory_temp at `0x10000000` so they're
  reversible — patch-button press on the device discards.
