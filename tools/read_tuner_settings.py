"""Read (and optionally round-trip) the SystemPitch tuner-config registers.

Block `0x0000_6000` — the four knobs on the device's own MENU -> TUNER page:

  0x0000_6000..6003  REF. PITCH     435-445 Hz, binary 4-nibble big-endian
                                    (low nibble of each byte; 440 = 0x01B8
                                    = `00 01 0B 08`)
  0x0000_6004        POLY/TT TYPE   0-5: 6-REG, 6-DROP D, 7-REG, 7-DROP A,
                                    4-B REG, 5-B REG
  0x0000_6005        POLY/TT OFFSET 11-15 = -5..-1, 16 = "----" (no offset).
                                    NOT zero-based.
  0x0000_6006        TUNER OUTPUT   0=MUTE, 1=BYPASS, 2=THRU

Encoding history: this script originally sprayed decode hypotheses because
the official chart only said "4 nibbles". That is long settled — see
docs/gaps.md §2, which recorded the binary-4-nibble-BE form verified
against a known on-device UI state (435 Hz / 6-DROP D / -1 / BYPASS), every
byte matching. Re-confirmed 2026-08-04 on a GX-10 (sw_rev 01.00.00.00),
which read `00 01 0B 08 00 0B 00` = 440 Hz / 6-REG / -5 / MUTE; the rival
BCD reading gives 218, outside the register's own 435-445 range. The
decoder below just applies the settled form, and `--verify-encoding`
prints the BCD comparison if you ever want to re-run the tie-break.

Naming: the official chart calls 0x6004/0x6005 "TT TUNER ...", the owner's
GX-10 menu and BTS both call them "POLY ...", and the values apply to BOTH
the POLY and TT displays. See docs/menus.md §TUNER.

Usage:
    python3 tools/read_tuner_settings.py                     # read + decode
    python3 tools/read_tuner_settings.py --verify-encoding    # + BCD tie-break
    python3 tools/read_tuner_settings.py --write              # + write round-trip

`--write` writes a distinct value to each of the four fields, reads each
back, then RESTORES the values found on entry, leaving the device as it
was. Verified end to end 2026-08-04. Run it with nothing else driving the
device.

Read paths are safe alongside an attached editor: replies are matched on
address, so another client's traffic is ignored.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
from device_id import require_alive_raw

BASE = 0x00006000
# 8 is 7-bit-clean and over-reads past the last documented byte (0x06).
# RQ1 sizes are raw big-endian with every byte <= 0x7F — see docs/protocol.md.
SIZE = 8

POLY_TYPES = ["6-REG", "6-DROP D", "7-REG", "7-DROP A", "4-B REG", "5-B REG"]
TUNER_OUTPUT = ["MUTE", "BYPASS", "THRU"]
PITCH_RANGE = (435, 445)


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def decode_pitch(b):
    """Binary 4-nibble big-endian: low nibble of each byte, MSN first."""
    return ((b[0] & 0x0F) << 12) | ((b[1] & 0x0F) << 8) \
         | ((b[2] & 0x0F) << 4) | (b[3] & 0x0F)


def encode_pitch(hz):
    hz = max(PITCH_RANGE[0], min(hz, PITCH_RANGE[1]))
    return bytes([(hz >> 12) & 0x0F, (hz >> 8) & 0x0F,
                  (hz >> 4) & 0x0F, hz & 0x0F])


def decode_bcd(b):
    """The rival reading, kept only for --verify-encoding."""
    return (b[0] & 0x0F) * 1000 + (b[1] & 0x0F) * 100 \
         + (b[2] & 0x0F) * 10 + (b[3] & 0x0F)


def offset_label(o):
    if 11 <= o <= 15:
        return f"{o - 16:+d}"
    if o == 16:
        return "---- (no offset)"
    return f"?({o})"


def read_block(out, events, lock, timeout=1.0):
    """One RQ1 of the whole block; returns the first 7 payload bytes."""
    with lock:
        events.clear()
    out.send_sysex(build_rq1(BASE, SIZE))
    deadline = time.time() + timeout
    while time.time() < deadline:
        with lock:
            snap = list(events)
        for e in snap:
            p = parse_dt1(e)
            if p and p[0] == BASE:
                return p[1][:7]
        time.sleep(0.02)
    return None


def show(payload, verify_encoding):
    print(f"raw 0x{BASE:08X}..0x{BASE + 6:08X} = "
          + " ".join(f"{b:02X}" for b in payload))
    print()
    pitch = payload[0:4]
    hz = decode_pitch(pitch)
    in_range = PITCH_RANGE[0] <= hz <= PITCH_RANGE[1]
    print(f"  REF. PITCH   {pitch.hex().upper()} -> {hz} Hz"
          + ("" if in_range else "   !! OUTSIDE 435-445"))
    if verify_encoding:
        bcd = decode_bcd(pitch)
        print(f"    binary 4-nibble BE -> {hz:5d}   "
              f"{'IN RANGE' if in_range else 'out of range'}")
        print(f"    BCD decimal digits -> {bcd:5d}   "
              f"{'IN RANGE' if PITCH_RANGE[0] <= bcd <= PITCH_RANGE[1] else 'out of range'}")

    t, o, u = payload[4], payload[5], payload[6]
    print(f"  TYPE         {t:02X} -> "
          f"{POLY_TYPES[t] if t < len(POLY_TYPES) else f'?({t})'}")
    print(f"  OFFSET       {o:02X} -> {offset_label(o)}")
    print(f"  TUNER OUTPUT {u:02X} -> "
          f"{TUNER_OUTPUT[u] if u < len(TUNER_OUTPUT) else f'?({u})'}")


def write_round_trip(out, events, lock, original):
    """Write a distinct value to each field, read it back, then restore.

    60 ms between DT1s — far clear of the 3 ms floor the chain-edit deadlock
    forced (docs/protocol.md §4). These are single-byte system registers,
    not a chain burst, so there is no reason to crowd them.
    """
    print()
    print("=== WRITE ROUND-TRIP (restores your values at the end) ===")
    print("  entry state: " + " ".join(f"{b:02X}" for b in original))

    cases = [
        ("REF. PITCH 443", 0x00, encode_pitch(443)),
        ("TYPE 7-DROP A",  0x04, bytes([0x03])),
        ('OFFSET "----"',  0x05, bytes([0x10])),
        ("OUTPUT BYPASS",  0x06, bytes([0x01])),
    ]

    failures = 0
    for label, off, payload in cases:
        out.send_sysex(build_dt1(BASE + off, payload))
        time.sleep(0.06)
        back = read_block(out, events, lock)
        if back is None:
            print(f"  {label:16s} FAIL — no read-back")
            failures += 1
            continue
        got = back[off:off + len(payload)]
        ok = got == payload
        failures += 0 if ok else 1
        print(f"  {label:16s} wrote {payload.hex().upper():8s} "
              f"read {got.hex().upper():8s} {'OK' if ok else 'MISMATCH'}")

    print("  restoring…")
    out.send_sysex(build_dt1(BASE + 0x00, bytes(original[0:4])))
    time.sleep(0.06)
    for off in (0x04, 0x05, 0x06):
        out.send_sysex(build_dt1(BASE + off, bytes([original[off]])))
        time.sleep(0.06)
    back = read_block(out, events, lock)
    restored = back == original
    print("  after restore: " + " ".join(f"{b:02X}" for b in (back or []))
          + ("  OK" if restored else "  !! DID NOT MATCH ENTRY STATE"))
    if failures or not restored:
        print(f"  {failures} field(s) failed; "
              f"restore {'ok' if restored else 'FAILED'}")
    else:
        print("  all 4 fields round-tripped, device restored")
    return failures == 0 and restored


def main():
    verify_encoding = "--verify-encoding" in sys.argv
    do_write = "--write" in sys.argv

    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        print("ERROR: no MIDI input")
        sys.exit(2)
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

    payload = read_block(out, events, lock)
    if payload is None or len(payload) < 7:
        print(f"RQ1 0x{BASE:08X} size={SIZE}: no usable reply")
        sys.stdout.flush()
        import os
        os._exit(1)

    show(payload, verify_encoding)
    ok = True
    if do_write:
        ok = write_round_trip(out, events, lock, payload)

    sys.stdout.flush()
    import os
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
