#!/usr/bin/env python3
"""Read a user-memory slot using BTS's EXACT region layout and size
encoding, observed in `captures/bts_import_export/`.

**RQ1 size is the REQUEST CEILING — not the response length.** The
device returns one DT1 per natural record at the addresses inside the
request, *regardless* of the size you ask for. For example
`RQ1 0x1100 size=0x103` returns one DT1 of **131** bytes (the slot
main's natural record), not 259 bytes. See
`reports/merge_read_findings.md` for the empirical proof; see
`docs/protocol.md` §3.1.2 for the corrected size-encoding rule.

Request sizes BTS uses (raw big-endian, every byte ≤ 0x7F):
  - 0x0000 +0x100   — header           (device returns 128 B)
  - 0x0100 +0x01    — misc             (1 B)
  - 0x0140 +0x1C    — knob block       (28 B)
  - 0x0200..+0xB40 in 0x2D chunks paired at +0x40 — assigns (45 B each)
  - 0x0F00 +0x3E    — master + chain   (62 B)
  - per slot: 0x1100+i*0x200 +0x103, 0x1203+i*0x200 +0x30 — device
    returns 131 B + 48 B (the BTS "atomic slot-main" + "slot-ext"
    records — NOT 259 + 48).

A single `RQ1 size=0x4000` against the slot base returns ALL 64 BTS
regions in ~43 DT1s in one round-trip; see
`tools/probe_merge_sizes.py` and `reports/merge_read_findings.md`.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rtmidi  # noqa: E402
import midi_io  # noqa: E402

SYSEX_HEADER = bytes([0xF0, 0x41, 0x10, 0x00, 0x00, 0x00, 0x00, 0x0B])
RQ1, DT1 = 0x11, 0x12


def checksum(addr_and_payload):
    return (0x80 - (sum(addr_and_payload) & 0x7F)) & 0x7F


def make_rq1(addr: int, size: int) -> bytes:
    """Raw big-endian size encoding (BTS-compatible).
    Caller must ensure each byte of `size` is ≤ 0x7F."""
    a = bytes([(addr >> 24) & 0x7F, (addr >> 16) & 0x7F,
               (addr >> 8) & 0x7F, addr & 0x7F])
    s = bytes([(size >> 24) & 0xFF, (size >> 16) & 0xFF,
               (size >> 8) & 0xFF, size & 0xFF])
    for b in s:
        if b > 0x7F:
            raise ValueError(f"size 0x{size:X} has byte 0x{b:02X} > 0x7F — illegal SysEx")
    body = a + s
    return SYSEX_HEADER + bytes([RQ1]) + body + bytes([checksum(body), 0xF7])


def parse_dt1(msg: bytes) -> tuple:
    """Returns (addr, payload) or None."""
    if len(msg) < 14: return None
    if msg[0] != 0xF0 or msg[-1] != 0xF7: return None
    if msg[1:8] != SYSEX_HEADER[1:]: return None
    if msg[8] != DT1: return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    payload = msg[13:-2]
    return (addr, payload)


def user_memory_address(n: int) -> int:
    base_lin = 0x4000000
    stride_lin = 0x18000
    lin = base_lin + n * stride_lin
    a = (lin >> 21) & 0x7F
    b = (lin >> 14) & 0x7F
    c = (lin >> 7)  & 0x7F
    d = lin & 0x7F
    return (a << 24) | (b << 16) | (c << 8) | d


def bts_regions():
    """Exact layout BTS uses, from import_export.jsonl capture."""
    regions = [
        (0x0000, 0x100),  # header — 256 bytes
        (0x0100, 0x01),   # misc
        (0x0140, 0x1C),   # knob block
    ]
    # Assign rows: 0x0200..0xB40 paired at +0x00 / +0x40, 45 bytes each
    for pair in range(10):
        row_base = 0x0200 + pair * 0x100
        regions.append((row_base,        0x2D))
        regions.append((row_base + 0x40, 0x2D))
    regions.append((0x0F00, 0x3E))  # master + chain
    # 20 slots: BTS requests 0x103 at +0x00 (device returns 131-B
    # natural record), then 0x30 at +0x103 (device returns 48 B).
    for slot in range(20):
        slot_base = 0x1100 + slot * 0x200
        regions.append((slot_base,         0x103))  # main
        regions.append((slot_base + 0x103,  0x30))  # ext
    return regions


def wire_to_linear(wire: int) -> int:
    """Convert a 4-byte 7-bit-packed wire address to its 28-bit linear
    value. Each wire byte is ≤ 0x7F; the linear address is the four
    7-bit groups concatenated. This is how the GX-10 increments
    addresses across DT1 splits: wire byte3 wraps at 0x7F → byte2
    increments → byte3 resets to 0x00. Straight arithmetic on wire
    addresses gives the wrong offset for multi-DT1 responses."""
    b0 = (wire >> 24) & 0x7F
    b1 = (wire >> 16) & 0x7F
    b2 = (wire >> 8)  & 0x7F
    b3 =  wire        & 0x7F
    return (b0 << 21) | (b1 << 14) | (b2 << 7) | b3


class Probe:
    def __init__(self, port_substr="GX-10"):
        self.out = rtmidi.MidiOut()
        self.inp = rtmidi.MidiIn()
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        for i, name in enumerate(self.out.get_ports()):
            if port_substr in name:
                self.out.open_port(i); break
        for i, name in enumerate(self.inp.get_ports()):
            if port_substr in name:
                self.inp.open_port(i); break
        self._buf = []
        self.inp.set_callback(self._on_msg)
        self.last_dt1_count = 0
        self.last_dt1_addrs: list[int] = []

    def _on_msg(self, evt, _user=None):
        self._buf.append(bytes(evt[0]))

    def drain(self):
        out, self._buf = self._buf, []
        return out

    def request(self, addr, size, timeout=2.0):
        """Send RQ1, return concatenated DT1 payload (covering
        [addr, addr+size)) or None on timeout. Offsets within `result`
        are LINEAR offsets from the request base — converting each DT1's
        wire address via `wire_to_linear` so multi-DT1 responses whose
        addresses cross a 7-bit byte boundary land at the right index.
        Tracks `last_dt1_count` / `last_dt1_addrs` for callers that
        want to see how the device split the response."""
        self.drain()
        self.out.send_message(list(make_rq1(addr, size)))
        deadline = time.monotonic() + timeout
        result = bytearray(size)
        covered = bytearray(size)
        total = 0
        last = time.monotonic()
        base_lin = wire_to_linear(addr)
        dt1_count = 0
        dt1_addrs: list[int] = []
        while time.monotonic() < deadline:
            msgs = self.drain()
            if msgs:
                last = time.monotonic()
                for m in msgs:
                    parsed = parse_dt1(m)
                    if parsed is None: continue
                    p_addr, p_data = parsed
                    dt1_count += 1
                    dt1_addrs.append(p_addr)
                    p_off = wire_to_linear(p_addr) - base_lin
                    if 0 <= p_off < size:
                        for j, b in enumerate(p_data):
                            if p_off + j < size and not covered[p_off + j]:
                                result[p_off + j] = b
                                covered[p_off + j] = 1
                                total += 1
            if total >= size:
                break
            # Debounce: ≥ 400 ms of silence with some data already in
            # → accept partial. Bumped from 250 ms because the GX-10
            # sometimes spaces multi-DT1 responses by ~300 ms on this
            # firmware (observed during merge probing, 2026-05-29).
            if time.monotonic() - last > 0.4 and total > 0:
                break
            time.sleep(0.005)
        self.last_dt1_count = dt1_count
        self.last_dt1_addrs = dt1_addrs
        if total == 0:
            return None
        if total >= size:
            return bytes(result)
        # Truncate to the highest covered byte so the caller doesn't see
        # trailing zeros from uncovered positions in the sparse buffer.
        end = max((i + 1 for i, c in enumerate(covered) if c), default=0)
        return bytes(result[:end])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v", type=int, default=33)
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()

    base = user_memory_address(args.v)
    print(f"# V={args.v} body @ 0x{base:08X}")

    p = Probe()
    buf = bytearray(0x4000)
    regions = bts_regions()
    failed = 0
    for i, (off, size) in enumerate(regions):
        time.sleep(0.02)
        data = p.request(base + off, size, timeout=2.0)
        if data is None or len(data) == 0:
            failed += 1
            continue
        n = min(len(data), size)
        for j in range(n):
            buf[off + j] = data[j]
    nonzero = sum(1 for b in buf if b != 0)
    print(f"# regions: {len(regions) - failed}/{len(regions)} ok")
    print(f"# non-zero bytes captured: {nonzero}")

    # Diagnostic: name, chain TOP, slot types
    name = bytes(buf[:16]).decode('ascii', errors='replace').rstrip()
    top = buf[0x0F0C]
    print(f"# name: {name!r}, chain TOP byte = {top}")
    print(f"# slot types (slot, type byte, on byte):")
    for n in range(20):
        b = 0x1100 + n * 0x200
        print(f"  slot {n:>2}: type={buf[b]:>3} on={buf[b+1]}")

    if args.output:
        out = {}
        for off in range(0x4000):
            if buf[off] != 0:
                out[f"{0x10000000 + off:08X}"] = buf[off]
        args.output.write_text(json.dumps(out, indent=2))
        print(f"# wrote {args.output} ({len(out)} non-zero)")


if __name__ == "__main__":
    sys.exit(main() or 0)
