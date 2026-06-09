#!/usr/bin/env python3
"""Probe U12-3's stored slot type bytes + chain order from the device.

Reads 20 slot type bytes (1 byte each) and the chain top + chain-next
linked list, then prints which slot indices are in the chain and what
fx type each chain position resolves to.

Reuses tools/midi_io.py for the actual MIDI I/O.

Usage:
    python3 tools/probe_u12_3_slots.py [--port-substring "GX-10"]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from midi_io import GxMidi, parse_dt1_payload  # noqa: E402


# U12-3 is V = (12-1)*3 + (3-1) = 35
SLOT_V = 35

# userMemoryAddress(n) — matches LiveDeviceLink.swift:1781.
def user_memory_address(n: int) -> int:
    base_lin = 0x4000000
    stride_lin = 0x18000
    lin = base_lin + n * stride_lin
    a = (lin >> 21) & 0x7F
    b = (lin >> 14) & 0x7F
    c = (lin >> 7)  & 0x7F
    d = lin & 0x7F
    return (a << 24) | (b << 16) | (c << 8) | d


SLOT_BASE   = 0x1100
SLOT_STRIDE = 0x200
SLOT_TYPE_OFF = 0x00
SLOT_ON_OFF   = 0x01
CHAIN_TOP_OFF = 0x0F0C
CHAIN_NEXT_OFF = 0x0F0D
CHAIN_NEXT_COUNT = 49


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port-substring", default="GX-10",
                    help="MIDI port name substring (default: GX-10)")
    ap.add_argument("--timeout", type=float, default=1.5)
    args = ap.parse_args()

    type_names = json.load(open(Path(__file__).resolve().parents[1] / "catalogs" / "fx_type_enum.json"))

    base = user_memory_address(SLOT_V)
    print(f"# U12-3 (V={SLOT_V}) body lives at 0x{base:08X}")

    g = GxMidi(port_substr=args.port_substring)
    try:
        chain_top_addr  = base + CHAIN_TOP_OFF
        chain_next_addr = base + CHAIN_NEXT_OFF
        top_msg = g.rq1(chain_top_addr, 1, timeout=args.timeout)
        next_msg = g.rq1(chain_next_addr, CHAIN_NEXT_COUNT, timeout=args.timeout)
        if top_msg is None or next_msg is None:
            print("ERROR: chain read timed out")
            return 2
        top_byte = parse_dt1_payload(top_msg)[0]
        next_bytes = list(parse_dt1_payload(next_msg)[:CHAIN_NEXT_COUNT])

        order = []
        if top_byte != 0:
            cursor = top_byte - 1
            visited = set()
            hops = 0
            while cursor is not None and hops < 50 and cursor not in visited:
                order.append(cursor)
                visited.add(cursor)
                nb = next_bytes[cursor]
                cursor = nb - 1 if nb != 0 else None
                hops += 1

        print(f"# chain top byte = {top_byte} (slot+1; 0 = empty)")
        print(f"# chain order (slot indices): {order}")

        # Read each slot's type + on byte.
        print()
        print(f"{'slot':>4} | {'in chain?':>10} | type | on  | type_name")
        print('-' * 65)
        for n in range(20):
            addr_type = base + SLOT_BASE + n * SLOT_STRIDE
            msg = g.rq1(addr_type, 2, timeout=args.timeout)
            if msg is None:
                print(f"{n:>4} | {'?':>10} | TIMEOUT")
                continue
            payload = parse_dt1_payload(msg)
            tb = payload[0]
            ob = payload[1]
            name = type_names.get(str(tb), f"<unknown {tb}>")
            in_chain = "YES (#{})".format(order.index(n)) if n in order else "."
            print(f"{n:>4} | {in_chain:>10} | {tb:>4} | {ob:>3} | {name}")
    finally:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
