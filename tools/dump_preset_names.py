"""Dump the GX-10/GX-100 patch name catalogue at 0x50000000.

Reads the 38 contiguous 256-byte chunks from `0x50000000` to `0x50002500`
and decodes them as 16-character ASCII patch names. Optionally also
pulls the user-memory names from `0x20000000 + N * 0x60000` to produce
a combined listing of all user-visible patches.

Background: `docs/protocol.md` §3.5. The 300-slot catalogue is read-only
and shared across both devices. Per-device totals (see
`docs/firmware_versions.md` "Per-device patch totals"):

  * GX-10:  297 usable = 198 user (66 banks × 3) + 99 preset (33 banks × 3)
  * GX-100: 300 usable = 200 user (50 banks × 4) + 100 preset (25 banks × 4)

Use --user-count to cap user-memory iteration appropriately for your
device. The default (198) matches the GX-10's user count; pass 200
for a GX-100.

Usage:
    python tools/dump_preset_names.py                      # catalogue only, table
    python tools/dump_preset_names.py --format json        # catalogue only, JSON
    python tools/dump_preset_names.py --format csv         # catalogue only, CSV
    python tools/dump_preset_names.py --include-user       # also dump user memories
    python tools/dump_preset_names.py --user-count 200     # GX-100
    python tools/dump_preset_names.py --out names.json --format json --include-user
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import GX10Session


CATALOGUE_BASE   = 0x50000000
CATALOGUE_END    = 0x50002500   # inclusive last chunk start; size of last chunk is 0x40
CHUNK_STRIDE     = 0x100
LAST_CHUNK_SIZE  = 0x40         # all earlier chunks are full 0x100; last is short
FULL_CHUNK_SIZE  = 0x100
NAME_LEN         = 16

USER_MEM_BASE    = 0x20000000
USER_MEM_STRIDE  = 0x60000      # per chart


def fetch_preset_catalogue(sess) -> bytes:
    """Sequential 38-chunk read from 0x50000000..0x50002500 inclusive.
    Returns the concatenated payload (9536 bytes on a healthy unit)."""
    buf = bytearray()
    addr = CATALOGUE_BASE
    while addr <= CATALOGUE_END:
        size = LAST_CHUNK_SIZE if addr == CATALOGUE_END else FULL_CHUNK_SIZE
        payload = sess.request(addr, size, timeout=1.5)
        if payload is None:
            raise RuntimeError(f"no reply at 0x{addr:08X} size=0x{size:X}")
        buf.extend(payload)
        addr += CHUNK_STRIDE
    return bytes(buf)


def decode_names(blob: bytes, base_addr: int):
    """Slice `blob` into 16-byte name slots and decode each as ASCII.
    Returns a list of dicts {index, address, name, empty}."""
    out = []
    for i in range(0, len(blob), NAME_LEN):
        chunk = blob[i:i + NAME_LEN]
        addr = base_addr + i
        # All 0x00 → empty slot; printable ASCII → name (rstripped)
        empty = all(b == 0 for b in chunk)
        try:
            name = chunk.decode("ascii").rstrip(" \x00")
        except UnicodeDecodeError:
            # Fall back to latin-1 if a non-ASCII byte slips in
            name = chunk.decode("latin-1").rstrip(" \x00")
        out.append({
            "index":   i // NAME_LEN,
            "address": f"0x{addr:08X}",
            "name":    name,
            "empty":   empty,
        })
    return out


def fetch_user_memory_names(sess, count: int = 198):
    """Read user-memory names one-by-one from 0x20000000 + N*0x60000.

    Each user memory's first 16 bytes is the name field (per chart
    MemoryCommon). Default count = 198 (GX-10 user count, 66 banks × 3).
    For GX-100 pass count=200 (BTS v1.0.2 treats only 198 as writable
    on fw 1.05). See `docs/firmware_versions.md` for the canonical
    per-device totals."""
    out = []
    for n in range(count):
        addr = USER_MEM_BASE + n * USER_MEM_STRIDE
        payload = sess.request(addr, NAME_LEN, timeout=1.0)
        if payload is None:
            out.append({
                "index":   n,
                "address": f"0x{addr:08X}",
                "name":    None,
                "empty":   True,
                "error":   "no reply",
            })
            continue
        try:
            name = payload.decode("ascii").rstrip(" \x00")
        except UnicodeDecodeError:
            name = payload.decode("latin-1").rstrip(" \x00")
        out.append({
            "index":   n,
            "address": f"0x{addr:08X}",
            "name":    name,
            "empty":   not name,
        })
    return out


def format_table(rows, kind: str):
    lines = [f"=== {kind} ({sum(1 for r in rows if not r['empty'])} non-empty / {len(rows)} slots) ==="]
    lines.append(f"{'idx':>4s}  {'address':<10s}  name")
    for r in rows:
        marker = "" if not r["empty"] else "  (empty)"
        name = r["name"] if r["name"] is not None else "(no reply)"
        lines.append(f"{r['index']:>4d}  {r['address']:<10s}  {name}{marker}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--format", choices=("table", "json", "csv"), default="table")
    ap.add_argument("--out", default=None, help="write to file; otherwise stdout")
    ap.add_argument("--include-user", action="store_true",
                    help="also pull user-memory names (slow: 200 separate RQ1s)")
    ap.add_argument("--user-count", type=int, default=198,
                    help="number of user memories to fetch (default 198 for GX-10; pass 200 for GX-100)")
    args = ap.parse_args()

    sess = GX10Session()

    print("Reading preset catalogue 0x50000000..0x50002500 …", file=sys.stderr)
    blob = fetch_preset_catalogue(sess)
    presets = decode_names(blob, CATALOGUE_BASE)

    users = []
    if args.include_user:
        print(f"Reading user-memory names (0x20000000..) ×{args.user_count} …", file=sys.stderr)
        users = fetch_user_memory_names(sess, args.user_count)

    if args.format == "table":
        text = format_table(presets, "PRESETS (0x50000000 catalogue)")
        if users:
            text += "\n\n" + format_table(users, "USER MEMORIES (0x20000000 + N*0x60000)")
    elif args.format == "json":
        text = json.dumps({"presets": presets, "users": users}, indent=2, ensure_ascii=False)
    elif args.format == "csv":
        import csv, io
        sio = io.StringIO()
        w = csv.writer(sio)
        w.writerow(["bank", "index", "address", "name", "empty"])
        for r in presets:
            w.writerow(["preset", r["index"], r["address"], r["name"], r["empty"]])
        for r in users:
            w.writerow(["user", r["index"], r["address"], r["name"], r["empty"]])
        text = sio.getvalue()

    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)

    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == "__main__":
    main()
