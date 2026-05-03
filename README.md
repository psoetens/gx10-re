# GX-10 reverse engineering

Tools and notes for reverse-engineering the BOSS GX-10's USB-MIDI control
protocol, as spoken between BOSS Tone Studio for GX-10 and the device.

```
gx10-re/
├── docs/protocol.md       # Protocol writeup (start here)
├── tools/                 # ctypes-only Python tools — no compiler / admin / driver install
│   ├── list_midi.py
│   ├── midi_sniff.py      # passive WinMM sniffer (JSONL log)
│   ├── midi_send.py       # active sender (DT1 / RQ1 / identity)
│   ├── address_scan.py    # combine sniffer + sender, sweep address space
│   ├── sysex_decode.py    # parse + validate JSONL captures
│   ├── inspect_ui.py      # dump Tone Studio's UI Automation tree
│   ├── screenshot.py      # capture Tone Studio window
│   └── drive_tone_studio.py  # autonomous editor driver with label fifo
└── captures/              # Captured JSONL logs and screenshots
```

## TL;DR findings

- GX-10 uses **standard Roland "extended" SysEx**: 5-byte model ID, 4-byte
  big-endian addresses, 7-bit checksum.
- Family code `0x040B`, model number `0x0000`, default device ID `0x10`.
- The device exposes its MIDI port through Microsoft's USB-MIDI class
  driver, which **allows multiple openers** — both a passive sniffer and
  Tone Studio can hold the port at the same time. The output port is
  similarly shareable, which means a Python script can issue its own RQ1
  reads even while Tone Studio is connected.
- We mapped the top-level address space (live patch, preset names, user
  bank, system block) and dumped all 16 user patches by issuing our own
  RQ1 probes — see `docs/protocol.md`.

## What this repo does *not* do

- Write to the device. All `midi_send.py` calls in the included scripts are
  reads. The DT1 builder is provided but no script writes patches.
- Decode the per-parameter layout inside a patch beyond name + first ~48
  bytes. This is doable with the existing tools but requires methodical
  diffing (tweak knob → diff patch dump → identify byte).
- Sniff the host → device direction at the wire level. The active-probe
  approach replaces this for most reverse-engineering; for *literally*
  capturing what Tone Studio sends, install USBPcap + Wireshark.
