"""
Cycle through every preset, capture the live patch buffer for each, save the
snapshots to a directory. Then we can diff across patches to discover which
bytes carry which kind of data.

Patch-select command (discovered): DT1 to 0x00000000 with 5 bytes encoding
the patch index. Empirically, writing b"\\x00\\x00\\x00\\x00\\x00" loaded
NATURAL AMP HB (preset index 0), and the live state's byte map is then
read at 0x00000000 as e.g. `00 00 0C 08 03` for GX DUAL DRIVE
(bank 12, position 3 — preset 99). Confirmation of the encoding is part
of this script's job.

For each preset index 0..295:
  - send DT1 0x00000000 = (encoding of N)
  - rapid-probe the live patch
  - save snapshot

Total time at ~3 seconds per preset: ~15 minutes for all presets.

Usage:
    python snapshot_all_presets.py --start 0 --count 296 --out snapshots/presets/
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
from rapid_probe import plan_live_patch_deep
from patch_snapshot import parse_log_to_address_map, save_snapshot


def encode_patch_index_bank_pos(n: int) -> bytes:
    """Encode preset index N as 5 bytes for DT1 0x00000000.

    Hypothesis based on observation: bytes are (00, 00, bank, pad?, pos)
    where bank = N // 8, pos = N % 8. The 4th byte is sometimes 0x08 in
    captures but loading with 0x00 also seems to work; we use 0x00 for now
    and let the device adjust.
    """
    bank = n // 8
    pos = n % 8
    return bytes([0x00, 0x00, bank, 0x00, pos])


def snapshot_one(out, idx_in, log_path: Path, settle: float = 0.015,
                 listen_after: float = 1.5):
    sniffer = midi_sniff.Sniffer(idx_in, log_path, "GX-10")
    sniffer.open()
    plan = plan_live_patch_deep()
    try:
        for addr, size in plan:
            out.send_sysex(midi_send.build_rq1(addr, size))
            time.sleep(settle)
        time.sleep(listen_after)
    finally:
        sniffer.close()
    return parse_log_to_address_map(log_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=296)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-jsonl", action="store_true",
                    help="keep per-patch jsonl logs for debugging")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    idx_in, _ = midi_sniff.find_port("GX-10")
    idx_out, _ = midi_send.find_output_port("GX-10")
    out = midi_send.MidiOut(idx_out)

    # announce editor
    out.send_sysex(midi_send.build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.3)

    try:
        for n in range(args.start, args.start + args.count):
            sel = encode_patch_index_bank_pos(n)
            out.send_sysex(midi_send.build_dt1(0x00000000, sel))
            time.sleep(0.4)
            log = out_dir / f"_p{n:03d}.jsonl"
            addr_map = snapshot_one(out, idx_in, log)
            snap_path = out_dir / f"p{n:03d}.json"
            save_snapshot(addr_map, snap_path)
            # patch name is always at 0x10000000-0x1000000F
            name_bytes = bytes(addr_map.get(0x10000000 + i, 0x20) for i in range(16))
            try:
                name = name_bytes.decode("ascii", errors="replace").strip()
            except Exception:
                name = "?"
            print(f"p{n:03d}  {name!r:32s}  {len(addr_map)} bytes")
            if not args.keep_jsonl:
                log.unlink(missing_ok=True)
    finally:
        out.close()


if __name__ == "__main__":
    main()
