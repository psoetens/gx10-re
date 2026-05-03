"""Read the tuner-config registers and decode them.

Per docs/menus.md / docs/gaps.md (chart-documented but unverified):
  0x0000_6000  SystemPitch        — reference pitch (e.g. 440 Hz)
  0x0000_6004  POLY TUNER TYPE    — 6-REG, 6-DROP D, 7-REG, 7-DROP A, 4-B REG, 5-B REG
  0x0000_6005  POLY TUNER OFFSET  — 11..16 = -5..-1, plus '----'
  0x0000_6006  TUNER OUTPUT       — MUTE, BYPASS, THRU

Caller reports current state:
  pitch=435Hz  poly_offset=-1  poly_type=6-DROP D  tuner_output=BYPASS
We compare what we read to those expectations to lock down the encoding.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff


POLY_TYPES = ["6-REG", "6-DROP D", "7-REG", "7-DROP A", "4-B REG", "5-B REG"]
TUNER_OUTPUT = ["MUTE", "BYPASS", "THRU"]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def read_one(out, in_events, lock, addr, sz, timeout=0.5):
    """Send RQ1 and wait for matching DT1."""
    out.send_sysex(build_rq1(addr, sz))
    deadline = time.time() + timeout
    while time.time() < deadline:
        with lock:
            for _, e in in_events:
                p = parse_dt1(e)
                if p and p[0] == addr:
                    return p[1]
        time.sleep(0.02)
    return None


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
                    events.append((time.time(), bytes.fromhex(o["hex"])))
            except Exception:
                pass
    s._emit = emit
    s.open()
    out_idx, _ = find_output_port("GX-10")
    out = MidiOut(out_idx)
    time.sleep(0.3)

    # Read a small block at 0x6000 (8 bytes covers all 4 fields)
    payload = read_one(out, events, lock, 0x00006000, 8, timeout=1.0)
    if not payload:
        # Fall back to one-by-one
        print("Block read failed, reading individually...")
        fields = {}
        for off in (0x00, 0x04, 0x05, 0x06):
            with lock:
                events.clear()
            v = read_one(out, events, lock, 0x00006000 + off, 1)
            fields[off] = v
        b0 = fields.get(0x00, b"")
        b4 = fields.get(0x04, b"") or b""
        b5 = fields.get(0x05, b"") or b""
        b6 = fields.get(0x06, b"") or b""
        payload = b0 + b"\x00\x00\x00" + b4 + b5 + b6
    print(f"raw 0x00006000..0x00006007 = {payload.hex().upper()}")
    print()

    # 0x6000: SystemPitch — likely 2 bytes packed, or 1 byte offset from 440
    pitch_bytes = payload[0:4]
    print(f"0x00006000 SystemPitch     bytes={pitch_bytes.hex().upper()}")
    # Decoding hypothesis: high+low nibble offset binary (4-nibble)?
    # Or simple scalar: byte0 = freq - 400 (e.g. 435 -> 35 = 0x23)?
    # Try a few interpretations:
    if len(pitch_bytes) >= 2:
        # 7-bit big-endian 2 bytes: (b0<<7) | b1
        v_7bit = (pitch_bytes[0] << 7) | pitch_bytes[1]
        # raw byte
        v_b0 = pitch_bytes[0]
        # 4-nibble offset binary
        v_4n = ((pitch_bytes[0] & 0xF) << 12 | (pitch_bytes[1] & 0xF) << 8
                | (pitch_bytes[2] & 0xF) << 4 | (pitch_bytes[3] & 0xF))
        print(f"  byte0          = {v_b0}      (if directly = freq - 400 -> {v_b0 + 400} Hz)")
        print(f"  7-bit BE 2B    = {v_7bit}    (could be Hz directly)")
        print(f"  4-nibble (low nibble of each byte) = {v_4n}  (= 0x{v_4n:04X})")
        print(f"     -> if value is Hz directly: {v_4n} Hz")
        print(f"     -> if offset binary: {v_4n - 32768}")

    # 0x6004 POLY TUNER TYPE
    if len(payload) > 4:
        t = payload[4]
        name = POLY_TYPES[t] if t < len(POLY_TYPES) else f"?({t})"
        print(f"\n0x00006004 POLY TUNER TYPE   = {t} ({name})")

    # 0x6005 POLY TUNER OFFSET — chart says 11..16 = -5..-1 (or '----')
    if len(payload) > 5:
        o = payload[5]
        if 11 <= o <= 15:
            offset = o - 16
            print(f"0x00006005 POLY OFFSET       = {o} (= {offset:+d})")
        elif o == 16:
            print(f"0x00006005 POLY OFFSET       = {o} (= ----, no offset)")
        elif o < 11:
            print(f"0x00006005 POLY OFFSET       = {o} (= {o:+d}? or 0..N range)")
        else:
            print(f"0x00006005 POLY OFFSET       = {o} (?)")

    # 0x6006 TUNER OUTPUT
    if len(payload) > 6:
        u = payload[6]
        name = TUNER_OUTPUT[u] if u < len(TUNER_OUTPUT) else f"?({u})"
        print(f"0x00006006 TUNER OUTPUT      = {u} ({name})")

    print()
    print("Expected from caller: pitch=435 Hz, poly_offset=-1, poly_type=6-DROP D, output=BYPASS")
    print("If decoding matches -> encoding confirmed.")
    sys.stdout.flush()

    import os; os._exit(0)


if __name__ == "__main__":
    main()
