"""Restore FxItem #0 from a snapshot.bin captured by sweep_all_types.py.

Writes back: TYPE byte first, then each FX Param 1..N as separate 4-byte DT1s.
Bulk DT1 of the whole block is silently rejected by the device.
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
from example_lib import GX10Session
from device_id import require_alive

FXITEM0_BASE = 0x10001100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True, help="path to snapshot.bin")
    ap.add_argument("--port", default="GX-10")
    args = ap.parse_args()

    data = Path(args.snapshot).read_bytes()
    print(f"snapshot: {len(data)} bytes; first 16: {data[:16].hex()}", flush=True)
    if len(data) < 7:
        print("ERROR: snapshot too short")
        return 2

    # GX10Session gives a sniffer for the identity check; we use
    # its .out for the actual writes.
    sess = GX10Session(port_substr=args.port)
    require_alive(sess)
    out = sess.out

    try:
        # 1. Write the FxItem header bytes (TYPE, ON/OFF, DupNum) individually
        for off in range(min(3, len(data))):
            msg = midi_send.build_dt1(FXITEM0_BASE + off, bytes([data[off]]))
            out.send_sysex(msg)
            time.sleep(0.01)
        print(f"  wrote header bytes 0..2", flush=True)

        # 2. Write each FX Param (4 bytes, starting at offset 0x03 stride 0x04) individually.
        # Cap at offset 0x7C so that FX-Param Param-32 (offset 0x7F-0x80 wrap) doesn't
        # trip the Roland 7-bit-per-byte address check. Effects only use ≤21 params anyway.
        n_written = 0
        for offset in range(0x03, min(len(data) - 3, 0x7C), 0x04):
            payload = data[offset:offset + 4]
            if len(payload) != 4:
                break
            if any(b > 0x7F for b in payload):
                continue
            msg = midi_send.build_dt1(FXITEM0_BASE + offset, payload)
            out.send_sysex(msg)
            time.sleep(0.005)
            n_written += 1
        print(f"  wrote {n_written} FX-Param 4-byte slots (offsets 0x03..0x7B)", flush=True)
        time.sleep(0.1)
    finally:
        try: sess.sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass
    print("done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
