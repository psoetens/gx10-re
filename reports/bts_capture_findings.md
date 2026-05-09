# BTS USBPcap session — findings

**Branch:** `windows-bts-captures`
**Date:** 2026-05-09
**Device:** BOSS GX-10, firmware **1.04** (user-confirmed via device
MENU → SYSTEM → VERSION). USB connection direct USB-C-to-USB-C to
laptop (no hub).
**Capture method:** Passive `tools/midi_sniff.py` (WinMM input port
loopback) running while the user drove BTS through each scenario.
**USBPcap was unusable** on the Intel xHCI 3.10 controller the GX-10
sits on — see "Capture-method note" below — so all captures here are
SysEx-only (MIDI traffic), not raw USB.

---

## Status table

| Task | Status | Headline |
|------|--------|----------|
| 1. Startup handshake | **Done** | `0x7F000001 = 0x01` editor-attach bit confirmed; `0x7F000703 = 0x00→0x01` is a previously-undocumented second handshake-style write. P2-4 settled. |
| 2. Chain edit (INSERT/DELETE/OVERWRITE) | **Done (via drag-drop)** | `0x00200003 ChainEditTrigger` still active; **new** `0x7F000701` mirror register (0x05 editing / 0x03 idle). gaps.md §1.1 device-side **clear** — BTS button bug is BTS-internal. |
| 3. Knob drag (SUSTAIN, P0-1) | **Done** | BTS sends canonical 4-nibble offset binary. 50 → `08 00 03 02`, 100 → `08 00 06 04`, 1 → `08 00 00 01`. P0-1 confirmed; gxnarly's `knob_cell` encoder fix per the cross-check **stands**. |
| 4. Firmware version source (P1-1) | **Unsettled** | No SysEx fetched the firmware version while BTS ran. Most likely path is a USB control transfer, which is invisible to MIDI sniffers and unreachable here without working USBPcap. |
| 5. Device-knob broadcast (follow-up, post-Linux pull) | **Done** | Device DOES broadcast knob changes via DT1 to the FxItem FX-Param addresses, contrary to Linux commit `bccde3e`. Captured 39+24 events while user turned two physical knobs; BTS mirrored both. **Overturns "no broadcast" Linux finding** — they listened with no physical movement. See §5. |

---

## Capture-method note (read this first)

The plan called for USBPcap captures of raw USB traffic. That did
not work on this machine:

- The GX-10 is on the Intel xHCI 3.10 controller (PCI VEN_8086
  DEV_51ED), exposed by USBPcap as `USBPcap5` in the registry.
- Adding USBPcap as an `UpperFilters` entry to that root hub broke
  USB enumeration on reboot — the controller went into
  `CM_PROB_DISABLED` and the GX-10 disappeared. Recovered by
  rolling back `UpperFilters` to empty, `pnputil /enable-device`
  on the controller, then a disable+enable cycle on the GX-10
  itself.
- USBPcap2 (a different USB controller) saw 22 KB of traffic but
  none of it from VID_0582 — the GX-10 was simply not on that bus.

So all captures are **MIDI-level** via WinMM. Conveniently the
GX-10's MIDI loopback feeds **both** host-out and device-out streams
into the input port, so `midi_sniff.py` sees BTS's writes AND the
device's replies on a single port. Not as rich as USBPcap (no USB
control transfers, no audio/CDC traffic), but sufficient for three
of the four tasks.

---

## §1. Startup handshake (Task 1)

Source: `captures/bts_startup.summary.md`,
`captures/bts_startup/startup.jsonl` (300 events, t=4.72..9.08).

### What BTS reads/writes at `0x7F0xxxxx`

| Address | Op | Value | Notes |
|---------|----|-------|-------|
| `0x7F000000` | RQ1 → DT1 | `0x03` | system-mode flag, same as the Linux probe saw |
| `0x7F000001` | DT1 ×2 | `0x01`, `0x01` | **editor-attach bit set** at t=4.799 / 4.801 |
| `0x7F000002` | RQ1 → DT1 | `0x00` | RunningMode = EDIT — replied **only because** `0x7F000001` was set; silent on Linux probe without the handshake |
| `0x7F000003` | RQ1 → DT1 | `0x00` | revision-check stub |
| `0x7F000703` | DT1 ×2 | `0x00`, `0x01` | **second handshake-style write**, undocumented in protocol.md |

The disconnect-side `0x7F000001 = 0x00` write was not captured because
the first session ended with `taskkill /F` (which corrupts BTS's
persisted device selection — see "Operational lessons" below). The
clean-exit DT1 will be observable in any future capture that lets the
user close BTS via its window button.

### Verdict on cross_check_findings P2-4

**Settled.** The Linux-side observation that `0x7F000002` and
`0x7F000703` go silent on probes was correct; both registers reply
once `0x7F000001 = 0x01` is set. BTS performs that write twice
back-to-back immediately after the Identity Reply. `0x7F000703` adds
a previously-unrecorded second handshake-style toggle worth a
follow-up probe (write it from a custom probe without launching BTS,
see whether new unsolicited DT1 broadcasts appear).

### Bonus: full BTS startup read sweep

Once the handshake is complete BTS bulk-reads the chart-documented
address space in ~4.4 seconds. The full per-block list is in
`captures/bts_startup.summary.md` §"BTS reads the entire device
snapshot". Two notable observations:

- **User patches read at `0x60400000..0x604F0000`**, not the
  chart-documented persistent range `0x20000000..0x29A00000`. This is
  the RAM/working mirror; worth a note in `protocol.md §3.6`.
- **Specific FxItem `+0x03` re-reads** for slots 4, 9, 12, 13 after
  the bulk pass — possibly post-validation of TYPE bytes that
  triggered something else.

---

## §2. Chain edit (Task 2)

Source: `captures/bts_chain_edit.summary.md`,
`captures/bts_combo/all.jsonl`.

### What was captured

The BTS INSERT / DELETE / OVERWRITE **buttons remained dead** on this
install (BTS 1.04-era, Generic USB driver mode on Windows 11). Even
after killing 18 zombie `msedgewebview2.exe` processes from earlier
sessions and confirming `0x00200003 = 0x00` on the device side, the
buttons produced no MIDI traffic. The user worked around this by
performing the equivalent operations via **drag-drop** in the chain
panel (drag adds, drag-off-chain removes, drag-onto-slot replaces).
Drag-drop uses a different BTS code path that is not affected by
whatever is breaking the buttons.

### ChainEditTrigger — confirmed

Each drag operation produces a paired `0x00200003` write:

```
DT1 0x00200003 = 0x01    (begin chain edit)
DT1 0x00200003 = 0x00    (end chain edit)
```

16 begin/end cycles were captured across the session. The trigger
address is **unchanged** from `protocol.md §5.6`; BTS did **not**
switch to a replacement.

### NEW finding: `0x7F000701` is a state mirror

Every `0x00200003` write is paired with a `0x7F000701` write 0–10 ms
later. The pattern is rock-solid across all 16 cycles:

- `0x00200003 = 0x01` → `0x7F000701 = 0x05` (editing)
- `0x00200003 = 0x00` → `0x7F000701 = 0x03` (idle)

`0x7F000701` was never observed in Linux probes (it doesn't reply
without the editor-attach bit, just like its siblings). It's a third
member of the small "global state mirror" family in the `0x7F00xxxx`
range alongside `0x7F000002` and `0x7F000703`. It should be added to
`protocol.md §3.7`.

### Per-drag SysEx sequence

```
1.  DT1 0x10000F0C  CHAIN_LIST   (50 bytes — new linked-list ordering)
2.  DT1 0x00200003 = 0x00       (end of previous edit if open)
3.  DT1 0x10001300 = <FX TYPE>  (FxItem N TYPE byte for the new effect)
4.  DT1 0x10001302 = 0x00       (DuplicationNumber)
5.  DT1 0x10001301 = 0x01       (ON/OFF)
6.  DT1 0x7F000701 = 0x03       (state-mirror back to idle)
7.  DT1 0x10000F0C  CHAIN_LIST   (re-write of the new list)
8.  DT1 0x10001303 = <32 bytes> (FX Param 1+ initial values)
9.  DT1 0x00200003 = 0x00       (final end)
```

This matches `protocol.md §5.6` with one nuance: the chain
linked-list is written **twice per drag** (steps 1 + 7), separated by
the new-effect TYPE/ON-OFF/DupNum writes. Plausibly the second write
commits the final state after the device has had a chance to react
to the TYPE change.

### Verdict on gaps.md §1.1

**Device-side: clear.** `ChainEditTrigger` works as documented; the
device responds correctly to begin/end pairs.

**BTS-side: still broken on this install** but no longer relevant to
the device protocol. Possible BTS-internal root causes (not
investigated, deferred — out of scope for protocol RE):

- BTS's `globalIsChainEditing` JS variable persisted in localStorage
  between sessions at a stale value
- BTS's WebView2 user-data corrupted from earlier force-kill cycles
  (the user ran several `taskkill /F` cycles before we figured out
  this corrupts persisted state — see Operational lessons)
- The buttons require a state BTS only enters on a particular
  connect handshake variant that wasn't reached this session

Recommended next-step (BTS-internal, low priority): clear
`%LOCALAPPDATA%\BOSS\BOSS TONE STUDIO for GX-10\WebView2\` (or
whatever path BTS uses for persistent user-data) before the next
session.

---

## §3. Knob encoding (Task 3)

Source: `captures/bts_knob_drag.summary.md`,
`captures/bts_knob_drag/sustain.jsonl` (39 events).

### Three decisive hex strings

| Display value | DT1 payload | Raw nibble word | Computed (raw − 0x8000) |
|----:|:------------|:---------------|---:|
| 0   | `08 00 00 00` | `0x8000` | 0 |
| 1   | `08 00 00 01` | `0x8001` | 1 |
| 50  | `08 00 03 02` | `0x8032` | 50 |
| 100 | `08 00 06 04` | `0x8064` | 100 |

(The drag passed through 0 and 1 as transient values rather than the
plan's prescribed sequence of just 1/50/100, but the encoding picture
is the same: every byte's high-nibble is zero and only the low
nibbles carry value bits.)

### Encoding picture

- byte 0 = `0x08` — offset-binary positive sign for non-negative
  values
- byte 1 = `0x00` — high-byte high-nibble (always zero for SUSTAIN
  range 0..100)
- byte 2 = high nibble of the 8-bit display value (`0x03` for 50,
  `0x06` for 100)
- byte 3 = low nibble of the 8-bit display value (`0x02` for 50,
  `0x04` for 100)

### Verdict on cross_check_findings P0-1

**BTS uses 4-nibble offset binary [confirmed]; gxnarly's `knob_cell`
encoder fix per P0-1 [stands].**

If BTS had used the alternative single-byte form
(`08 00 00 64` for 100, `08 00 00 32` for 50), the device — which
truncates each cell byte to its low nibble — would have stored
`08 00 00 04` and `08 00 00 02` instead, and the slider would have
been visibly stuck at 4 / 2. That's a bug the user would have
noticed long ago.

All 39 DT1 events in the drag use the same `[08 00 ?? ??]` 4-byte
form; **none** use the alternative single-byte form. Encoding is
consistent across the entire drag, with no observable
firmware-version or driver-mode dependency.

### Slot/parameter caveat — resolved 2026-05-09 (Linux probe)

The drag wrote to `0x10001117` (offset `+0x17` of FxItem #0) =
**FX Parameter 6** (formula `0x03 + (N−1)*4`, so
`(0x17 − 0x03)/4 + 1 = 6`). Which parameter that is depends on the
TYPE byte FxItem #0 holds at capture time:

| FxItem 0 TYPE | Param at offset 0x17 | Source |
|---------------|---------------------|--------|
| 0x08 COMP     | DIRECT MIX          | `docs/effect_catalog.md` |
| 0x09 X-COMP   | DIRECT MIX          | `docs/effect_catalog.md` |
| 0x35 WAH (53) | DIRECT MIX          | **verified live 2026-05-09** by writing distinctive values and reading the device display — see `linux_probe_results.md` 2026-05-09 follow-up |

The Windows captures don't preserve the TYPE byte BTS read at
startup (BTS bulk-reads all 20 FxItems but the committed summary
files only record the *addresses* read, not the *bytes returned*).
Subsequent Linux probe found FxItem 0 = WAH = 0x35; in WAH FAT
variant `0x10001117` is **DIRECT MIX**, not PEDAL MIN as
`docs/effect_catalog.md` previously claimed (catalog has a
permuted name→address bug for WAH — task #29).

So the most likely slot identity of the captured drag is **WAH
DIRECT MIX**, not SUSTAIN. The user's UI label "SUSTAIN" was the
BTS panel layout for a *different* selected FxItem, not slot 0.

**For P0-1 the slot identity doesn't matter** — only the wire format
of each value, and that is unambiguous. But for any future
parameter-meaning analysis from these captures, treat
`0x10001117` as WAH PEDAL MIN (display 0..100, raw 32768..32868)
unless re-verified.

---

## §4. Firmware version source (Task 4)

Source: nothing — no firmware-version SysEx was captured.

### What we observed

Across both capture sessions (Task 1 startup; Task 2 chain-edit
session that also covered Tasks 3 & 4), **no RQ1 reads to addresses
outside the chart-documented map** were issued by BTS. In particular,
no read whose reply payload contained anything resembling `1.04` /
`0x01 0x04` / `01 00 04 00`.

The user did open BTS dialogs that mention the device, but no SysEx
traffic correlated with those dialog opens.

### Verdict on cross_check_findings P1-1

**Unsettled. Strong hypothesis: BTS does not fetch the firmware
version via SysEx — it likely uses a USB control transfer or reads
the version from the USB descriptor / HID descriptor.**

Justification for the hypothesis:

- The GX-10 enumerates as a USB-class composite device (Audio + MIDI
  + maybe HID). The USB descriptor's `bcdDevice` field, or a
  vendor-specific control transfer, would be a natural place for a
  firmware version that BTS can read once at connect and cache.
- Identity Reply returns `01 00 00 00` regardless of firmware
  version (Linux-side observation), so BTS cannot be using that.
- The chart-documented MIDI address space we have read in full
  during this session does not contain anything obviously
  version-shaped.
- Roland editors for other products are known to use vendor-specific
  USB control transfers for version queries.

**This task is not settleable from MIDI traffic alone.** A working
USBPcap on this controller would settle it definitively, but
USBPcap is broken here (see Capture-method note). Resolution paths:

1. Linux-side `lsusb -v` reading the `bcdDevice` field on a 1.04
   device vs a 1.0x device — if those differ, that's the source.
2. A USB analyser hardware (Beagle USB, Ellisys, ...) — the only way
   to see the control transfers if `bcdDevice` doesn't match.
3. Reverse engineering of the BTS native bridge DLL, looking for
   `WinUsb_ControlTransfer` calls.

Recommended: **mark P1-1 as "deferred — needs USB-level capture"**
on the Linux side and document the hypothesis in
`docs/firmware_versions.md`.

---

## §5. Device-knob broadcast — overturns the Linux "no broadcast" finding

Source: `captures/bts_device_knob.summary.md`,
`captures/bts_device_knob/sniff2.jsonl`. Captured **after** the Linux
side merged `firmware-versions` and reported that device LCD/knob
edits "don't broadcast on MIDI" (commit `bccde3e`).

### The setup

User opened BTS. BTS performed its standard editor-attach handshake
(`0x7F000001 = 0x01` ×2, `0x7F000703 = 0x00 → 0x01`, etc.) and the
usual bulk-read sweep. Then the user **physically turned two knobs on
the GX-10**. BTS visually mirrored both movements in real time
(user-confirmed: "both done and seen on device and in bts").

### What the device broadcast

| Address | Decode | Events | Sweep |
|---------|--------|-------:|-------|
| `0x10002D07` | FxItem #14, FX Param 2 | 39 | display 42 → 0 over 3.1 s |
| `0x10002D0F` | FxItem #14, FX Param 4 | 24 | display 51 → 100 over 1.9 s |

Every event is a **DT1 with no preceding RQ1** — pure unsolicited
broadcast. Encoding is the canonical 4-nibble offset binary
(payload `08 00 NN NN`, low nibbles concatenated, minus `0x8000`),
identical to BTS's own knob writes (cross_check P0-1).

Decisive samples (full curve in
`captures/bts_device_knob.summary.md`):

```
t=37.627  DT1 0x10002D07 = 08 00 02 0A   raw=0x802A  display=42  (start)
t=38.088  DT1 0x10002D07 = 08 00 02 01   raw=0x8021  display=33
t=39.302  DT1 0x10002D07 = 08 00 00 0E   raw=0x800E  display=14
t=40.737  DT1 0x10002D07 = 08 00 00 00   raw=0x8000  display=0   (settled)

t=62.189  DT1 0x10002D0F = 08 00 03 03   raw=0x8033  display=51  (start)
t=62.503  DT1 0x10002D0F = 08 00 06 00   raw=0x8060  display=96
t=64.093  DT1 0x10002D0F = 08 00 06 04   raw=0x8064  display=100 (settled)
```

### Why the Linux probe missed this

`reports/linux_probe_results.md` (commit `bccde3e`) replicated the
full BTS startup handshake on Linux, **listened 8 seconds**, and saw
zero unsolicited broadcasts. From that the Linux Claude concluded the
broadcast hypothesis was rejected and that "device LCD edits don't
broadcast on MIDI".

The miss was the listen design, not the device behaviour: **the
device only broadcasts on change**, and the 8 s window apparently had
no physical user input. With nothing changing on the device, there is
nothing to broadcast — a quiet 8 s is the expected reading regardless
of whether the channel exists. Once the user turns a knob, the
channel produces tens of events per second.

### Verdict

**Linux conclusions to revise:**

1. `0x7F000703 = 0x01` broadcast hypothesis: not rejected. The
   broadcast channel is real; what `0x7F000703` specifically does
   inside it is still open (it might or might not gate broadcasts —
   needs a comparison test: knob-turn with vs without `0x7F000703`).
2. `tools/passive_sniff.py` description: device knob/LCD edits **do**
   broadcast on MIDI when the editor-attach bit is set.

**Re-test recipe for Linux:**

```
1. Identity Request → reply
2. DT1 0x7F000001 = 0x01 (×2)
3. (optional) DT1 0x7F000703 = 0x00 then 0x01
4. Start passive listening on the SAME MIDI device session
5. **HUMAN TURNS A PHYSICAL KNOB** for 5 seconds
6. Expect N DT1 events at FxItem-region addresses
```

### Implications

- Real-time device-state mirroring is feasible **without polling**:
  set the editor-attach bit, listen, get every parameter change as a
  one-line DT1.
- "BTS magic" (BTS knowing about device edits) is just MIDI — no USB
  control transfers, no HID, no vendor side-channel needed. Linux
  can do exactly the same with rtmidi/ALSA.
- Ties together two previously-disconnected findings:
  - Editor-attach (`0x7F000001 = 0x01`) gates **both** the
    `0x7F0xxxxx` reply paths (settled via Task 1) **and** the
    parameter-broadcast channel (settled here).
  - The 4-nibble offset-binary encoding (Task 3) is the same in
    both directions: device → host broadcasts use the same wire
    format BTS uses on the way in.

This finding alone would justify the Windows session.

---

## Open follow-ups

These are observations that don't block any of the four tasks but
deserve a note for the Linux-side Claude:

### 1. `0x7F000703 = 0x00 → 0x01` toggle (from Task 1)

A second handshake-style write that BTS performs at startup, not
mentioned in `protocol.md §3.7`. The pattern (`0x00` then `0x01`)
mirrors `0x7F000001`. Hypotheses:

- A separate broadcast-subscribe bit (perhaps for the audio-level
  meter channel that the user previously asked about and we couldn't
  locate)
- A sub-mode flag for the same editor-attach state machine

Worth a focused experiment from the Linux side: write
`0x7F000703 = 0x01` from a probe without launching BTS, then watch
for new unsolicited DT1 broadcasts.

### 2. `0x7F000701` (from Task 2)

New global state mirror register, observed transitioning `0x05 ↔ 0x03`
in lockstep with `ChainEditTrigger`. Should be added to
`protocol.md §3.7` as documented. Open question: are there other
values the device ever sets it to, or does only BTS write it?

### 3. User-patch RAM mirror at `0x60400000` (from Task 1)

BTS bulk-read 16 patch slots at `0x60400000..0x604F0000` (stride
`0x10000`), **not** the chart-documented persistent range
`0x20000000..0x29A00000`. The persistent range is for patch storage
on flash; the `0x60400000+` range is the working RAM mirror BTS reads
to display the live patch list. Worth a `protocol.md §3.6` note.
The Linux-side observation that `0x60400000` returns the literal
string `"USER 1   "` is consistent — that's the bank-label header for
the first user patch.

### 4. Chain-list double-write (from Task 2)

Step 1 and step 7 of the per-drag sequence write the chain linked-list
twice. The first looks like an optimistic prediction; the second
reads like a commit after the device's TYPE-change reaction. If the
chain-link structure ever races on a slow device, this might be why.
Not blocking anything — just an observation.

### 5. INSERT/DELETE/OVERWRITE button bug (from Task 2)

Out of scope for protocol RE but tracked here so the next BTS session
can investigate. Buttons remained dead after WebView2 zombies were
killed. Suspect BTS-side `localStorage` or `WebView2` user-data
corruption from earlier `taskkill /F` cycles.

---

## Operational lessons (for future Windows sessions)

These are not protocol findings but matter for any follow-up
session that uses this machine.

1. **Never `taskkill /F` BOSS Tone Studio.** It corrupts the
   persisted MIDI-out port selection. Next BTS launch shows a
   comm-error dialog plus a "confirm MIDI output device" dialog with
   the wrong device pre-selected. Use the user-driven open/close
   flow (`tools/bts_capture_with_pause.py` with the user closing BTS
   manually before pressing Enter, or skip orchestration entirely
   and run the sniffer alongside a user-driven BTS).
   Saved as a memory entry.
2. **USBPcap is unusable on the Intel xHCI 3.10 controller** (PCI
   VEN_8086 DEV_51ED) on this machine. Adding `USBPcap` as an
   `UpperFilters` entry on the root hub disables the controller on
   reboot. Recovery is non-trivial. Stick to MIDI-level captures
   here; a different machine or external USB hub on a different
   controller would be needed for raw-USB work.
3. **Generic USB driver mode is fine** for protocol RE — all SysEx
   traffic flows. Vendor mode wasn't tested in this session.
4. **WebView2 zombies leak** from terminated BTS sessions and can
   block reconnects. Kill them via Stop-Process before next BTS
   launch if BTS hangs at "Connecting...".

---

## Deliverables

Committed in this session:

- `reports/bts_capture_findings.md` (this file)
- `captures/bts_startup.summary.md`
- `captures/bts_chain_edit.summary.md`
- `captures/bts_knob_drag.summary.md`
- `captures/bts_device_knob.summary.md` (§5 follow-up — overturns Linux "no broadcast" finding)
- `tools/bts_orchestrate.py` (sniffer + BTS launch + taskkill flow,
  superseded by the pause variant — kept for reference)
- `tools/bts_capture_with_pause.py` (sniffer + user-driven BTS flow)
- `tools/bts_capture.ps1` (USBPcap wrapper, unused — kept for any
  future machine where USBPcap works)
- `tools/midi_send.py` modification: added `send_short_msg()` for
  PC# / CC injection during captures

Local-only (gitignored, available for re-analysis):

- `captures/bts_startup/` (raw JSONL + decoded .txt)
- `captures/bts_combo/` (chain-edit + Task 3 + Task 4 attempts)
- `captures/bts_knob_drag/sustain.jsonl`
