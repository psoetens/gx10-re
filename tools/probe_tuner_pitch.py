"""Read-only probe of the SystemPitch block (0x00006000) — the MENU->TUNER knobs.

Resolves ONE open question: how REF. PITCH is encoded on the wire.

The official chart (docs/official_xref.md "TUNER (SystemPitch)") lists
REF. PITCH as offsets 0x00-0x03, "435-445 Hz (4 nibbles)", which leaves
two candidate encodings:

  binary 4-nibble BE   440 -> 0x01B8 -> bytes 00 01 0B 08
  BCD decimal digits   440 -> "0440"  -> bytes 00 04 04 00

Both fit "4 nibbles" and both are plausible; the rest of this device's
multi-byte fields (FX Parameter cells, program map) are binary 4-nibble
BE via tools/encoding.py, so that is the prior — but it has never been
confirmed on THIS register.

The remaining three bytes are single-byte enums already documented:

  0x00006004  TT/POLY TUNER TYPE    0-5  6-REG, 6-DROP D, 7-REG,
                                         7-DROP A, 4-B REG, 5-B REG
  0x00006005  TT/POLY TUNER OFFSET  11-16 (-5..-1, ----)
  0x00006006  TUNER OUTPUT          0-2  MUTE, BYPASS, THRU

Read-only by default. Safe to run while an editor is attached: replies
are matched on address, so another client's traffic is ignored.

With `--write` it additionally round-trips each of the four fields
(write a distinct value -> read back -> compare) and then **restores the
values it found on entry**, so the device is left as it was. Run it with
nothing else talking to the device.

Expected reading on a factory-default unit: REF. PITCH = 440 Hz.
Set the pedal's MENU->TUNER REF. PITCH to a known non-default value
(e.g. 437) and re-run to confirm the decode tracks it.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff
from device_id import require_alive_raw

BASE = 0x00006000
# 8 is 7-bit-clean and over-reads past the last documented byte (0x06).
# See docs/protocol.md on RQ1 size encoding: raw big-endian, each byte <= 0x7F.
SIZE = 8

TYPE_LABELS = ["6-REG", "6-DROP D", "7-REG", "7-DROP A", "4-B REG", "5-B REG"]
OFFSET_LABELS = {11: "-5", 12: "-4", 13: "-3", 14: "-2", 15: "-1", 16: "----"}
OUTPUT_LABELS = ["MUTE", "BYPASS", "THRU"]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def decode_binary_nibbles(b):
    """Low nibble of each byte, big-endian — tools/encoding.py convention."""
    return ((b[0] & 0x0F) << 12) | ((b[1] & 0x0F) << 8) \
         | ((b[2] & 0x0F) << 4) | (b[3] & 0x0F)


def decode_bcd(b):
    """Each byte one decimal digit, most significant first."""
    return (b[0] & 0x0F) * 1000 + (b[1] & 0x0F) * 100 \
         + (b[2] & 0x0F) * 10 + (b[3] & 0x0F)


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
    require_alive_raw(out, events, lock)

    with lock:
        events.clear()
    out.send_sysex(build_rq1(BASE, SIZE))
    time.sleep(0.6)
    with lock:
        snap = list(events)

    payload = None
    for e in snap:
        p = parse_dt1(e)
        if p and p[0] == BASE:
            payload = p[1]
            break

    print(f"RQ1 0x{BASE:08X} size={SIZE}")
    if payload is None:
        naks = [e for e in snap if len(e) > 8 and e[8] == 0x11]
        print(f"  NO REPLY ({len(snap)} sysex seen, {len(naks)} RQ1 echoes/NAKs)")
        for e in snap[:5]:
            print(f"    {e.hex().upper()[:64]}")
        sys.stdout.flush()
        import os
        os._exit(1)

    print(f"  {len(payload)} bytes: " + " ".join(f"{b:02X}" for b in payload))
    if len(payload) < 7:
        print("  short reply — cannot decode")
        sys.stdout.flush()
        import os
        os._exit(1)

    pitch = payload[0:4]
    as_bin = decode_binary_nibbles(pitch)
    as_bcd = decode_bcd(pitch)
    print()
    print(f"  REF. PITCH bytes 0x00-0x03 = " + " ".join(f"{b:02X}" for b in pitch))
    ok_bin = 435 <= as_bin <= 445
    ok_bcd = 435 <= as_bcd <= 445
    print(f"    binary 4-nibble BE -> {as_bin:5d}   {'IN RANGE' if ok_bin else 'out of 435-445'}")
    print(f"    BCD decimal digits -> {as_bcd:5d}   {'IN RANGE' if ok_bcd else 'out of 435-445'}")
    if ok_bin and not ok_bcd:
        print("    VERDICT: binary 4-nibble BE (NibbleCodec.encode4Nib)")
    elif ok_bcd and not ok_bin:
        print("    VERDICT: BCD decimal digits")
    elif ok_bin and ok_bcd:
        print("    AMBIGUOUS: both decode in range — change REF. PITCH on the")
        print("               pedal to 437 or 443 and re-run to break the tie.")
    else:
        print("    NEITHER decodes in range — layout assumption is wrong")

    t = payload[4]
    o = payload[5]
    u = payload[6]
    print()
    print(f"  TYPE   0x04 = {t:02X} -> "
          f"{TYPE_LABELS[t] if t < len(TYPE_LABELS) else 'OUT OF RANGE'}")
    print(f"  OFFSET 0x05 = {o:02X} -> {OFFSET_LABELS.get(o, 'OUT OF RANGE (expect 11-16)')}")
    print(f"  OUTPUT 0x06 = {u:02X} -> "
          f"{OUTPUT_LABELS[u] if u < len(OUTPUT_LABELS) else 'OUT OF RANGE'}")
    if len(payload) > 7:
        print()
        print("  over-read past 0x06: " + " ".join(f"{b:02X}" for b in payload[7:]))

    if "--write" in sys.argv:
        write_round_trip(out, events, lock, original=payload[:7])

    sys.stdout.flush()
    import os
    os._exit(0)


def read_block(out, events, lock):
    """One RQ1 of the whole block; returns the first 7 payload bytes."""
    with lock:
        events.clear()
    out.send_sysex(build_rq1(BASE, SIZE))
    time.sleep(0.5)
    with lock:
        snap = list(events)
    for e in snap:
        p = parse_dt1(e)
        if p and p[0] == BASE:
            return p[1][:7]
    return None


def write_round_trip(out, events, lock, original):
    """Write a distinct value to each field, read it back, then restore.

    Pacing: 60 ms between DT1s. Well clear of the 3 ms floor the chain-edit
    deadlock forced (docs/protocol.md §4) — these are single-byte system
    registers, not a chain burst, so there is no reason to crowd them.
    """
    from midi_send import build_dt1

    print()
    print("=== WRITE ROUND-TRIP (restores your values at the end) ===")
    print("  entry state: " + " ".join(f"{b:02X}" for b in original))

    # (label, offset, payload bytes, expected read-back bytes)
    cases = [
        ("REF. PITCH 443", 0x00, bytes([0x00, 0x01, 0x0B, 0x0B]),
         bytes([0x00, 0x01, 0x0B, 0x0B])),
        ("TYPE 7-DROP A", 0x04, bytes([0x03]), bytes([0x03])),
        ("OFFSET ----",   0x05, bytes([0x10]), bytes([0x10])),
        ("OUTPUT BYPASS", 0x06, bytes([0x01]), bytes([0x01])),
    ]

    failures = 0
    for label, off, payload, expect in cases:
        out.send_sysex(build_dt1(BASE + off, payload))
        time.sleep(0.06)
        back = read_block(out, events, lock)
        if back is None:
            print(f"  {label:16s} FAIL — no read-back")
            failures += 1
            continue
        got = back[off:off + len(expect)]
        ok = got == expect
        failures += 0 if ok else 1
        print(f"  {label:16s} wrote {payload.hex().upper():8s} "
              f"read {got.hex().upper():8s} {'OK' if ok else 'MISMATCH'}")

    # Restore, field by field, in the same shape the app writes them.
    print("  restoring…")
    out.send_sysex(build_dt1(BASE + 0x00, bytes(original[0:4])))
    time.sleep(0.06)
    for off in (0x04, 0x05, 0x06):
        out.send_sysex(build_dt1(BASE + off, bytes([original[off]])))
        time.sleep(0.06)
    back = read_block(out, events, lock)
    restored = back == original
    print(f"  after restore: " + " ".join(f"{b:02X}" for b in (back or [])) +
          ("  OK" if restored else "  !! DID NOT MATCH ENTRY STATE"))
    if failures or not restored:
        print(f"  {failures} field(s) failed; restore "
              f"{'ok' if restored else 'FAILED'}")
    else:
        print("  all 4 fields round-tripped, device restored")


if __name__ == "__main__":
    main()
