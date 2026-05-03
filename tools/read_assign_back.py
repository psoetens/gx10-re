"""Read Assign #1 back from the device and decode every field."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff


SOURCE_NAMES = (
    ["NUM 1", "NUM 2", "NUM 3", "NUM 4",
     "MAN 1", "MAN 2", "MAN 3", "MAN 4",
     "CUR NUM", "BANK DOWN", "BANK UP",
     "CTL 1", "CTL 2", "CTL 3", "CTL 4",
     "EXP 1 SW", "EXP 1", "EXP 2", "INT PDL", "WAVE PDL", "INPUT"]
    + [f"CC#{i}" for i in range(1, 32)]
    + [f"CC#{i}" for i in range(64, 96)]
)


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def decode_4nibble_offset(b):
    raw = ((b[0] & 0xF) << 12) | ((b[1] & 0xF) << 8) \
          | ((b[2] & 0xF) << 4) | (b[3] & 0xF)
    return raw - 0x8000


def decode_4nibble_direct(b):
    return ((b[0] & 0xF) << 12) | ((b[1] & 0xF) << 8) \
           | ((b[2] & 0xF) << 4) | (b[3] & 0xF)


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

    # Read 0x40 bytes (one assign stride) at 0x10000200
    out.send_sysex(build_rq1(0x10000200, 0x40))
    time.sleep(0.6)

    with lock:
        snap = list(events)
    p = None
    for e in snap:
        r = parse_dt1(e)
        if r and r[0] == 0x10000200:
            p = r[1]
            break
    if not p or len(p) < 0x2D:
        print("ERROR: did not get a full reply")
        if p:
            print(f"got {len(p)} bytes: {p.hex().upper()}")
        sys.exit(2)

    print(f"Raw 0x10000200..0x1000022C ({len(p)} bytes):")
    print(f"  {p.hex().upper()}")
    print()
    print("Decoded:")
    print(f"  0x00 SW                = {p[0x00]}  ({'ON' if p[0x00] else 'OFF'})")
    print(f"  0x01 TARGET_FX_ITEM    = {p[0x01]}")
    print(f"  0x02-05 TARGET         = {decode_4nibble_direct(p[0x02:0x06])} "
          f"(bytes {p[0x02:0x06].hex().upper()})")
    print(f"  0x06-09 TARGET MIN     = {decode_4nibble_offset(p[0x06:0x0A])}+0x8000 "
          f"(bytes {p[0x06:0x0A].hex().upper()})")
    print(f"  0x0A-0D TARGET MAX     = {decode_4nibble_offset(p[0x0A:0x0E])}+0x8000 "
          f"(bytes {p[0x0A:0x0E].hex().upper()})")
    src = p[0x0E]
    src_name = SOURCE_NAMES[src] if src < len(SOURCE_NAMES) else "?"
    print(f"  0x0E SOURCE            = {src} ({src_name})")
    print(f"  0x0F MODE              = {p[0x0F]}  ({'TOGGLE' if p[0x0F]==0 else 'MOMENT'})")
    print(f"  0x10 WAVE RATE         = {p[0x10]}")
    print(f"  0x11 WAVEFORM          = {p[0x11]}")
    print(f"  0x12 INT PDL TRIGGER   = {p[0x12]}")
    print(f"  0x13 INT PDL TIME      = {p[0x13]}")
    print(f"  0x14 INT PDL CURVE     = {p[0x14]}")
    print(f"  0x15-18 ACT RANGE LO   = {decode_4nibble_direct(p[0x15:0x19])}")
    print(f"  0x19-1C ACT RANGE HI   = {decode_4nibble_direct(p[0x19:0x1D])}")
    print(f"  0x1D MIDI CH           = {p[0x1D]}")
    print(f"  0x1E MIDI CC#          = {p[0x1E]}")
    print(f"  0x1F-22 MIDI CC VAL MIN= {decode_4nibble_direct(p[0x1F:0x23])}")
    print(f"  0x23-26 MIDI CC VAL MAX= {decode_4nibble_direct(p[0x23:0x27])}")
    print(f"  0x27 N/A fixed         = {p[0x27]}")
    print(f"  0x28 MIDI PC#          = {p[0x28]}")
    print(f"  0x29-2A MIDI BANK MSB  = {p[0x29]:02X}{p[0x2A]:02X}")
    print(f"  0x2B-2C MIDI BANK LSB  = {p[0x2B]:02X}{p[0x2C]:02X}")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
