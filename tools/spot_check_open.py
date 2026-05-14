"""Spot-check all chart-documented-but-unverified addresses in one pass.

Reads every "🧪 SPOT-CHECK" address from docs/gaps.md, decodes by the
chart's documented encoding, prints `addr | label | raw | decoded`.

Caller eyeballs the table against the on-device UI. Mismatches → bug,
matches → flip the gap entry from 🧪 to ✅.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff


# (addr, size, label, decoder_or_None)
# Decoders are simple enums; non-trivial ones decode below.
LOCK_NAMES = ["OFF", "ON"]
EXP_HOLD_NAMES = ["OFF", "ON"]
AUTO_OFF_NAMES = ["OFF", "10HOURS", "5HOURS", "1HOUR", "20MIN"]
FX_ORDER_NAMES = ["BY TYPE", "BY NAME"]
INPUT_TYPE = ["GUITAR", "BASS"]
OUTPUT_SELECT = [
    "LINE/PHONES",     # 0 (verified by user: recording-style output)
    "?1", "?2", "?3", "?4", "?5", "?6", "?7",
    "?8", "?9", "?10", "?11", "?12", "?13", "?14"
]
TUNER_OUTPUT = ["MUTE", "BYPASS", "THRU"]
CONTROL_MODE = {0: "UP/DOWN", 1: "MANUAL", 2: "BANK/NUM", 3: "MANUAL (alt)"}
THRU_NAMES = ["OFF", "ON", "USB-MIDI", "MIDI"]   # placeholder; see chart
CLOCK_OUT = ["OFF", "ON", "AUTO"]
MAP_SELECT = ["FIX", "PROG"]


def enum_decode(b: int, names):
    if 0 <= b < len(names):
        return f"{b}={names[b]}"
    return f"{b}=?"


# Chart-documented spot-check fields.
SPOT_CHECKS = [
    # (addr, size, label, decoder)

    # §1.3 SORT BY
    (0x00000018, 1, "FX ORDER (SortBy)", lambda p: enum_decode(p[0], FX_ORDER_NAMES)),

    # §6.1 HARDWARE
    (0x0000000D, 1, "EXP1 HOLD",         lambda p: enum_decode(p[0], EXP_HOLD_NAMES)),
    (0x0000000E, 1, "EXP2 HOLD",         lambda p: enum_decode(p[0], EXP_HOLD_NAMES)),
    (0x0000000F, 1, "AUTO OFF",          lambda p: enum_decode(p[0], AUTO_OFF_NAMES)),
    (0x00000011, 1, "LOCK (master?)",    lambda p: enum_decode(p[0], LOCK_NAMES)),
    (0x00000012, 1, "LOCK KNOB",         lambda p: enum_decode(p[0], LOCK_NAMES)),
    (0x00000013, 1, "LOCK TOUCH SCREEN", lambda p: enum_decode(p[0], LOCK_NAMES)),
    (0x00000014, 1, "LOCK BUTTON",       lambda p: enum_decode(p[0], LOCK_NAMES)),
    (0x00000015, 1, "LOCK OUTPUT LEVEL", lambda p: enum_decode(p[0], LOCK_NAMES)),

    # §6.2 PLAY OPTION
    (0x00001034, 1, "CONTROL MODE",      lambda p: f"{p[0]}={CONTROL_MODE.get(p[0],'?')}"),
    (0x00001064, 1, "FOOTSWITCH DOWN&UP Function", lambda p: f"{p[0]} (raw)"),
    (0x00001065, 1, "FOOTSWITCH UP&CTL1 Function", lambda p: f"{p[0]} (raw)"),

    # §6.3 MIDI SETTINGS
    (0x00003000, 1, "RX CHANNEL",        lambda p: f"{p[0]} (0..15 -> ch {p[0]+1})"),
    (0x00003002, 1, "TX CHANNEL",        lambda p: f"{p[0]} (0..15=ch+1, 16=RX)"),
    (0x00003004, 1, "MIDI IN THRU",      lambda p: f"{p[0]} (raw 4-value)"),
    (0x00003006, 1, "CLOCK OUT",         lambda p: enum_decode(p[0], CLOCK_OUT)),
    (0x00003007, 1, "MAP SELECT",        lambda p: enum_decode(p[0], MAP_SELECT)),
    (0x00003008, 1, "CC# NUM 1",         lambda p: f"CC{p[0]}"),
    (0x00003009, 1, "CC# NUM 2",         lambda p: f"CC{p[0]}"),
    (0x0000300A, 1, "CC# NUM 3",         lambda p: f"CC{p[0]}"),
    (0x0000300B, 1, "CC# NUM 4",         lambda p: f"CC{p[0]}"),
    (0x0000300C, 1, "CC# BANK DOWN",        lambda p: f"CC{p[0]}"),
    (0x0000300D, 1, "CC# BANK UP",        lambda p: f"CC{p[0]}"),
    (0x0000300E, 1, "CC# CTL1",          lambda p: f"CC{p[0]}"),
    (0x0000300F, 1, "CC# CTL2",          lambda p: f"CC{p[0]}"),
    (0x00003010, 1, "CC# CTL3",          lambda p: f"CC{p[0]}"),
    (0x00003011, 1, "CC# CTL4",          lambda p: f"CC{p[0]}"),
    (0x00003012, 1, "CC# EXP1 SW",       lambda p: f"CC{p[0]}"),
    (0x00003013, 1, "CC# EXP1",          lambda p: f"CC{p[0]}"),
    (0x00003014, 1, "CC# EXP2",          lambda p: f"CC{p[0]}"),

    # §4 IN/OUT
    (0x00006110, 1, "INPUT TYPE",        lambda p: enum_decode(p[0], INPUT_TYPE)),
    (0x00006111, 1, "INPUT SENS",        lambda p: f"{p[0]} (12..52 dB)"),
    (0x00001061, 1, "INPUT memory selector", lambda p: f"{p[0]} (0..9 = mem 1..10)"),
    (0x0000400C, 1, "OUTPUT SELECT",     lambda p: enum_decode(p[0], OUTPUT_SELECT)),

    # §4 GLOBAL EQ knobs (chart: SystemGlobalEq base 0x6B00, offsets 0x10..0x1A)
    (0x00006B10, 1, "EQ LOW GAIN",       lambda p: f"{p[0]} (raw, see chart for unit)"),
    (0x00006B11, 1, "EQ LOW MID GAIN",   lambda p: f"{p[0]}"),
    (0x00006B12, 1, "EQ LOW MID FREQ",   lambda p: f"{p[0]}"),
    (0x00006B13, 1, "EQ LOW MID Q",      lambda p: f"{p[0]}"),
    (0x00006B14, 1, "EQ HIGH MID GAIN",  lambda p: f"{p[0]}"),
    (0x00006B15, 1, "EQ HIGH MID FREQ",  lambda p: f"{p[0]}"),
    (0x00006B16, 1, "EQ HIGH MID Q",     lambda p: f"{p[0]}"),
    (0x00006B17, 1, "EQ HIGH GAIN",      lambda p: f"{p[0]}"),
    (0x00006B18, 1, "EQ LOW CUT",        lambda p: f"{p[0]}"),
    (0x00006B19, 1, "EQ HIGH CUT",       lambda p: f"{p[0]}"),
    (0x00006B1A, 1, "EQ LEVEL",          lambda p: f"{p[0]}"),
]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def main():
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
                    events.append(bytes.fromhex(o["hex"]))
            except Exception:
                pass
    s._emit = emit
    s.open()
    out_idx, _ = find_output_port("GX-10")
    out = MidiOut(out_idx)
    time.sleep(0.3)

    # Burst all RQ1s. 12 ms per send was measured safe on macOS / CoreMIDI
    # (45/45 replies across repeated runs, 2026-05-14). If you see drops
    # at the tail, bump this to 20–30 ms — the per-send overhead has
    # gotten the device near its input-queue limit once or twice when
    # another MIDI client (e.g. BTS) was contending for the port.
    print(f"Sending {len(SPOT_CHECKS)} RQ1s...")
    for addr, sz, _label, _dec in SPOT_CHECKS:
        out.send_sysex(build_rq1(addr, sz))
        time.sleep(0.012)
    time.sleep(2.0)

    with lock:
        snap = list(events)

    by_addr = {}
    for e in snap:
        p = parse_dt1(e)
        if p:
            by_addr[p[0]] = p[1]

    print(f"\n{'Addr':<14} | {'Field':<32} | Raw         | Decoded")
    print("-" * 90)
    missing = []
    for addr, sz, label, dec in SPOT_CHECKS:
        payload = by_addr.get(addr)
        if payload is None:
            missing.append((addr, label))
            print(f"0x{addr:08X}   | {label:<32} | (no reply)  | -")
            continue
        raw_hex = payload.hex().upper()
        try:
            decoded = dec(payload)
        except Exception as ex:
            decoded = f"(decode err: {ex})"
        print(f"0x{addr:08X}   | {label:<32} | {raw_hex:<11} | {decoded}")

    if missing:
        print(f"\n{len(missing)} address(es) returned no reply:")
        for addr, lbl in missing:
            print(f"  0x{addr:08X}  {lbl}")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
