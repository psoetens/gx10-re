"""Read live tuner state + sniff broadcasts for a few seconds.

Polls the chart-documented tuner addresses and also passively listens
for any DT1 the device broadcasts (the device pushes periodic updates
when the on-screen tuner is active — that's how BTS animates its
tuner display in real time).

Addresses (per chart):
  SetupTemp           (0x00200000):
    0x05  TTMode (0..7)             — tuner sub-mode
    0x06  TTTargetStringNum (1..7)  — which string is targeted
    0x07  TTTargetName (0..11)      — note name (C..B)
    0x08  TTCentOffset (-10..+10)   — pitch offset in cents
  SystemPitch         (0x00006000):
    0x00..03  ReferencePitch (435..445 Hz, 4-nibble)
    0x04  PolyTunerType
    0x06  TunerOutput (0=MUTE, 1=BYPASS, 2=THRU)
"""
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff


PROBES = [
    (0x00200005, "SetupTemp.TTMode"),
    (0x00200006, "SetupTemp.TTTargetStringNum"),
    (0x00200007, "SetupTemp.TTTargetName"),
    (0x00200008, "SetupTemp.TTCentOffset"),
    (0x00006000, "SystemPitch.ReferencePitch (4 bytes)"),
    (0x00006004, "SystemPitch.PolyTunerType"),
    (0x00006005, "SystemPitch.PolyTunerOffset"),
    (0x00006006, "SystemPitch.TunerOutput"),
]
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]
TT_MODE_NAMES = {  # guessed from typical Roland enums
    0: "OFF", 1: "MONO", 2: "POLY", 3: "TT-MONO?",
    4: "TT-POLY?", 5: "?", 6: "?", 7: "?",
}
TUNER_OUTPUT_NAMES = {0: "MUTE", 1: "BYPASS", 2: "THRU"}


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
    timestamps = []
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
                    timestamps.append(time.time())
            except Exception:
                pass
    s._emit = emit
    s.open()
    out_idx, _ = find_output_port("GX-10")
    out = MidiOut(out_idx)
    time.sleep(0.4)

    # 1) Send the probes.
    print("Probing tuner-related addresses...")
    sizes = {0x00006000: 4}  # ReferencePitch is 4 bytes
    for addr, _label in PROBES:
        out.send_sysex(build_rq1(addr, sizes.get(addr, 1)))
        time.sleep(0.02)

    # 2) Then sit and listen for broadcasts for ~5 seconds.
    print("Sniffing device broadcasts for 5s — wiggle the tuner...")
    listen_start = time.time()
    time.sleep(5.0)

    # Snapshot
    with lock:
        snap = list(zip(timestamps, events))

    # Print probe results
    by_addr_first = {}
    for ts, e in snap:
        p = parse_dt1(e)
        if p and p[0] not in by_addr_first:
            by_addr_first[p[0]] = p[1]

    print("\n=== Tuner-related register snapshot ===")
    for addr, label in PROBES:
        v = by_addr_first.get(addr)
        if v is None:
            print(f"  0x{addr:08X}  {label:38s}  TIMEOUT")
            continue
        if addr == 0x00006000 and len(v) >= 4:
            ref_pitch = ((v[0] & 0xF) << 12 | (v[1] & 0xF) << 8 |
                         (v[2] & 0xF) << 4 | (v[3] & 0xF))
            print(f"  0x{addr:08X}  {label:38s}  raw={v.hex().upper()}  "
                  f"= {ref_pitch} (interpret as 435..445 Hz)")
            continue
        b = v[0]
        if addr == 0x00200007:  # TTTargetName
            note = NOTE_NAMES[b] if b < 12 else "?"
            print(f"  0x{addr:08X}  {label:38s}  = {b}  ({note})")
        elif addr == 0x00200008:  # TTCentOffset (signed-ish)
            sb = b if b < 64 else b - 128
            print(f"  0x{addr:08X}  {label:38s}  = {b}  ({sb:+d} cents)")
        elif addr == 0x00200005:  # TTMode
            print(f"  0x{addr:08X}  {label:38s}  = {b}  ({TT_MODE_NAMES.get(b, '?')})")
        elif addr == 0x00006006:  # TunerOutput
            print(f"  0x{addr:08X}  {label:38s}  = {b}  ({TUNER_OUTPUT_NAMES.get(b, '?')})")
        else:
            print(f"  0x{addr:08X}  {label:38s}  = {b}")

    # Categorize broadcasts during sniff window
    print("\n=== Broadcasts seen during 5s sniff ===")
    addr_hits = Counter()
    addr_examples = {}
    for ts, e in snap:
        if ts < listen_start:
            continue
        p = parse_dt1(e)
        if not p:
            continue
        addr, payload = p
        addr_hits[addr] += 1
        if addr not in addr_examples:
            addr_examples[addr] = payload
    if not addr_hits:
        print("  (no broadcasts received)")
    else:
        for addr, n in addr_hits.most_common():
            sample = addr_examples[addr]
            print(f"  0x{addr:08X}  hits={n:3d}  first_payload={sample.hex().upper()[:24]}")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
