# Patch-select after a memory write — the commit window is NOT the navigation one (2026-07-26)

A GX-10 (sw_rev `01 00 00 00`, USB, iPad host) wedged hard enough to need a
power cycle while a single user memory was being saved. Read-only probing was
not involved: this is a field report from gxnarly, reconstructed from its debug
log, and it refines what `tools/probe_load_read_window.py` established on
2026-07-24.

**One-line finding.** Selecting a memory *immediately after writing that
memory* provokes a much longer audio-engine commit than selecting a memory the
device already held. Traffic issued inside that window — an RQ1 body read, or a
plain identity request — can make the firmware drop a chain slot's TYPE byte,
and can take the device down entirely. The dropped byte is written to flash.

## What the host did

The save flow, per save:

```
DT1 0x27280000 …            # writeUserSlotFully: 64 regions, 16 KiB, ~4 ms apart
DT1 0x00000000 <4 nibbles>  # patch-select of the SAME memory (make it live)
RQ1 0x27280000 size 0x4000  # verify read-back
```

Memory number 156, which was **already the selected memory**. The patch: 13
effects, all bass variants, including AIRD BASS PREAMP (an AMP-family block, so
the load does model + cabinet IR + reverb-tail setup).

## Timeline of the failure

Times are offsets from the last write DT1.

| offset | event |
|---|---|
| 0 | write complete (0.27 s for 64 regions) |
| ~0 | patch-select sent; host held only 100 ms after it |
| +107 ms | RQ1 `0x27280000` size `0x4000` issued |
| +1.0 s | reply reassembles, but one chain slot's TYPE byte reads `0x00` (decodes as AC GUITAR SIMULATOR; its cells read −20000) |
| +1.8 s | host's periodic identity request gets no reply |
| +2.9 s | host declares the session lost; 11 reconnect attempts all fail with an identity-reply timeout |
| — | device silent until power-cycled; CoreMIDI ports stayed enumerated throughout |

After the power cycle the **same** `0x00` TYPE byte was still there: reads at
+60 s and +170 s show the identical AC SIM / −20000 signature. The corruption
was committed to flash, so a wedge in this window damages the stored patch.

A lighter body saved to the same memory 105 s earlier survived (the device
renormalised a single assign field). The failure needed the AMP-bearing body.

## Why this isn't contradicted by `probe_load_read_window.py`

That probe (2026-07-24, `captures/load_read_window.json`) asked how early after
a patch-select user memory can be read, and found the read safe well before the
device's own bulk-emit lands — user memory being static. Its method is:

```
select the OTHER memory, settle 2 s     # force a real load
select the TARGET memory      -> t0
wait d ms ; RQ1 memory(TARGET)
```

There is **no write before the select**. So it measures the navigation case,
where the device recalls what it already had. It says nothing about a select
whose source bytes arrived milliseconds earlier — which is the case that fails.
Both results stand; they are different scenarios.

## Suggested probe extension

A `--after-write` mode for `probe_load_read_window.py` would pin the real
window, sweeping `d` over the same range but with the write in front:

```
write memory(TARGET) fully (64 regions, ~4 ms apart)
select TARGET                 -> t0
wait d ms ; RQ1 memory(TARGET) ; classify vs a settled reference
health-check identity; abort on no reply
```

Worth running twice — once with an AMP-family block in the body, once without —
since the AMP model load is what appears to lengthen the commit. Note the
safety profile is worse than the existing probe: this one writes a memory (use a
scratch slot and restore it) and its realistic failure mode is a wedge **plus a
corrupted TYPE byte in that slot**, so expect to re-save it afterwards.

## Consumer-side handling (gxnarly, for reference)

gxnarly now picks the hold by what the select is loading: a select of a memory
written within the last 3 s waits the full 1 s edit-buffer commit window instead
of the 100 ms navigation figure, with its bulk gate held across the wait so
neither the verify read nor the heartbeat can enter it. Details and regression
cover: `gxnarly/docs/specs/midi-protocol.md` §4.2.3.

## Related

- `docs/gaps.md` §8 — patch-select register, and the ~1126 ms device bulk-emit.
- `reports/raw_to_display_contamination_2026-05-27.md` — unrelated cause, same
  "rogue AC SIM" read symptom; TYPE byte `0x00` decoding as AC GUITAR SIMULATOR
  is a generic signal that a slot main was lost, not a specific bug.
