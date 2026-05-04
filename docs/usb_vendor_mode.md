# GX-10 vendor-mode USB descriptors

Reverse-engineered 2026-05-04 with the device set to vendor mode and
the Roland RDID1261 driver still bound. libusb-1.0 (via pyusb) can
read descriptors without disturbing the driver, but **cannot issue
I/O** — control transfers fail with "Operation not supported or
unimplemented on this platform" because Roland's driver holds the
device exclusively.

## Device-level

```
VID                : 0x0582 (Roland)
PID                : 0x0311 (GX-10)
bcdUSB             : 2.00
bDeviceClass       : 0xFF (vendor-specific)
bDeviceSubClass    : 0x00
bDeviceProtocol    : 0xFF
bMaxPacketSize0    : 64 bytes (control endpoint)
bcdDevice          : 1.00
bNumConfigurations : 1
```

Compatible IDs `USB\Class_FF&SubClass_FF&Prot_00`. Windows installs
service `RDID1261` (Roland's vendor driver), provider "Roland".

String descriptors `iManufacturer` and `iProduct` exist but require
control-transfer access — locked by the Roland driver.

## Configuration 1 — 4 interfaces, 188 bytes total

| Interface | Class/Sub/Proto | Alt 0 | Alt 1 | Purpose |
|-----------|-----------------|-------|-------|---------|
| 0 | FF/FF/00 | 0 EPs | – | **Vendor control** (uses EP0 only) |
| 1 | FF/02/02 | 0 EPs | 1 EP iso OUT | **Audio playback** (host→device) |
| 2 | FF/02/01 | 0 EPs | 1 EP iso IN | **Audio capture** (device→host) — DRY+WET stream |
| 3 | FF/03/00 | 2 EPs bulk | 2 EPs interrupt | **MIDI / SysEx** (Roland's vendor framing) |

`bAlternateSetting=0` for streaming interfaces means "no streaming";
the host activates streaming by switching to `bAlternateSetting=1`.
Standard USB-Audio Class idiom, kept here in vendor framing.

### Interface 0 — vendor control (no endpoints)

Pure EP0 control transfers. This is where Roland's driver presumably
sends mode-set / start-streaming / configure-format / get-meter
commands. **Untested** — likely the gateway to anything we want.

### Interface 1 — audio playback (host → device)

```
Alt 1 — bNumEndpoints=1
  EP 0x0D OUT  Isochronous  wMaxPacketSize=132 (0x84)  bInterval=1 (1 frame)
```

The host sends 132-byte frames every 1 ms when this alt is selected.
Format unknown — needs vendor-control negotiation to decode. 132 ≈
2 ch × 16-bit × 32 kHz, OR 44.1/48 kHz with channel-grouping
sub-slots, OR custom Roland framing. Sample analysis once endpoint
is reachable.

### Interface 2 — audio capture (device → host)

```
Alt 1 — bNumEndpoints=1
  EP 0x8E IN   Isochronous  wMaxPacketSize=132 (0x84)  bInterval=1 (1 frame)
```

**This is the meter source.** Same 132-byte frame size, 1 ms cadence.
With Roland's driver bound, this exposes both DRY and MAIN channel
pairs (4 audio endpoints in Windows) — confirms the stream is
multi-channel multiplexed inside that 132-byte frame.

### Interface 3 — MIDI / SysEx

Two alternate settings, same endpoint addresses, different transfer types:

```
Alt 0 — bulk (default)
  EP 0x03 OUT  Bulk        wMaxPacketSize=512  bInterval=1 (ignored for Bulk)
  EP 0x84 IN   Bulk        wMaxPacketSize=512  bInterval=0

Alt 1 — interrupt (low-latency variant?)
  EP 0x03 OUT  Interrupt   wMaxPacketSize=512  bInterval=4 (≤ 4 ms)
  EP 0x85 IN   Interrupt   wMaxPacketSize=512  bInterval=4
```

Endpoint 0x03 is shared (different transfer types per alt setting).
The IN endpoint number changes between alts (0x84 → 0x85). Roland's
driver presumably picks one based on the use-case (DAW MIDI Control
vs SysEx). Both carry the same SysEx wire format we already know
from MIDI-class mode.

## What we can do without swapping the driver

- **Read descriptors** — done, this document.
- **Read installed-driver metadata** — done (registry keys under
  `HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_0582&PID_0311\…`).
- **Use Roland's driver normally** — WinMM MIDI works; WASAPI/ASIO
  audio works. This is what `tools/midi_send.py` already does.

## What needs WinUSB binding (admin) to do

- Issue **EP0 control transfers** (vendor-control commands on
  Interface 0).
- Stream from EP 0x8E IN (audio capture) directly — useful only if
  we want a non-WASAPI path.
- Send raw MIDI via EP 0x03 OUT / receive on EP 0x84 IN — replicates
  what WinMM already does, just one layer down.

The driver swap is destructive in the sense that:
- BTS stops working (no Roland driver bound)
- Windows audio endpoints disappear from sound panel
- Windows MIDI ports disappear from WinMM
- DAWs lose access

…until you swap back. Use Zadig's "Replace Driver" → "Restore Original"
or `pnputil /add-driver` with the Roland INF.

## Recommended path for "build a vanilla driver"

The least-disruptive plan:

1. **Make a separate USB device-instance** by installing WinUSB on
   only a *subset* of interfaces (Windows supports per-interface
   drivers via composite-device parents). Specifically, bind WinUSB
   to **Interface 0 (vendor control)** while leaving Interfaces 1/2/3
   on the Roland driver. That gives us:
   - direct access to vendor commands
   - audio + MIDI continue working through Roland's driver
   - BTS still works
   This requires a custom INF that *explicitly* claims only one
   interface — Microsoft's "Reusable Driver Architecture for Windows
   Audio (RDAW)" docs cover the pattern.

2. **Once Interface 0 is reachable**, sniff what BTS sends as control
   transfers (USBPcap captures these) and replay them. That tells us:
   - Format-set commands for the audio streams
   - Any metering / status / mode-control commands
   - Whether an audio-level register exists at the control endpoint

3. **Only if (2) shows the meters live there**, build a minimal
   level-meter tool that issues control reads at ~30 Hz.

If the meters don't live in vendor-control (probably they don't —
they're more likely embedded in the audio capture stream itself,
or computed locally on the device), step 2 just helps us understand
the stream-format negotiation, after which we can either:
- Decode the iso stream directly (replace audio endpoints too — full
  driver replacement), or
- Continue using Roland's driver and read levels via WASAPI/ASIO from
  the existing DRY/MAIN endpoints (much simpler).

## Bottom line

For the **practical goal of meters**: Roland's vendor driver already
exposes DRY + MAIN as standard Windows audio endpoints. A 50-line
`sounddevice` Python script reads RMS per channel and renders bars.
We don't need to replace the driver to get this.

For the **research goal of full driver independence**: feasible but
multi-week. Start with WinUSB on Interface 0 only, sniff vendor
control transfers, decide whether the audio stream-format
negotiation is worth replicating.
