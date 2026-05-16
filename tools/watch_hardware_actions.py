"""Passive watcher for on-device hardware events.

Subscribes as editor (DT1 0x7F000001 = 1) so the device pushes any
state-change broadcasts. Then logs every DT1 the device emits with
a human-readable address tag. No polling — purely event-driven.

Use this to find out whether the device emits notification DT1s
when the user:
  - presses a footswitch (BANK ▼/▲, CTL1, CTL2, NUM1..NUM4)
  - moves the EXP1 expression pedal (continuous CC?)
  - plugs / unplugs an external EXP2 pedal
  - turns a knob on the front panel
  - touches the front-panel touch screen
  - receives MIDI on the rear MIDI-IN DIN

Press one button / wiggle the pedal at a time so the trace is easy to
attribute. Hit Ctrl+C to stop. The script lists, on exit, every unique
address that emitted a DT1 and the count of payloads each.

Restoring `EditorCommunicationMode = 0` on exit so the device returns
to silent mode.
"""
import argparse
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1
import midi_sniff
from device_id import require_alive_raw


# Tags for addresses we already understand — anything else gets the
# generic "(unknown)" tag, which is the interesting case for new
# hardware-event addresses.
KNOWN_TAGS = {
    0x7F000300: "TUNER pitch broadcast (poly 48B)",
    0x00001036: "MODE_SWITCH",
    0x7F000002: "RunningMode",
    0x7F000701: "0x7F000701 (state?)",
    0x10000154: "0x10000154 (live FxItem byte?)",
    0x1000230F: "FxItem #10 FX Param 4 (mono cents)",
}


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def short_payload(p):
    h = p.hex().upper()
    if len(p) <= 16:
        return h
    return h[:32] + "..."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=0,
                    help="Stop after N seconds (0 = run until Ctrl+C)")
    ap.add_argument("--out", default="captures/hw_action_log.jsonl",
                    help="JSONL log file (one line per DT1)")
    args = ap.parse_args()

    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        print("ERROR: no MIDI input"); sys.exit(2)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = out_path.open("w", encoding="utf-8")

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
    require_alive_raw(out, events, lock)

    # Subscribe so the device pushes state changes
    out.send_sysex(build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.2)
    print("Subscribed (EditorCommunicationMode=1).")
    print("Now exercise the device hardware:")
    print("  - press each footswitch one at a time")
    print("  - sweep EXP1 from heel to toe and back")
    print("  - if you have an external EXP2: plug it in, wiggle, unplug")
    print("  - turn the front-panel rotary knob a few clicks")
    print("  - tap the touch screen briefly")
    print("  - send MIDI on the DIN if you have a source handy")
    print("Stop with Ctrl+C; script prints a summary and exits cleanly.\n", flush=True)

    addr_hits = Counter()
    addr_first_payload = {}
    seen = 0
    started = time.time()
    try:
        while True:
            if args.seconds and time.time() - started >= args.seconds:
                break
            time.sleep(0.05)
            with lock:
                new = list(events[seen:])
                seen = len(events)
            for ts, e in new:
                p = parse_dt1(e)
                if not p:
                    continue
                addr, payload = p
                tag = KNOWN_TAGS.get(addr, "(NEW)")
                addr_hits[addr] += 1
                addr_first_payload.setdefault(addr, payload)
                # Only log/print first 6 hits per addr, plus every change of payload
                # (otherwise tuner/sweep streams flood)
                line = (f"{ts:.3f}  0x{addr:08X}  {tag:<40s}  "
                        f"{len(payload):3d}B  {short_payload(payload)}")
                # Console: print only first 6 per addr OR if payload differs from first
                if (addr_hits[addr] <= 6
                        or addr_first_payload[addr] != payload):
                    print(line, flush=True)
                # Log: everything
                import json
                log_fh.write(json.dumps({
                    "ts": ts, "addr": f"{addr:08X}", "tag": tag,
                    "len": len(payload), "hex": payload.hex().upper()
                }) + "\n")
    except KeyboardInterrupt:
        print("\n[Ctrl+C] stopping...", flush=True)
    finally:
        try:
            out.send_sysex(build_dt1(0x7F000001, b"\x00"))
            time.sleep(0.2)
        except Exception:
            pass

    log_fh.close()

    print(f"\n=== {sum(addr_hits.values())} DT1 events; {len(addr_hits)} unique addresses ===")
    print(f"Full log: {out_path}\n")
    print(f"{'Addr':<12} {'Tag':<42} {'Hits':>5}  {'First payload':<32}")
    print("-" * 100)
    for addr, n in addr_hits.most_common():
        tag = KNOWN_TAGS.get(addr, "(NEW)")
        first = short_payload(addr_first_payload[addr])
        print(f"0x{addr:08X}  {tag:<42} {n:5d}  {first}")

    # Highlight new addresses not in the known set
    new_addrs = [a for a in addr_hits if a not in KNOWN_TAGS]
    if new_addrs:
        print(f"\n*** {len(new_addrs)} previously-unknown address(es) ***")
        for a in new_addrs:
            print(f"  0x{a:08X}  hits={addr_hits[a]}  first={short_payload(addr_first_payload[a])}")
    else:
        print("\n(no new addresses — only known channels emitted)")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
