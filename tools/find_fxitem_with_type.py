"""Scan all 20 FxItem indices for one with a given TYPE byte.

Reads the byte at 0x10001N00 + (N * 0x200) for N=0..19 and reports
which slots have which TYPE. Useful when BTS's chain panel maps
chain-slot positions to non-obvious FxItem indices.
"""
from __future__ import annotations
import argparse
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
from device_id import require_alive_raw


FXITEM0_BASE = 0x10001100
FXITEM_STRIDE = 0x200


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", type=lambda x: int(x, 0), default=None,
                    help="if set, print only FxItems with this TYPE byte")
    args = ap.parse_args()

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = Path("captures/_probe/find_fxitem.jsonl")
    sn_log.parent.mkdir(parents=True, exist_ok=True)
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    q: "queue.Queue[bytes]" = queue.Queue()
    id_events: list = []
    def silent(o):
        import json as _j
        o.setdefault("t", round(sniffer._ts(), 6))
        o.setdefault("label", sniffer.label)
        sniffer.log_fp.write(_j.dumps(o, ensure_ascii=False) + "\n")
        if o.get("kind") == "sysex":
            try:
                raw = bytes.fromhex(o["hex"])
                q.put(raw); id_events.append(raw)
            except: pass
    sniffer._emit = silent
    sniffer.open()
    time.sleep(0.3)
    require_alive_raw(out, id_events)

    def drain(secs=0.05):
        time.sleep(secs); msgs = []
        while not q.empty():
            try: msgs.append(q.get_nowait())
            except: break
        return msgs

    def rq1(addr, size, timeout=0.8):
        drain(0)
        out.send_sysex(midi_send.build_rq1(addr, size))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in drain(0.02):
                p = parse_dt1(m)
                if p and p[0] == addr: return p[1]
        return None

    print(f"{'FxItem':>6}  {'addr':>10}  TYPE")
    matches = []
    try:
        for n in range(20):
            addr = FXITEM0_BASE + n * FXITEM_STRIDE
            # Roland 7-bit-per-byte address check
            addr_bytes = addr.to_bytes(4, "big")
            if any(b > 0x7F for b in addr_bytes):
                print(f"  #{n:<2d}  0x{addr:08X}  (un-encodable)")
                continue
            block = rq1(addr, 0x10, timeout=0.5)
            if block is None:
                print(f"  #{n:<2d}  0x{addr:08X}  (no reply)")
                continue
            type_byte = block[0]
            on_off = block[1] if len(block) > 1 else None
            print(f"  #{n:<2d}  0x{addr:08X}  TYPE=0x{type_byte:02X}  on/off={on_off}")
            if args.type is not None and type_byte == args.type:
                matches.append((n, addr))
    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass

    if args.type is not None:
        if matches:
            print(f"\nFxItems with TYPE 0x{args.type:02X}:")
            for n, addr in matches:
                print(f"  #{n:<2d}  base=0x{addr:08X}")
        else:
            print(f"\nNo FxItem has TYPE 0x{args.type:02X}.")


if __name__ == "__main__":
    sys.exit(main())
