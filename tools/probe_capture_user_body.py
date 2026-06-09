#!/usr/bin/env python3
"""Capture the full 16-KiB body of a user memory slot from the device,
emitting it in u10-1_init.json's format (hex-address → byte). Used to
re-capture the GX-10 INIT MEMORY pattern when the existing
snapshots/u10-1_init.json doesn't have a chain populated.

The capture follows BTS's region layout — a series of single-shot RQ1
reads at specific offsets, each request sized to overshoot the natural
record at that address (the device returns one DT1 of the natural
record size per RQ1; see `probe_bts_match.py` for the size table).
Total reads: 1 header + 1 misc + 1 knob block + 20 assign rows + 1
master/chain + 20×2 slot regions ≈ 60. NOTE: an alternative single-
shot `RQ1 size=0x4000` returns the same data in ~1 second — see
`probe_merge_sizes.py` and `reports/merge_read_findings.md`.

Usage:
    python3 tools/probe_capture_user_body.py --v 35 -o snapshot.json

V=35 == U12-3 on GX-10 (3 patches per bank). V values:
    user U01-1=0..U66-3=197, presets P01-1=200..P33-3=298.
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
    """Mirror of LiveDeviceLink.btsPatchRegions(), but with the 128-byte
    header split into 8x16-byte chunks (the device sometimes can't
    serve the full 128-byte region in one RQ1, which would leave
    knob-config + memory-MIDI bytes unset)."""
    regions = []
    # Header: 8 × 16-byte chunks covering 0x00..0x80
    # (name 0x00, ctl-function 0x10, ctl-mode 0x22, mem-midi 0x35,
    #  knob-fx-item 0x69, knob-setting 0x6D)
    for i in range(8):
        regions.append((i * 16, 16))
    regions.append((0x0100, 1))
    regions.append((0x0140, 28))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v", type=int, required=True, help="Memory V (0..197 user, 200..298 preset)")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output JSON path")
    ap.add_argument("--port", default="GX-10")
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--retry-timeout", type=float, default=3.0)
    args = ap.parse_args()

    base = user_memory_address(args.v)
    print(f"# V={args.v} body lives at device address 0x{base:08X}")

    buf = bytearray(0x4000)
    regions = bts_patch_regions()

    g = GxMidi(port_substr=args.port)
    failed = []
    for i, (off, size) in enumerate(regions):
        addr = base + off
        time.sleep(0.02)  # small inter-RQ1 delay; device drops back-to-back fast reads
        msg = g.rq1(addr, size, timeout=args.timeout)
        if msg is None:
            failed.append(i)
            continue
        payload = parse_dt1_payload(msg)
        for j, b in enumerate(payload[:size]):
            buf[off + j] = b
    print(f"# pass 1: {len(regions) - len(failed)}/{len(regions)} regions ok, {len(failed)} failed")

    # Retry failed regions with a longer timeout.
    if failed:
        still_failed = []
        for i in failed:
            off, size = regions[i]
            addr = base + off
            msg = g.rq1(addr, size, timeout=args.retry_timeout)
            if msg is None:
                still_failed.append(i)
                continue
            payload = parse_dt1_payload(msg)
            for j, b in enumerate(payload[:size]):
                buf[off + j] = b
        print(f"# retry: {len(failed) - len(still_failed)}/{len(failed)} recovered, {len(still_failed)} still failed")
        if still_failed:
            print(f"# WARN: still-failed regions: {still_failed}")

    # Emit u10-1_init.json compatible mapping: only NON-ZERO bytes,
    # keyed by absolute device address (uppercase hex, no 0x prefix).
    out = {}
    for off in range(0x4000):
        b = buf[off]
        if b != 0:
            addr = 0x10000000 + off  # snapshot uses base 0x10000000
            out[f"{addr:08X}"] = b
    args.output.write_text(json.dumps(out, indent=2))
    nonzero = sum(1 for v in out.values() if v != 0)
    print(f"# wrote {args.output} — {len(out)} non-zero bytes")

    # Quick sanity: chain TOP at 0x0F0C
    top = buf[0x0F0C]
    print(f"# chain TOP byte = {top} (slot+1; 0 = empty chain)")
    if top == 0:
        print("# WARN: chain is EMPTY in this snapshot")
    else:
        print(f"# first chain slot = {top - 1}")


if __name__ == "__main__":
    sys.exit(main() or 0)
