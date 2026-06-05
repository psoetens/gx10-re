#!/usr/bin/env python3
"""Read the GX-10 edit buffer's chain list and report whether a
SPLITTER (FX TYPE 0x1E) sits between DIVIDER (0x1D) and MIXER (0x1F).

Motivation (2026-06-05): gxnarly bug #10 only triggers on a DIV/MIX
span WITHOUT a SPLITTER. BTS-edited chains always carry one; whether
the DEVICE's own front-panel "insert DIV" does too was unknown. Load
the patch in question on the device, connect over USB, run this.

Read-only: emits RQ1s against the edit buffer only.

    ~/.venvs/midi/bin/python3 tools/probe_chain_splitter.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from midi_send import build_rq1  # noqa: E402

import rtmidi  # noqa: E402

EDIT = 0x10000000
CHAIN_TOP = EDIT + 0x0F0C        # 1 byte, slot+1 (0 = empty)
CHAIN_NEXT = EDIT + 0x0F0D       # 49 bytes of next-pointers (slot+1)
SLOT_BASE = EDIT + 0x1100        # + slot*0x200: TYPE, ON, DUP, params
NAME = EDIT + 0x0000             # 16 ASCII bytes

TYPE_NAMES = {0x1D: "DIVIDER", 0x1E: "SPLITTER", 0x1F: "MIXER"}


def open_ports(substr: str = "GX-10"):
    mi, mo = rtmidi.MidiIn(), rtmidi.MidiOut()
    ip = next(i for i in range(mi.get_port_count()) if substr in mi.get_port_name(i))
    op = next(i for i in range(mo.get_port_count()) if substr in mo.get_port_name(i))
    mi.open_port(ip)
    mi.ignore_types(sysex=False)
    mo.open_port(op)
    return mi, mo


def main() -> int:
    mi, mo = open_ports()
    replies: dict[int, bytes] = {}
    cond = threading.Condition()

    def on_msg(event, _data):
        raw = bytes(event[0])
        # DT1: F0 41 dev 00 00 00 09 12? — GX framing per protocol.md:
        # command byte at index 8 == 0x12, addr big-endian at 9..12.
        if len(raw) >= 15 and raw[0] == 0xF0 and raw[-1] == 0xF7 and raw[8] == 0x12:
            addr = int.from_bytes(raw[9:13], "big")
            with cond:
                replies[addr] = raw[13:-2]
                cond.notify_all()

    mi.set_callback(on_msg)

    def read(addr: int, size: int, timeout: float = 1.5) -> bytes | None:
        mo.send_message(list(build_rq1(addr, size)))
        deadline = time.time() + timeout
        with cond:
            while addr not in replies:
                if not cond.wait(timeout=deadline - time.time()):
                    return None
                if time.time() > deadline and addr not in replies:
                    return None
        return replies[addr]

    name = read(NAME, 0x10)
    print(f"patch: {bytes(name).decode('ascii', 'replace').strip() if name else '<no reply>'}")

    chain = read(CHAIN_TOP, 0x32)
    if chain is None:
        print("no reply for chain list — is the device on USB and idle?")
        return 1
    top, nxt = chain[0], chain[1:]
    order: list[int] = []
    cur = top - 1
    while cur >= 0 and cur < 49 and len(order) < 25:
        order.append(cur)
        cur = (nxt[cur] - 1) if cur < len(nxt) else -1
    print(f"chain slots ({len(order)}): {order}")

    types: list[int] = []
    for slot in order:
        hdr = read(SLOT_BASE + slot * 0x200, 4)
        t = hdr[0] if hdr else -1
        types.append(t)
        label = TYPE_NAMES.get(t, f"0x{t:02X}")
        print(f"  slot {slot:2d}: type={label} on={hdr[1] if hdr else '?'} dup={hdr[2] if hdr else '?'}")

    if 0x1D in types:
        d, m = types.index(0x1D), types.index(0x1F) if 0x1F in types else len(types)
        between = types[d + 1:m]
        verdict = "YES" if 0x1E in between else "NO"
        print(f"\nSPLITTER between DIV and MIX: {verdict}")
        print(f"span DIV..MIX types: {[TYPE_NAMES.get(t, hex(t)) for t in types[d:m + 1]]}")
    else:
        print("\nno DIVIDER in this chain — load the DIV/MIX patch first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
