"""
Pretty-print a snapshot file: hex + ASCII columns, with run boundaries.
Useful for finding patch names, type IDs, and structure by eye.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--start", type=lambda x: int(x, 16), default=None)
    ap.add_argument("--end", type=lambda x: int(x, 16), default=None)
    args = ap.parse_args()

    raw = json.loads(Path(args.snapshot).read_text())
    m = {int(a, 16): b for a, b in raw.items()}

    if not m:
        print("(empty)")
        return

    sorted_addrs = sorted(m)
    if args.start is not None:
        sorted_addrs = [a for a in sorted_addrs if a >= args.start]
    if args.end is not None:
        sorted_addrs = [a for a in sorted_addrs if a < args.end]
    if not sorted_addrs:
        print("(no bytes in selected range)")
        return

    # Group into 16-byte rows aligned to 16-byte boundaries
    base = sorted_addrs[0] & ~0xF
    addr_set = set(sorted_addrs)
    last_addr = max(sorted_addrs)
    cur = base
    while cur <= last_addr:
        row = []
        ascii_part = []
        for i in range(16):
            if (cur + i) in addr_set:
                b = m[cur + i]
                row.append(f"{b:02X}")
                ascii_part.append(chr(b) if 0x20 <= b < 0x7F else ".")
            else:
                row.append("--")
                ascii_part.append(" ")
        # Only print rows that have at least one mapped byte
        if any(c != "--" for c in row):
            row_hex = " ".join(row[:8]) + "  " + " ".join(row[8:])
            print(f"{cur:08X}  {row_hex}  |{''.join(ascii_part)}|")
        cur += 16


if __name__ == "__main__":
    main()
