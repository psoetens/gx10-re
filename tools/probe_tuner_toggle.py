"""Probe the GX-10 tuner-mode toggle for the gxnarly "watch tuner on device"
feature.

Two questions:
  AUTO phase  — does writing RunningMode (0x7F000002 = 1/2/3) put the device
                into MONO/POLY/TT tuner, start the 0x7F000300 pitch stream,
                and restore cleanly to EDIT (=0)? Does the device echo any
                status mirror when WE set the mode?
  FRONTPANEL  — does the device emit a status mirror (0x7F000002 /
   phase        0x00000007 / 0x7F000701) when the user enters/exits tuner
                from the PEDAL? Determines whether gxnarly can keep its
                menu-button toggle in sync with hardware-initiated changes.

Editor-attach (0x7F000001 = 1) is sent first — RunningMode is silent until
then. Both fields are restored on exit so the device returns to EDIT.

Usage (device on USB, no other CoreMIDI client — pkill -f gxnarly first):
  python3 tools/probe_tuner_toggle.py --phase auto
  python3 tools/probe_tuner_toggle.py --phase frontpanel --seconds 15
"""
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1
import midi_sniff
from device_id import require_alive_raw

EDITOR_ATTACH = 0x7F000001
RUNNING_MODE  = 0x7F000002   # 0=EDIT 1=MONO 2=POLY 3=TT (mirror of 0x00000007)
RUNNING_MODE_CANON = 0x00000007
STATE_MIRROR  = 0x7F000701   # menu/chain-edit mode mirror (02/03/05/06)
TUNER_STREAM  = 0x7F000300   # 48-byte pitch buffer, ~5 Hz while in tuner
MODE_NAME = {0: "EDIT", 1: "MONO", 2: "POLY", 3: "TT"}
WATCH = {RUNNING_MODE: "RunningMode(0x7F000002)",
         RUNNING_MODE_CANON: "RunningMode(0x00000007)",
         STATE_MIRROR: "StateMirror(0x7F000701)"}


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7 or len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def open_link():
    events, lock = [], threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        raise SystemExit("no MIDI input matching 'GX-10'")
    s = midi_sniff.Sniffer(in_idx, Path("/tmp/__tuner_nul.jsonl"), in_name)

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
    return out, s, events, lock


def since(events, lock, t0):
    with lock:
        return [(t, r) for (t, r) in events if t >= t0]


def summarize(rows, t0):
    """Print status-mirror writes + tuner-stream count in a window."""
    stream = 0
    mirrors = []
    for t, r in rows:
        p = parse_dt1(r)
        if not p:
            continue
        addr, payload = p
        if addr == TUNER_STREAM:
            stream += 1
        elif addr in WATCH:
            mirrors.append((round(t - t0, 3), WATCH[addr], payload.hex().upper()))
    print(f"    tuner-stream (0x7F000300) frames: {stream}")
    if mirrors:
        for dt, name, hexv in mirrors:
            print(f"    +{dt:>5}s  {name} = {hexv}")
    else:
        print("    (no status-mirror echoes seen)")


def run_auto(out, events, lock):
    print("\n=== AUTO phase — set each tuner mode via MIDI, watch device ===")
    out.send_sysex(build_dt1(EDITOR_ATTACH, b"\x01"))
    time.sleep(0.2)
    for mode in (1, 2, 3):
        print(f"\n  RunningMode = {mode} ({MODE_NAME[mode]}) — "
              f"LOOK AT THE PEDAL (should show {MODE_NAME[mode]} tuner). "
              f"Pluck a string.")
        t0 = time.time()
        out.send_sysex(build_dt1(RUNNING_MODE, bytes([mode])))
        time.sleep(4.0)
        summarize(since(events, lock, t0), t0)
        out.send_sysex(build_dt1(RUNNING_MODE, b"\x00"))
        time.sleep(0.8)
    print("\n  Restored RunningMode = 0 (EDIT). Pedal should be back to normal.")


def run_frontpanel(out, events, lock, seconds):
    print("\n=== FRONTPANEL phase — YOU toggle the tuner on the pedal ===")
    out.send_sysex(build_dt1(EDITOR_ATTACH, b"\x01"))
    time.sleep(0.3)
    print(f"  Editor attached. You have {seconds:.0f}s:")
    print("    1) press/hold the pedal control that opens the TUNER,")
    print("    2) wait ~3s, then exit the tuner back to play mode.")
    print("  Watching for status-mirror echoes + stream ...")
    t0 = time.time()
    time.sleep(seconds)
    print(f"\n  --- captured over {seconds:.0f}s ---")
    summarize(since(events, lock, t0), t0)
    # If a mirror appeared, gxnarly can subscribe to it to sync its toggle.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["auto", "frontpanel"], default="auto")
    ap.add_argument("--seconds", type=float, default=15.0)
    args = ap.parse_args()
    out, sniffer, events, lock = open_link()
    try:
        if args.phase == "auto":
            run_auto(out, events, lock)
        else:
            run_frontpanel(out, events, lock, args.seconds)
    finally:
        # Always restore to EDIT + detach.
        out.send_sysex(build_dt1(RUNNING_MODE, b"\x00"))
        time.sleep(0.15)
        out.send_sysex(build_dt1(EDITOR_ATTACH, b"\x00"))
        time.sleep(0.15)
        try:
            sniffer.close()
        except Exception:
            pass
        out.close()
    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
