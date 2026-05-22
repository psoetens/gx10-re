# GX-10 / GX-100 — Programmatic Patch Construction

How to build a complete patch (effect chain + main-display knob mapping +
MIDI assigns) over USB SysEx, end-to-end. Every fact below is verified
against a live GX-10 by `tools/demo_full_patch.py` (2026-05-03).

For the full chart-level address-block table, see `docs/protocol.md` §3.
For the per-effect knob catalogue, see `catalogs/bts_effect_catalog_complete.json`
(schema: `docs/bts_catalog_schema.md`).

---

## Mental model

A patch lives in two parallel address ranges:

- **`0x10000000+`** — *memory_temp*, the live edit buffer. Everything
  the device is currently playing comes from here. Reversible — pressing
  any patch button on the device discards `memory_temp` and reloads the
  saved patch.
- **`0x20000000 + n × 0x60000`** — *user memory slot N*. Persistent
  across power cycles. The on-device WRITE button copies `memory_temp`
  into the current user slot. (Stride is in 7-bit-per-byte arithmetic;
  see `tools/probe_user_memory_names_burst.py:memory_addr` for the
  helper.)

This document only writes to `memory_temp`. Promoting the result to a
user slot is one extra DT1 (`Setup_temp.WriteTrigger` per chart) — left
out here so the demo stays fully reversible.

A patch's structure inside `memory_temp`:

```
0x10000000  MemoryCommon        0x101 bytes  patch name, knob settings,
                                              assigns 1..20, memory MIDI
0x10000140  MemoryLed           0x1C  bytes  per-memory LED state
0x10000200  Assign 1            0x40  bytes  (0x2D used)  ← group params
0x10000240  Assign 2            0x40
...
0x10000F00  MemoryEfct          0x3E  bytes  master block (BPM, KEY,
                                              CARRYOVER, chain top + 49
                                              NEXT pointers)
0x10001100  Fx Item 0           0x200 bytes  TYPE byte + ON/OFF + 44
                                              FX Parameters
0x10001300  Fx Item 1           0x200
...                                            (storage slots, 0..19
                                              addressable by the chart;
                                              up to 49 internal slots)
```

Chain order is encoded as a **linked list** in MemoryEfct, *not* by
position in storage. Storage slot ≠ chain position unless you set them
to match.

---

## End-to-end recipe — BOOST CLEAN + PEQ + REV PLATE

### Phase 1: build the chain

Wrap chain edits in the ChainEditTrigger handshake — BTS does this and
the device caches the flag, so leaving it stuck at 1 silently breaks
INSERT/DELETE/OVERWRITE for subsequent BTS sessions (see
`tools/fix_stuck_chain_edit.py`).

```
DT1  0x00200003  =  01                              # ChainEditTrigger ON

# Pick storage slots for the new chain. Slot 0/1/2 work for an empty
# patch. To add to an existing chain, first read the existing
# MemoryFxItem TYPE bytes and pick unused (0x00) slots.

# FxItem #0 = BOOSTER (FX TYPE 0x24), ON, sub-TYPE = CLEAN BOOST (1)
DT1  0x10001100  =  24                              # global FX TYPE
DT1  0x10001101  =  01                              # ON/OFF
DT1  0x10001103  =  08 00 00 01                     # FX Param 1 = sub-TYPE,
                                                      # offset-binary: 1 + 0x8000

# FxItem #1 = PARAMETRIC EQ (FX TYPE 0x14), ON
DT1  0x10001300  =  14
DT1  0x10001301  =  01

# FxItem #2 = REVERB (FX TYPE 0x3E), ON, sub-TYPE = PLATE (2)
DT1  0x10001500  =  3E
DT1  0x10001501  =  01
DT1  0x10001503  =  08 00 00 02

# Chain linked list — one bulk DT1 of 50 bytes:
#   byte 0   = TOP        = 1   (= storage slot #0 + 1)
#   byte 1   = NEXT[0]    = 2   (= storage slot #1 + 1)
#   byte 2   = NEXT[1]    = 3   (= storage slot #2 + 1)
#   byte 3   = NEXT[2]    = 0   (end of chain)
#   bytes 4..49                 (NEXT[3..48], all zero)
DT1  0x10000F0C  =  01 02 03 00 00 .. 00 (×46)

DT1  0x00200003  =  00                              # ChainEditTrigger OFF
```

The FX TYPE bytes come from `tools/fx_type_enum.py` (the global 0..82
table). The sub-TYPE values come from `tools/per_effect_types.py`.

### Phase 2: configure the 4 main-display knobs

Two contiguous fields in MemoryCommon:

```
# KnobN SettingFxItem (1 byte each, chain position 0..19):
#   knob 1 -> slot 0 (BOOST)
#   knob 2 -> slot 1 (PEQ)
#   knob 3 -> slot 2 (REV)
#   knob 4 -> 0     (no 4th effect; will appear unmapped)
DT1  0x10000069  =  00 01 02 00

# KnobN SETTING (4 nibbles each = 16 bytes total, ASSIGN TARGET TABLE
# index from the 741-entry chart table):
#   knob 1 -> 73  (BOOSTER TYPE)              = 00 00 04 09
#   knob 2 -> 221 (PARAMETRIC EQ HIGH GAIN)   = 00 00 0D 0D
#   knob 3 -> 374 (REVERB PRE-DELAY)          = 00 01 07 06
#   knob 4 -> 0   (---- unmapped)             = 00 00 00 00
DT1  0x1000006D  =  00 00 04 09  00 00 0D 0D  00 01 07 06  00 00 00 00
```

Both DT1s are bulk (multi-byte) and commit immediately — group-parameter
treatment seems specific to the [Assign] row, not knob settings.

### Phase 3: write the assign — field-by-field

**The non-obvious part.** A single bulk DT1 of all 45 bytes to
`0x10000200` does NOT commit the TARGET sub-group. Each chart-listed
field must be its own DT1, ending with the MIDI-BANK-LSB write at
`0x1000022B` to trigger the group commit-check.

Example: CC#64 toggles REV ON/OFF, MODE=TOGGLE.

```
DT1  0x10000200  =  01            # SW = ON
DT1  0x10000201  =  02            # TARGET_FX_ITEM = 2 (REV at chain pos 2)
DT1  0x10000202  =  00 00 00 01   # TARGET = 1 (generic EFFECT ON/OFF)
DT1  0x10000206  =  08 00 00 00   # TARGET MIN = 0 + 0x8000 (offset-binary)
DT1  0x1000020A  =  08 00 00 01   # TARGET MAX = 1 + 0x8000
DT1  0x1000020E  =  34            # SOURCE = 52 = CC#64
DT1  0x1000020F  =  00            # MODE = TOGGLE
DT1  0x10000215  =  00 00 00 00   # ACT RANGE LO  = 0
DT1  0x10000219  =  03 0F 0F 0F   # ACT RANGE HI  = 16383 (full)
DT1  0x1000021D  =  00            # MIDI CH       = SYSTEM
DT1  0x1000021E  =  00            # MIDI CC# (output, unused for CC source)
DT1  0x1000021F  =  00 00 00 00   # MIDI CC VAL MIN
DT1  0x10000223  =  03 0F 0F 0F   # MIDI CC VAL MAX
DT1  0x10000227  =  00            # N/A fixed
DT1  0x10000228  =  00            # MIDI PC#
DT1  0x10000229  =  00 00         # MIDI BANK MSB = OFF
DT1  0x1000022B  =  00 00         # MIDI BANK LSB = OFF  ← FINAL: commits the group
```

The reference helper is `write_assign_fields()` in `tools/demo_full_patch.py`.

---

## Encoding cheat sheet

| Field type | Bytes | Encoding |
|------------|-------|----------|
| 1-byte enum | 1 | direct value (e.g., FX TYPE, ON/OFF, MODE) |
| 2-byte (e.g., MEMORY LEVEL, BANK MSB/LSB) | 2 | low nibble of each byte; value = `(b0 << 4) \| b1` |
| 4-byte 4-nibble TARGET (0..740) | 4 | low nibble of each byte; value = `(b0<<12)\|(b1<<8)\|(b2<<4)\|b3` |
| 4-byte 4-nibble FX Parameter / TARGET MIN/MAX | 4 | as above, **plus** add 0x8000 to displayed value before encoding (offset-binary). Decode: `raw - 0x8000`. |
| 4-byte 4-nibble REF PITCH | 4 | low nibble = direct Hz. 435 Hz → `0x01B3` → bytes `00 01 0B 03`. |
| 4-byte 4-nibble ACT RANGE / MIDI CC VAL | 4 | direct (no +0x8000), max value 16383 = `03 0F 0F 0F` |

---

## Things to know if returning to this work later

- **The on-device assign-category label is cached.** Bytes you write
  via SysEx update the underlying state immediately, but the device's
  on-screen label only re-renders when you navigate into the assign
  settings view OR trigger an on-device WRITE. Read-back via RQ1 tells
  the truth.
- **BTS's UI is also cached.** If BTS is open while you SysEx-write,
  BTS may show stale state, and clicking a control in BTS can push
  BTS's stale cache back over your write. Either close BTS during
  programmatic work, or do read-after-write to verify and re-apply.
- **`Setup_temp.ChainEditTrigger` (0x00200003)** must end a chain edit
  at 0 (a writes 1 → make changes → write 0). Leaving it at 1 silently
  disables BTS's chain-edit buttons on next launch — fix is
  `tools/fix_stuck_chain_edit.py`.
- **CC#32..CC#63 are not valid SOURCE values.** Roland excludes them
  (CC#32 = Bank-Select LSB, 33..63 reserved). Use CC#1..31 (SOURCE
  bytes 21..51) or CC#64..95 (SOURCE bytes 52..83).
- **Hardware actions emit DT1s** at chart-documented addresses — see
  `gx10_hw_action_protocol.md` memory. Subscribe with
  `DT1 0x7F000001 = 1` and you receive a live event stream covering
  every effect on/off, knob movement, TYPE change, and mode/page change.
  No polling needed.
