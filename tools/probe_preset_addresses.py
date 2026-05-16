"""Probe candidate preset-memory base addresses.

The chart explicitly maps user memories #0..199 to 0x20000000 stride
0x60000 (in 7-bit-per-byte arithmetic = 6*128*128 linear). Presets
(GX-10: #200..295, GX-100: #200..299) are NOT in the chart's address
table — only the Memory Number register acknowledges they exist.

Two candidate bases:
  A) 0x29300000 — direct continuation of the user-memory stride
                  (memory #200 = #199 + 0x60000 in 7-bit space)
  B) 0x30000000 — round-number guess

We RQ1 16 bytes (the name field) at each candidate and see whether
either replies. If exactly one does, that's the preset base.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff
from device_id import require_alive_raw


CANDIDATES = [
    ("continuation", 0x29300000),
    ("round-number", 0x30000000),
    # extra hunches:
    ("user-base+1G", 0x21000000),
    ("preset 0x40", 0x40000000),
    ("preset 0x70", 0x70000000),
]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def main():
    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        print("ERROR: no MIDI input"); sys.exit(2)
    s = midi_sniff.Sniffer(in_idx, Path("__nul__.jsonl"), in_name)

    def emit(o):
        if o.get("kind") == "sysex":
            try:
                with lock:
                    events.append(bytes.fromhex(o["hex"]))
            except Exception:
                pass
    s._emit = emit
    s.open()
    out_idx, _ = find_output_port("GX-10")
    out = MidiOut(out_idx)
    time.sleep(0.3)
    require_alive_raw(out, events, lock)

    print(f"Probing {len(CANDIDATES)} candidate preset bases...")
    for tag, addr in CANDIDATES:
        out.send_sysex(build_rq1(addr, 16))
        time.sleep(0.05)
    time.sleep(2.0)

    with lock:
        snap = list(events)

    by_addr = {}
    for e in snap:
        p = parse_dt1(e)
        if p:
            by_addr[p[0]] = p[1]

    print(f"\nGot {len(by_addr)} replies out of {len(CANDIDATES)} requests")
    print(f"All DT1 replies received (any address):")
    for addr, payload in by_addr.items():
        ascii_name = "".join(chr(b) if 32 <= b <= 126 else "?"
                              for b in payload[:16])
        print(f"  0x{addr:08X}  '{ascii_name}'  raw={payload.hex().upper()[:32]}")
    print(f"All raw events ({len(snap)}):")
    for e in snap:
        print(f"  {e.hex().upper()[:80]}")
    print(f"\n{'Tag':<14} {'Addr':<12} {'Reply?':<7} Payload")
    print("-" * 80)
    hits = []
    for tag, addr in CANDIDATES:
        payload = by_addr.get(addr)
        if payload:
            ascii_name = "".join(chr(b) if 32 <= b <= 126 else "?"
                                  for b in payload[:16])
            print(f"{tag:<14} 0x{addr:08X} YES     '{ascii_name}'  ({payload.hex().upper()})")
            hits.append((tag, addr, ascii_name))
        else:
            print(f"{tag:<14} 0x{addr:08X} no      -")

    print()
    if not hits:
        print("No candidate replied. Presets may live behind a load-into-buffer flow.")
    elif len(hits) == 1:
        tag, addr, name = hits[0]
        print(f"WINNER: {tag} (0x{addr:08X}) — preset #200 name = '{name}'")
        print("Use this base + stride 0x60000 in 7-bit arithmetic for #200..295.")
    else:
        print("Multiple candidates replied — need more info to disambiguate.")
        for h in hits:
            print(f"  {h[0]} 0x{h[1]:08X} '{h[2]}'")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
