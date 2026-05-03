"""Change Assign #1 from PEQ-on/off to REVERB-on/off.

The user has Assign #1 currently configured as:
  SW=ON, FX_ITEM=1 (PEQ), TARGET=1 (ON/OFF), SOURCE=CC#64, MODE=TOGGLE

We rewrite it field-by-field with FX_ITEM=2 (REV) — same MIN/MAX/SOURCE/MODE.
Then read back to verify. Then read back AGAIN after a 1-second delay
to see if BTS overrides us.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def encode_4nib(v):
    return bytes([(v >> 12) & 0xF, (v >> 8) & 0xF,
                  (v >> 4) & 0xF, v & 0xF])


def write_assign_fbf(out, base, target_fx_item, target_idx, source_byte,
                       mode_toggle=True, target_min=0, target_max=1):
    out.send_sysex(build_dt1(base + 0x00, b"\x01"))
    out.send_sysex(build_dt1(base + 0x01, bytes([target_fx_item])))
    out.send_sysex(build_dt1(base + 0x02, encode_4nib(target_idx)))
    out.send_sysex(build_dt1(base + 0x06, encode_4nib(target_min + 0x8000)))
    out.send_sysex(build_dt1(base + 0x0A, encode_4nib(target_max + 0x8000)))
    out.send_sysex(build_dt1(base + 0x0E, bytes([source_byte])))
    out.send_sysex(build_dt1(base + 0x0F, b"\x00" if mode_toggle else b"\x01"))
    out.send_sysex(build_dt1(base + 0x15, encode_4nib(0)))
    out.send_sysex(build_dt1(base + 0x19, encode_4nib(16383)))
    out.send_sysex(build_dt1(base + 0x1D, b"\x00"))
    out.send_sysex(build_dt1(base + 0x1E, b"\x00"))
    out.send_sysex(build_dt1(base + 0x1F, encode_4nib(0)))
    out.send_sysex(build_dt1(base + 0x23, encode_4nib(16383)))
    out.send_sysex(build_dt1(base + 0x27, b"\x00"))
    out.send_sysex(build_dt1(base + 0x28, b"\x00"))
    out.send_sysex(build_dt1(base + 0x29, b"\x00\x00"))
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


def show(p, label):
    target = ((p[0x02] & 0xF) << 12 | (p[0x03] & 0xF) << 8
              | (p[0x04] & 0xF) << 4 | (p[0x05] & 0xF))
    print(f"  {label}: SW={p[0x00]} FX_ITEM={p[0x01]} TARGET={target} "
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

    BASE = 0x10000200

    print("Step 1: read current Assign #1")
    p = read_assign(out, events, lock, BASE)
    if p:
        show(p, "before")
    else:
        print("  no reply!")

    print("\nStep 2: write Assign #1 = REV ON/OFF on CC#64 (field-by-field)")
    write_assign_fbf(out, BASE,
                       target_fx_item=2,        # REV at chain position 2
                       target_idx=1,             # generic EFFECT ON/OFF
                       source_byte=52,           # CC#64
                       mode_toggle=True,
                       target_min=0, target_max=1)

    time.sleep(0.3)
    print("\nStep 3: read back IMMEDIATELY")
    p = read_assign(out, events, lock, BASE)
    if p:
        show(p, "after  (t=+0s)")

    print("\nStep 4: wait 1 second, read back again (catch BTS overrides)")
    time.sleep(1.2)
    p = read_assign(out, events, lock, BASE)
    if p:
        show(p, "after  (t=+1s)")

    print("\nStep 5: wait another 2 seconds, read back again")
    time.sleep(2.0)
    p = read_assign(out, events, lock, BASE)
    if p:
        show(p, "after  (t=+3s)")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
