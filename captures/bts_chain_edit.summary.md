# BTS chain-edit (Task 2) capture summary

Source: `captures/bts_combo/all.jsonl` (the same capture session also covered
attempts at Tasks 3 and 4; see end of file).

User report: BTS's INSERT / DELETE / OVERWRITE buttons remained dead in this
session even after the WebView2 zombie cleanup. User performed the equivalent
operations via **drag-drop** instead — drag adds, drag-off-chain removes,
drag-replaces-slot is the OVERWRITE equivalent. Drag-drop uses a different
code path in BTS that doesn't suffer the cache-guard short-circuit.

## ChainEditTrigger handshake — confirmed.

Each drag operation produces a paired `0x00200003` write:

```
t=31.11  DT1 0x00200003 = 01     (begin chain edit)
t=31.26  DT1 0x00200003 = 00     (end chain edit)
t=32.47  DT1 0x00200003 = 01
t=32.66  DT1 0x00200003 = 00
...
```

In total **16 begin/end cycles** over the session — consistent with the user
performing many drag operations.

## NEW finding: `0x7F000701` is a state mirror.

Every `0x00200003` write is accompanied by a `0x7F000701` write 0–10 ms later:

```
t=31.11  DT1 0x00200003 = 01    AND    DT1 0x7F000701 = 05
t=31.26  DT1 0x00200003 = 00    AND    DT1 0x7F000701 = 03
```

The pattern is rock-solid across all 16 cycles:
- chain-edit begin → `0x7F000701 = 0x05`
- chain-edit end → `0x7F000701 = 0x03`

This register was previously listed in `protocol.md` as "unknown / undocumented"
in the `0x7F00xxxx` range (only `0x7F000700` had been observed for tuner
state). The value `0x7F000701` was never seen in Linux probes. It now joins
the small family of "global state mirror" registers BTS maintains alongside
the actual functional bits.

## Per-drag SysEx sequence (verified at t≈62.7 and t≈72.2)

```
1.  DT1 0x10000F0C  CHAIN_LIST   (50 bytes — new linked-list ordering)
2.  DT1 0x00200003 = 0x00       (end of previous edit if open)
3.  DT1 0x10001300 = <FX TYPE>  (FxItem N TYPE byte for the dropped effect)
4.  DT1 0x10001302 = 0x00       (DuplicationNumber)
5.  DT1 0x10001301 = 0x01       (ON/OFF)
6.  DT1 0x7F000701 = 0x03       (state mirror back to idle)
7.  DT1 0x10000F0C  CHAIN_LIST   (re-write of the new list)
8.  DT1 0x10001303 = <32 bytes> (FX Param 1+ initial values)
9.  DT1 0x00200003 = 0x00       (final end)
```

This matches `docs/protocol.md` §5.6 with one nuance: BTS writes the
chain linked-list *twice* per drag (steps 1 + 7), separated by the new-effect
TYPE/ON-OFF/DupNum writes. Plausibly the second write commits the final
state after the device has had a chance to react to the TYPE change.

## Verdict on `gaps.md §1.1` (chain-edit buttons broken)

The buttons remain broken on this BTS install (1.04-era firmware, Generic
USB driver mode). Even after killing 18 zombie `msedgewebview2.exe`
processes and confirming the device-side `0x00200003 = 0x00`, the
INSERT/DELETE/OVERWRITE buttons in BTS still produced no MIDI traffic.

Drag-drop works fine — meaning the protocol is unambiguous and the
device is in good shape; the issue is contained to BTS's button-click
handlers. Possible BTS-side root causes (not investigated):

- BTS's `globalIsChainEditing` JS variable persisted in localStorage between
  sessions at a stale value
- BTS's WebView2 user-data corrupted from earlier force-kill cycles —
  reinstall would reset it
- The buttons require a state BTS only enters when its connect handshake
  reaches a particular point that isn't always reached

Recommended next-step: clear `%LOCALAPPDATA%\BOSS\BOSS TONE STUDIO for GX-10\
WebView2\` (or whatever path BTS uses for its persistent user-data) before
the next session.

## Tasks 3 & 4 within the same capture

- **Task 3 (SUSTAIN drag)** — no FX-Parameter writes (4-byte writes to
  any FxItem `+0x07` / `+0x0B` / etc.) are present in the session. Either
  the user didn't drag any sliders, or BTS's sliders went to a chain-affected
  effect that doesn't have the COMP layout. **Status: not captured.**
- **Task 4 (firmware version)** — no RQ1 reads to any address outside the
  chart-documented map. If the user opened a dialog, **it didn't fetch the
  firmware version via SysEx**. Strong hypothesis: BTS gets the firmware
  version from a USB control transfer, not MIDI. We can't observe that
  without USBPcap (which is unusable on this controller). **Status: probably
  un-resolvable without USBPcap.**
