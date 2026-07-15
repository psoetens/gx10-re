"""Probe the undocumented LOOPER_CONTROL runtime register (0x7F000705).

BTS v1.0.0 ships `LOOPER_CONTROL: 0x7f000705` in address_const.js's
COMMAND block (the 0x7F00xxxx runtime-register family we already use
for editor subscribe 0x7F000001 and tuner/running-mode 0x7F000002).
The only reference is a commented-out GT-1000-era connect-time
`RQ1(LOOPER_CONTROL, 4)` gated on communication level >= 2 (the GX-10
reports 3), so the register is *plausibly* implemented in firmware but
has never been exercised against a GX-10. Same story for
`MODE_SWITCH: 0x00001036` (read by the same dead code to "get control
mode status"; distinct from the CONTROL_MODE config byte 0x00001034 —
suspected runtime memory<->manual flag flipped by the MEMORY/MAN
footswitch function).

This probe answers, in order:
  1. Does 0x7F000705 reply to RQ1 at all, and with how many bytes?
  2. Do its bytes track looper transport state (stop/rec/play/dub)
     while the physical LOOP CTL / LOOPER STOP / LOOPER CLEAR pedals
     are operated?
  3. Does 0x00001036 track MEMORY/MAN (manual-mode) switching?
  4. Do looper pedal presses broadcast any *other* runtime DT1s while
     editor events are subscribed?
  5. (--write only) Does DT1-writing an observed value back drive the
     looper transport?

Operator script (phase 1, read-only — the default):
  a. Close BTS / gxnarly (single MIDI consumer).
  b. Load a memory whose chain contains PHRASE LOOP; set a footswitch
     FUNC to LOOP CTL (and ideally another to LOOPER STOP), control
     mode MANUAL.
  c. Run:  python tools/probe_looper_control.py
  d. Stomp: record -> play -> overdub -> stop -> clear, pausing ~2 s
     between presses so transitions attribute cleanly. Also toggle
     MEMORY/MAN if a switch has it.
  e. Ctrl-C for the transition summary.

Phase 2 (ONLY after phase 1 shows a live register; writes an
observed value back, then keeps observing):
     python tools/probe_looper_control.py --write 02
     python tools/probe_looper_control.py --write "00 00 00 02"

Findings go to docs/protocol.md (runtime-register table) once
hardware-verified.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1, build_dt1
import midi_sniff
from device_id import require_alive_raw

LOOPER_CONTROL = 0x7F000705
MODE_SWITCH = 0x00001036
CONTROL_MODE = 0x00001034     # config byte, for reference alongside 0x1036
EDITOR_SUBSCRIBE = 0x7F000001

POLL_REGS = [
    ("LOOPER_CONTROL", LOOPER_CONTROL, 4),
    ("MODE_SWITCH",    MODE_SWITCH,    4),
    ("CONTROL_MODE",   CONTROL_MODE,   1),
]
POLL_PERIOD_S = 0.25
INTER_RQ1_S = 0.015           # empirical: >30 unpaced RQ1s drop replies
NO_REPLY_CYCLES = 8           # ~2 s silent -> call the register dead


def parse_dt1(raw: bytes):
    """(addr, payload) for a Roland DT1, else None."""
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def hexs(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", metavar="HEXBYTES",
                    help="phase 2: DT1 these bytes (e.g. '02' or "
                         "'00 00 00 02') to LOOPER_CONTROL, then observe")
    ap.add_argument("--write-addr", type=lambda s: int(s, 16),
                    default=LOOPER_CONTROL, metavar="HEX",
                    help="override --write target address "
                         "(default 7F000705)")
    ap.add_argument("--no-subscribe", action="store_true",
                    help="skip the 0x7F000001=01 editor-event subscribe")
    ap.add_argument("--port", default="GX-10",
                    help="MIDI port substring (default GX-10)")
    args = ap.parse_args()

    events: list[bytes] = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port(args.port)
    if in_idx is None:
        print(f"ERROR: no MIDI input port matching '{args.port}'")
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
    out_idx, _ = find_output_port(args.port)
    if out_idx is None:
        print("ERROR: no output port")
        sys.exit(2)
    out = MidiOut(out_idx)
    time.sleep(0.4)
    require_alive_raw(out, events, lock)

    subscribed = False
    if not args.no_subscribe:
        # Same host-register handshake BTS/gxnarly use; makes the device
        # broadcast editor events so looper presses can reveal any other
        # runtime addresses. Unsubscribed again on exit.
        out.send_sysex(build_dt1(EDITOR_SUBSCRIBE, b"\x01"))
        subscribed = True
        time.sleep(0.1)

    poll_addrs = {addr for _, addr, _ in POLL_REGS}
    last_val: dict[int, bytes] = {}
    reply_seen: dict[int, bool] = {addr: False for addr in poll_addrs}
    silent_cycles: dict[int, int] = {addr: 0 for addr in poll_addrs}
    dead_announced: set[int] = set()
    transitions: list[tuple[float, str, str, str]] = []   # t, reg, old, new
    broadcasts: dict[int, list[bytes]] = {}
    t0 = time.time()
    consumed = 0

    def reg_name(addr: int) -> str:
        for n, a, _ in POLL_REGS:
            if a == addr:
                return n
        return f"0x{addr:08X}"

    def drain():
        nonlocal consumed
        with lock:
            fresh = events[consumed:]
            consumed = len(events)
        for raw in fresh:
            p = parse_dt1(raw)
            if p is None:
                continue
            addr, payload = p
            t = time.time() - t0
            if addr in poll_addrs:
                reply_seen[addr] = True
                silent_cycles[addr] = 0
                old = last_val.get(addr)
                if old != payload:
                    o = hexs(old) if old is not None else "(first)"
                    print(f"[{t:8.2f}s] {reg_name(addr):14s} "
                          f"{o:>12s} -> {hexs(payload)}")
                    transitions.append((t, reg_name(addr), o, hexs(payload)))
                    last_val[addr] = payload
            else:
                seen = broadcasts.setdefault(addr, [])
                if not seen or seen[-1] != payload:
                    print(f"[{t:8.2f}s] broadcast 0x{addr:08X} = "
                          f"{hexs(payload)}")
                    seen.append(payload)

    if args.write:
        payload = bytes(int(x, 16) for x in args.write.split())
        print(f"\n--write: DT1 0x{args.write_addr:08X} <- {hexs(payload)}")
        out.send_sysex(build_dt1(args.write_addr, payload))
        time.sleep(0.05)

    print("\nObserving. Operate the looper pedals now "
          "(record/play/dub/stop/clear, ~2 s apart). Ctrl-C to finish.\n")
    try:
        while True:
            for _, addr, size in POLL_REGS:
                out.send_sysex(build_rq1(addr, size))
                time.sleep(INTER_RQ1_S)
            time.sleep(POLL_PERIOD_S)
            drain()
            for addr in poll_addrs:
                if reply_seen[addr]:
                    continue
                silent_cycles[addr] += 1
                if silent_cycles[addr] == NO_REPLY_CYCLES and \
                        addr not in dead_announced:
                    dead_announced.add(addr)
                    print(f"  !! {reg_name(addr)} has not replied after "
                          f"{NO_REPLY_CYCLES} polls — likely "
                          f"unimplemented (RQ1 silently ignored)")
    except KeyboardInterrupt:
        pass
    finally:
        if subscribed:
            try:
                out.send_sysex(build_dt1(EDITOR_SUBSCRIBE, b"\x00"))
                time.sleep(0.05)
            except Exception:
                pass

    drain()
    print("\n=== SUMMARY ===")
    for name, addr, _ in POLL_REGS:
        if not reply_seen[addr]:
            print(f"{name:14s}  NO REPLY — register not implemented, or "
                  f"RQ1 size mismatch (try other sizes)")
        else:
            print(f"{name:14s}  last = {hexs(last_val.get(addr, b''))}")
    if transitions:
        print("\nTransitions:")
        for t, name, old, new in transitions:
            print(f"  [{t:8.2f}s] {name:14s} {old:>12s} -> {new}")
    if broadcasts:
        print("\nBroadcast addresses seen (non-polled):")
        for addr, vals in sorted(broadcasts.items()):
            print(f"  0x{addr:08X}  {len(vals)} value(s), "
                  f"last = {hexs(vals[-1])}")
    print("\nNext: if LOOPER_CONTROL tracked the transport, note the "
          "value per state and retry with --write <observed value>.")
    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == "__main__":
    main()
