# BTS-on-Linux feasibility + Windows-deferred work plan

**Date:** 2026-05-09
**Question:** What can we do without BOSS Tone Studio (BTS)? When is
BTS strictly required? Is it feasible to run BTS under Wine on Linux?

---

## TL;DR

- **Most reverse-engineering work does NOT need BTS.** With
  `tools/midi_io_linux.py` (rtmidi) + the manuals + the device
  attached, we can probe addresses, verify encodings, write and
  read patches, and discover undocumented behaviour.
- **BTS is required for**: (a) discovering device commands not in
  the manual by sniffing what BTS sends and reverse-engineering it;
  (b) cross-validating our internal state model against BTS's UI
  display; (c) testing the ChainEditTrigger handshake's
  observed-via-BTS behaviour.
- **Wine + BTS on Linux is impractical** in the typical case (Roland
  vendor USB driver needed). Strong recommendation: **defer all
  BTS-required work to a Windows session**, run *everything else* on
  Linux.

---

## What requires BTS (deferred to Windows)

These items in `reports/cross_check_findings.md` and
`reports/linux_probe_results.md` cannot be settled without watching
or driving BTS:

1. **Sniff BTS startup handshake** — capture exactly what BTS writes
   to `0x7F000001` and what it reads at `0x7F000000..0x7F000010`. We
   confirmed those addresses respond on Linux but `0x7F000002` and
   `0x7F000703` go quiet without a real handshake. (`P2-4` partial
   verdict.)
2. **Sniff ChainEditTrigger** — when BTS does an INSERT/DELETE/
   OVERWRITE on the chain, capture the SysEx sequence around
   `0x00200003`. Settles `gaps.md §1.1` "BROKEN" hypothesis and
   confirms whether the v2 manual's Setup-region removal corresponds
   to a *firmware* change BTS works around.
3. **Sniff TYPE-78..82 selection** — we know the bytes work; we
   don't know whether BTS sets any companion registers (e.g. AIRD
   sub-type, knob defaults) when switching to a new effect.
4. **Sniff the parameter-write encoding for sliders > 15** — verifies
   our P0-1 4-nibble fix matches what BTS sends. (We are confident
   the device-side encoding is 4-nibble; BTS observation is the
   final cross-check.)
5. **Capture firmware-update traffic** — if any firmware exposes
   version via SysEx, BTS' "check for updates" or "device info"
   dialog will probe it. Capture and decode.
6. **Cross-validate dictionary semantics** — for any parameter
   whose decoded value disagrees with display, cross-check by
   moving the slider in BTS and watching MIDI traffic.

Each of these is a "capture USB traffic while BTS does X, then decode
the SysEx" task. They don't require coding.

---

## What does NOT require BTS (do on Linux now)

All other items in `reports/cross_check_findings.md`:

- **P0-1** fix in our Python implementation (use 4-nibble encoder).
- **P0-2 / P0-3** are complete (Linux-confirmed); only the
  **upstream** gxnarly fixes need filing as issues.
- **P1-1** rewrite `firmware_versions.md` — already settled.
- **P1-2** regenerate `effect_catalog.md` / `all_effects.json` from
  raw captures using 4-nibble decoding.
- **P1-3 / P2-6** diff v1 vs v2 GX-100 manual chunks (offline doc
  diff).
- **P1-4 / P1-5** doc cross-link / canonical-label cleanup.
- **P3-1** gxnarly model_id metadata fix (issue filing).
- **P3-2** adopt gxnarly pacing profile in Python tools.
- Any new probe of un-documented addresses, knob ranges, address-map
  exploration.

---

## BTS-on-Linux feasibility

### Architecture summary

BTS is a Windows/macOS app. Linux is unsupported. To run BTS on Linux:

1. **Wine** — Windows-API translator. Works for many GUI apps.
   Doesn't directly translate kernel-mode USB drivers.
2. **A Windows VM with USB passthrough** — the GX-10 device is passed
   through to the guest, BTS sees it natively. Works but complex
   setup; performance-sensitive on USB-Audio.
3. **Native Linux port** — does not exist. Roland has not announced
   one, and the codebase is closed.

### Wine specifically

BTS' MIDI traffic to the GX-10 is standard MIDI SysEx over USB. On
Windows it goes through the Roland USB-MIDI class driver (or Roland's
proprietary driver for Audio modes). Wine implements `winmm.dll` and
Windows-MIDI APIs by mapping them onto ALSA/PipeWire. In principle a
SysEx-only app could work.

**Known issues** (general Wine + Roland MIDI editors, from community
reports — not specifically tested on this GX-10):
- BTS is shipped via the BOSS Tone Central installer and uses
  signature-checked update mechanisms that may fail under Wine.
- Some Roland editors check for the proprietary "BOSS USB" driver and
  refuse to run with the generic class driver. The GX-10 uses a
  generic USB-MIDI class device for MIDI (no proprietary driver
  needed for MIDI), but BTS may still be picky.
- Audio passthrough (BTS' "Live monitor" features) won't work; for
  reverse-engineering work we don't need audio.

### Recommendation

**Don't sink time into Wine.** The risk/reward is poor:
- Even a successful Wine install gives us **the same SysEx traffic**
  we could get on a real Windows machine, and capturing it via Wine
  introduces a layer of indirection that complicates analysis.
- The user prefers Linux — they can keep Linux as the primary dev
  environment and book Windows time when a BTS observation is
  scheduled. A 1-2 hour Windows session per quarter would settle most
  open BTS-dependent items.

If the user later decides they want BTS-style editing on Linux, the
right path is **building this Python editor + the gxnarly Swift
editor** (which is what both projects are doing), not running BTS
under Wine.

---

## Plan for the next sessions

### Linux-session task plan (do here, no BTS)

| Task | Outcome | Output |
|------|---------|--------|
| Apply P0-1 to gx10-re Python | Encoder/decoder uses 4-nibble offset binary; tests pass on real device | `tools/midi_io_linux.py` updated with `encode_knob_cell`, write tests |
| File gxnarly upstream issues for P0-1, P0-2, P0-3, P1-1b, P3-1 | Cross-check findings forwarded to gxnarly maintainer | (issue filing — out of this session's scope; we cannot push to gxnarly remote) |
| Rewrite `docs/firmware_versions.md` per P1-1 | Doc reflects "Identity Reply byte 10 = product id, firmware version not exposed" | `docs/firmware_versions.md` rewrite |
| Update `docs/midi_firmware_analysis.md` §1, §2 with probe results | Doc reflects "Setup region intact in firmware, only doc-removed" | edits |
| Regenerate `effect_catalog.md` + `all_effects.json` (P1-2) | All 22 mismatch entries reduced; ranges correct | new commit + report |
| Diff v1 vs v2 GX-100 Parameter Guide chunks (P2-6) | Definitive list of v2.0-added subtypes | `reports/v2_subtype_additions.md` |
| Update `firmware_overlay.json` per P2-6 results (P1-3) | Per-subtype gating completed | json update |
| Decide product detection strategy (P1-1 follow-up) | One of options (a)/(b)/(c) chosen, documented, implemented | doc + code |
| Probe the `0x60400000` "USER N" labels region | Determine its purpose (bank labels? backup names?) | extension to `probe_v2_findings.py` + report section |
| Probe `[SystemMidi]` `0x00003000` block on GX-10 | Confirm GX-100-only fields (SYNC CLOCK, USB IN THRU) actually return / behave on GX-10 | report section |
| Adopt gxnarly pacing profile in Python (P3-2) | Probes hit gxnarly's measured 60 ms p50 / 17 msg/s | benchmark + commit |

### Windows-session task plan (deferred)

When the user has BTS available on a Windows host with the GX-10:

| Task | Outcome | Capture |
|------|---------|---------|
| BTS startup capture | Discover handshake sequence | Wireshark `usbmon` or USBPcap → JSONL via existing `tools/pcap_to_jsonl.py` |
| BTS chain-edit capture | INSERT/DELETE/OVERWRITE SysEx sequence | as above |
| BTS effect-type-switch capture | Companion writes when switching to TYPE 78..82 | as above |
| BTS knob-drag capture, slider value > 15 | Confirm 4-nibble encoding matches our P0-1 fix | as above |
| BTS firmware-info dialog capture | Discover whether firmware version is queryable | as above |
| BTS USB descriptor probe | Confirm whether BTS uses the generic class or vendor-mode | descriptor dump |
| Send the captures to gx10-re | One PR per topic with `captures/<topic>.jsonl` + analysis | report + commit |

---

## Equipment / setup notes

For the Windows session:

- BOSS GX-10 (this device, firmware 1.04 — keep the same so probes
  cross-reference)
- Latest BTS for GX-10 from BOSS Tone Central
- USBPcap (Windows) or `usbmon` (any Linux host running Windows VM)
- The repo's `tools/pcap_to_jsonl.py` to normalise captures
- 1-2 hours should cover all open items
