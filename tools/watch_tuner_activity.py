"""Persistent tuner-activity watcher.

  - Subscribes as editor (DT1 0x7F000001 = 1) so the device pushes
    state-change broadcasts.
  - Polls a small set of tuner-related addresses every 500ms.
  - Listens for any DT1 from the device.
  - Emits one stdout line per detected change of the watched fields,
    with a clear tag so it stands out in a Monitor stream.

Watched addresses:
  0x7F000002  RunningMode      (0=EDIT, 1=MONO_TUNER, 2=POLY_TUNER)
  0x7F000300  Tuner pitch      (mono+poly pitch broadcast)
  0x7F000701  Undocumented     (state-change notification — observed
                                  to flip when RunningMode changes)
  0x00001036  MODE_SWITCH      (BTS reads but ignores)
  0x00000006  SystemCommon.TunerMode
  0x00000007  SystemCommon.TunerType
  0x00200005  SetupTemp.TTMode
  0x00200007  SetupTemp.TTTargetName  (which note is detected)
  0x00200008  SetupTemp.TTCentOffset  (cents off pitch)

On Ctrl+C: unsubscribe (DT1 0x7F000001 = 0) so the device returns to
its pre-watcher state, then exit cleanly.
"""
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
from device_id import require_alive_raw


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]
RUNNING_MODE_NAMES = {0: "EDIT", 1: "MONO_TUNER", 2: "POLY_TUNER"}

POLL_ADDRS = [
    (0x7F000002, 1, "RunningMode"),
    (0x7F000701, 1, "0x7F000701 (state?)"),
    (0x00000006, 1, "SysCommon.TunerMode"),
    (0x00000007, 1, "SysCommon.TunerType"),
    (0x00200005, 1, "TTMode"),
    (0x00200007, 1, "TTTargetName"),
    (0x00200008, 1, "TTCentOffset"),
]
PUSH_ADDRS = {
    0x7F000300: "TUNER_PITCH",
    0x00001036: "MODE_SWITCH",
}


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def fmt_value(addr, payload):
    """Pretty-print a payload by what address it came from."""
    if not payload:
        return "(empty)"
    b = payload[0]
    if addr == 0x7F000002:
        return f"{b} ({RUNNING_MODE_NAMES.get(b, '?')})"
    if addr == 0x00200007:
        if b < 12:
            return f"{b} ({NOTE_NAMES[b]})"
        return f"{b}"
    if addr == 0x00200008:
        sb = b if b < 64 else b - 128
        return f"{b} ({sb:+d} cents)"
    if len(payload) <= 4:
        return f"0x{payload.hex().upper()}"
    return f"0x{payload.hex().upper()[:32]}…"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll-ms", type=int, default=500)
    ap.add_argument("--seconds", type=float, default=0,
                    help="Stop after N seconds (0 = run until Ctrl+C)")
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
    require_alive_raw(out, events, lock)

    # Subscribe as editor so the device pushes notifications
    out.send_sysex(build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.2)
    print("[init] subscribed (EditorCommunicationMode=1); polling every "
          f"{args.poll_ms}ms; watching {len(POLL_ADDRS)} polled fields + "
          f"{len(PUSH_ADDRS)} push fields", flush=True)

    last_values = {}    # addr -> last seen payload
    last_seen = 0
    started = time.time()
    next_poll = 0.0

    try:
        while True:
            now = time.time()
            if args.seconds and now - started >= args.seconds:
                break

            # Poll the small set of addresses
            if now >= next_poll:
                for addr, sz, _label in POLL_ADDRS:
                    out.send_sysex(build_rq1(addr, sz))
                    time.sleep(0.012)
                next_poll = now + args.poll_ms / 1000.0

            time.sleep(0.05)

            # Drain new events and flag changes
            with lock:
                new = list(events[last_seen:])
                last_seen = len(events)
            for ts, e in new:
                p = parse_dt1(e)
                if not p:
                    continue
                addr, payload = p
                # Push-broadcast addresses — dedupe identical consecutive
                # payloads so the idle-pattern stream doesn't flood the
                # output. Only print when the payload changed.
                if addr in PUSH_ADDRS:
                    label = PUSH_ADDRS[addr]
                    if last_values.get(addr) == payload:
                        continue   # silent, same as before
                    print(f"[push  ] 0x{addr:08X} {label:14s} = {fmt_value(addr, payload)}",
                          flush=True)
                    last_values[addr] = payload
                    continue
                # Polled addresses — only flag on change
                old = last_values.get(addr)
                if old != payload:
                    label = next((l for a, _, l in POLL_ADDRS if a == addr), f"0x{addr:08X}")
                    if old is None:
                        print(f"[init  ] 0x{addr:08X} {label:24s} = "
                              f"{fmt_value(addr, payload)}", flush=True)
                    else:
                        print(f"[CHANGE] 0x{addr:08X} {label:24s} : "
                              f"{fmt_value(addr, old)} -> {fmt_value(addr, payload)}",
                              flush=True)
                    last_values[addr] = payload
    except KeyboardInterrupt:
        print("[exit  ] Ctrl+C — unsubscribing", flush=True)
    finally:
        try:
            out.send_sysex(build_dt1(0x7F000001, b"\x00"))
            time.sleep(0.2)
        except Exception:
            pass

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
