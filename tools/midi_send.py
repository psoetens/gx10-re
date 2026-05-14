"""
Send arbitrary SysEx to the GX-10.

Backwards-compatible primitives originally written against Win32 `winmm`;
on macOS and Linux the same API is now served by python-rtmidi (which
also wraps WinMM on Windows, so we could collapse the two paths — kept
split so existing Windows-RE tooling sees byte-identical behaviour).

  - find_output_port(name_substr) -> (idx, name)
  - MidiOut(idx).send_sysex(bytes) / .send_short_msg(bytes) / .close()
  - build_dt1(addr, payload), build_rq1(addr, size), build_identity_request()

CLI:
    python midi_send.py --identity
    python midi_send.py --rq1 10000000 00000010
    python midi_send.py --raw F07E7F0601F7
"""
import argparse
import sys
import time

_IS_WIN = sys.platform == "win32"


# --- Roland helpers (pure-Python, shared across backends) ----------------

ROLAND_HEADER = bytes([0xF0, 0x41, 0x10, 0x00, 0x00, 0x00, 0x00, 0x0B])

def roland_checksum(addr_data: bytes) -> int:
    return (-sum(addr_data)) & 0x7F

def build_dt1(addr: int, payload: bytes) -> bytes:
    if not (0 <= addr <= 0xFFFFFFFF):
        raise ValueError("addr must fit in 32 bits")
    if any(b > 0x7F for b in payload):
        raise ValueError("DT1 payload bytes must be <= 0x7F")
    addr_b = addr.to_bytes(4, "big")
    if any(b > 0x7F for b in addr_b):
        raise ValueError("addr bytes must be <= 0x7F")
    body = addr_b + payload
    return ROLAND_HEADER + b"\x12" + body + bytes([roland_checksum(body)]) + b"\xF7"

def build_rq1(addr: int, size: int) -> bytes:
    addr_b = addr.to_bytes(4, "big")
    size_b = size.to_bytes(4, "big")
    if any(b > 0x7F for b in addr_b + size_b):
        raise ValueError("addr/size bytes must be <= 0x7F")
    body = addr_b + size_b
    return ROLAND_HEADER + b"\x11" + body + bytes([roland_checksum(body)]) + b"\xF7"

def build_identity_request() -> bytes:
    return bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])


# --- backend: WinMM (Windows) --------------------------------------------

if _IS_WIN:
    import ctypes
    from ctypes import wintypes

    winmm = ctypes.WinDLL("winmm")

    class MIDIOUTCAPSW(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD),
            ("wPid", wintypes.WORD),
            ("vDriverVersion", wintypes.DWORD),
            ("szPname", wintypes.WCHAR * 32),
            ("wTechnology", wintypes.WORD),
            ("wVoices", wintypes.WORD),
            ("wNotes", wintypes.WORD),
            ("wChannelMask", wintypes.WORD),
            ("dwSupport", wintypes.DWORD),
        ]

    class MIDIHDR(ctypes.Structure):
        _fields_ = [
            ("lpData", ctypes.c_void_p),
            ("dwBufferLength", wintypes.DWORD),
            ("dwBytesRecorded", wintypes.DWORD),
            ("dwUser", ctypes.c_void_p),
            ("dwFlags", wintypes.DWORD),
            ("lpNext", ctypes.c_void_p),
            ("reserved", ctypes.c_void_p),
            ("dwOffset", wintypes.DWORD),
            ("dwReserved", ctypes.c_void_p * 8),
        ]

    HMIDIOUT = ctypes.c_void_p
    LPMIDIHDR = ctypes.c_void_p

    def _bind(fn, argtypes, restype=wintypes.UINT):
        fn.argtypes = argtypes
        fn.restype = restype

    _bind(winmm.midiOutGetNumDevs, [], wintypes.UINT)
    _bind(winmm.midiOutGetDevCapsW, [wintypes.UINT, ctypes.c_void_p, wintypes.UINT])
    _bind(winmm.midiOutGetErrorTextW, [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT])
    _bind(winmm.midiOutOpen, [ctypes.POINTER(HMIDIOUT), wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD])
    _bind(winmm.midiOutClose, [HMIDIOUT])
    _bind(winmm.midiOutPrepareHeader, [HMIDIOUT, LPMIDIHDR, wintypes.UINT])
    _bind(winmm.midiOutUnprepareHeader, [HMIDIOUT, LPMIDIHDR, wintypes.UINT])
    _bind(winmm.midiOutLongMsg, [HMIDIOUT, LPMIDIHDR, wintypes.UINT])
    _bind(winmm.midiOutShortMsg, [HMIDIOUT, wintypes.DWORD])

    CALLBACK_NULL = 0

    def _err(rc):
        buf = ctypes.create_unicode_buffer(256)
        winmm.midiOutGetErrorTextW(rc, buf, 256)
        return f"mmsyserr {rc}: {buf.value}"

    def find_output_port(name_substr: str):
        n = winmm.midiOutGetNumDevs()
        for i in range(n):
            caps = MIDIOUTCAPSW()
            rc = winmm.midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
            if rc == 0 and name_substr.lower() in caps.szPname.lower():
                return i, caps.szPname
        return None, None

    class MidiOut:
        def __init__(self, port_index: int):
            self.handle = HMIDIOUT()
            rc = winmm.midiOutOpen(ctypes.byref(self.handle), port_index, None, None, CALLBACK_NULL)
            if rc != 0:
                raise RuntimeError(f"midiOutOpen failed: {_err(rc)}")

        def send_short_msg(self, data: bytes):
            """Send a 1- to 3-byte MIDI short message. Used for PC#, CC, etc."""
            if not (1 <= len(data) <= 3):
                raise ValueError("short message must be 1-3 bytes")
            msg = data[0]
            if len(data) >= 2:
                msg |= data[1] << 8
            if len(data) == 3:
                msg |= data[2] << 16
            rc = winmm.midiOutShortMsg(self.handle, msg)
            if rc != 0:
                raise RuntimeError(f"midiOutShortMsg: {_err(rc)}")

        def send_sysex(self, data: bytes):
            if not data or data[0] != 0xF0 or data[-1] != 0xF7:
                raise ValueError("data must be a complete SysEx (F0..F7)")
            buf = ctypes.create_string_buffer(data, len(data))
            hdr = MIDIHDR()
            hdr.lpData = ctypes.addressof(buf)
            hdr.dwBufferLength = len(data)
            hdr.dwBytesRecorded = len(data)
            hdr.dwFlags = 0
            rc = winmm.midiOutPrepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(MIDIHDR))
            if rc != 0:
                raise RuntimeError(f"midiOutPrepareHeader: {_err(rc)}")
            try:
                rc = winmm.midiOutLongMsg(self.handle, ctypes.byref(hdr), ctypes.sizeof(MIDIHDR))
                if rc != 0:
                    raise RuntimeError(f"midiOutLongMsg: {_err(rc)}")
                for _ in range(100):
                    if hdr.dwFlags & 0x00000001:  # MHDR_DONE
                        break
                    time.sleep(0.005)
            finally:
                winmm.midiOutUnprepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(MIDIHDR))

        def close(self):
            try:
                winmm.midiOutClose(self.handle)
            except Exception:
                pass


# --- backend: python-rtmidi (macOS / Linux) ------------------------------

else:
    import rtmidi

    def find_output_port(name_substr: str):
        mo = rtmidi.MidiOut()
        try:
            ports = mo.get_ports()
        finally:
            del mo
        for i, name in enumerate(ports):
            if name_substr.lower() in name.lower():
                return i, name
        return None, None

    class MidiOut:
        def __init__(self, port_index: int):
            self._out = rtmidi.MidiOut()
            try:
                self._out.open_port(port_index)
            except Exception:
                try:
                    self._out.close_port()
                except Exception:
                    pass
                raise

        def send_short_msg(self, data: bytes):
            if not (1 <= len(data) <= 3):
                raise ValueError("short message must be 1-3 bytes")
            self._out.send_message(list(data))

        def send_sysex(self, data: bytes):
            if not data or data[0] != 0xF0 or data[-1] != 0xF7:
                raise ValueError("data must be a complete SysEx (F0..F7)")
            self._out.send_message(list(data))
            # Mirrors the WinMM per-buffer settle wait so back-to-back
            # SysEx don't race the device's parser.
            time.sleep(0.005)

        def close(self):
            try:
                self._out.close_port()
            except Exception:
                pass
            try:
                del self._out
            except Exception:
                pass


# --- CLI -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="GX-10")
    ap.add_argument("--identity", action="store_true")
    ap.add_argument("--rq1", nargs=2, metavar=("ADDR_HEX", "SIZE_HEX"))
    ap.add_argument("--raw", help="raw hex SysEx, e.g. F07E7F0601F7")
    args = ap.parse_args()

    idx, name = find_output_port(args.port)
    if idx is None:
        print(f"ERROR: no MIDI output port matching '{args.port}'", file=sys.stderr)
        sys.exit(2)
    print(f"opening output port [{idx}] {name}", file=sys.stderr)
    out = MidiOut(idx)
    try:
        if args.identity:
            data = build_identity_request()
            print(f"sending identity request: {data.hex().upper()}", file=sys.stderr)
            out.send_sysex(data)
        if args.rq1:
            addr = int(args.rq1[0], 16)
            size = int(args.rq1[1], 16)
            data = build_rq1(addr, size)
            print(f"sending RQ1 addr={addr:08X} size={size:08X}: {data.hex().upper()}", file=sys.stderr)
            out.send_sysex(data)
        if args.raw:
            data = bytes.fromhex(args.raw.replace(" ", ""))
            print(f"sending raw: {data.hex().upper()}", file=sys.stderr)
            out.send_sysex(data)
    finally:
        out.close()


if __name__ == "__main__":
    main()
