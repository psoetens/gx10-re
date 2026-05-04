# GX-10 reverse engineering

Tools and notes for reverse-engineering the BOSS GX-10's USB-MIDI control
protocol, as spoken between BOSS Tone Studio for GX-10 and the device.

```
gx10-re/
├── docs/
│   ├── protocol.md                   # Address map + 10 sub-protocols (start here)
│   ├── programmatic_construction.md  # End-to-end recipe for building a patch
│   ├── effect_catalog.md             # 81 effects, every captured knob (auto-gen)
│   ├── gaps.md                       # What's done / deferred / un-investigable
│   ├── menus.md, methodology.md, official_xref.md, bpm_encoding.md, API.md
│   └── manuals/                      # Roland MIDI Implementation chart + Parameter Guide
├── tools/
│   ├── midi_send.py                  # Active sender (DT1 / RQ1 / identity)
│   ├── midi_sniff.py                 # Passive WinMM sniffer (JSONL log)
│   ├── address_scan.py               # Combine sniffer + sender, sweep address space
│   ├── example_lib.py                # Shared utilities for the example_*.py scripts
│   ├── example2_zero_knobs.py        # Zero the 4 main-display knobs
│   ├── example3_show_chain.py        # Render chain with DIV/MIX A/B paths
│   ├── example4_all_off.py           # Turn off every effect (DIV -> A path)
│   ├── demo_full_patch.py            # Build a custom patch end-to-end
│   ├── build_effect_catalog.py       # Regenerate docs/effect_catalog.md
│   ├── probe_user_memory_names_burst.py / probe_preset_names.py  # Patch DB capture
│   ├── watch_hardware_actions.py     # Subscribe + log device-side events
│   ├── spot_check_open.py            # Bulk-read chart-documented registers
│   ├── read_tuner_settings.py        # REF PITCH / POLY TYPE / OFFSET / OUTPUT
│   ├── fix_stuck_chain_edit.py       # Clear stuck ChainEditTrigger
│   └── (~50 more — capture, diagnostic, and one-off probes)
└── captures/                         # JSON / JSONL summaries of capture sessions
```

## TL;DR findings

- GX-10 uses **standard Roland "extended" SysEx**: 5-byte model ID, 4-byte
  big-endian addresses, 7-bit checksum.
- Family code `0x040B`, model number `0x0000`, default device ID `0x10`.
- The device exposes its MIDI port through Microsoft's USB-MIDI class
  driver, which **allows multiple openers** — both a passive sniffer and
  Tone Studio can hold the port at the same time. The output port is
  similarly shareable, which means a Python script can issue its own
  RQ1 reads / DT1 writes even while Tone Studio is connected.
- Subscribe with `DT1 0x7F000001 = 1` and the device pushes a real-time
  event stream of every footswitch, knob, screen, and menu action — all
  at chart-documented addresses (see `gx10_hw_action_protocol` memory).
  No polling needed for state mirroring.
- A patch is fully programmatically constructable: chain edit (linked
  list at `0x10000F0C` with the `0x00200003` ChainEditTrigger handshake),
  main-display knob settings (MemoryCommon `0x69..0x7C`), and 20 MIDI
  assigns (per-row 0x40 stride at `0x10000200..0x10000B7F`). See
  `docs/programmatic_construction.md` for the recipe and
  `tools/demo_full_patch.py` for a working example.

## Quick examples

Four self-contained example scripts demonstrate the major operations:

```
tools/demo_full_patch.py        Build BOOST CLEAN + PEQ + REV PLATE chain,
                                 configure the 4 main-display knobs, arm
                                 a CC#64 -> REV ON/OFF assign.

tools/example2_zero_knobs.py    Zero the 4 main-display knobs of the
                                 currently loaded patch (handles 1-byte
                                 ON/OFF and 4-byte FX-Param targets).

tools/example3_show_chain.py    Read the chain linked-list, render it
                                 with DIVIDER / MIXER parallel-section
                                 A/B path attribution via the per-FxItem
                                 DuplicationNumber byte.

tools/example4_all_off.py       Turn every effect in the chain OFF.
                                 DIVIDER is special-cased to switch to
                                 SINGLE / A path rather than ON/OFF=0.
```

Every example writes only to memory_temp at `0x10000000+`, so a patch
button press on the device discards the changes.

## Protocol-level "what we know"

- **Address map** (`docs/protocol.md` §3): MemoryCommon, MemoryLed,
  20 Assigns, MemoryEfct (BPM + chain linked list), 20 MemoryFxItems
  (each 0x200 bytes, with TYPE byte + ON/OFF + DupNumber + 44 FX
  Parameters).
- **FX Parameter encoding**: each is **4 nibbles big-endian, offset
  binary** (raw − 0x8000 = display value). The chart prints this as
  range `12768..52768` = `−20000..+20000`.
- **DuplicationNumber** (MemoryFxItem offset 0x02) tags A/B path
  inside a DIVIDER..MIXER parallel section: `dup=1` is path A,
  `dup=2` is path B. The SPLITTER (FX TYPE 30) is an internal
  housekeeping marker between the two paths; it doesn't appear on
  the device's chain display.
- **Per-effect TYPE selectors** are at MemoryFxItem FX Param 1 (offset
  `0x03`). Some effects expose this in the ASSIGN TARGET TABLE (BOOSTER,
  REVERB, …); others hide it (PHASER's `STAGE` is FX Param 2 because the
  TYPE selector at Param 1 isn't user-assignable). `tools/example_lib.py`
  resolves all of this automatically.
- **Assign-row writes are field-by-field** — the chart documents the
  group-parameter rule, but a single bulk DT1 of all 45 bytes is
  rejected (only SOURCE/MODE/ACT-RANGE/MIDI-CC commit; SW/TARGET/MIN/MAX
  get cleared to defaults). Each chart-listed field needs its own DT1,
  ending with the MIDI BANK LSB write at offset `0x2B` to trigger the
  group commit-check. See `docs/protocol.md` §5.9.
- **Roland excludes CC#32..CC#63** from the assign SOURCE enum (CC#32 is
  Bank-Select LSB, 33..63 reserved). Use CC#1..31 or CC#64..95.

## What this repo does *not* do

- **Sniff the host → device direction at the wire level.** WinMM only
  shows what the device sends back. The active-probe approach replaces
  this for most reverse-engineering; for *literally* capturing what
  Tone Studio sends, install USBPcap + Wireshark.
- **LIBRARIAN / TONE EXCHANGE / IR LOADER.** Not exercised; user-deferred.
- **RESTORE / Factory reset / AUTO OFF triggering.** Destructive or
  observation-only; deferred. AUTO OFF investigation confirmed there's
  no countdown register or farewell SysEx — USB just disconnects.

## Earlier "TBD" items now resolved

The repo's first README warned that decoding "the per-parameter layout
inside a patch beyond name + first ~48 bytes" required methodical
tweak-and-diff against the live device. That's no longer true for
visible knobs: the chart-documented layout (each FxItem = TYPE + ON/OFF
+ DupNumber + 44 FX Params, each 4-nibble offset-binary), combined
with the 741-entry ASSIGN TARGET TABLE and the per-effect captured
knob addresses, gives `target_to_offset()` enough data to resolve any
visible-knob target to its exact byte address. The diffing workflow
is still required for genuinely conditional / hidden parameters
(DELAY PLUS DUAL-mode extras, FB OSC-mode extras, HARMONY=USER scale
notes), but those are the exception, not the rule.
