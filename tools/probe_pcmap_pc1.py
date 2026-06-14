#!/usr/bin/env python3
"""Read-only probe: dump MAP SELECT + the first N PROGRAM MAP entries of
all 3 PcmapPc banks, decoded to memory index + GX-10 label.

Purpose: confirm that what the device holds for the leading PC# rows of
each bank (after the user set MAP SELECT=PROG and bumped PC#1) matches
the expected decoding: 4 bytes, low nibble each, big-endian, masked
& 0x0F; 0xFFFF / >299 = unassigned.

Writes nothing. Safe to run any time.

Usage:
    python3 tools/probe_pcmap_pc1.py [--entries 8] [--port GX-10]
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

# Sibling tools in this same gx10-re/tools dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from midi_send import find_output_port, MidiOut, build_rq1   # type: ignore
import midi_sniff   # type: ignore
from device_id import require_alive_raw   # type: ignore

BANK_BASE = {1: 0x0010_0000, 2: 0x0010_0400, 3: 0x0010_0800}
MAP_SELECT_ADDR = 0x0000_3007
ENTRY_BYTES = 4


def parse_dt1(raw: bytes):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def open_session(port_substr: str = "GX-10"):
    events: list[tuple[float, bytes]] = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port(port_substr)
    if in_idx is None:
        raise SystemExit(f"no MIDI input matching {port_substr!r}")
    sniffer = midi_sniff.Sniffer(in_idx, Path("/tmp/__probe_nul.jsonl"), in_name)

    def _emit(o):
        if o.get("kind") == "sysex":
            try:
                with lock:
                    events.append((time.time(), bytes.fromhex(o["hex"])))
            except Exception:
                pass

    sniffer._emit = _emit
    sniffer.open()
    out_idx, _ = find_output_port(port_substr)
    if out_idx is None:
        raise SystemExit(f"no MIDI output matching {port_substr!r}")
    out = MidiOut(out_idx)
    time.sleep(0.3)
    require_alive_raw(out, events, lock)
    return sniffer, out, events, lock


def read_range(out, events, lock, addr: int, size: int, chunk: int = 0x40) -> bytes:
    """Chunked RQ1 read (matches the app's 0x40-byte chunking); a single
    512-byte RQ1 gets truncated by the device near ~240 bytes, so we
    loop in `chunk`-sized requests and reassemble by address."""
    buf = bytearray(size)
    seen = bytearray(size)
    offset = 0
    while offset < size:
        want = min(chunk, size - offset)
        with lock:
            events.clear()
        out.send_sysex(build_rq1(addr + offset, want))
        deadline = time.time() + 1.0
        while time.time() < deadline and sum(seen[offset:offset + want]) < want:
            with lock:
                new = list(events)
                events.clear()
            for _, raw in new:
                p = parse_dt1(raw)
                if not p:
                    continue
                pa, pp = p
                if addr <= pa < addr + size:
                    start = pa - addr
                    end = min(start + len(pp), size)
                    buf[start:end] = pp[:end - start]
                    for i in range(start, end):
                        seen[i] = 1
            time.sleep(0.02)
        offset += want
        time.sleep(0.03)
    return bytes(buf)


def decode4nib(cell: bytes) -> int:
    return ((cell[0] & 0x0F) << 12) | ((cell[1] & 0x0F) << 8) \
        | ((cell[2] & 0x0F) << 4) | (cell[3] & 0x0F)


def gx10_label(raw: int) -> str:
    if raw < 0 or raw > 299:
        return "----"
    if raw in (198, 199, 299):
        return "NIU"
    if raw < 198:
        return "U%02d-%d" % (raw // 3 + 1, raw % 3 + 1)
    p = raw - 200
    return "P%02d-%d" % (p // 3 + 1, p % 3 + 1)


def gx100_label(raw: int) -> str:
    if raw < 0 or raw > 299:
        return "----"
    if raw < 200:
        return "U%02d-%d" % (raw // 4 + 1, raw % 4 + 1)
    p = raw - 200
    return "P%02d-%d" % (p // 4 + 1, p % 4 + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", type=int, default=8)
    ap.add_argument("--port", default="GX-10")
    args = ap.parse_args()

    sniffer, out, events, lock = open_session(args.port)

    ms = read_range(out, events, lock, MAP_SELECT_ADDR, 1)
    ms_val = ms[0] if ms else None
    ms_label = {0: "FIX", 1: "PROG"}.get(ms_val, f"?({ms_val})")
    print(f"\nMAP SELECT @0x{MAP_SELECT_ADDR:08X} = {ms_val}  -> {ms_label}\n")

    n = args.entries
    for bank, base in BANK_BASE.items():
        size = n * ENTRY_BYTES
        data = read_range(out, events, lock, base, size)
        print(f"BANK {bank} @0x{base:08X}  (first {n} entries)")
        print(f"  {'row':<6}{'rawhex':<14}{'mem#':<6}{'GX-10':<8}{'GX-100'}")
        for i in range(n):
            cell = data[i * 4:i * 4 + 4]
            raw = decode4nib(cell)
            mem = raw if raw <= 299 else None
            hexs = " ".join("%02X" % b for b in cell)
            mems = str(mem) if mem is not None else "--"
            print(f"  PC{i:<4}{hexs:<14}{mems:<6}"
                  f"{gx10_label(raw):<8}{gx100_label(raw)}")
        print()


if __name__ == "__main__":
    main()
