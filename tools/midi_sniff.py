"""
MIDI input sniffer.

Original API kept stable so example_lib.GX10Session and the rest of the
WinMM-era tooling work unchanged. Backend is python-rtmidi on macOS and
Linux, raw WinMM via ctypes on Windows.

Opens a MIDI INPUT port by name (default 'GX-10') and logs every short
message and SysEx with a high-resolution timestamp + direction tag, both
to stdout (one event per line) and to a JSONL log file.

  - find_port(name_substr) -> (idx, name)
  - Sniffer(port_index, log_path, port_name).open() / .close()
                                            .set_label(label)
                                            ._emit({...})   # overridable

CLI:
    python midi_sniff.py --port "GX-10" --log captures/sniff.jsonl
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

_IS_WIN = sys.platform == "win32"


# --- backend: WinMM (Windows) --------------------------------------------

if _IS_WIN:
    import ctypes
    from ctypes import wintypes

    winmm = ctypes.WinDLL("winmm")

    LPMIDIHDR = ctypes.c_void_p
    HMIDIIN = ctypes.c_void_p

    def _bind(fn, argtypes, restype=wintypes.UINT):
        fn.argtypes = argtypes
        fn.restype = restype

    _bind(winmm.midiInGetNumDevs, [], wintypes.UINT)
    _bind(winmm.midiInGetDevCapsW, [wintypes.UINT, ctypes.c_void_p, wintypes.UINT])
    _bind(winmm.midiInGetErrorTextW, [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT])
    _bind(winmm.midiInOpen, [ctypes.POINTER(HMIDIIN), wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD])
    _bind(winmm.midiInClose, [HMIDIIN])
    _bind(winmm.midiInStart, [HMIDIIN])
    _bind(winmm.midiInStop, [HMIDIIN])
    _bind(winmm.midiInReset, [HMIDIIN])
    _bind(winmm.midiInPrepareHeader, [HMIDIIN, LPMIDIHDR, wintypes.UINT])
    _bind(winmm.midiInUnprepareHeader, [HMIDIIN, LPMIDIHDR, wintypes.UINT])
    _bind(winmm.midiInAddBuffer, [HMIDIIN, LPMIDIHDR, wintypes.UINT])

    CALLBACK_FUNCTION = 0x00030000
    MIM_OPEN = 0x3C1
    MIM_CLOSE = 0x3C2
    MIM_DATA = 0x3C3
    MIM_LONGDATA = 0x3C4
    MIM_ERROR = 0x3C5
    MIM_LONGERROR = 0x3C6
    MHDR_DONE = 0x00000001

    class MIDIINCAPSW(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD),
            ("wPid", wintypes.WORD),
            ("vDriverVersion", wintypes.DWORD),
            ("szPname", wintypes.WCHAR * 32),
            ("dwSupport", wintypes.DWORD),
        ]

    class MIDIHDR(ctypes.Structure):
        # IMPORTANT: lpData is c_void_p (not c_char_p), otherwise ctypes
        # auto-marshals to a NUL-terminated Python bytes and silently
        # truncates the SysEx payload.
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

    MIDI_PROC = ctypes.WINFUNCTYPE(
        None, HMIDIIN, wintypes.UINT, ctypes.c_size_t,
        ctypes.c_size_t, ctypes.c_size_t,
    )

    def _err(rc):
        buf = ctypes.create_unicode_buffer(256)
        winmm.midiInGetErrorTextW(rc, buf, 256)
        return f"mmsyserr {rc}: {buf.value}"

    def find_port(name_substr):
        n = winmm.midiInGetNumDevs()
        for i in range(n):
            caps = MIDIINCAPSW()
            rc = winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
            if rc == 0 and name_substr.lower() in caps.szPname.lower():
                return i, caps.szPname
        return None, None


    class Sniffer:
        SYSEX_BUF_SIZE = 8192
        NUM_BUFFERS = 4

        def __init__(self, port_index: int, log_path: Path, port_name: str):
            self.port_index = port_index
            self.port_name = port_name
            self.log_path = log_path
            self.t0 = time.perf_counter()
            self.handle = HMIDIIN()
            self.buffers = []
            self.headers = []
            self.lock = threading.Lock()
            self.log_fp = log_path.open("w", buffering=1, encoding="utf-8")
            self.label = "(no label)"
            self._proc = MIDI_PROC(self._callback)

        def set_label(self, label: str):
            with self.lock:
                self.label = label
            self._emit({"event": "label", "label": label})

        def _ts(self):
            return time.perf_counter() - self.t0

        def _emit(self, obj):
            obj.setdefault("t", round(self._ts(), 6))
            obj.setdefault("label", self.label)
            line = json.dumps(obj, ensure_ascii=False)
            self.log_fp.write(line + "\n")
            print(line, flush=True)

        def _callback(self, hMidiIn, wMsg, dwInstance, dwParam1, dwParam2):
            try:
                if wMsg == MIM_DATA:
                    p1 = (dwParam1 or 0) & 0xFFFFFFFF
                    status = p1 & 0xFF
                    d1 = (p1 >> 8) & 0xFF
                    d2 = (p1 >> 16) & 0xFF
                    msg_type = status & 0xF0 if status < 0xF0 else status
                    channel = (status & 0x0F) if status < 0xF0 else None
                    if status in (0xF6, 0xF8, 0xFA, 0xFB, 0xFC, 0xFE, 0xFF):
                        data = [status]
                    elif msg_type in (0xC0, 0xD0) or status in (0xF1, 0xF3):
                        data = [status, d1]
                    elif msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0) or status == 0xF2:
                        data = [status, d1, d2]
                    else:
                        data = [status, d1, d2]
                    self._emit({
                        "dir": "dev->host",
                        "kind": "short",
                        "status": f"{status:02X}",
                        "ch": channel,
                        "bytes": [f"{b:02X}" for b in data],
                    })
                elif wMsg == MIM_LONGDATA:
                    hdr_ptr = dwParam1
                    hdr = ctypes.cast(hdr_ptr, ctypes.POINTER(MIDIHDR)).contents
                    if hdr.dwBytesRecorded > 0:
                        raw = ctypes.string_at(hdr.lpData, hdr.dwBytesRecorded)
                        self._emit({
                            "dir": "dev->host",
                            "kind": "sysex" if raw[:1] == b"\xF0" else "long",
                            "len": len(raw),
                            "hex": raw.hex().upper(),
                        })
                    rc = winmm.midiInAddBuffer(self.handle, hdr_ptr, ctypes.sizeof(MIDIHDR))
                    if rc != 0:
                        self._emit({"event": "addbuffer-error", "rc": rc})
                elif wMsg == MIM_ERROR:
                    self._emit({"event": "short-error", "data": int(dwParam1) if dwParam1 else None})
                elif wMsg == MIM_LONGERROR:
                    self._emit({"event": "long-error"})
                elif wMsg == MIM_OPEN:
                    self._emit({"event": "open"})
                elif wMsg == MIM_CLOSE:
                    self._emit({"event": "close"})
            except Exception as e:
                try:
                    self._emit({"event": "callback-exception", "err": repr(e)})
                except Exception:
                    pass

        def open(self):
            rc = winmm.midiInOpen(
                ctypes.byref(self.handle),
                self.port_index,
                self._proc,
                None,
                CALLBACK_FUNCTION,
            )
            if rc != 0:
                raise RuntimeError(f"midiInOpen failed: {_err(rc)}")
            self._emit({"event": "opened", "port_index": self.port_index, "port_name": self.port_name})
            for _ in range(self.NUM_BUFFERS):
                buf = ctypes.create_string_buffer(self.SYSEX_BUF_SIZE)
                hdr = MIDIHDR()
                hdr.lpData = ctypes.addressof(buf)
                hdr.dwBufferLength = self.SYSEX_BUF_SIZE
                hdr.dwBytesRecorded = 0
                hdr.dwUser = None
                hdr.dwFlags = 0
                self.buffers.append(buf)
                self.headers.append(hdr)
                rc = winmm.midiInPrepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(MIDIHDR))
                if rc != 0:
                    raise RuntimeError(f"midiInPrepareHeader: {_err(rc)}")
                rc = winmm.midiInAddBuffer(self.handle, ctypes.byref(hdr), ctypes.sizeof(MIDIHDR))
                if rc != 0:
                    raise RuntimeError(f"midiInAddBuffer: {_err(rc)}")
            rc = winmm.midiInStart(self.handle)
            if rc != 0:
                raise RuntimeError(f"midiInStart: {_err(rc)}")
            self._emit({"event": "started"})

        def close(self):
            try:
                winmm.midiInStop(self.handle)
                winmm.midiInReset(self.handle)
                for hdr in self.headers:
                    winmm.midiInUnprepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(MIDIHDR))
                winmm.midiInClose(self.handle)
            finally:
                self.log_fp.close()


# --- backend: python-rtmidi (macOS / Linux) ------------------------------

else:
    import rtmidi

    def find_port(name_substr):
        mi = rtmidi.MidiIn()
        try:
            ports = mi.get_ports()
        finally:
            del mi
        for i, name in enumerate(ports):
            if name_substr.lower() in name.lower():
                return i, name
        return None, None


    class Sniffer:
        def __init__(self, port_index: int, log_path: Path, port_name: str):
            self.port_index = port_index
            self.port_name = port_name
            self.log_path = log_path
            self.t0 = time.perf_counter()
            self.lock = threading.Lock()
            self.log_fp = log_path.open("w", buffering=1, encoding="utf-8")
            self.label = "(no label)"
            self._in = rtmidi.MidiIn()
            # rtmidi ignores SysEx by default — turn it back on. Active
            # sensing (FE) and timing (F8) get filtered to mirror what
            # the WinMM Sniffer effectively saw (the device's FE flood
            # used to spam the log).
            self._in.ignore_types(sysex=False, timing=True, active_sense=True)

        def set_label(self, label: str):
            with self.lock:
                self.label = label
            self._emit({"event": "label", "label": label})

        def _ts(self):
            return time.perf_counter() - self.t0

        def _emit(self, obj):
            obj.setdefault("t", round(self._ts(), 6))
            obj.setdefault("label", self.label)
            line = json.dumps(obj, ensure_ascii=False)
            self.log_fp.write(line + "\n")
            print(line, flush=True)

        def _callback(self, event, _data=None):
            try:
                msg, _dt = event
                if not msg:
                    return
                raw = bytes(msg)
                status = raw[0]
                if status == 0xF0:
                    self._emit({
                        "dir": "dev->host",
                        "kind": "sysex",
                        "len": len(raw),
                        "hex": raw.hex().upper(),
                    })
                    return
                msg_type = status & 0xF0 if status < 0xF0 else status
                channel = (status & 0x0F) if status < 0xF0 else None
                self._emit({
                    "dir": "dev->host",
                    "kind": "short",
                    "status": f"{status:02X}",
                    "ch": channel,
                    "bytes": [f"{b:02X}" for b in raw],
                })
            except Exception as e:
                try:
                    self._emit({"event": "callback-exception", "err": repr(e)})
                except Exception:
                    pass

        def open(self):
            self._in.open_port(self.port_index)
            self._in.set_callback(self._callback)
            self._emit({"event": "opened",
                        "port_index": self.port_index,
                        "port_name": self.port_name})
            self._emit({"event": "started"})

        def close(self):
            try:
                self._in.cancel_callback()
            except Exception:
                pass
            try:
                self._in.close_port()
            except Exception:
                pass
            try:
                self.log_fp.close()
            except Exception:
                pass


# --- CLI -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="GX-10", help="MIDI input port name substring")
    ap.add_argument("--log", default="captures/sniff.jsonl", help="output JSONL log path")
    ap.add_argument("--label-fifo", default=None, help="Optional path to a file we read labels from (one per line)")
    ap.add_argument("--seconds", type=float, default=None, help="Stop after N seconds (default: run until Ctrl+C)")
    args = ap.parse_args()

    idx, name = find_port(args.port)
    if idx is None:
        print(f"ERROR: no MIDI input port matching '{args.port}'", file=sys.stderr)
        sys.exit(2)

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    s = Sniffer(idx, log_path, name)
    try:
        s.open()
    except RuntimeError as e:
        print(f"OPEN FAILED: {e}", file=sys.stderr)
        sys.exit(3)

    label_path = Path(args.label_fifo) if args.label_fifo else None
    if label_path:
        label_path.parent.mkdir(parents=True, exist_ok=True)
        if not label_path.exists():
            label_path.write_text("")

    last_label_pos = 0
    start = time.time()
    try:
        while True:
            if args.seconds is not None and time.time() - start >= args.seconds:
                break
            if label_path and label_path.exists():
                try:
                    text = label_path.read_text(encoding="utf-8", errors="replace")
                    if len(text) > last_label_pos:
                        new = text[last_label_pos:]
                        last_label_pos = len(text)
                        for line in new.splitlines():
                            line = line.strip()
                            if line:
                                s.set_label(line)
                except Exception:
                    pass
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        s.close()


if __name__ == "__main__":
    main()
