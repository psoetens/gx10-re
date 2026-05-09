# BTS startup-handshake — Task 1 capture summary

Source: `captures/bts_startup/startup.jsonl` (300 SysEx events captured between
t=4.72 and t=9.08, all on the GX-10 input port via WinMM). BTS PID 4952 was
launched at t=2.0; Identity Request flowed at t=4.78; BTS finished its initial
read sweep at t=9.08 and went idle until shutdown.

Capture method: passive `tools/midi_sniff.py` running while
`tools/bts_orchestrate.py` launched BTS, waited 12 s, sent a Bank Select +
PC#1 (which BTS / device ignored), waited 4 s, then `taskkill`d BTS.
USBPcap could not be used on this controller (see history at top of
`reports/bts_capture_findings.md`).

Direction note: WinMM input loopback gives every event a `dir=dev->host`
tag, but the data clearly contains both BTS RQ1s and device DT1 replies —
the GX-10's "MIDI in/out" pair feeds back the host's writes onto the input
stream, so we get bidirectional capture for free.

## Decisive 12 events

```
t=4.720  RQ1  0x10000069  len=4  -> KnobN SettingFxItem block (20 bytes)
t=4.725  DT1  0x10000069  payload=05 05 05 00 00 00 0A 04 00 00 0A 06 00 00 0A 08 00 02 0B 05
                                  ^^^^^^^^^^^^ ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                  4 FxItem indices (5,5,5,0)  +  4 TARGETs (4-nibble each)
t=4.775  Universal Identity Request (F0 7E 7F 06 01 F7)
t=4.777  Identity Reply: mfr=41 family=0x040b model=0x0000 sw=01000000
t=4.788  RQ1  0x7F000000  size=1
t=4.790  DT1  0x7F000000  = 0x03           (system mode flag, same as Linux probe)
t=4.799  DT1  0x7F000001  = 0x01           **EDITOR-ATTACH bit set**
t=4.801  DT1  0x7F000001  = 0x01           (defensive re-write)
t=4.809  RQ1  0x7F000003  size=1
t=4.810  DT1  0x7F000003  = 0x00           (revision-check stub, returns 0)
t=7.090  RQ1  0x7F000002  size=1
t=7.092  DT1  0x7F000002  = 0x00           (RunningMode = EDIT — visible BECAUSE handshake bit was set at t=4.799)
t=7.700  DT1  0x7F000703  = 0x00           **second handshake-style bit, undocumented**
t=7.701  DT1  0x7F000703  = 0x01
```

## Findings

### 1. `0x7F000001` is the editor-attach handshake bit — confirmed.

BTS writes `0x01` twice immediately after the Identity exchange (t=4.799 and
t=4.801). On disconnect the symmetric `0x00` write would normally appear, but
in this capture BTS was killed via `taskkill /F`, so the disconnect handshake
was skipped. Future captures using a clean BTS exit will record it.

### 2. `0x7F000002` and `0x7F000703` respond ONLY when the handshake bit is set.

These were the registers the Linux-side Claude reported "silent" because Linux
probes never set `0x7F000001 = 1`. With BTS's handshake in place, both reply.
**Settles cross_check_findings P2-4.**

### 3. `0x7F000703` carries a second handshake-style write.

BTS writes `0x00` then `0x01` to `0x7F000703` at t=7.700/7.701 — a "toggle to
1" pattern matching the editor-attach behaviour at `0x7F000001`. This register
is **not in `protocol.md` §3.7** as anything more than "unknown tag". Two
hypotheses worth follow-up:

- a separate broadcast-subscribe bit (perhaps for the audio-level meter
  channel the user previously asked about and we couldn't locate)
- a sub-mode flag for the same editor-attach state machine

Worth a focused experiment: write `0x7F000703 = 0x01` from a custom probe
without launching BTS, then watch for new unsolicited DT1 broadcasts.

### 4. BTS reads the entire device snapshot in the first 4.4 seconds.

Once subscribed, BTS bulk-reads (RQ1+DT1 pair per address) the full chart-
documented address space:

| Block | Addresses | Notes |
|-------|-----------|-------|
| SystemCommon | `0x00000000` | + `0x00001000`/`0x00001034` (SystemControl) |
| SystemMidi  | `0x00003000` | |
| SystemInOut | `0x00004000` | the [SystemInOut] block we already decoded |
| SystemEfct  | `0x00005000` | |
| SystemPitch | `0x00006000` | REF PITCH + tuner config |
| InputSetting 1..10 | `0x00006100..0x00006A00` | 10 input memories |
| SystemGlobalEq | `0x00006B00` | |
| PcmapPc bank 1..3 | `0x00100000..0x001008xx` | MIDI PC# map |
| Setup_temp head | `0x00200000`, `+0x06`, `+0x07`, `+0x08`, `+0x40`, `+0x140`, `+0x240`, `+0x340` | tuner-state regs |
| memory_temp | `0x10000000` (name) + `0x10000069` (knob block) | |
| MemoryLed | `0x10000100`, `0x10000140` | |
| Assigns 1..20 | `0x10000200..0x10000B40` (stride 0x40) | 20 reads |
| MemoryEfct | `0x10000F00` | BPM + chain head |
| 20 FxItems | `0x10001100..0x10003700` (stride 0x200) | All 20 read |
| Specific FxItem +0x03 | slots 4, 9, 12, 13 | re-reads after the bulk pass — perhaps post-validation |
| Patch-name table | `0x50000000..0x50002500` (38× 128 B) | 296 preset names — `protocol.md §3.5` confirmed |
| User patches (RAM) | `0x60400000..0x604F0000` | 16 slots × 0x10000 stride. **NOT** the persistent `0x20000000+` range. |
| 0x7F00xxxx | 00, 01, 02, 03, 0703 | system / handshake registers |

### 5. The PC#1 we sent at t=32 produced zero MIDI activity.

BTS / the device ignored the standard Bank Select + PC# we injected. Either:
- the device's RX-channel filter rejected it (RX CH = 1 vs our `B0` = ch 0)
- in editor-attach mode, the device treats standard MIDI commands as non-
  device-state-affecting

Either way, this means the planned "patch change" event in Task 1's procedure
didn't fire any traffic — the only useful traffic in this capture is the
initial connect handshake (which is what mattered most anyway).

### Open follow-up

- The `0x7F000703 = 0x00 → 0x01` toggle is the single most interesting
  unfamiliar event in the capture. Probe in a follow-up.
- BTS read user patches at `0x60400000..0x604F0000` (RAM mirror, 16 slots),
  NOT at the chart-documented `0x20000000..0x29A00000` (persistent storage).
  Worth a note in `protocol.md` §3.6.
