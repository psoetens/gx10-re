"""Probe every USER memory's name field on the GX-10 by sending RQ1 and
reading the 16-byte ASCII Memory Name from MemoryCommon offset 0x00..0x0F.

Per the chart's address-block map:
  - Memory N base: 0x20000000 + (N - 1) * 0x60000  for N in 1..200
  - MemoryCommon starts at offset 0 of each memory
  - Memory Name1..16 at offsets 0x00..0x0F (one ASCII byte each, 32..126)

Produces 200 user names. Preset memories (memory # 200..299) are not in
the documented address map and need a separate flow (load via PC# +
read temporary buffer).

Usage:
  Close BTS first (it holds the MIDI port open).
  python tools/probe_user_memory_names.py --out captures/user_memory_names.json

  # Probe a subset:
  python tools/probe_user_memory_names.py --start 0 --end 49
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff


MEMORY_BASE = 0x20000000
MEMORY_STRIDE_LINEAR = 6 * 128 * 128  # 6 in byte-b in 7-bit-per-byte space
NAME_LEN = 16


def memory_addr(n: int) -> int:
    """Compute chart-hex absolute address of user memory N (0..199)."""
    base_a = (MEMORY_BASE >> 24) & 0xFF
    base_b = (MEMORY_BASE >> 16) & 0xFF
    base_c = (MEMORY_BASE >> 8) & 0xFF
    base_d = MEMORY_BASE & 0xFF
    base_lin = ((base_a & 0x7F) << 21) | ((base_b & 0x7F) << 14) | \
               ((base_c & 0x7F) << 7) | (base_d & 0x7F)
    addr_lin = base_lin + n * MEMORY_STRIDE_LINEAR
    a = (addr_lin >> 21) & 0x7F
    b = (addr_lin >> 14) & 0x7F
    c = (addr_lin >> 7) & 0x7F
    d = addr_lin & 0x7F
    return (a << 24) | (b << 16) | (c << 8) | d


def parse_dt1(raw: bytes):
    """Return (addr, payload) or None if not a valid DT1."""
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14:
        return None
    if raw[8] != 0x12:
        return None
    addr = int.from_bytes(raw[9:13], "big")
    payload = bytes(raw[13:-2])
    return addr, payload


class Collector:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def on_sysex(self, raw: bytes):
        with self.lock:
            self.events.append(raw)

    def find_dt1(self, expected_addr: int, since_idx: int):
        with self.lock:
            for i in range(since_idx, len(self.events)):
                parsed = parse_dt1(self.events[i])
                if parsed and parsed[0] == expected_addr:
                    return (i, parsed[0], parsed[1])
        return None


def setup_sniffer(port_substr: str, collector: Collector):
    idx, name = midi_sniff.find_port(port_substr)
    if idx is None:
        raise RuntimeError(f"No MIDI input port matching '{port_substr}'")
    s = midi_sniff.Sniffer(idx, Path("__nul__.jsonl"), name)

    def emit(obj):
        if obj.get("kind") == "sysex":
            try:
                raw = bytes.fromhex(obj["hex"])
                collector.on_sysex(raw)
            except Exception:
                pass
    s._emit = emit
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="GX-10")
    ap.add_argument("--out", default="captures/user_memory_names.json")
    ap.add_argument("--start", type=int, default=0, help="first memory # (0..199)")
    ap.add_argument("--end", type=int, default=199, help="last memory # inclusive")
    ap.add_argument("--timeout", type=float, default=1.5)
    args = ap.parse_args()

    print(f"Opening MIDI input '{args.port}'...")
    coll = Collector()
    sniffer = setup_sniffer(args.port, coll)
    sniffer.open()

    print(f"Opening MIDI output '{args.port}'...")
    out_idx, out_name = find_output_port(args.port)
    if out_idx is None:
        print(f"ERROR: no MIDI output port matching '{args.port}'")
        sys.exit(2)
    out = MidiOut(out_idx)
    print(f"  output: {out_name}")
    time.sleep(0.5)
    require_alive_raw(out, coll.events, coll.lock)

    names = {}
    try:
        for n in range(args.start, args.end + 1):
            addr = memory_addr(n)
            mark = len(coll.events)
            req = build_rq1(addr, NAME_LEN)
            out.send_sysex(req)
            t0 = time.time()
            found = None
            while time.time() - t0 < args.timeout:
                found = coll.find_dt1(addr, mark)
                if found:
                    break
                time.sleep(0.02)
            if found is None:
                print(f"  mem {n:3d}: TIMEOUT (addr=0x{addr:08X})")
                names[str(n)] = {"addr": f"{addr:08X}", "name": None,
                                  "error": "timeout"}
                continue
            _, _, payload = found
            ascii_name = "".join(chr(b) if 32 <= b <= 126 else "?"
                                  for b in payload[:NAME_LEN])
            print(f"  mem {n:3d}: 0x{addr:08X} '{ascii_name}'")
            names[str(n)] = {"addr": f"{addr:08X}", "name": ascii_name}
    finally:
        sniffer.close()
        out.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(names, indent=2))
    print(f"\nWrote {out_path} ({len(names)} entries)")


if __name__ == "__main__":
    main()
