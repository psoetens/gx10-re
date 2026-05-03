"""
Stitch all DT1 replies in a JSONL log into a single {address: byte} snapshot.
Also report contiguous regions and gaps so we know what we have.

Usage:
    python jsonl_to_snapshot.py captures/livepatch_deep.jsonl --out snapshots/u10-1_init.json
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from patch_snapshot import parse_log_to_address_map, save_snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    addr_map = parse_log_to_address_map(Path(args.jsonl))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    save_snapshot(addr_map, Path(args.out))
    print(f"snapshot: {len(addr_map)} bytes -> {args.out}")

    if not addr_map:
        return
    sorted_addrs = sorted(addr_map)
    runs = []
    run_start = sorted_addrs[0]
    prev = run_start
    for a in sorted_addrs[1:]:
        if a != prev + 1:
            runs.append((run_start, prev))
            run_start = a
        prev = a
    runs.append((run_start, prev))
    print(f"contiguous runs: {len(runs)}")
    for r in runs[:50]:
        size = r[1] - r[0] + 1
        print(f"  {r[0]:08X}..{r[1]:08X}  ({size} bytes)")
    if len(runs) > 50:
        print(f"  ... +{len(runs) - 50} more")


if __name__ == "__main__":
    main()
