# BTS knob drag (Task 3) — settles cross_check P0-1

Source: `captures/bts_knob_drag/sustain.jsonl`. The user dragged a SUSTAIN
slider in BTS on FxItem #0 (X-COMP variant), sweeping through values 0..100
then settling at 50.

## Verdict

**BTS uses canonical 4-nibble offset binary**. The Linux-observed device
behaviour (each cell byte is interpreted as a single nibble; `[08 00 00 64]`
gets stored as `[08 00 00 04]` because only the low nibble of each byte
counts) is consistent with BTS's wire format. **gxnarly's knob_cell encoder
needs no revision** — it already produces what BTS produces.

## The decisive 7 events

The user's drag passed through 50, 100, 1 / 0. BTS sent at each transient
display value:

```
t=32.96   DT1  ...0117 = 08 00 02 0A    raw=0x802A  display=42
t=33.01                    08 00 00 01    raw=0x8001  display=1     ← canonical encoding for value 1
t=33.03                    08 00 00 00    raw=0x8000  display=0     ← display 0 = 4 zero nibbles, high-nibble 0x08 marker
t=35.50                    08 00 03 02    raw=0x8032  display=50    ← decisive: 50 -> 0x32 (low nibbles 3 and 2)
t=35.56                    08 00 06 04    raw=0x8064  display=100   ← decisive: 100 -> 0x64 (low nibbles 6 and 4)
t=37.40                    08 00 06 02    raw=0x8062  display=98
t=41.75                    08 00 03 02    raw=0x8032  display=50    ← settled here
```

The encoding is unambiguous:
- byte 0: always `0x08` (offset-binary positive sign — fixed for non-negative values)
- byte 1: high-byte high-nibble (always `0x00` for SUSTAIN range 0..100)
- byte 2: high nibble of the 8-bit value (e.g. `0x03` for 50, `0x06` for 100)
- byte 3: low nibble of the 8-bit value (e.g. `0x02` for 50, `0x04` for 100)

…which is exactly what `protocol.md §3.5` (post-Linux-side update) documented:

> Each FX Parameter is **4 nibbles big-endian, offset binary**.
> `display = (low nibble of each byte concatenated) − 0x8000`.

If BTS had used the alternative single-byte form (`08 00 00 64` for 100,
`08 00 00 32` for 50), the device would have truncated and the slider
would have appeared to be at value 4 / 2 instead of 100 / 50 — a bug
the user would have noticed long ago.

## Address used

The drag wrote to `0x10001117` (offset `+0x17` of FxItem #0). That's
**FX Parameter 6** (formula: `0x03 + (N−1)*4` so `(0x17 − 0x03)/4 + 1 = 6`).
Whether this is "SUSTAIN" depends on what TYPE byte FxItem #0 holds in
the user's current patch — if it's COMP (TYPE 0x08) param 6 would be
DIRECT MIX, not SUSTAIN. If FxItem #0 is X-COMPRESSOR (TYPE 0x09), the
parameter listing for X-COMPRESSOR (per Parameter Guide and our captured
catalog) puts DIRECT MIX at param 6 too. So the user's "SUSTAIN" UI label
may not have matched the parameter slot the slider was actually wired
to — but **for our purposes (verifying BTS's encoding) the slot identity
doesn't matter**, only the wire format of each value.

## Total drag events

39 individual DT1 writes during the ~9-second drag window (t=32.96 to
t=41.75). All use the same `[08 00 ?? ??]` 4-byte canonical form. None
use the alternative single-byte form. Encoding fully consistent across
the entire drag.

## Takeaway

P0-1 from the cross-check findings is **CONFIRMED**: BTS sends 4-nibble
offset-binary FX Parameter values, matching what the device decodes. No
firmware-version or driver-mode dependency observed.
