"""Probe SystemCommon lock/warning flags to see if the device is in a
state that would cause BTS's INSERT/DELETE/OVERWRITE to silently noop.

Per the chart, SystemCommon at 0x00000000:
  0x11 LOCK STATUS         (0=OFF, 1=ON)
  0x12 KNOB                (0=OFF, 1=ON)
  0x13 TOUCH SCREEN        (0=OFF, 1=ON)
  0x14 BUTTON              (0=OFF, 1=ON)
  0x15 OUTPUT LEVEL\nLOCK   (0=OFF, 1=ON)
  0x16 DELETE\nWARNING      (0=OFF, 1=ON)
  0x17 OVERWRITE\nWARNING   (0=OFF, 1=ON)
  0x18 FX ORDER            (0=BY TYPE, 1=BY NAME)

If LOCK STATUS=1 + BUTTON=1, BTS may treat all device-modifying clicks
as no-ops. If DELETE/OVERWRITE WARNING=1, BTS shows confirmation
dialogs; if those got stuck, INSERT/DELETE/OVERWRITE clicks would
appear silent (the dialog never renders).
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff
from device_id import require_alive_raw


FLAGS = [
    (0x00000011, "LOCK STATUS"),
    (0x00000012, "KNOB lock"),
    (0x00000013, "TOUCH SCREEN lock"),
    (0x00000014, "BUTTON lock"),
    (0x00000015, "OUTPUT LEVEL LOCK"),
    (0x00000016, "DELETE WARNING"),
    (0x00000017, "OVERWRITE WARNING"),
    (0x00000018, "FX ORDER"),
]


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    addr = int.from_bytes(raw[9:13], "big")
    payload = bytes(raw[13:-2])
    return addr, payload


class Collector:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()
    def on_sysex(self, raw):
        with self.lock: self.events.append(raw)
    def find(self, addr, since):
        with self.lock:
            for i in range(since, len(self.events)):
                p = parse_dt1(self.events[i])
                if p and p[0] == addr:
                    return p
        return None


def setup_sniffer(port_substr, coll):
    idx, name = midi_sniff.find_port(port_substr)
    if idx is None:
        raise RuntimeError(f"No MIDI input port matching '{port_substr}'")
    s = midi_sniff.Sniffer(idx, Path("__nul__.jsonl"), name)
    def emit(obj):
        if obj.get("kind") == "sysex":
            try:
                coll.on_sysex(bytes.fromhex(obj["hex"]))
            except Exception:
                pass
    s._emit = emit
    return s


def main():
    coll = Collector()
    sniffer = setup_sniffer("GX-10", coll)
    sniffer.open()
    out_idx, _ = find_output_port("GX-10")
    if out_idx is None:
        print("ERROR: no MIDI output port"); sys.exit(2)
    out = MidiOut(out_idx)
    time.sleep(0.4)
    require_alive_raw(out, coll.events, coll.lock)
    try:
        for addr, label in FLAGS:
            mark = len(coll.events)
            out.send_sysex(build_rq1(addr, 1))
            t0 = time.time()
            found = None
            while time.time() - t0 < 1.0:
                found = coll.find(addr, mark)
                if found: break
                time.sleep(0.01)
            if not found:
                print(f"  0x{addr:08X}  {label:24s}  TIMEOUT")
                continue
            _, payload = found
            val = payload[0] if payload else None
            print(f"  0x{addr:08X}  {label:24s}  = {val}")
    finally:
        sniffer.close(); out.close()


if __name__ == "__main__":
    main()
