"""
Snapshot the current live patch (and optionally other regions) into a flat
{address: byte} map, save as JSON. The diff between two snapshots reveals
exactly which bytes changed when the user (or we) changed something — the
core technique for mapping parameter addresses.

Usage:
    python patch_snapshot.py --out snap_before.json
    # ... change something in Tone Studio ...
    python patch_snapshot.py --out snap_after.json
    python patch_snapshot.py --diff snap_before.json snap_after.json
"""
import argparse
import ctypes
import json
import sys
import time
from pathlib import Path

# Reuse our existing primitives
sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


REGIONS = [
    # (label, start_addr, end_addr_exclusive, chunk_size)
    ("live_low",  0x10000000, 0x10001000, 0x40),
    ("live_chain", 0x10001000, 0x10004000, 0x40),
    ("system",    0x7F000000, 0x7F000800, 0x40),
]

REGION_BY_NAME = {r[0]: r for r in REGIONS}


def snapshot(regions, settle_per_chunk: float = 0.04, listen_seconds: float = 1.0,
             tmp_log: Path = None):
    """Issue many small RQ1s, listen to the device's replies, return {addr: byte}."""
    idx_in, name_in = midi_sniff.find_port("GX-10")
    idx_out, _ = midi_send.find_output_port("GX-10")
    if idx_in is None or idx_out is None:
        raise RuntimeError("GX-10 MIDI ports not found")

    if tmp_log is None:
        tmp_log = Path("captures") / f"_snap_{int(time.time())}.jsonl"
    tmp_log.parent.mkdir(parents=True, exist_ok=True)

    sniffer = midi_sniff.Sniffer(idx_in, tmp_log, name_in)
    sniffer.open()
    out = midi_send.MidiOut(idx_out)
    try:
        for label, start, end, step in regions:
            sniffer.set_label(f"snapshot region {label}")
            for addr in range(start, end, step):
                out.send_sysex(midi_send.build_rq1(addr, step))
                time.sleep(settle_per_chunk)
        # drain
        time.sleep(listen_seconds)
    finally:
        out.close()
        sniffer.close()

    # Parse the log we just wrote
    return parse_log_to_address_map(tmp_log)


def parse_log_to_address_map(log_path: Path):
    """Read JSONL, return {addr_int: byte_int} from all DT1 replies."""
    addr_map = {}
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex":
                continue
            raw = bytes.fromhex(ev["hex"])
            # Validate Roland GX-10 DT1
            if (len(raw) < 16 or raw[0] != 0xF0 or raw[-1] != 0xF7
                    or raw[1] != 0x41 or raw[3:8] != b"\x00\x00\x00\x00\x0B"
                    or raw[8] != 0x12):
                continue
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            for i, b in enumerate(payload):
                addr_map[addr + i] = b
    return addr_map


def save_snapshot(addr_map, path: Path):
    serial = {f"{a:08X}": b for a, b in sorted(addr_map.items())}
    path.write_text(json.dumps(serial, indent=2))


def load_snapshot(path: Path):
    raw = json.loads(path.read_text())
    return {int(a, 16): b for a, b in raw.items()}


def diff_snapshots(a, b):
    """Return list of (addr, before, after) tuples for differing bytes
    or bytes only present in one snapshot."""
    keys = set(a) | set(b)
    out = []
    for k in sorted(keys):
        va = a.get(k)
        vb = b.get(k)
        if va != vb:
            out.append((k, va, vb))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write a fresh snapshot to this path")
    ap.add_argument("--regions", nargs="*", default=["live_low", "live_chain"],
                    help=f"regions to snapshot. Available: {list(REGION_BY_NAME)}")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="diff two snapshot files")
    ap.add_argument("--settle", type=float, default=0.04,
                    help="seconds to wait between successive RQ1 (default 0.04)")
    args = ap.parse_args()

    if args.diff:
        a = load_snapshot(Path(args.diff[0]))
        b = load_snapshot(Path(args.diff[1]))
        diffs = diff_snapshots(a, b)
        print(f"diffs: {len(diffs)}")
        for addr, before, after in diffs:
            bs = "--" if before is None else f"{before:02X}"
            af = "--" if after is None else f"{after:02X}"
            print(f"  {addr:08X}  {bs} -> {af}")
        return

    if args.out:
        regions = [REGION_BY_NAME[r] for r in args.regions]
        addr_map = snapshot(regions, settle_per_chunk=args.settle)
        save_snapshot(addr_map, Path(args.out))
        print(f"snapshot: {len(addr_map)} bytes -> {args.out}")


if __name__ == "__main__":
    main()
