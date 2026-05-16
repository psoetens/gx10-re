"""Live watcher for the GX-10 LED ON/OFF bitmap.

Polls MemoryLed offset 0x14..0x1B (32-bit ON OFF STATE) every 250 ms
and prints a line whenever any bit changes, identifying which bit
flipped. Run it, then press each footswitch / toe switch one at a
time to nail down the GX-10's bit-to-pedal mapping (the chart's
bit table is GX-100-centric and doesn't necessarily match GX-10
hardware labels).

Usage:
  Close BTS first.
  python tools/watch_pedal_status.py
  Press Ctrl+C when done.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff
from device_id import require_alive_raw
from device_profile import detect_and_profile


TEMP_BASE = 0x10000000
LED_OFS = 0x000140 + 0x14
LED_ADDR = TEMP_BASE + LED_OFS


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    addr = int.from_bytes(raw[9:13], "big")
    payload = bytes(raw[13:-2])
    return addr, payload


def decode_bitmap(payload: bytes) -> int:
    if len(payload) < 8:
        return 0
    val = 0
    for i in range(8):
        val = (val << 4) | (payload[i] & 0x0F)
    return val


def main():
    model, profile = detect_and_profile(port_substr="GX-10")
    bit_names = profile["led_bits"]
    print(f"Device detected: {model}")

    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        print("ERROR: no MIDI input port"); sys.exit(2)
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
    if out_idx is None:
        print("ERROR: no MIDI output port"); sys.exit(2)
    out = MidiOut(out_idx)
    time.sleep(0.4)
    require_alive_raw(out, events, lock)

    print("Watching MemoryLed.ON_OFF_STATE — press each button one at a time.")
    print("Ctrl+C to stop.\n")

    last_val = None
    last_seen_idx = 0
    try:
        while True:
            out.send_sysex(build_rq1(LED_ADDR, 0x08))
            time.sleep(0.18)
            with lock:
                snap = list(events[last_seen_idx:])
                last_seen_idx = len(events)
            for ev in snap:
                p = parse_dt1(ev)
                if not p or p[0] != LED_ADDR:
                    continue
                val = decode_bitmap(p[1])
                if last_val is None:
                    print(f"[init]  bitmap = 0x{val:08X}  bits set:", end=" ")
                    print(", ".join(f"{i}({bit_names.get(i,'?')})"
                                     for i in range(32) if (val >> i) & 1))
                    last_val = val
                elif val != last_val:
                    diff = val ^ last_val
                    changed = []
                    for i in range(32):
                        if (diff >> i) & 1:
                            new_state = (val >> i) & 1
                            tag = bit_names.get(i, f"bit{i}")
                            changed.append(f"bit {i:2d} ({tag}) -> {'ON ' if new_state else 'off'}")
                    print(f"  0x{val:08X}  | {' | '.join(changed)}")
                    last_val = val
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopped.")
    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
