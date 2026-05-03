"""
Standalone helper: snapshot a region, do something, snapshot again, diff.
Used to find which byte address corresponds to a specific knob.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
from rapid_probe import step_7bit


def snapshot_regions(out, regions):
    """regions: list of (start, end_excl) tuples"""
    log = Path("captures") / f"_fka_{int(time.time()*1000)%1000000:06d}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    idx_in, _ = midi_sniff.find_port("GX-10")
    sniffer = midi_sniff.Sniffer(idx_in, log, "GX-10")
    sniffer.open()
    try:
        for start, end in regions:
            for addr in step_7bit(start, end, 0x40):
                out.send_sysex(midi_send.build_rq1(addr, 0x40))
                time.sleep(0.015)
        time.sleep(0.6)
    finally:
        sniffer.close()
    addr_map = {}
    with log.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex":
                continue
            raw = bytes.fromhex(ev["hex"])
            if (len(raw) < 16 or raw[0] != 0xF0 or raw[-1] != 0xF7
                    or raw[8] != 0x12):
                continue
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            for i, b in enumerate(payload):
                addr_map[addr + i] = b
    log.unlink(missing_ok=True)
    return addr_map


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-before", required=True)
    ap.add_argument("--out-after", required=True)
    ap.add_argument("--mode", choices=["before", "after", "both", "diff"], required=True)
    ap.add_argument("--regions", nargs="+", default=["10000200:10000B80", "10001100:10001200"])
    args = ap.parse_args()

    region_pairs = []
    for r in args.regions:
        a, b = r.split(":")
        region_pairs.append((int(a, 16), int(b, 16)))

    if args.mode in ("before", "both"):
        idx, _ = midi_send.find_output_port("GX-10")
        out = midi_send.MidiOut(idx)
        out.send_sysex(midi_send.build_dt1(0x7F000001, b"\x01"))
        time.sleep(0.1)
        m = snapshot_regions(out, region_pairs)
        out.close()
        Path(args.out_before).write_text(json.dumps({f"{a:08X}": b for a, b in sorted(m.items())}, indent=2))
        print(f"before: {len(m)} bytes -> {args.out_before}")

    if args.mode == "both":
        input("press ENTER after manipulating Tone Studio knob...")

    if args.mode in ("after", "both"):
        idx, _ = midi_send.find_output_port("GX-10")
        out = midi_send.MidiOut(idx)
        out.send_sysex(midi_send.build_dt1(0x7F000001, b"\x01"))
        time.sleep(0.1)
        m = snapshot_regions(out, region_pairs)
        out.close()
        Path(args.out_after).write_text(json.dumps({f"{a:08X}": b for a, b in sorted(m.items())}, indent=2))
        print(f"after: {len(m)} bytes -> {args.out_after}")

    if args.mode == "diff":
        a = json.loads(Path(args.out_before).read_text())
        b = json.loads(Path(args.out_after).read_text())
        ai = {int(k, 16): v for k, v in a.items()}
        bi = {int(k, 16): v for k, v in b.items()}
        keys = set(ai) | set(bi)
        print(f"diffs:")
        for k in sorted(keys):
            va, vb = ai.get(k), bi.get(k)
            if va != vb:
                print(f"  {k:08X}  {('--' if va is None else f'{va:02X}')} -> {('--' if vb is None else f'{vb:02X}')}")


if __name__ == "__main__":
    main()
