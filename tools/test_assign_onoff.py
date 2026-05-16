"""Test if TARGET=1 (generic EFFECT ON/OFF) commits when written
field-by-field (the bulk write earlier was rejected for this target).

If field-by-field works -> bulk write was the issue.
If field-by-field also fails -> the generic ON/OFF entry has special rules
                                 (or we need to set MIN/MAX differently).
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
from device_id import require_alive_raw


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def encode_4nib(value):
    return bytes([(value >> 12) & 0xF, (value >> 8) & 0xF,
                  (value >> 4) & 0xF, value & 0xF])


def write_assign_fbf(out, base, target_idx, target_fx_item, mode_toggle=True):
    """Write assign fields one DT1 at a time, ending at MIDI BANK LSB."""
    # SW=1, TARGET_FX_ITEM, TARGET
    out.send_sysex(build_dt1(base + 0x00, b"\x01"))
    out.send_sysex(build_dt1(base + 0x01, bytes([target_fx_item])))
    out.send_sysex(build_dt1(base + 0x02, encode_4nib(target_idx)))
    # MIN=0+0x8000, MAX=1+0x8000  (ON/OFF range)
    out.send_sysex(build_dt1(base + 0x06, encode_4nib(0x8000)))
    out.send_sysex(build_dt1(base + 0x0A, encode_4nib(0x8001)))
    # SOURCE = CC#64 (52), MODE
    out.send_sysex(build_dt1(base + 0x0E, b"\x34"))
    out.send_sysex(build_dt1(base + 0x0F, b"\x00" if mode_toggle else b"\x01"))
    # ACT RANGE
    out.send_sysex(build_dt1(base + 0x15, encode_4nib(0)))
    out.send_sysex(build_dt1(base + 0x19, encode_4nib(16383)))
    # MIDI defaults
    out.send_sysex(build_dt1(base + 0x1D, b"\x00"))
    out.send_sysex(build_dt1(base + 0x1E, b"\x00"))
    out.send_sysex(build_dt1(base + 0x1F, encode_4nib(0)))
    out.send_sysex(build_dt1(base + 0x23, encode_4nib(16383)))
    out.send_sysex(build_dt1(base + 0x27, b"\x00"))
    out.send_sysex(build_dt1(base + 0x28, b"\x00"))
    out.send_sysex(build_dt1(base + 0x29, b"\x00\x00"))
    # Final: this commit triggers the group check
    out.send_sysex(build_dt1(base + 0x2B, b"\x00\x00"))


def read_assign(out, events, lock, base):
    with lock:
        events.clear()
    out.send_sysex(build_rq1(base, 0x2D))
    time.sleep(0.5)
    with lock:
        snap = list(events)
    for e in snap:
        r = parse_dt1(e)
        if r and r[0] == base:
            return r[1]
    return None


def show(p):
    target = ((p[0x02] & 0xF) << 12 | (p[0x03] & 0xF) << 8
              | (p[0x04] & 0xF) << 4 | (p[0x05] & 0xF))
    tmin = ((p[0x06] & 0xF) << 12 | (p[0x07] & 0xF) << 8
            | (p[0x08] & 0xF) << 4 | (p[0x09] & 0xF))
    tmax = ((p[0x0A] & 0xF) << 12 | (p[0x0B] & 0xF) << 8
            | (p[0x0C] & 0xF) << 4 | (p[0x0D] & 0xF))
    print(f"  SW={p[0x00]} FX_ITEM={p[0x01]} TARGET={target} "
          f"MIN={tmin}({tmin-0x8000:+d}) MAX={tmax}({tmax-0x8000:+d}) "
          f"SOURCE={p[0x0E]} MODE={p[0x0F]}")


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
    time.sleep(0.4)
    require_alive_raw(out, events, lock)

    BASE = 0x10000200

    # Try field-by-field with TARGET=1 (generic EFFECT ON/OFF), TARGET_FX_ITEM=2
    print("Test 1: field-by-field, TARGET=1 (EFFECT ON/OFF), FX_ITEM=2")
    write_assign_fbf(out, BASE, target_idx=1, target_fx_item=2)
    time.sleep(0.3)
    p = read_assign(out, events, lock, BASE)
    if p:
        show(p)
        if p[0x00] == 1 and ((p[0x02] & 0xF) << 12 | (p[0x03] & 0xF) << 8
                | (p[0x04] & 0xF) << 4 | (p[0x05] & 0xF)) == 1:
            print("  -> SUCCESS: generic TARGET=1 ON/OFF works field-by-field")
        else:
            print("  -> FAIL: generic TARGET=1 ON/OFF still rejected")

    # Try TARGET_FX_ITEM = 0 (BOOST), see if generic ON/OFF works for any slot
    print("\nTest 2: TARGET=1, FX_ITEM=0 (BOOST)")
    write_assign_fbf(out, BASE, target_idx=1, target_fx_item=0)
    time.sleep(0.3)
    p = read_assign(out, events, lock, BASE)
    if p:
        show(p)

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
