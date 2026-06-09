#!/usr/bin/env python3
"""Probe how far we can merge contiguous RQ1 reads on the GX-10 / GX-100,
beyond BTS's proven small-region layout.

Strategy
--------
1. Capture a ground-truth buffer of a user-memory slot using the *proven*
   BTS small-region method (`probe_bts_match.bts_regions()`).
2. For each candidate "merge zone" (e.g. header+misc+knob, all-assigns,
   full-slot-pair, etc.), try progressively larger single-shot RQ1 reads:
     - Step by `STEP = 0x40` from `baseline_size` up to `max_size`.
     - Skip sizes whose any 4-byte BE byte > 0x7F (SysEx illegal).
     - For each size: send RQ1, drain DT1s, assemble, compare to ground
       truth.
3. Print PASS / TIMEOUT / PARTIAL / MISMATCH for each size and report
   the largest size that worked for each zone.

Conservative bias: stop a zone after 2 consecutive non-OK results — the
device has clearly told us where the limit is, no point in poking it
further. We never double; we only increment by 0x40.

The script does NOT modify device state. RQ1 is read-only.

Usage
-----
    python3 tools/probe_merge_sizes.py --v 33

`--v 33` defaults to U12-1 (slot index 33), the same fixture
`probe_bts_match.py` uses.
"""
import argparse
import json
import sys
import time
from pathlib import Path

# Pull the BTS-method probe + raw-BE RQ1 helpers from the upstream
# module — its `Probe.request()` already does proper wire→linear
# conversion and exposes `last_dt1_count` / `last_dt1_addrs`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_bts_match import (  # noqa: E402
    Probe,
    bts_regions,
    user_memory_address,
    make_rq1,
    parse_dt1,
    wire_to_linear,
)


STEP = 0x40
MAX_CONSECUTIVE_FAILS = 2
REQUEST_TIMEOUT = 2.5
SETTLE_BETWEEN_REQUESTS = 0.05


def is_7bit_clean(size: int) -> bool:
    """RQ1 size is 4 raw big-endian bytes; every byte must be ≤ 0x7F."""
    return all(((size >> shift) & 0xFF) <= 0x7F for shift in (24, 16, 8, 0))


def bulk_read_ground_truth(p: Probe, base: int) -> bytes:
    """Assemble a 0x4000-byte buffer using BTS's small-region method.
    Stores whatever the device returned at each region's natural record
    address — the BTS "region size" is a REQUEST ceiling, not the
    expected response length. The device responds with its natural
    record (e.g. 131 B for a slot main, even when 259 was requested).
    A region is only counted as "failed" when the device returned no
    DT1 at all."""
    buf = bytearray(0x4000)
    fails = []
    short_replies = []
    for off, size in bts_regions():
        time.sleep(0.02)
        data = p.request(base + off, size, timeout=REQUEST_TIMEOUT)
        if data is None or len(data) == 0:
            fails.append((off, size))
            continue
        if len(data) < size:
            short_replies.append((off, size, len(data)))
        # Trust the partial — it IS the natural record at this address.
        for j in range(min(len(data), len(buf) - off)):
            buf[off + j] = data[j]
    if fails:
        print(f"# {len(fails)} region(s) returned nothing:")
        for off, size in fails[:8]:
            print(f"#   offset 0x{off:04X} size=0x{size:X}")
    if short_replies:
        print(f"# {len(short_replies)} region(s) returned a natural record "
              f"smaller than the requested size (this is normal — the device "
              f"sends its native record, regardless of request size):")
        # Show the distinct (request → response) size pairs that occurred
        pairs = {}
        for _, sz, got in short_replies:
            pairs.setdefault((sz, got), 0)
            pairs[(sz, got)] += 1
        for (sz, got), count in sorted(pairs.items()):
            print(f"#   asked 0x{sz:>4X} → got {got:>3} bytes  (×{count})")
    return bytes(buf)


def first_mismatch(a: bytes, b: bytes) -> int | None:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return None


def probe_zone(
    p: Probe,
    base: int,
    ground_truth: bytes,
    label: str,
    start_off: int,
    baseline_size: int,
    max_size: int,
) -> dict:
    """Probe one merge zone. Returns a dict with the largest single-RQ1
    payload (in bytes) the device returned, along with the request size
    and DT1 count that achieved it.

    Result semantics for each request size attempted:
      - MATCH   : every byte the device returned matches ground truth.
                  This is the success case — we extracted N bytes (≤ size)
                  in K DT1s in one round-trip.
      - MISMATCH: device returned bytes that disagree with ground truth.
                  Real bug — stop probing this zone.
      - NONE    : device sent no DT1 at all.

    The 'ceiling' is the largest request size where the device sent
    something useful (MATCH); we stop after 2 consecutive failures."""
    print(f"\n=== {label}  @ +0x{start_off:04X}  "
          f"(baseline=0x{baseline_size:X}, max=0x{max_size:X}) ===")
    print(f"  {'size':>6} | {'got':>5} | {'DT1s':>4} | {'time':>5} | result")
    print(f"  {'-'*6}-+-{'-'*5}-+-{'-'*4}-+-{'-'*5}-+-{'-'*40}")
    best = {"request_size": None, "got_bytes": 0, "dt1_count": 0}
    consecutive_fails = 0
    size = baseline_size
    while size <= max_size:
        if not is_7bit_clean(size):
            size += STEP
            continue
        if start_off + size > 0x4000:
            print(f"  ...exceeds 0x4000-byte body, stopping")
            break
        time.sleep(SETTLE_BETWEEN_REQUESTS)
        t0 = time.monotonic()
        data = p.request(base + start_off, size, timeout=REQUEST_TIMEOUT)
        dt = time.monotonic() - t0
        dt1s = p.last_dt1_count
        got = len(data) if data else 0
        if data is None or got == 0:
            print(f"  0x{size:04X} | {got:>5} | {dt1s:>4} | {dt:5.2f} | NONE")
            consecutive_fails += 1
        else:
            # Compare against ground truth at the same offset, byte-by-byte
            # over what the device actually sent. Zeros at uncovered
            # positions in `data` and `ground_truth` both indicate "no
            # natural record at this byte" — those should match.
            mm = first_mismatch(
                data, ground_truth[start_off:start_off + len(data)])
            saturated = "" if got >= size else " (natural ceiling)"
            if mm is None:
                print(f"  0x{size:04X} | {got:>5} | {dt1s:>4} | {dt:5.2f} | "
                      f"MATCH{saturated}")
                if got > best["got_bytes"]:
                    best = {"request_size": size, "got_bytes": got,
                            "dt1_count": dt1s}
                consecutive_fails = 0
            else:
                exp = ground_truth[start_off + mm]
                act = data[mm]
                print(f"  0x{size:04X} | {got:>5} | {dt1s:>4} | {dt:5.2f} | "
                      f"MISMATCH@+0x{mm:04X} (exp {exp:02X} got {act:02X})")
                consecutive_fails += 1
        if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
            print(f"  ...{MAX_CONSECUTIVE_FAILS} consecutive non-MATCH, "
                  f"stopping zone")
            break
        size += STEP
    if best["request_size"] is not None:
        print(f"  >>> best: request 0x{best['request_size']:X} → "
              f"{best['got_bytes']} bytes in {best['dt1_count']} DT1(s)  "
              f"({best['got_bytes'] / max(1, best['dt1_count']):.0f} B/DT1)")
    else:
        print(f"  >>> no MATCH size found in zone")
    return best


# Candidate merge zones within a user-memory slot body (0x4000 B).
# Each entry: (label, start_off, baseline_size, max_size)
# - baseline = the BTS-proven size for that region (or smaller)
# - max_size chosen to test a meaningful upper bound:
#     - up to next region's start, or
#     - capped at the body size where it would overflow
PATCH_ZONES = [
    # Header (256) + misc (1) + knob (28) cluster — natural gap at 0x015C..0x01FF
    ("hdr+misc+knob",        0x0000, 0x0100, 0x0200),
    # Single assign pair (45+45 = 0x6D at +0x00 and +0x40)
    ("assign-pair-merge",    0x0200, 0x002D, 0x0100),
    # All 10 assign pairs span 0x0200..0x0B6D — try as one shot
    ("all-assigns",          0x0200, 0x0100, 0x0B80),
    # Master + chain at 0x0F00 (62 B) — try to merge with end-of-assigns gap
    ("master+chain",         0x0F00, 0x003E, 0x0100),
    # One slot: main (259) + 12-byte gap + ext (48) = 0x133 (307 B)
    ("slot0-full",           0x1100, 0x0103, 0x0180),
    # Two slots in one read: 0x200 stride × 2 = 0x400
    ("slot0+1-block",        0x1100, 0x0103, 0x0400),
    # 4-slot block
    ("slot0..3-block",       0x1100, 0x0103, 0x0800),
    # All 20 slots in one read: 0x1100..0x4900 = 0x3800
    ("all-slots-block",      0x1100, 0x0103, 0x2D00),
]


# Candidate merge zones in system memory.
# Each entry: (label, abs_addr, span_for_ground_truth, baseline, max_size)
# Ground truth is captured by walking `span` in 0x40 chunks first.
SYSTEM_ZONES = [
    # SystemCommon — per official chart spans some hundreds of bytes
    ("syscommon",       0x00000000, 0x0200, 0x0040, 0x0200),
    # SystemControl (0x66 B per chart) — try larger one-shot
    ("syscontrol",      0x00001000, 0x0100, 0x0040, 0x0140),
    # SystemMidi (0x15 B)
    ("sysmidi",         0x00003000, 0x0040, 0x0040, 0x0100),
    # SystemInOut (0x0D B)
    ("sysinout",        0x00004000, 0x0040, 0x0040, 0x0100),
    # SystemPitch (TUNER REF, etc.)
    ("syspitch",        0x00006000, 0x0040, 0x0040, 0x0100),
    # Patch name catalogue chunk — BTS uses 0x100 here; try larger
    ("catalogue-chunk", 0x50000000, 0x0200, 0x0100, 0x0240),
    # User-patch RAM mirror header
    ("userram-hdr",     0x60400000, 0x0200, 0x0100, 0x0240),
]


def system_ground_truth(p: Probe, abs_addr: int, span: int) -> bytes | None:
    """Walk a system region in 0x40 chunks to build a ground-truth buffer.
    Returns None if too many chunks fail (region likely unsupported)."""
    buf = bytearray(span)
    covered = bytearray(span)
    fails = 0
    for off in range(0, span, 0x40):
        time.sleep(0.03)
        data = p.request(abs_addr + off, 0x40, timeout=REQUEST_TIMEOUT)
        if data is None or len(data) == 0:
            fails += 1
            continue
        for j in range(min(len(data), 0x40)):
            if off + j < span:
                buf[off + j] = data[j]
                covered[off + j] = 1
    if fails > span // 0x40 // 2:
        return None
    return bytes(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v", type=int, default=33,
                    help="user-memory slot index (default 33 = U12-1)")
    ap.add_argument("--target", choices=("patch", "system", "both"),
                    default="both",
                    help="which probe to run (default: both)")
    ap.add_argument("--output", "-o", type=Path,
                    help="JSON output of per-zone max sizes")
    ap.add_argument("--port", default="GX-10",
                    help="MIDI port substring (matches GX-10 and GX-100)")
    args = ap.parse_args()

    print(f"# step=0x{STEP:X}, max-consecutive-fails={MAX_CONSECUTIVE_FAILS}, "
          f"timeout={REQUEST_TIMEOUT}s")

    p = Probe(port_substr=args.port)
    results: dict[str, dict] = {"patch": {}, "system": {}}

    if args.target in ("patch", "both"):
        base = user_memory_address(args.v)
        print(f"\n# Probing user slot V={args.v} body @ 0x{base:08X}")
        print("\n--- ground truth (BTS method, 64 small regions) ---")
        t0 = time.monotonic()
        gt = bulk_read_ground_truth(p, base)
        dt = time.monotonic() - t0
        nonzero = sum(1 for b in gt if b != 0)
        print(f"# ground-truth read: {dt:.2f}s, {nonzero} non-zero bytes "
              f"(of {len(gt)} total)")
        name = bytes(gt[:16]).decode("ascii", errors="replace") \
            .rstrip("\x00").rstrip()
        print(f"# patch name: {name!r}  chain TOP={gt[0x0F0C]}")
        if nonzero < 100:
            print("# WARNING: ground truth looks empty — skipping patch "
                  "probes. Pick a populated slot with --v.")
        else:
            print("\n--- patch merge-zone probes ---")
            for label, start, base_sz, max_sz in PATCH_ZONES:
                results["patch"][label] = probe_zone(
                    p, base, gt, label, start, base_sz, max_sz)

    if args.target in ("system", "both"):
        print(f"\n# Probing system regions")
        for label, abs_addr, span, base_sz, max_sz in SYSTEM_ZONES:
            print(f"\n--- {label} ground truth @ 0x{abs_addr:08X} "
                  f"(span 0x{span:X}, 0x40 chunks) ---")
            gt = system_ground_truth(p, abs_addr, span)
            if gt is None:
                print(f"# SKIP: {label} too many failures, region likely unsupported")
                results["system"][label] = None
                continue
            nonzero = sum(1 for b in gt if b != 0)
            print(f"# ground-truth: {nonzero} non-zero of {span} bytes")
            results["system"][label] = probe_zone(
                p, abs_addr, gt, label, 0x0, base_sz, max_sz)

    print("\n=== SUMMARY ===")
    header = (f"  {'zone':<22} {'baseline':>8} {'best req':>9} "
              f"{'bytes':>6} {'DT1s':>5} {'gain':>6}")
    if results["patch"]:
        print("\n  PATCH zones:")
        print(header)
        for label, _, base_sz, _ in PATCH_ZONES:
            b = results["patch"].get(label) or {}
            if not b.get("request_size"):
                print(f"  {label:<22} 0x{base_sz:>6X} {'—':>9} "
                      f"{'—':>6} {'—':>5} {'—':>6}")
                continue
            gain = b['got_bytes'] / max(1, base_sz)
            print(f"  {label:<22} 0x{base_sz:>6X} 0x{b['request_size']:>7X} "
                  f"{b['got_bytes']:>6} {b['dt1_count']:>5} {gain:>5.1f}×")
    if results["system"]:
        print("\n  SYSTEM zones:")
        print(header)
        for label, _, _, base_sz, _ in SYSTEM_ZONES:
            b = results["system"].get(label) or {}
            if not b.get("request_size"):
                print(f"  {label:<22} 0x{base_sz:>6X} {'—':>9} "
                      f"{'—':>6} {'—':>5} {'—':>6}")
                continue
            gain = b['got_bytes'] / max(1, base_sz)
            print(f"  {label:<22} 0x{base_sz:>6X} 0x{b['request_size']:>7X} "
                  f"{b['got_bytes']:>6} {b['dt1_count']:>5} {gain:>5.1f}×")

    if args.output:
        args.output.write_text(json.dumps(results, indent=2))
        print(f"\n# wrote {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
