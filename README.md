## Preamble

First of all, Roland Corporation, **thank you** for creating the best and most affordable musical instruments, effects, gear and so much more!
BUT: you are in your genes a hardware company, not a software company and that shows :-( 

I reverse engineered with Claude Code the GX-10 in a timespan of ~48 hours... just because I got so frustrated with the iOS 'BOSS Tone Studio' app for this device. It was excruciating slow, did not work in landscape mode and has a dated look and feel.

Everything you find in this repo was written by Claude. I just told it what to do, where to look, what makes sense. A lot of it seems to check out and work, but the vast parameter space (we estimated >800 parameters) means that we may have overlooked corner cases. Especially GX-100 users will not be fully covered, since my unit is a gx-10 (hence the repo name). But **a lot** should also work for the GX-100.

Next station: the ios app. Not so sure if this will take ~48 hours as well... but maybe it just does 🤯

# BOSS GX-10 / GX-100 — Reverse-Engineered USB MIDI Protocol

> Tools, observations, and a complete-enough protocol description to
> programmatically read and write any user-visible state of the
> BOSS GX-10 (and, by extension, the GX-100) over USB MIDI, without
> using BOSS Tone Studio.

What's documented and verified against a live device:

- **Full address map** — every chart-documented register decoded, with
  encoding rules and gotchas
- **Programmatic patch construction** — chain edits, knob settings,
  MIDI assigns, end-to-end working example
- **Per-effect knob catalogue** — 81 effects, every captured knob
  named and addressed
- **Patch database** — all 200 user + 100 preset memory slots,
  read/write flow, name decoding
- **Tuner protocol** — including pitch encoding (½-cent unsigned
  magnitude with note-byte sign recovery)
- **Hardware-event channel** — every footswitch / knob / screen /
  menu action emits a chart-documented DT1; subscribing once with
  `DT1 0x7F000001 = 1` gives a real-time event stream
- **USB / driver layer** — vendor-mode descriptors, generic-vs-vendor
  driver differences, a per-OS support landscape (Windows / macOS /
  iOS / Linux)
- **A small set of demo scripts** that exercise the protocol end-to-end

## Where to start

| If you want to… | Read this |
|------------------|-----------|
| Understand the address map and SysEx framing | [`docs/protocol.md`](docs/protocol.md) |
| Build a patch from scratch programmatically | [`docs/programmatic_construction.md`](docs/programmatic_construction.md) |
| Look up a specific effect's knobs and addresses | [`catalogs/bts_effect_catalog_complete.json`](catalogs/bts_effect_catalog_complete.json) (schema: [`docs/bts_catalog_schema.md`](docs/bts_catalog_schema.md)) |
| See what's done, deferred, and out-of-scope | [`docs/gaps.md`](docs/gaps.md) |
| Talk to the device from Linux / macOS / iOS | [`docs/linux_macos_ios_support.md`](docs/linux_macos_ios_support.md) |
| Understand the vendor-mode USB layout | [`docs/usb_vendor_mode.md`](docs/usb_vendor_mode.md) |

## Quickstart — try it on a connected device

The tools are pure Python with `ctypes` and `winmm` on Windows
(no compiler / driver install needed). On Linux / macOS, swap the
`midi_send.py` backend for `python-rtmidi` (a TODO in this repo).

```bash
# 1. Confirm we can see the GX-10
python tools/list_midi.py

# 2. Read the device's full chain layout
python tools/example3_show_chain.py

# 3. Read the USB-settings block
python tools/example5_usb_settings.py

# 4. Subscribe and watch every footswitch / knob / screen event
python tools/watch_hardware_actions.py
# (Press something on the device; events stream to stdout.)
```

To programmatically build a chain (BOOSTER + PEQ + REVERB PLATE) plus
configure the four main-display knobs and arm a CC#64 → REVERB ON/OFF
assign, all reversibly via memory_temp:

```bash
python tools/demo_full_patch.py
# (Press any patch button on the device to discard.)
```

## Layout

```
catalogs/                       # Ground-truth JSON reference tables
  bts_effect_catalog_complete.json  # 83 effects × 632 knobs, addresses verified
  firmware_overlay.json             # Per-effect firmware-version coverage
  per_effect_types.json             # Per-effect TYPE / SP TYPE / MIC TYPE enums
  assign_target_table.json          # 741-entry ASSIGN TARGET enum table
  README.md                         # What each catalog is and who built it

docs/
  protocol.md                   # Address map + 10 sub-protocols (start here)
  programmatic_construction.md  # End-to-end recipe for building a patch
  bts_catalog_schema.md         # Schema for catalogs/bts_effect_catalog_complete.json
  gaps.md                       # What's done / deferred / un-investigable
  usb_vendor_mode.md            # Vendor-mode USB descriptor breakdown
  linux_macos_ios_support.md    # Per-OS support landscape
  menus.md / methodology.md / official_xref.md / bpm_encoding.md / API.md
  effects/README.md             # Status pointer to catalogs/
  manuals/                      # Empty by design — see manuals/README.md

tools/
  midi_send.py                  # DT1 / RQ1 / Identity Reply senders
  midi_sniff.py                 # Passive WinMM sysex sniffer
  example*.py                   # Five small demo scripts
  demo_full_patch.py            # End-to-end patch construction
  example_lib.py                # Shared session helper, target→offset resolver
  merge_bts_into_catalog.py     # Regenerate catalogs/bts_effect_catalog_complete.json
  watch_hardware_actions.py     # Subscribe + log device-side broadcasts
  fix_stuck_chain_edit.py       # Rescue BTS when the ChainEditTrigger gets stuck
  fx_type_enum.py / per_effect_types.py / assign_target_table.py
  (~60 more — captures, diagnostics, one-off probes)

captures/                       # JSON / JSONL summaries of capture sessions
snapshots/                      # JSON dumps of patches and per-slot state
LICENSE                         # MIT (see notes about Roland docs below)
```

## Legal — what this repo *is* and *is not*

**It is**: independent reverse-engineering of behaviour observable on a
device the contributors own, performed for the purpose of
interoperability (driving the device from non-BOSS software). The
work is permitted under EU Software Directive Article 6 (decompilation
for interoperability), US 17 USC §1201(f) and §117, and equivalent
provisions in JP/AU/CA. All code, prose, and observations are original.

**It is not** a redistribution of Roland's documentation or software.
The Markdown chart and parameter-guide files some tools optionally
consume are not in this repository — see [`docs/manuals/README.md`](docs/manuals/README.md)
for the URLs to download them from Roland yourself. The repository's
own factual reference material (e.g. [`catalogs/assign_target_table.json`](catalogs/assign_target_table.json),
[`catalogs/bts_effect_catalog_complete.json`](catalogs/bts_effect_catalog_complete.json), the `tools/*_enum.py`
modules) is independently structured / paraphrased, not verbatim, and
documents factual behaviour rather than copyrightable expression.

If you are at Roland and you'd prefer specific framing or additional
disclaimers anywhere, please open an issue rather than a takedown —
this is fan-made interoperability work, not piracy.

The MIT licence in [`LICENSE`](LICENSE) covers the original code and
prose. It does not (and cannot) cover Roland's IP referenced here.

## Status & contributions

This is a one-person research project that reached "good enough to
publish" on 2026-05-06. Every byte and behaviour mentioned here was
verified empirically on a single GX-10 unit. The GX-100 is described
based on chart symmetry and a vguitarforums report that the sister
device behaves analogously on Linux — please open an issue with your
findings if you have access to one.

Issues and PRs welcome. Particular interest in:
- macOS / Linux / iOS testing reports
- The 4-byte poly-tuner per-string `pitch` field encoding (deferred)
- Any vendor-control transfers Tone Studio issues at startup that we
  haven't accounted for (USB-Pcap traces appreciated)

## Acknowledgements

- The Linux ALSA developers, whose pre-existing Roland 0x0582
  vendor-class catch-all in `sound/usb/quirks-table.h` and generic
  Roland implicit-feedback handling means *the GX-10 likely already
  works on Linux without any patch*.
- The vguitarforums and ALSA-devel community for prior art on Roland
  RE generally and the BOSS multi-effects family specifically.
- Anthropic's Claude as a research and writing partner for this
  project — it is, after all, why this folder lived under
  `C:\Users\Peter\Claude\` to begin with.
