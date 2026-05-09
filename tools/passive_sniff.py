"""Passive listener: open the GX-10 MIDI port and log every DT1
that comes in for N seconds. Used to identify which SysEx address
a UI control writes to when the user turns a knob.

Usage: python tools/passive_sniff.py [seconds]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_io_linux import GxMidi, parse_dt1_payload, hex_msg


def main(duration=15.0):
    g = GxMidi()
    print(f"sniffing on {g.port_name} for {duration}s — turn knobs now",
          file=sys.stderr)
    g.drain()
    start = time.monotonic()
    seen = {}        # addr -> list of (t_rel, payload)
    end = start + duration
    while time.monotonic() < end:
        msgs = g.drain()
        for msg in msgs:
            if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7:
                continue
            if msg[8] != 0x12:  # not a DT1
                continue
            addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
            payload = msg[13:-2]
            t_rel = time.monotonic() - start
            seen.setdefault(addr, []).append((t_rel, bytes(payload)))
        time.sleep(0.005)
    g.close()

    if not seen:
        print("no DT1 events captured", file=sys.stderr)
        return

    print(f"\n{len(seen)} unique address(es) seen:")
    for addr in sorted(seen):
        evs = seen[addr]
        print(f"\n  0x{addr:08X}  ({len(evs)} events, "
              f"first={evs[0][0]:.2f}s, last={evs[-1][0]:.2f}s)")
        # show first, middle, last
        idxs = sorted({0, len(evs)//2, len(evs)-1})
        for i in idxs:
            t, p = evs[i]
            # decode 4-nibble for context
            if len(p) == 4:
                raw = ((p[0] & 0xF) << 12) | ((p[1] & 0xF) << 8) \
                    | ((p[2] & 0xF) << 4) | (p[3] & 0xF)
                disp = raw - 0x8000
                print(f"    +{t:6.2f}s  {hex_msg(p)}  raw=0x{raw:04X}  display={disp}")
            else:
                print(f"    +{t:6.2f}s  {hex_msg(p)}  ({len(p)} bytes)")


if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    main(dur)
