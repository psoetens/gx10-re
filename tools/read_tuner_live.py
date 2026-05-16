"""Live tuner-pitch reader.

The active-tuner data lives at 0x7F000300 (48 bytes, undocumented in
the chart but visible in BTS source as ADDRESS_CONST.COMMAND.TUNER).
Layout per BTS midi_observe_controller.js:

  byte  0      monoNote      (0..11 = C..B; 0 = no signal)
  byte  1..4   monoPitch     (4-nibble cents-from-target signed)
  byte  5      isJustTune    (0/1 — perfect-tune flag)
  bytes 6..11  reserved/padding

  Then 7 polyphonic-string blocks of 12 bytes each:
    byte 0    polyNote        (0 = no signal)
    bytes 1..4 polyPitch
    byte 5    polyIsJustTune
    bytes 6..11 padding

Plus there's MODE_SWITCH at 0x00001036 — a 1-byte notification the
device pushes when toggling tuner / mode-related state.

Usage:
  python tools/read_tuner_live.py             # one snapshot + 5s sniff
  python tools/read_tuner_live.py --watch     # keep polling, Ctrl+C to stop
"""
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff
from device_id import require_alive_raw


TUNER_ADDR = 0x7F000300
TUNER_SIZE = 48
MODE_SWITCH_ADDR = 0x00001036
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    addr = int.from_bytes(raw[9:13], "big")
    payload = bytes(raw[13:-2])
    return addr, payload


def decode_4nibble(bs):
    if len(bs) < 4:
        return None
    return ((bs[0] & 0xF) << 12 | (bs[1] & 0xF) << 8 |
            (bs[2] & 0xF) << 4 | (bs[3] & 0xF))


def decode_tuner(payload):
    if len(payload) < 12:
        return None
    out = {}
    out["mono_note"] = payload[0]
    out["mono_pitch"] = decode_4nibble(payload[1:5])
    out["mono_just"] = payload[5] if len(payload) > 5 else None
    polys = []
    for i in range(7):
        off = 12 + i * 12
        if off + 6 > len(payload):
            break
        note = payload[off] if off < len(payload) else 0
        pitch = decode_4nibble(payload[off+1:off+5]) if off+5 <= len(payload) else None
        just = payload[off+5] if off+5 < len(payload) else None
        polys.append({"note": note, "pitch": pitch, "just": just})
    out["polys"] = polys
    return out


def fmt_tuner(d):
    if d is None:
        return "(no payload)"
    mono_n = d["mono_note"]
    mono_str = (f"{NOTE_NAMES[mono_n-1]}" if 1 <= mono_n <= 12
                else "----" if mono_n == 0 else f"?{mono_n}")
    parts = [f"MONO: note={mono_str:4s} pitch={d['mono_pitch']} just={d['mono_just']}"]
    polys_str = []
    for i, p in enumerate(d["polys"], 1):
        if p["note"]:
            n = NOTE_NAMES[p["note"]-1] if 1 <= p["note"] <= 12 else f"?{p['note']}"
            polys_str.append(f"S{i}={n}/{p['pitch']}")
    if polys_str:
        parts.append("POLY: " + " ".join(polys_str))
    return "  ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true",
                    help="Continuously poll the tuner address until Ctrl+C")
    ap.add_argument("--seconds", type=float, default=5.0,
                    help="Sniff window duration (one-shot mode)")
    args = ap.parse_args()

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
    time.sleep(0.3)
    require_alive_raw(out, events, lock)

    if args.watch:
        print("Polling 0x7F000300 every 100ms — Ctrl+C to stop.")
        last_seen = 0
        try:
            while True:
                out.send_sysex(build_rq1(TUNER_ADDR, TUNER_SIZE))
                time.sleep(0.1)
                with lock:
                    new = list(events[last_seen:])
                    last_seen = len(events)
                for ev in new:
                    p = parse_dt1(ev)
                    if not p:
                        continue
                    if p[0] == TUNER_ADDR:
                        d = decode_tuner(p[1])
                        print(f"[tuner] {fmt_tuner(d)}", flush=True)
                    elif p[0] == MODE_SWITCH_ADDR:
                        print(f"[mode-switch] payload={p[1].hex().upper()}", flush=True)
        except KeyboardInterrupt:
            pass
    else:
        # One probe + listen
        print("Probing 0x7F000300 + listening for tuner broadcasts...")
        out.send_sysex(build_rq1(TUNER_ADDR, TUNER_SIZE))
        out.send_sysex(build_rq1(MODE_SWITCH_ADDR, 1))
        time.sleep(args.seconds)
        with lock:
            snap = list(zip(timestamps, events))
        tuner_count = 0
        mode_count = 0
        first_tuner = None
        first_mode = None
        for ts, e in snap:
            p = parse_dt1(e)
            if not p:
                continue
            if p[0] == TUNER_ADDR:
                tuner_count += 1
                if first_tuner is None:
                    first_tuner = p[1]
            elif p[0] == MODE_SWITCH_ADDR:
                mode_count += 1
                if first_mode is None:
                    first_mode = p[1]
        print(f"\nTuner broadcasts (0x7F000300): {tuner_count}")
        if first_tuner:
            d = decode_tuner(first_tuner)
            print(f"  first payload (raw): {first_tuner.hex().upper()}")
            print(f"  decoded: {fmt_tuner(d)}")
        print(f"\nMODE_SWITCH (0x00001036): {mode_count}")
        if first_mode:
            print(f"  payload: {first_mode.hex().upper()}  (= byte {first_mode[0]})")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
