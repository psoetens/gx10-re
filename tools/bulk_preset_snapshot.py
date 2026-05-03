"""
Use Bank Select + Program Change MIDI messages (rather than DT1 to 0x00000000
whose encoding is incomplete) to step through presets and snapshot each.

Standard MIDI:
  CC0  (Bank Select MSB)  - typically 0
  CC32 (Bank Select LSB)  - bank within group
  PC   (Program Change)   - patch within bank

The device emits its own Bank/PC messages on patch change, so the encoding
should match.

We snapshot just the live patch HEADER region (0x10000000..0x100000FF) which
is fast and sufficient to identify effect type IDs / per-slot config in the
patch metadata + routing matrix.

Usage:
    python bulk_preset_snapshot.py --start 0 --count 30 --out snapshots/presets/
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
from rapid_probe import step_7bit
from patch_snapshot import parse_log_to_address_map, save_snapshot

import ctypes
from ctypes import wintypes

winmm = ctypes.WinDLL("winmm")


def short_msg_send(out_handle: int, status: int, d1: int, d2: int = 0):
    """Send a 3-byte MIDI message via midiOutShortMsg."""
    msg = (status & 0xFF) | ((d1 & 0xFF) << 8) | ((d2 & 0xFF) << 16)
    rc = winmm.midiOutShortMsg(ctypes.c_void_p(out_handle), wintypes.DWORD(msg))
    if rc != 0:
        raise RuntimeError(f"midiOutShortMsg rc={rc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", required=True)
    ap.add_argument("--region-start", type=lambda x: int(x, 16), default=0x10000000)
    ap.add_argument("--region-end", type=lambda x: int(x, 16), default=0x10000200,
                    help="exclusive")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    idx_in, _ = midi_sniff.find_port("GX-10")
    idx_out, _ = midi_send.find_output_port("GX-10")
    out = midi_send.MidiOut(idx_out)

    # announce editor
    out.send_sysex(midi_send.build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.3)

    addrs = list(step_7bit(args.region_start, args.region_end, 0x40))

    try:
        for n in range(args.start, args.start + args.count):
            # Standard MIDI bank+PC for preset N (assume bank 0 or LSB=N//128):
            bank_msb = 0
            bank_lsb = n // 128
            pc = n % 128
            short_msg_send(out.handle.value, 0xB0, 0, bank_msb)
            time.sleep(0.05)
            short_msg_send(out.handle.value, 0xB0, 32, bank_lsb)
            time.sleep(0.05)
            short_msg_send(out.handle.value, 0xC0, pc)
            time.sleep(0.6)  # let device settle

            log = out_dir / f"_p{n:03d}.jsonl"
            sniffer = midi_sniff.Sniffer(idx_in, log, "GX-10")
            sniffer.open()
            try:
                for addr in addrs:
                    out.send_sysex(midi_send.build_rq1(addr, 0x40))
                    time.sleep(0.015)
                time.sleep(0.5)
            finally:
                sniffer.close()

            addr_map = parse_log_to_address_map(log)
            snap = out_dir / f"p{n:03d}.json"
            save_snapshot(addr_map, snap)
            name = bytes(addr_map.get(0x10000000 + i, 0x20) for i in range(16)).decode("ascii", errors="replace").strip()
            print(f"p{n:03d}  {name!r:32s}  {len(addr_map)} bytes")
            log.unlink(missing_ok=True)
    finally:
        out.close()


if __name__ == "__main__":
    main()
