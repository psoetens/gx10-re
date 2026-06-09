# RQ1 merge-read empirical findings

**Date:** 2026-05-29
**Hardware:** GX-10, firmware 1.04, USB class-compliant MIDI
**Tools:** `tools/probe_merge_sizes.py` + ad-hoc diagnostic snippets

## Key revelation

The "BTS reads 0x103 bytes per slot main" framing was wrong. **0x103 is
the *requested* size; the device returns its own natural record size,
which is 131 bytes for a slot main.** Empirical confirmation from the
BTS USB capture (`gx10-re/captures/bts_import_export/import_export_decoded.txt`):

```
RQ1 addr=10001100 len=  4 OK  00000103   <-- BTS asks for 259 bytes
DT1 addr=10001100 len=131 ...            <-- device returns 131
```

Our probe produces the same response. So the device's chunking
strategy is:
- For an RQ1 covering a single natural record, return one DT1 of the
  record's natural size — regardless of the requested size.
- For an RQ1 spanning multiple natural records, return multiple DT1s,
  each at the natural record's wire address.

## Single-shot patch read: 11.9× faster, byte-identical

The big finding: **one RQ1 of size=0x4000 against a user-slot base
returns the entire patch body in ~43 DT1s, in under 1 second, with
byte-identical data to BTS's 64-region method.**

```
Method A (BTS regions, 64 RQ1s):     11.73 s, 1499 non-zero bytes
Method B (single RQ1 size=0x4000):    0.99 s, 1499 non-zero bytes
Diff: 0 bytes
Speedup: 11.9×
```

Same applies to the live edit buffer at `0x10000000` — same single-shot
read works (0.98 s).

## Catalogue: 3.3× faster

```
Method A (BTS, 38 separate 0x100 RQ1s):  2.85 s, 4800 bytes
Method B (single RQ1 size=0x2600):       0.85 s, 4800 bytes
Speedup: 3.3×
```

24 DT1s come back (vs 38 chunks), each ~210 bytes packed contiguously
in the linear address space — no gaps.

## What can be merged

| Current pattern | Bytes/RQ1 | Merge-into | Wall-time savings |
|---|---|---|---|
| 64-region patch read (BTS-style) | ~131 max | single `RQ1 size=0x4000` | **11.9× faster** |
| 38-row catalogue read (BTS-style 0x100 each) | 128 | single `RQ1 size=0x2600` | **3.3× faster** |
| 2 RQ1s per assign pair (45+45) | 45 | single `RQ1 size=0x6D` | 2× fewer RQ1s |
| Slot main (0x103) + slot ext (0x30) | 131 / 48 | single `RQ1 size=0x200` (returns 1 DT1 of 179) | 2× fewer RQ1s |

## What can NOT be merged

- **Cross-region gaps cause garbage.** Asking for a range that bridges
  the natural-record gap at slot offset `0x83..0x102` (between slot
  main and slot ext) makes the device pack records contiguously — the
  data is still correct *as bytes*, but it lands at different offsets
  than the canonical BTS layout. Decoders that assume the canonical
  layout will see "mismatches" unless they pivot to natural-record
  offsets.
- **Header + knob block** (0x0000..0x015C) has an unread gap; the
  device's response to a request spanning both gives mixed-up data.
- **All 10 assign pairs in one RQ1** (size=0xB80): byte 3 of size
  field is `0x80` — illegal under raw big-endian encoding. The next
  legal size that covers all pairs is `0xC00` (3072 bytes) — could
  work but would need testing.

## Implementation recommendation for gxnarly

Replace the 64-region `readUserSlotFully` loop with **one** RQ1:

```swift
let data = try await performBulkRead(
    address: userMemoryAddress(slot),
    byteCount: 0x4000,            // whole patch body
    chunkSize: 0x4000,            // no chunking
    timeout: 3.0)                 // device takes ~1s real-time
```

Then walk the resulting buffer's natural records (the codec already
knows where each lives — TYPE/ON/DUP at slot+0x00, cells at slot+0x03,
etc.). The 11.9× speedup applies to:
- Initial library refresh
- Memory-sync guard reads
- Any RQ1-driven patch comparison

Same change for `loadPatchIntoEditBuffer`'s read-back if any, and the
catalogue refresh path (`readCatalogueChunk` × 38 → one `0x2600` RQ1
against `0x50000000`).

## Probe limitations / things still to investigate

- The `Probe.request()` debounce is 400 ms — wall time is dominated by
  that. Tightening to 100–150 ms would help further but risks
  truncating slow multi-DT1 responses.
- `userram-hdr` at `0x60400000` showed mismatches at offset 0x60 —
  unclear if that region has a different chunking strategy or our
  ground-truth method (0x40 chunks across illegal 0x80 boundaries)
  was unreliable.
- Did not test the live edit buffer's read-back behaviour during
  device editing — there could be timing constraints.
