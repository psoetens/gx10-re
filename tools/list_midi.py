"""List MIDI input/output ports via Win32 winmm.dll (no rtmidi needed)."""
import ctypes
from ctypes import wintypes

winmm = ctypes.WinDLL("winmm")

# MIDIINCAPSW / MIDIOUTCAPSW use 32-char wszPname (Unicode)
class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.DWORD),
        ("szPname", wintypes.WCHAR * 32),
        ("dwSupport", wintypes.DWORD),
    ]

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

print("=== MIDI INPUT ===")
n_in = winmm.midiInGetNumDevs()
for i in range(n_in):
    caps = MIDIINCAPSW()
    rc = winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
    if rc == 0:
        print(f"  [{i}] {caps.szPname}  (mid={caps.wMid:#06x} pid={caps.wPid:#06x} ver={caps.vDriverVersion:#010x})")

print("\n=== MIDI OUTPUT ===")
n_out = winmm.midiOutGetNumDevs()
for i in range(n_out):
    caps = MIDIOUTCAPSW()
    rc = winmm.midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
    if rc == 0:
        print(f"  [{i}] {caps.szPname}  (mid={caps.wMid:#06x} pid={caps.wPid:#06x} tech={caps.wTechnology})")
