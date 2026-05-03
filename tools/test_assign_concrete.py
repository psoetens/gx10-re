"""Test whether the assign-row TARGET issue is specific to TARGET=1 (the
generic EFFECT ON/OFF) or applies to ALL targets.

Plan:
  1. Read Assign #1 back as baseline.
  2. Write Assign #1 with TARGET=374 (REVERB PRE-DELAY, a concrete row).
     MIN=0, MAX=100 (the chart says PRE-DELAY range is 0..100).
  3. Read back. Did the TARGET sub-group commit this time?

If concrete target works -> problem is specific to TARGET=1.
If concrete target also fails -> problem is encoding / write-order / timing.

Adds an explicit 300ms delay before the assign write (in case the chain
needs to settle). Also writes individual DT1s instead of one bulk row.
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


def encode_4nib(value):
    return bytes([(value >> 12) & 0xF, (value >> 8) & 0xF,
                  (value >> 4) & 0xF, value & 0xF])


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

    # Write assign field-by-field with individual DT1s, ending at 0x2C
    BASE = 0x10000200
    print("Writing Assign #1 fields one at a time, "
          "TARGET=374 (REVERB PRE-DELAY)...")

    # Wait so the chain has settled
    time.sleep(0.3)

    # SW=1
    out.send_sysex(build_dt1(BASE + 0x00, b"\x01"))
    # TARGET_FX_ITEM=2 (REV)
    out.send_sysex(build_dt1(BASE + 0x01, b"\x02"))
    # TARGET=374 = 0x176 -> nibbles 0,1,7,6 -> bytes 00 01 07 06
    out.send_sysex(build_dt1(BASE + 0x02, encode_4nib(374)))
    # TARGET MIN=0+0x8000=0x8000 -> nibbles 8,0,0,0 -> bytes 08 00 00 00
    out.send_sysex(build_dt1(BASE + 0x06, encode_4nib(0x8000)))
    # TARGET MAX=100+0x8000=0x8064 -> nibbles 8,0,6,4 -> bytes 08 00 06 04
    out.send_sysex(build_dt1(BASE + 0x0A, encode_4nib(0x8064)))
    # SOURCE = CC#64 (=52)
    out.send_sysex(build_dt1(BASE + 0x0E, b"\x34"))
    # MODE = TOGGLE
    out.send_sysex(build_dt1(BASE + 0x0F, b"\x00"))
    # ACT RANGE LO = 0
    out.send_sysex(build_dt1(BASE + 0x15, encode_4nib(0)))
    # ACT RANGE HI = 16383
    out.send_sysex(build_dt1(BASE + 0x19, encode_4nib(16383)))
    # MIDI CH = SYSTEM
    out.send_sysex(build_dt1(BASE + 0x1D, b"\x00"))
    # MIDI CC# = 0
    out.send_sysex(build_dt1(BASE + 0x1E, b"\x00"))
    # MIDI CC VAL MIN = 0
    out.send_sysex(build_dt1(BASE + 0x1F, encode_4nib(0)))
    # MIDI CC VAL MAX = 16383
    out.send_sysex(build_dt1(BASE + 0x23, encode_4nib(16383)))
    # 0x27 fixed
    out.send_sysex(build_dt1(BASE + 0x27, b"\x00"))
    # MIDI PC# = 0
    out.send_sysex(build_dt1(BASE + 0x28, b"\x00"))
    # MIDI BANK MSB = OFF (2 bytes at 0x29, 0x2A)
    out.send_sysex(build_dt1(BASE + 0x29, b"\x00\x00"))
    # MIDI BANK LSB = OFF (2 bytes at 0x2B, 0x2C — last write commits the group)
    out.send_sysex(build_dt1(BASE + 0x2B, b"\x00\x00"))
    time.sleep(0.5)

    # Read back
    print("Reading back...")
    with lock:
        events.clear()
    out.send_sysex(build_rq1(BASE, 0x2D))
    time.sleep(0.6)
    with lock:
        snap = list(events)
    p = None
    for e in snap:
        r = parse_dt1(e)
        if r and r[0] == BASE:
            p = r[1]
            break
    if not p or len(p) < 0x2D:
        print("ERROR: no full reply"); sys.exit(2)
    print(f"  raw: {p.hex().upper()}")
    print()
    print(f"  SW              = {p[0x00]}")
    print(f"  TARGET_FX_ITEM  = {p[0x01]}")
    target = ((p[0x02] & 0xF) << 12 | (p[0x03] & 0xF) << 8
              | (p[0x04] & 0xF) << 4 | (p[0x05] & 0xF))
    print(f"  TARGET          = {target} (bytes {p[0x02:0x06].hex().upper()})")
    tmin = ((p[0x06] & 0xF) << 12 | (p[0x07] & 0xF) << 8
            | (p[0x08] & 0xF) << 4 | (p[0x09] & 0xF))
    tmax = ((p[0x0A] & 0xF) << 12 | (p[0x0B] & 0xF) << 8
            | (p[0x0C] & 0xF) << 4 | (p[0x0D] & 0xF))
    print(f"  TARGET MIN      = {tmin}  (-> display {tmin - 0x8000})")
    print(f"  TARGET MAX      = {tmax}  (-> display {tmax - 0x8000})")
    print(f"  SOURCE          = {p[0x0E]}")
    print(f"  MODE            = {p[0x0F]}")

    if p[0x00] == 1 and p[0x01] == 2 and target == 374:
        print("\nSUCCESS: TARGET sub-group committed correctly")
        print(" -> writing field-by-field works with concrete target")
    else:
        print("\nFAIL: TARGET sub-group still rejected")
        print(" -> even concrete TARGET=374 (REVERB PRE-DELAY) doesn't commit")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
