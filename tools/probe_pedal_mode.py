"""Probe the GX-10/GX-100 pedal-mode bytes:

  0x00001034  SystemControl.ControlMode      (0..3)
  0x00001064  SystemControl.PairPdl1Function (0..3) — "Down & Up" pair mode
  0x00001065  SystemControl.PairPdl2Function (0..3) — "Up & Ctl1" pair mode

These addresses are documented in BTS's address_map.js but the chart's
prose section doesn't enumerate the value names. Run this in different
hardware modes (Manual / Up-Down / Bank-Num) to discover the mapping
empirically.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff


PROBES = [
    (0x00001034, "ControlMode"),
    (0x00001064, "PairPdl1Function (Down & Up)"),
    (0x00001065, "PairPdl2Function (Up & Ctl1)"),
    (0x10000154, "MemoryLed.ON_OFF_STATE byte 0 (a-nibble)"),  # for context
]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    addr = int.from_bytes(raw[9:13], "big")
    payload = bytes(raw[13:-2])
    return addr, payload


def main():
    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
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
    for addr, _ in PROBES:
        out.send_sysex(build_rq1(addr, 1))
        time.sleep(0.05)
    time.sleep(0.8)

    by_addr = {}
    with lock:
        for e in events:
            p = parse_dt1(e)
            if p:
                by_addr[p[0]] = p[1]

    # Also read the LED bitmap in full (8 bytes)
    out.send_sysex(build_rq1(0x10000154, 8))
    time.sleep(0.5)
    led_payload = None
    with lock:
        for e in events:
            p = parse_dt1(e)
            if p and p[0] == 0x10000154 and len(p[1]) == 8:
                led_payload = p[1]

    for addr, label in PROBES:
        v = by_addr.get(addr)
        if v is None:
            print(f"  0x{addr:08X}  {label:38s}  TIMEOUT")
        else:
            print(f"  0x{addr:08X}  {label:38s}  = {v[0]}")
    if led_payload:
        led32 = 0
        for b in led_payload:
            led32 = (led32 << 4) | (b & 0x0F)
        print(f"\n  0x10000154  ON_OFF_STATE bitmap            = 0x{led32:08X}")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
