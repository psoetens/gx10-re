"""
Write a saved snapshot back to the device's live edit buffer. Useful for
restoring U10-1 INIT state between effect-mapping experiments.

Walks the snapshot in address order, batches contiguous bytes into single
DT1 writes (so we send fewer, larger messages instead of one DT1 per byte).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
from example_lib import GX10Session
from device_id import require_alive


def restore(snap_path: Path, addr_min: int, addr_max: int, gap: float = 0.005):
    raw = json.loads(snap_path.read_text())
    items = sorted((int(a, 16), b) for a, b in raw.items())
    items = [(a, b) for a, b in items if addr_min <= a < addr_max]

    # GX10Session gives a sniffer + MidiOut; require_alive does the
    # strict identity/product check before we start writing.
    sess = GX10Session()
    require_alive(sess)
    out = sess.out
    # editor-attached
    out.send_sysex(midi_send.build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.2)

    # Group contiguous addresses into runs, but cap each run at ~32 bytes so
    # the DT1 SysEx stays comfortably under USB-MIDI single-transfer limits.
    MAX_RUN = 32
    runs = []
    cur_start = None
    cur_data = bytearray()

    def emit(start, data):
        if not data:
            return
        # Address bytes must all be <=0x7F; check at run start
        if any(b > 0x7F for b in start.to_bytes(4, "big")):
            print(f"skip non-7bit-clean addr {start:08X}", file=sys.stderr)
            return
        # All payload bytes must also be <=0x7F. INIT data should already be.
        if any(b > 0x7F for b in data):
            # split at offending byte: write everything before, skip the bad one
            for i, b in enumerate(data):
                if b > 0x7F:
                    if i > 0:
                        runs.append((start, bytes(data[:i])))
                    if i + 1 < len(data):
                        emit(start + i + 1, data[i + 1:])
                    return
        runs.append((start, bytes(data)))

    for addr, byte in items:
        if cur_start is None:
            cur_start = addr
            cur_data = bytearray([byte])
        elif addr == cur_start + len(cur_data) and len(cur_data) < MAX_RUN:
            cur_data.append(byte)
        else:
            emit(cur_start, cur_data)
            cur_start = addr
            cur_data = bytearray([byte])
    if cur_data:
        emit(cur_start, cur_data)

    print(f"restoring {len(runs)} runs from {snap_path.name}", file=sys.stderr)
    try:
        for addr, data in runs:
            out.send_sysex(midi_send.build_dt1(addr, data))
            time.sleep(gap)
    finally:
        try: sess.sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass
    print("done", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snap")
    ap.add_argument("--addr-min", type=lambda x: int(x, 16), default=0x10000000)
    ap.add_argument("--addr-max", type=lambda x: int(x, 16), default=0x10004000)
    ap.add_argument("--gap", type=float, default=0.005)
    args = ap.parse_args()
    restore(Path(args.snap), args.addr_min, args.addr_max, args.gap)


if __name__ == "__main__":
    main()
