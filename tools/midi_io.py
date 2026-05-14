"""Cross-platform MIDI I/O for GX-10 / GX-100 probing.

python-rtmidi backend — CoreMIDI on macOS, ALSA on Linux, WinMM on
Windows. This is the canonical I/O module. `midi_send.py` and
`midi_sniff.py` remain as thin compatibility shims (their API is kept
stable for the original Windows-RE tooling) and on non-Windows
delegate here.

  - find_port(name_substr)        -> port index for I/O
  - send_sysex(port_idx, data)    -> bytes
  - rq1(addr, size_in_bytes)      -> raw bytes for a Roland RQ1
  - dt1(addr, data_bytes)         -> raw bytes for a Roland DT1
  - identity_request()            -> raw bytes (broadcast)
  - identity_reply(timeout=2.0)   -> first F0 7E .. 06 02 .. F7 message
  - rq1_read(addr, size, timeout) -> the 4..N data bytes returned for an RQ1

CLI:
    python midi_io.py --identity
    python midi_io.py --rq1 10000000 00000010
    python midi_io.py --dt1 1000000F 04
"""
import argparse
import sys
import time
import threading

try:
    import rtmidi
except ImportError:
    sys.stderr.write("python-rtmidi not installed; pip install python-rtmidi\n")
    raise

DEVICE_PORT_SUBSTR = "GX-10"  # also matches GX-100

# Roland framing
SYSEX_HEADER = bytes([0xF0, 0x41, 0x10, 0x00, 0x00, 0x00, 0x00, 0x0B])
RQ1, DT1 = 0x11, 0x12
IDENTITY_REQUEST = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])


def _checksum(addr_and_data: bytes) -> int:
    return (0x80 - (sum(addr_and_data) & 0x7F)) & 0x7F


def _addr_bytes(addr: int) -> bytes:
    return bytes([(addr >> 24) & 0x7F, (addr >> 16) & 0x7F,
                  (addr >> 8) & 0x7F, addr & 0x7F])


def _size_bytes(size: int) -> bytes:
    return bytes([(size >> 24) & 0x7F, (size >> 16) & 0x7F,
                  (size >> 8) & 0x7F, size & 0x7F])


def rq1(addr: int, size: int) -> bytes:
    """Build a Roland RQ1 (data request) SysEx for `size` bytes at `addr`."""
    body = _addr_bytes(addr) + _size_bytes(size)
    return SYSEX_HEADER + bytes([RQ1]) + body + bytes([_checksum(body), 0xF7])


def dt1(addr: int, data: bytes) -> bytes:
    """Build a Roland DT1 (data set) SysEx that writes `data` at `addr`."""
    body = _addr_bytes(addr) + bytes(data)
    return SYSEX_HEADER + bytes([DT1]) + body + bytes([_checksum(body), 0xF7])


def find_port(midi_io, name_substr=DEVICE_PORT_SUBSTR):
    for i, name in enumerate(midi_io.get_ports()):
        if name_substr in name:
            return i, name
    return None, None


class GxMidi:
    """Open both input and output to the GX device. The GX exposes one
    bidirectional ALSA port; we open it once for read and once for write.
    """

    def __init__(self, port_substr=DEVICE_PORT_SUBSTR):
        self.out = rtmidi.MidiOut()
        out_idx, out_name = find_port(self.out, port_substr)
        if out_idx is None:
            raise RuntimeError(f"no MIDI OUT port matching {port_substr!r}")
        self.out.open_port(out_idx)

        self.inp = rtmidi.MidiIn()
        # Allow long SysEx through (default ignores SysEx)
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        in_idx, in_name = find_port(self.inp, port_substr)
        if in_idx is None:
            self.out.close_port()
            raise RuntimeError(f"no MIDI IN port matching {port_substr!r}")
        self.inp.open_port(in_idx)
        self._buf = []
        self._lock = threading.Lock()
        self.inp.set_callback(self._on_msg)
        self.port_name = out_name

    def _on_msg(self, evt, _user=None):
        msg, _ts = evt
        with self._lock:
            self._buf.append(bytes(msg))

    def send(self, data: bytes):
        # rtmidi expects a list of ints
        self.out.send_message(list(data))

    def drain(self):
        with self._lock:
            out, self._buf = self._buf, []
        return out

    def wait_for(self, predicate, timeout=2.0, poll=0.01):
        """Wait until predicate(msg) returns True for some incoming message,
        return that message. Returns None on timeout. Drains messages
        before predicate-matching is started."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg in self.drain():
                if predicate(msg):
                    return msg
            time.sleep(poll)
        return None

    def identity(self, timeout=2.0):
        self.drain()
        self.send(IDENTITY_REQUEST)
        return self.wait_for(
            lambda m: len(m) >= 7 and m[0] == 0xF0 and m[1] == 0x7E
                      and m[3] == 0x06 and m[4] == 0x02,
            timeout=timeout,
        )

    def rq1(self, addr: int, size: int, timeout=1.0):
        """Issue RQ1 and return the first matching DT1 reply. Returns the
        raw SysEx bytes (incl. F0/F7) or None on timeout."""
        self.drain()
        self.send(rq1(addr, size))
        return self.wait_for(self._is_dt1_reply(addr), timeout=timeout)

    def _is_dt1_reply(self, addr: int):
        target = _addr_bytes(addr)

        def _matches(msg: bytes) -> bool:
            if len(msg) < 13 or msg[0] != 0xF0 or msg[-1] != 0xF7:
                return False
            if msg[1:8] != SYSEX_HEADER[1:]:
                return False
            if msg[8] != DT1:
                return False
            return msg[9:13] == target

        return _matches

    def dt1(self, addr: int, data: bytes):
        """Send a DT1 write, no acknowledgement."""
        self.send(dt1(addr, data))

    def close(self):
        try:
            self.inp.close_port()
        finally:
            self.out.close_port()


def parse_dt1_payload(msg: bytes) -> bytes:
    """Given a DT1 reply SysEx, return the payload (after addr, before
    checksum/F7)."""
    if msg is None or len(msg) < 14 or msg[8] != DT1:
        return b""
    return msg[13:-2]


def hex_msg(msg) -> str:
    if msg is None:
        return "(None)"
    return " ".join(f"{b:02X}" for b in msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--identity", action="store_true")
    ap.add_argument("--rq1", nargs=2, metavar=("ADDR", "SIZE"))
    ap.add_argument("--dt1", nargs="+", metavar="ADDR DATA",
                    help="ADDR (hex) followed by space-separated data hex")
    ap.add_argument("--timeout", type=float, default=1.5)
    args = ap.parse_args()

    g = GxMidi()
    print(f"port: {g.port_name}", file=sys.stderr)

    try:
        if args.identity:
            r = g.identity(timeout=args.timeout)
            print(hex_msg(r))
            return 0
        if args.rq1:
            addr = int(args.rq1[0], 16)
            size = int(args.rq1[1], 16)
            r = g.rq1(addr, size, timeout=args.timeout)
            print(hex_msg(r))
            if r:
                print("payload:", " ".join(f"{b:02X}" for b in parse_dt1_payload(r)))
            return 0
        if args.dt1:
            addr = int(args.dt1[0], 16)
            data = bytes(int(b, 16) for b in args.dt1[1:])
            g.dt1(addr, data)
            print(f"sent DT1 @ 0x{addr:08X} = {data.hex(' ')}")
            return 0
        ap.print_help()
    finally:
        g.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
