# Methodology — how to extend this map

This document captures the **techniques** for further reverse-engineering of
the GX-10 protocol. The goal is that anyone can pick up where this session
left off and keep mapping effects, knobs, and menu items.

## Core insights, in order of importance

1. **The output port is shareable.** A Python script can hold the GX-10
   `midiOut` open at the same time as Tone Studio. So we can interleave our
   own RQ1 / DT1 with Tone Studio's traffic and the device handles both.
2. **USBPcap captures both directions** at the wire level. Always pass
   `--inject-descriptors`, otherwise Wireshark can't find the USB-MIDI class
   descriptors and the dissector won't run. Capture, then `pcap_to_jsonl.py`
   produces the same JSONL shape as `midi_sniff.py` so all the same tools
   work on either source.
3. **DT1 writes are reversible by replug.** Writing to the live patch
   buffer (`0x10000000+`) only affects the edit buffer, not user storage,
   until the user explicitly executes WRITE. Writing to system registers
   (`0x7F000000+`) survives until the device is power-cycled. Be cautious
   with `0x7F000001` (editor-attached bit) — set it on connect, clear on
   disconnect, mirror Tone Studio's behaviour.
4. **Address bytes must be 7-bit clean.** Every address byte and every size
   byte must be `<= 0x7F`. The `step_7bit` helper in
   `tools/rapid_probe.py` handles this.

## The snapshot / perturb / diff loop

This is the central technique for parameter mapping:

```
1. snapshot_before = patch_snapshot.snapshot(["live_low", "live_chain"])
2. perturb()       # change ONE thing — knob, dropdown, on/off, etc.
3. snapshot_after  = patch_snapshot.snapshot(...)
4. diff = snapshot_diff(snapshot_before, snapshot_after)
5. attribute the changed bytes to the perturbation
```

Steps 2 / `perturb()` can be:

- **Direct DT1 from us**: `midi_send.build_dt1(addr, payload)` — most reliable.
- **A Tone Studio UI action via `drive_tone_studio.py`** — works when the
  control is reachable by mouse coordinates, but unreliable when Tone Studio
  uses WebView2 (knobs, dropdowns) because the DOM isn't exposed via UIA.
- **A real-time MIDI message** (Bank Select / Program Change / CC) sent
  from us via `midiOutShortMsg`.

For step 5, a single byte change in the diff identifies a single parameter.
Multi-byte diffs come from:

- compound-encoded parameters (e.g. 16-bit value spanning two bytes),
- the device updating derived state (the `0x10000154` "current slot"
  register changes every time the user clicks a hex block, contributing
  noise),
- the patch checksum / dirty-flag byte (look for `0x00200000+` updates).

## What's been mapped vs. what's left

### Mapped
- SysEx framing (§2)
- Top-level address regions (§3.1, §3.6.5)
- Editor-attached handshake bit `0x7F000001` (§3.7)
- TUNER mode + TUNER pitch streaming buffer at `0x7F000300` (§3.7, §3.8)
- UI-mode register `0x00000007` (TUNER MONO / POLY / TT) (§3.8)
- Patch-select register at `0x00000000` — partial encoding table (§3.2)
- Live patch buffer LAYOUT (header / routing matrix / 10 × per-slot block /
  big-chunk parameter dump) (§3.3)
- Tone Studio's startup handshake sequence (§4)
- IR Loader has 11 USER slots visible (display only — actual upload protocol
  not yet captured because no `.wav` was loaded)

### Not mapped — known structure, unknown content
- **Per-effect type IDs**: each slot in the chain has a "type ID" byte
  somewhere in the slot's 90-byte block. Diffing one preset against
  another (e.g. preset 0 NATURAL AMP HB vs preset 1 BOUTIQUE AMP HB) and
  isolating to a single slot identifies the byte. The `bulk_preset_snapshot.py`
  tool runs this loop automatically across all 296 presets — just needs
  Tone Studio closed and the script left to run for ~10 minutes.
- **Per-knob parameter offsets**: within a slot's 90-byte block, individual
  knob values live at fixed byte offsets. To find one: load a preset with
  a known knob value, snapshot, write a different value to a candidate byte
  offset via DT1, snapshot again, see if the device echoes a knob change.
- **Effect-type list**: the GX-10 has ~30 effect types in the upper type
  bar (COMP, X-COMP, BOOST, OD, ..., HARM) and additional categories
  (DELAY, REVERB, etc.). Iterating a "type ID" byte from 0 to 255 and
  reading back the slot's block will reveal which IDs are valid and what
  the default parameter set is for each.
- **`0x00200000` editor-metadata region**: format unknown; queried by
  Tone Studio when the editor enters edit-modify mode.

### Not mapped — protocol unknown
- **WRITE / OVERWRITE / INSERT / DELETE patch operations**: clicking the
  dropdown queries `0x00200000+` but the actual write-to-user-slot
  command was not yet captured. Likely either:
  - a DT1 write of the entire 4475-byte patch to the user-slot address
    (`0x60400000 + N*0x10000`) — fits the existing pattern, OR
  - a vendor-specific "save" command at a different region.
- **IR (impulse response) upload**: the IR Loader modal opens but no SysEx
  is sent until the user actually clicks LOAD with a `.wav` file. Likely
  a chunked binary upload at a yet-unmapped address.
- **TONE EXCHANGE**: cloud-side feature; would emit when downloading.
- **MENU**: deferred — likely contains factory-reset / diagnostics.
- **Tone Studio's exact patch-select encoding**: writes to `0x00000000`
  do change the loaded preset, but the relationship between the 5-byte
  payload and the resulting preset index isn't a simple linear mapping.
  Standard MIDI Bank-Select+PC also works; may be the cleaner channel for
  scripted patch traversal.

## A specific recipe to map one effect type

Worked example: **map the COMP-class effect type byte for slot 0**.

What we know empirically:

- Tone Studio's drag-and-drop of a type-bar item onto a chain slot writes
  a 3-byte triplet at `0x10001100..0x10001102` plus a chain-order DT1 at
  `0x10000F00`, plus an editor-mode flag at `0x00200003`.
- For COMP onto slot 0 the triplet was `08 01 00` (category, modifier, sub).
- Direct-DT1 replay of just those bytes is **not sufficient** — Tone Studio's
  UI only updates when a fresh launch reads device state, and even then
  the underlying chain state has more dependencies than the triplet alone.
- The reliable way to reproduce a "place effect X on slot Y" command is to
  capture Tone Studio's full drag sequence with USBPcap (`tools/drag_each_typebar.py`)
  and replay it byte-for-byte.

### What works reliably

1. **Per-effect drag captures**: each drag's `.pcap` is the atomic
   "replay this and you will get effect X in slot Y" recipe. Pair the pcap
   with a Tone Studio screenshot taken right after the drag — the screenshot
   gives the human-readable effect name and the visible knob labels.
2. **Snapshot/diff for parameter byte discovery**: with the device in a known
   state (e.g. just after a drag-COMP), a knob change in Tone Studio
   produces a single-byte DT1 at the parameter's address. `tools/patch_snapshot.py`
   diffs before/after.
3. **Replay patches**: full restoration of a snapshot via
   `tools/restore_snapshot.py` works for most patch buffer bytes, but the
   chain visualisation in Tone Studio relies on additional state outside
   the captured region.

### What we ran out of session time to finish

- A complete type-bar drag-replay capture for all ~30 effect categories
  (`tools/drag_each_typebar.py` is set up for this — needs Tone Studio's
  drag-and-drop to be reliable; mouse coordinates may need tuning per
  display).
- Per-effect parameter byte attribution (knob X = byte address Y): each
  effect's parameter region must be diffed across knob positions. This is
  bounded but tedious work.
- Min/max/step values per knob: each parameter's range is discovered by
  driving the knob to each extreme in Tone Studio (or by direct DT1 writes
  to find which values the device accepts vs caps).

## When direct DT1 is faster than UI driving

Whenever a Tone Studio UI control is *not* exposed via UI Automation (most
WebView2 knobs and dropdowns), don't waste time with pyautogui. Instead:

1. Find the parameter address by snapshot/diff against a preset that has
   that parameter set differently.
2. Write the value via `midi_send.build_dt1(addr, value)`.
3. Read the slot's region back and confirm.

This is **far** more reliable than mouse driving in WebView2.

## Tool standard: identity check is mandatory

Every Python tool in `tools/` that opens the MIDI port to talk to the device
MUST call `device_id.require_alive*()` immediately after opening that port
and BEFORE issuing any other RQ1/DT1. On failure it prints diagnostics and
aborts with a non-zero exit code — no silent fall-through to wrong-product
or no-device states.

Three adapters exist in `tools/device_id.py`, one per I/O pattern in this
codebase:

| Pattern | Adapter | Where to call |
|---|---|---|
| `GX10Session()` from `example_lib` | `require_alive(sess)` | after `sess = GX10Session()` |
| Raw `MidiOut` + `midi_sniff.Sniffer` + events list/queue | `require_alive_raw(out, events, lock=None)` | after sniffer opens & a 0.3s settle |
| `GxMidi()` from `midi_io` | `require_alive_gxmidi(g)` | after `g = GxMidi()` |

The `require_alive_raw` adapter normalises events: bytes, `(timestamp, bytes)`
tuples, and dicts with `hex` / `bytes` / `raw` fields are all accepted, so
tools can keep their existing storage format unchanged.

What `require_alive*` enforces:

1. The device answers a Universal Identity Request within the timeout
   (default 1s). If not, exit 2 with a "device unreachable" diagnostic.
2. The Identity Reply's product flag (`sw_revision[0]`) is `0x00` (GX-100)
   or `0x01` (GX-10). Other values → exit 3 with a full hex dump of the
   reply so the operator can decide whether it's a related but unsupported
   Roland product or a corrupted reply.
3. Optionally, the product matches `allow=` (e.g. `allow={"GX-10"}` for
   tools that hard-code GX-10 patch counts or chain layouts).

This is a project-wide standard. Any new device-talking tool that skips
the check will be reverted on review.

## Safety notes

- Never write to `0x60400000 + N*0x10000` (user patch storage) unless you
  intend to permanently overwrite that slot. The user explicitly authorised
  one such write to U10-1 (slot index 9) in this session.
- Don't write `0x7F000001 = 0x00` while Tone Studio is still connected —
  it may confuse Tone Studio's editor-attached state.
- Factory reset, all-data backup/restore are end-of-session activities.
  In particular, the all-data backup capture is ~5 minutes of high-volume
  binary traffic and the factory reset *might* switch the GX-10's USB
  enumeration mode away from the generic class driver, requiring a replug
  to recover.
