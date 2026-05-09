"""Walk a JSONL capture (output of midi_sniff.py or pcap_to_jsonl.py),
filter DT1 events in the FxItem range, and print a per-address
timeline summary.

Use case: a BTS session where the user dragged in an effect and
swept every knob — this script pulls out every (timestamp, address,
display value) event so the BTS-UI order of knob turns can be
mapped to addresses.

Usage:
    python tools/extract_knob_addresses.py captures/bts_combo/all.jsonl
    python tools/extract_knob_addresses.py captures/bts_combo/all.jsonl --addr-low 0x10001100 --addr-high 0x10001300
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def decode_4nib(payload):
    if len(payload) < 4:
        return None
    return ((payload[0] & 0x0F) << 12) | ((payload[1] & 0x0F) << 8) \
         | ((payload[2] & 0x0F) << 4) |  (payload[3] & 0x0F)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--addr-low",  default="0x10000000")
    ap.add_argument("--addr-high", default="0x10004000")
    ap.add_argument("--max-events-per-addr", type=int, default=10,
                    help="Show at most N events per address (first/middle/last).")
    args = ap.parse_args()

    addr_low = int(args.addr_low, 16)
    addr_high = int(args.addr_high, 16)

    by_addr = defaultdict(list)        # addr -> [(t, display)]
    type_writes = []                   # (t, addr, type_byte) — track effect drops

    with open(args.jsonl) as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            hex_str = ev.get("hex") or ev.get("sysex") or ""
            if not hex_str:
                continue
            raw = bytes.fromhex(hex_str.replace(" ", ""))
            # Filter Roland DT1
            if (len(raw) < 14 or raw[0] != 0xF0 or raw[-1] != 0xF7
                    or raw[1:8] != b"\x41\x10\x00\x00\x00\x00\x0B"
                    or raw[8] != 0x12):
                continue
            addr = (raw[9] << 24) | (raw[10] << 16) | (raw[11] << 8) | raw[12]
            payload = raw[13:-2]
            if not (addr_low <= addr < addr_high):
                continue
            t = ev.get("t") or ev.get("ts") or 0.0

            # Track TYPE-byte writes (1-byte payloads at FxItem +0x00)
            offset_in_fxitem = (addr - 0x10001100) % 0x200
            if 0x10001100 <= addr < 0x10004000 and offset_in_fxitem == 0 and len(payload) == 1:
                type_writes.append((t, addr, payload[0]))

            # 4-byte cells: store as display value
            if len(payload) == 4:
                disp = decode_4nib(payload) - 0x8000
                by_addr[addr].append((t, disp, payload.hex(" ")))
            else:
                by_addr[addr].append((t, None, payload.hex(" ")))

    # Print TYPE writes timeline first (effect drops mark new contexts)
    print("# TYPE-byte writes (effect-drop events)")
    print()
    if not type_writes:
        print("(none — no TYPE byte writes seen)")
    else:
        for t, addr, tb in type_writes:
            slot = (addr - 0x10001100) // 0x200
            print(f"  t={t:8.3f}  FxItem {slot:2d}  TYPE = 0x{tb:02X} ({tb})")
    print()

    # Per-address summary
    print("# Per-address knob events")
    print()
    print("| Address    | Slot | Off  | Events | First t  | Last t   | Display range | Sample values |")
    print("|------------|-----:|------|-------:|---------:|---------:|---------------|---------------|")
    for addr in sorted(by_addr):
        evs = by_addr[addr]
        slot = (addr - 0x10001100) // 0x200
        off = (addr - 0x10001100) - slot * 0x200
        disps = [d for _, d, _ in evs if d is not None]
        if disps:
            d_lo, d_hi = min(disps), max(disps)
            d_range = f"{d_lo}..{d_hi}"
        else:
            d_range = "-"
        # Sample: first, middle, last
        idxs = sorted({0, len(evs) // 2, len(evs) - 1})
        sample = ", ".join(
            f"{evs[i][1]}@{evs[i][0]:.1f}" if evs[i][1] is not None
            else f"{evs[i][2][:20]}@{evs[i][0]:.1f}"
            for i in idxs
        )
        first_t = evs[0][0]
        last_t = evs[-1][0]
        print(f"| 0x{addr:08X} | {slot:4d} | 0x{off:02X} | {len(evs):6d} | "
              f"{first_t:8.3f} | {last_t:8.3f} | {d_range:>13} | {sample} |")

    # Per-address detail (timeline)
    print()
    print("# Per-address timeline detail")
    print()
    for addr in sorted(by_addr):
        evs = by_addr[addr]
        slot = (addr - 0x10001100) // 0x200
        off = (addr - 0x10001100) - slot * 0x200
        print(f"## 0x{addr:08X} (FxItem {slot}, offset 0x{off:02X}) — {len(evs)} events")
        for i, (t, d, h) in enumerate(evs[: args.max_events_per_addr]):
            d_str = f"display={d}" if d is not None else f"({h})"
            print(f"  +{t:8.3f}  {d_str}")
        if len(evs) > args.max_events_per_addr:
            print(f"  ... ({len(evs) - args.max_events_per_addr} more events)")
        print()


if __name__ == "__main__":
    main()
