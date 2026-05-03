"""Pure-passive sniffer — listens for any DT1 the GX-10 broadcasts.

When the on-device tuner is active and BTS is running, BTS receives a
stream of DT1s at 0x7F000300 with pitch data. We sit quietly and log
everything the device sends for N seconds, then summarise per-address
hit counts.

Run while you've got the tuner active on the device. Wiggle a string
during the window so the pitch data changes.
"""
import argparse
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_sniff


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    addr = int.from_bytes(raw[9:13], "big")
    payload = bytes(raw[13:-2])
    return addr, payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
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
    print(f"Listening for {args.seconds}s — sending NO RQ1.")
    print("Wiggle a string / cycle the tuner to generate broadcasts.")
    time.sleep(args.seconds)
    with lock:
        snap = list(events)
    print(f"\nGot {len(snap)} sysex events.")
    addr_hits = Counter()
    addr_first = {}
    for ts, e in snap:
        p = parse_dt1(e)
        if not p:
            continue
        addr_hits[p[0]] += 1
        if p[0] not in addr_first:
            addr_first[p[0]] = (ts, p[1])
    if not addr_hits:
        print("(no DT1 broadcasts seen)")
    else:
        print("\nPer-address hit counts (most active first):")
        for addr, n in addr_hits.most_common():
            ts, payload = addr_first[addr]
            print(f"  0x{addr:08X}  hits={n:4d}  first_payload={payload.hex().upper()[:48]}")
    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
