"""Read FxItem #0 and compare to a snapshot.bin.

Uses size=0x140 in the RQ1 (each byte ≤ 0x7F). Device replies with as
much as it has — empirically ~179 bytes.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import GX10Session
from device_id import require_alive


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--port", default="GX-10")
    args = ap.parse_args()
    snapshot = Path(args.snapshot).read_bytes()

    sess = GX10Session(port_substr=args.port)
    require_alive(sess)
    found = sess.request(0x10001100, 0x140, timeout=1.5)
    if found is None:
        print("ERROR: no reply"); return 2
    print(f"current FxItem #0 ({len(found)} bytes): {found[:32].hex()}...")
    print(f"snapshot     ({len(snapshot)} bytes): {snapshot[:32].hex()}...")
    if found == snapshot:
        print("EXACT MATCH ✓")
    else:
        # Show byte-by-byte diff
        diffs = []
        for i in range(min(len(found), len(snapshot))):
            if found[i] != snapshot[i]:
                diffs.append((i, snapshot[i], found[i]))
        print(f"DIFFERS at {len(diffs)} of {min(len(found), len(snapshot))} bytes")
        for i, s, c in diffs[:20]:
            print(f"  off=0x{i:02X}: snapshot=0x{s:02X}  current=0x{c:02X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
