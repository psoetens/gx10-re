"""Long-running broadcast listener for the GX-10.

Sets the editor-attach handshake (0x7F000001 = 0x01 + 0x7F000703 = 0x01),
then writes every incoming DT1 event to a JSONL file. On SIGTERM/SIGINT
restores the attach bit and exits cleanly.

Output JSONL (one event per line, sorted by arrival):
  {"t": 1.234, "addr_hex": "10001107", "addr": 268439815,
   "payload_hex": "08000604", "display": 100, "len": 4}

The "display" field is the 4-nibble offset-binary decode (raw - 0x8000)
when the payload is 4 bytes; null otherwise.

Usage:
    python tools/long_listener.py --out /tmp/sniff.jsonl --duration 600

The duration is just a max — stop early via SIGTERM (`kill <pid>`).
"""
import argparse
import json
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_io_linux import GxMidi


_running = True
_g = None


def _stop(signum, frame):
    global _running
    _running = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/sniff.jsonl")
    ap.add_argument("--duration", type=float, default=600.0,
                    help="max seconds to run; SIGTERM stops earlier")
    args = ap.parse_args()

    out_path = Path(args.out)
    # Truncate / start fresh so the user can re-launch without confusion
    out_path.write_text("")
    log = out_path.open("a", buffering=1)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    global _g
    _g = GxMidi()
    print(f"port: {_g.port_name}", file=sys.stderr)
    print(f"writing events to {out_path}", file=sys.stderr)

    # Set handshake
    _g.dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.005)
    _g.dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.05)
    _g.dt1(0x7F000703, bytes([0x00]))
    time.sleep(0.005)
    _g.dt1(0x7F000703, bytes([0x01]))
    time.sleep(0.1)
    _g.drain()
    print("handshake set; listening", file=sys.stderr)

    start = time.monotonic()
    deadline = start + args.duration
    n = 0
    try:
        while _running and time.monotonic() < deadline:
            for msg in _g.drain():
                if (len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7
                        or msg[8] != 0x12):
                    continue
                addr = ((msg[9] << 24) | (msg[10] << 16)
                        | (msg[11] << 8) | msg[12])
                payload = bytes(msg[13:-2])
                t = time.monotonic() - start
                disp = None
                if len(payload) == 4:
                    raw = (((payload[0] & 0xF) << 12)
                           | ((payload[1] & 0xF) << 8)
                           | ((payload[2] & 0xF) << 4)
                           | (payload[3] & 0xF))
                    disp = raw - 0x8000
                rec = {
                    "t":           round(t, 3),
                    "addr_hex":    f"{addr:08X}",
                    "addr":        addr,
                    "payload_hex": payload.hex(),
                    "display":     disp,
                    "len":         len(payload),
                }
                log.write(json.dumps(rec) + "\n")
                n += 1
            time.sleep(0.005)
    finally:
        # Restore handshake (best-effort)
        try:
            _g.dt1(0x7F000703, bytes([0x00]))
            time.sleep(0.05)
            _g.dt1(0x7F000001, bytes([0x00]))
            time.sleep(0.05)
        except Exception:
            pass
        _g.close()
        log.close()
        print(f"stopped after {time.monotonic() - start:.1f}s, "
              f"{n} events captured", file=sys.stderr)


if __name__ == "__main__":
    main()
