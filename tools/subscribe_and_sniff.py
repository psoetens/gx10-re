"""Replicate BTS's "I'm here, please broadcast" handshake, then sniff.

Per BTS midi_connect_controller.js:startCommunication:
  1. Identity Request (we skip, we already know the device).
  2. RQ1  0x7F000000  EditorCommunicationLevel.
  3. DT1  0x7F000001 = 1  EditorCommunicationMode (subscribe).
  4. RQ1  0x7F000003  EditorCommunicationRevision.
  5. RQ1  0x7F000002  RunningMode (read-back).

Step 3 is the one that opens the floodgates. After that the device
starts pushing TUNER/CONTROL_MODE/MODE_SWITCH/TT_MODE notifications.

Run with the on-device tuner active and watch what comes back.
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

    print("1. RQ1 EditorCommunicationLevel (0x7F000000)")
    out.send_sysex(build_rq1(0x7F000000, 1))
    time.sleep(0.2)

    print("2. DT1 EditorCommunicationMode = 1 (subscribe)")
    out.send_sysex(build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.2)

    print("3. RQ1 EditorCommunicationRevision")
    out.send_sysex(build_rq1(0x7F000003, 1))
    time.sleep(0.2)

    print("4. RQ1 RunningMode")
    out.send_sysex(build_rq1(0x7F000002, 1))
    time.sleep(0.2)

    print(f"5. Sniffing for {args.seconds}s — wiggle the tuner...")
    t_listen = time.time()
    time.sleep(args.seconds)

    # Restore — write back so device returns to silent mode
    print("6. DT1 EditorCommunicationMode = 0 (un-subscribe)")
    out.send_sysex(build_dt1(0x7F000001, b"\x00"))
    time.sleep(0.2)

    with lock:
        snap = list(events)

    print(f"\n=== Got {len(snap)} sysex events ===")
    addr_hits = Counter()
    addr_first = {}
    addr_listen = Counter()
    for ts, e in snap:
        p = parse_dt1(e)
        if not p:
            continue
        addr_hits[p[0]] += 1
        if p[0] not in addr_first:
            addr_first[p[0]] = p[1]
        if ts >= t_listen:
            addr_listen[p[0]] += 1

    if not addr_hits:
        print("(no events)")
    else:
        print("\nAll hit counts (handshake + sniff):")
        for addr, n in addr_hits.most_common():
            payload = addr_first[addr]
            during = addr_listen.get(addr, 0)
            print(f"  0x{addr:08X}  total={n:4d}  during_listen={during:4d}  "
                  f"first={payload.hex().upper()[:60]}")

    # If we got tuner broadcasts, decode the most recent one
    tuner_payloads = [e for ts, e in snap if ts >= t_listen
                       and parse_dt1(e) and parse_dt1(e)[0] == 0x7F000300]
    if tuner_payloads:
        last = parse_dt1(tuner_payloads[-1])[1]
        if len(last) >= 12:
            n = last[0]
            note = NOTE_NAMES[n-1] if 1 <= n <= 12 else "----"
            print(f"\nMost-recent tuner broadcast: mono note={note} "
                  f"({n})  raw={last.hex().upper()[:48]}")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
