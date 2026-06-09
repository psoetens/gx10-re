#!/usr/bin/env python3
"""Validate the GX-10's RQ1 read behaviour for user-memory slots.

Tests:
  1. Bulk read of a slot's 16-KiB body using gxnarly's BTS region layout.
  2. Repeat the same bulk read — compare for stability (same bytes both times?).
  3. Per-byte read of every offset in the header (0x00..0x80) and a
     sample of slot/assign areas, with no chunking. Compare against the
     bulk-read result for those offsets.

Outputs a clear report of:
  - Bytes that the device CONSISTENTLY refuses to read (per-byte
    request times out)
  - Bytes that the bulk read returns but per-byte requests don't
    (suggests chunking artefacts; address space is fine)
  - Bytes that differ between the two bulk reads (read instability)

Usage:
    python3 tools/probe_read_validation.py --v 33
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from midi_io import GxMidi, parse_dt1_payload  # noqa: E402


def user_memory_address(n: int) -> int:
    base_lin = 0x4000000
    stride_lin = 0x18000
    lin = base_lin + n * stride_lin
    a = (lin >> 21) & 0x7F
    b = (lin >> 14) & 0x7F
    c = (lin >> 7)  & 0x7F
    d = lin & 0x7F
    return (a << 24) | (b << 16) | (c << 8) | d


def bts_patch_regions():
    """Mirror of LiveDeviceLink.btsPatchRegions()."""
    regions = [
        (0x0000, 128),
        (0x0100, 1),
        (0x0140, 28),
    ]
    for pair in range(10):
        row_base = 0x0200 + pair * 0x100
        regions.append((row_base, 45))
        regions.append((row_base + 0x40, 45))
    regions.append((0x0F00, 62))
    for slot in range(20):
        slot_base = 0x1100 + slot * 0x200
        regions.append((slot_base, 131))
        regions.append((slot_base + 0x103, 48))
    return regions


def bulk_read(g, base, timeout=2.0, settle=0.02):
    """Read the slot body using gxnarly's BTS region layout, chunking
    requests at ≤0x40 bytes (device silently drops larger RQ1s per
    LiveDeviceLink performBulkReadCritical comment §3.1.2)."""
    buf = bytearray(0x4000)
    regions = bts_patch_regions()
    fails = []
    for i, (off, size) in enumerate(regions):
        # Chunk each region at 0x40 max.
        sub_off = 0
        any_data = False
        while sub_off < size:
            this = min(0x40, size - sub_off)
            time.sleep(settle)
            msg = g.rq1(base + off + sub_off, this, timeout=timeout)
            if msg is None:
                sub_off += this
                continue
            payload = parse_dt1_payload(msg)[:this]
            if payload:
                any_data = True
            for j, b in enumerate(payload):
                buf[off + sub_off + j] = b
            sub_off += this
        if not any_data:
            fails.append((i, off, size))
    return buf, fails


def per_byte_read(g, base, offsets, timeout=1.5, settle=0.03):
    """Read each offset as a 1-byte RQ1. Returns {offset: byte_or_None}."""
    result = {}
    for off in offsets:
        time.sleep(settle)
        msg = g.rq1(base + off, 1, timeout=timeout)
        if msg is None:
            result[off] = None
        else:
            result[off] = parse_dt1_payload(msg)[0]
    return result


def diff_buffers(a, b, label_a="A", label_b="B"):
    diffs = []
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            diffs.append((i, a[i], b[i]))
    return diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v", type=int, default=33)
    ap.add_argument("--port", default="GX-10")
    args = ap.parse_args()

    base = user_memory_address(args.v)
    print(f"# V={args.v} body lives at 0x{base:08X}")

    g = GxMidi(port_substr=args.port)

    print()
    print("=== Bulk read 1 ===")
    buf1, fails1 = bulk_read(g, base)
    nonzero1 = sum(1 for b in buf1 if b != 0)
    print(f"non-zero bytes: {nonzero1}, failed regions: {len(fails1)}")
    for i, off, size in fails1[:5]:
        print(f"  fail #{i}: offset 0x{off:04X} size={size}")
    if len(fails1) > 5:
        print(f"  ...and {len(fails1) - 5} more")

    print()
    print("=== Bulk read 2 (stability check) ===")
    buf2, fails2 = bulk_read(g, base)
    nonzero2 = sum(1 for b in buf2 if b != 0)
    print(f"non-zero bytes: {nonzero2}, failed regions: {len(fails2)}")

    print()
    print("=== Diff bulk1 vs bulk2 ===")
    diffs = diff_buffers(buf1, buf2)
    print(f"differing bytes: {len(diffs)}")
    for off, b1, b2 in diffs[:20]:
        print(f"  0x{off:04X}: {b1} vs {b2}")
    if len(diffs) > 20:
        print(f"  ...and {len(diffs) - 20} more")

    print()
    print("=== Per-byte read of header (0x00..0x7F) ===")
    pb = per_byte_read(g, base, list(range(0x80)))
    timeouts = [off for off, b in pb.items() if b is None]
    print(f"per-byte timeouts: {len(timeouts)} / 128")
    if timeouts:
        print(f"  offsets:", ", ".join(f"0x{o:02X}" for o in timeouts[:30]))
        if len(timeouts) > 30:
            print(f"  ...and {len(timeouts) - 30} more")

    print()
    print("=== Bulk-vs-per-byte diff (header, only where per-byte succeeded) ===")
    pb_diffs = []
    for off, b in pb.items():
        if b is None: continue
        if buf1[off] != b:
            pb_diffs.append((off, buf1[off], b))
    print(f"differing bytes: {len(pb_diffs)}")
    for off, b1, b_single in pb_diffs[:20]:
        print(f"  0x{off:04X}: bulk={b1} per-byte={b_single}")


if __name__ == "__main__":
    sys.exit(main() or 0)
