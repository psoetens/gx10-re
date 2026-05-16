"""Subscribe to broadcasts AND set RunningMode = MONO_TUNER, then sniff.

  DT1  0x7F000001 = 1   (subscribe as editor)
  DT1  0x7F000002 = 1   (RunningMode = MONO_TUNER)

Listen for ~8 seconds. The device should now push 0x7F000300 every
time it has new pitch data (i.e. while you play / strum / wiggle a
string). Pluck a string during the sniff window to see the broadcast
fire.

Restores both fields on exit so the device returns to its
pre-existing state.
"""
import argparse
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
from device_id import require_alive_raw


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--mode", type=int, default=1,
                    help="RunningMode value (0=EDIT, 1=MONO_TUNER, 2=POLY_TUNER)")
    args = ap.parse_args()

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

    require_alive_raw(out, events, lock=lock)

    print("Subscribing as editor...")
    out.send_sysex(build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.2)
    print(f"Setting RunningMode = {args.mode} "
          f"({'EDIT' if args.mode==0 else 'MONO_TUNER' if args.mode==1 else 'POLY_TUNER' if args.mode==2 else '?'})")
    out.send_sysex(build_dt1(0x7F000002, bytes([args.mode])))
    time.sleep(0.3)
    t_listen = time.time()
    print(f"Sniffing {args.seconds}s — pluck strings now!")
    time.sleep(args.seconds)

    print("Restoring RunningMode = 0 (EDIT)")
    out.send_sysex(build_dt1(0x7F000002, b"\x00"))
    time.sleep(0.2)
    print("Restoring EditorCommunicationMode = 0")
    out.send_sysex(build_dt1(0x7F000001, b"\x00"))
    time.sleep(0.2)

    with lock:
        snap = list(events)

    addr_hits = Counter()
    addr_first = {}
    addr_last_during_listen = {}
    for ts, e in snap:
        p = parse_dt1(e)
        if not p:
            continue
        addr_hits[p[0]] += 1
        if p[0] not in addr_first:
            addr_first[p[0]] = p[1]
        if ts >= t_listen:
            addr_last_during_listen[p[0]] = (ts, p[1])

    print(f"\n=== {len(snap)} sysex events total ===")
    for addr, n in addr_hits.most_common():
        payload = addr_first[addr]
        last = addr_last_during_listen.get(addr)
        last_str = f"  last={last[1].hex().upper()[:48]}" if last else ""
        print(f"  0x{addr:08X}  hits={n:3d}  first={payload.hex().upper()[:48]}{last_str}")

    # Decode the most-recent tuner broadcast
    tuner_evts = [(ts, e) for ts, e in snap if ts >= t_listen
                   and parse_dt1(e) and parse_dt1(e)[0] == 0x7F000300]
    if tuner_evts:
        last_payload = parse_dt1(tuner_evts[-1][1])[1]
        print(f"\nLast tuner broadcast: {len(last_payload)} bytes")
        print(f"  raw: {last_payload.hex().upper()}")
        if len(last_payload) >= 12:
            n = last_payload[0]
            note = NOTE_NAMES[n-1] if 1 <= n <= 12 else "----"
            pitch = ((last_payload[1] & 0xF) << 12 |
                     (last_payload[2] & 0xF) << 8 |
                     (last_payload[3] & 0xF) << 4 |
                     (last_payload[4] & 0xF))
            print(f"  mono note: {note} ({n})  pitch_raw={pitch}  "
                  f"just={last_payload[5] if len(last_payload) > 5 else '?'}")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
