"""Probe the USB-settings address range to find any vendor-mode-only knobs.

Known from docs/menus.md §USB SETTINGS:
  0x00004003..04   EFX OUT LEVEL (2 bytes, 14-bit value)
  0x00004005..06   MIX LEVEL
  0x00004007..08   DRY OUT
  0x00004009..0A   DRY TO EFX
  0x0000400C       OUTPUT SELECT (1 byte enum)
  0x00200113       DIRECT MONITOR
  0x00200114       LOOP BACK

Probe wider:
  0x00004000..0x0000403F  (whole USB block)
  0x00200110..0x0020012F  (editor I/O staging around DIRECT MONITOR)

Vendor mode is supposed to expose extra knobs that generic mode hides.
If new bytes return non-zero / non-error values that we didn't see
in the generic-mode capture, they're probably the dry-out routing
controls only available in vendor mode.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff
from device_id import require_alive_raw


RANGES = [
    ("USB block",   0x00004000, 0x40),
    ("IO staging",  0x00200110, 0x20),
]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def main():
    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    s = midi_sniff.Sniffer(in_idx, Path("__nul__.jsonl"), in_name)

    def emit(o):
        if o.get("kind") == "sysex":
            try:
                with lock:
                    events.append(bytes.fromhex(o["hex"]))
            except Exception:
                pass
    s._emit = emit
    s.open()
    out_idx, _ = find_output_port("GX-10")
    out = MidiOut(out_idx)
    time.sleep(0.3)
    require_alive_raw(out, events, lock)

    for label, base, size in RANGES:
        with lock:
            events.clear()
        out.send_sysex(build_rq1(base, size))
        time.sleep(0.6)
        with lock:
            snap = list(events)
        # Find the full reply
        payload = None
        for e in snap:
            p = parse_dt1(e)
            if p and p[0] == base:
                payload = p[1]
                break
        # Also collect any RQ1 NAK echoes (header byte 0x11 instead of 0x12)
        naks = [e for e in snap if len(e) > 8 and e[8] == 0x11]
        print(f"\n{label}  base=0x{base:08X}  size=0x{size:02X}")
        if payload is None:
            print(f"  (no DT1 reply; {len(naks)} RQ1 echoes/NAKs)")
            for e in naks[:3]:
                print(f"    NAK {e.hex().upper()[:60]}")
            continue
        print(f"  got {len(payload)} bytes")
        # Show in 16-byte rows
        for i in range(0, len(payload), 16):
            row = payload[i:i+16]
            hexs = " ".join(f"{b:02X}" for b in row)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
            print(f"  +0x{i:02X}  {hexs:<48s}  {asc}")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
