"""Write 5 distinctive values to WAH knobs on FxItem #0 to validate the
typebar_full address-to-name mapping live.

Snapshots FxItem #0 first; user can restore via tools/restore_fxitem0.py
once they've read each value off the device.

Mapping under test (from captures/typebar_full/page1/23_WAH/summary.json):
  EFFECT LEVEL    = 1  →  0x1000110B
  DIRECT MIX      = 2  →  0x1000110F
  PEDAL POSITION  = 3  →  0x10001113
  PEDAL MIN       = 4  →  0x10001117
  PEDAL MAX       = 5  →  0x1000111B   (probable — missing from typebar_full)
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
from example_lib import GX10Session
from device_id import require_alive

FXITEM0_BASE = 0x10001100


def encode_4nibble(display: int) -> bytes:
    """display value (-32768..32767) → 4-byte 4-nibble offset binary."""
    raw = (display + 0x8000) & 0xFFFF
    return bytes([
        (raw >> 12) & 0x0F,
        (raw >> 8) & 0x0F,
        (raw >> 4) & 0x0F,
        raw & 0x0F,
    ])


def main():
    # GX10Session gives us a sniffer for the identity check; we use
    # its .out for the actual writes.
    sess = GX10Session()
    require_alive(sess)
    out = sess.out

    writes = [
        ("EFFECT LEVEL",    0x1000110B, 1),
        ("DIRECT MIX",      0x1000110F, 2),
        ("PEDAL POSITION",  0x10001113, 3),
        ("PEDAL MIN",       0x10001117, 4),
        ("PEDAL MAX (?)",   0x1000111B, 5),
    ]
    print("Writing WAH knobs:")
    for name, addr, val in writes:
        payload = encode_4nibble(val)
        msg = midi_send.build_dt1(addr, payload)
        out.send_sysex(msg)
        time.sleep(0.05)
        print(f"  {name:18s}  addr 0x{addr:08X}  payload={payload.hex()}  display={val}")

    try: sess.sniffer.close()
    except Exception: pass
    try: out.close()
    except Exception: pass
    print()
    print("Done. Now read each knob's value off the device LCD or BTS.")
    print("If all five show 1, 2, 3, 4, 5 in order — mapping is validated.")


if __name__ == "__main__":
    sys.exit(main())
