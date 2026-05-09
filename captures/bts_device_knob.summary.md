# BTS device-knob broadcast capture — overturns Linux "no broadcast" finding

Source: `captures/bts_device_knob/sniff2.jsonl`. Passive `midi_sniff.py`
running while user opened BTS, BTS performed its standard editor-attach
handshake, then user turned **two physical knobs** on the GX-10. BTS
visually mirrored both knob movements in real time (user-confirmed:
"both done and seen on device and in bts").

## Verdict

**The device DOES broadcast knob changes via SysEx DT1, contrary to
the Linux conclusion in commit `bccde3e`.** The broadcasts are
unsolicited (no preceding RQ1), they target the same FX-Parameter
addresses BTS would write to, and they use the same canonical 4-nibble
offset-binary encoding. They occur only when an editor is attached
(`0x7F000001 = 0x01`).

**Why the Linux probe missed this:** the Linux test set the
editor-attach bit, listened 8 seconds, and saw nothing. But it never
physically touched the device during those 8 seconds. The device only
broadcasts on **change** — it's a state-mirror channel, not a free-
running stream. With no physical input, there is nothing to broadcast,
and the experiment is a no-op.

## Capture timeline

```
t=15.42   BTS does its standard startup handshake (RQ1 0x10000069,
          Identity exchange, 0x7F000001 = 0x01 editor-attach ×2,
          0x7F000003 read, 0x7F000703 = 0x00 → 0x01)
t=15.6..37  BTS bulk-reads the chart-documented address space
            (patch names, FxItems, etc.) — same as Task 1 startup
t=37.6    USER TURNS KNOB #1 (sweeps DOWN: 42 → 0)
          Device broadcasts 39 DT1s to 0x10002D07
t=40.7    knob #1 settles at 0
t=62.2    USER TURNS KNOB #2 (sweeps UP: 51 → 100)
          Device broadcasts 24 DT1s to 0x10002D0F
t=64.1    knob #2 settles at 100
```

## Decisive events — knob #1 (FxItem #14 / FX Param 2)

```
t=37.627  DT1 0x10002D07 = 08 00 02 0A   raw=0x802A  display=42   ← start
t=37.751  DT1 0x10002D07 = 08 00 02 07   raw=0x8027  display=39
t=38.088  DT1 0x10002D07 = 08 00 02 01   raw=0x8021  display=33
t=38.317  DT1 0x10002D07 = 08 00 01 0E   raw=0x801E  display=30
t=39.049  DT1 0x10002D07 = 08 00 01 07   raw=0x8017  display=23
t=39.802  DT1 0x10002D07 = 08 00 00 0A   raw=0x800A  display=10
t=40.113  DT1 0x10002D07 = 08 00 00 01   raw=0x8001  display=1
t=40.737  DT1 0x10002D07 = 08 00 00 00   raw=0x8000  display=0    ← settled
```

39 events total. Cadence ~30–60 ms between events during active
turning, occasional larger gaps where the knob paused.

## Decisive events — knob #2 (FxItem #14 / FX Param 4)

```
t=62.189  DT1 0x10002D0F = 08 00 03 03   raw=0x8033  display=51   ← start
t=62.256  DT1 0x10002D0F = 08 00 04 01   raw=0x8041  display=65
t=62.359  DT1 0x10002D0F = 08 00 05 00   raw=0x8050  display=80
t=62.503  DT1 0x10002D0F = 08 00 06 00   raw=0x8060  display=96
t=64.093  DT1 0x10002D0F = 08 00 06 04   raw=0x8064  display=100  ← settled
```

24 events total. Same encoding, same broadcast mechanism, different
parameter slot (offset `+0x0F` = FX Param 4 by the formula
`0x03 + (N-1)*4`).

## Why these are device-originated, not BTS

1. **No preceding RQ1 to either address.** Across the whole capture
   (359 SysEx events) BTS issued exactly one RQ1 to the FxItem #14
   region (`0x10002D00`, the FxItem header) during its bulk-read phase
   at startup, and never RQ1'd `0x10002D07` or `0x10002D0F`. So these
   DT1s are not RQ1 replies.
2. **Cadence too fast for round-trip.** 39 events in 3.1 seconds with
   gaps as short as 5 ms; no host could RQ1+wait that fast on a USB
   MIDI loop.
3. **Monotonic sweep with intermediate values** is a classic physical-
   knob signature. BTS would write target values, not transient ones.
4. **The user reports the action came from the physical device** and
   that BTS displayed the change — meaning BTS received it via this
   broadcast (or via something equivalent) and its UI followed.

## Encoding

Identical to BTS's outgoing knob writes (cross_check P0-1):
4-nibble offset binary, `display = (low nibble of each byte
concatenated) − 0x8000`. Per-byte high nibble is always `0x0`; only
the low nibble carries data.

## Implications for the Linux side

`reports/linux_probe_results.md` (commit `bccde3e`) reports two
related findings:

> "0x7F000703 = 0x01 broadcast hypothesis REJECTED. ... Listened 8s.
> Zero unsolicited broadcasts."

> "Linux observation: device LCD edits don't broadcast on MIDI — only
> host-driven edits show up here." (in the description of
> `tools/passive_sniff.py`)

Both should be **revised**:

1. The hypothesis is not rejected — the broadcast channel IS active
   when the editor-attach handshake is done. The 8-second listening
   window simply didn't include any physical activity.
2. Device LCD/knob edits **do** broadcast on MIDI — provided
   `0x7F000001 = 0x01` is set on the same MIDI session that listens.

**Re-test recipe (Linux):**

```
1. Send Identity Request, wait for reply.
2. DT1 0x7F000001 = 0x01     # editor-attach
3. DT1 0x7F000001 = 0x01     # BTS does it twice; mirror that
4. (optional) DT1 0x7F000703 = 0x00 then 0x01
5. Start passive listening on the SAME MIDI device session.
6. **Have a human turn a knob on the device for 5 seconds.**
7. Verify N DT1 events arrive at addresses inside the FxItem block
   (0x10001100..0x10003700 depending on which slot the user touched).
```

Step 6 is the missing piece in the prior probe. Without it the
listen window is a no-op.

## Address mapping

The user's two knobs sat at:

| Address | FxItem stride decode | FX Param formula |
|---------|---------------------|------------------|
| `0x10002D07` | (0x10002D07 − 0x10001100) / 0x200 = 14 | (0x07 − 0x03)/4 + 1 = **2** |
| `0x10002D0F` | (0x10002D0F − 0x10001100) / 0x200 = 14 | (0x0F − 0x03)/4 + 1 = **4** |

**Slot 14 of the FxItem table** — whichever effect is currently
assigned there in the user's patch. Without the patch's CHAIN_LIST
contents I can't map "slot 14" to a chain position, but the address
math is unambiguous.

## What this changes

- **Real-time device-mirror is feasible without polling.** Set the
  editor-attach bit, listen on the same MIDI session, get every
  parameter change as a one-line DT1.
- The "BTS magic" the Linux side observed (BTS knows about device
  edits) is **just MIDI** — no USB control transfers, no HID, no
  vendor side-channel needed. Sniffing this same MIDI port from the
  Linux side will show the same data.
- Combined with the Task 1 startup capture, the editor-attach
  handshake is now fully understood:
  - `0x7F000001 = 0x01` enables broadcast (and unlocks the
    `0x7F000002`/`0x7F000003`/`0x7F000703` reply paths)
  - `0x7F000701` is a state mirror tracked during chain edits
  - `0x7F000703` is still mysterious (write-only, no broadcast
    triggered by it alone) — re-test once Linux side has knob-broadcast
    confirmed to disambiguate
