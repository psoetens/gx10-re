"""
Probe the encoding of address 0x00000000 (the "select patch" register).

Writes a sequence of 5-byte values and reads back the loaded patch name to
build a {bytes -> patch_name} table.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
import ctypes
from device_id import require_alive_raw


def setup():
    idx_in, _ = midi_sniff.find_port("GX-10")
    idx_out, _ = midi_send.find_output_port("GX-10")
    out = midi_send.MidiOut(idx_out)
    return out, idx_in


def write_select_then_read_name(out, sniffer, value: bytes):
    sniffer.set_label(f"WRITE 00000000 = {value.hex().upper()}")
    out.send_sysex(midi_send.build_dt1(0x00000000, value))
    time.sleep(0.4)
    sniffer.set_label("READ 10000000")
    out.send_sysex(midi_send.build_rq1(0x10000000, 0x10))
    time.sleep(0.3)


def main():
    out, idx_in = setup()
    log = Path("captures/probe_select.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    sniffer = midi_sniff.Sniffer(idx_in, log, "GX-10")
    # Hook _emit before open() so require_alive_raw sees identity reply.
    events: list = []
    orig_emit = sniffer._emit
    def _cap(o):
        if o.get("kind") == "sysex":
            try: events.append(bytes.fromhex(o["hex"]))
            except Exception: pass
        return orig_emit(o)
    sniffer._emit = _cap
    sniffer.open()
    time.sleep(0.3)
    require_alive_raw(out, events)
    events.clear()
    # announce editor
    out.send_sysex(midi_send.build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.3)

    probes = [
        b"\x00\x00\x00\x00\x00",  # baseline
        b"\x00\x00\x00\x00\x01",  # ++byte4
        b"\x00\x00\x00\x00\x07",  # byte4=7
        b"\x00\x00\x00\x01\x00",  # byte3=1
        b"\x00\x00\x01\x00\x00",  # byte2=1
        b"\x00\x00\x0C\x00\x03",  # bank 12 pos 3 (GX DUAL DRIVE if encoding (00,00,bank,??,pos))
        b"\x00\x00\x0C\x08\x03",  # with original "08" middle byte
        b"\x00\x00\x12\x08\x00",  # bank 18 pos 0 (GITARRE SPIELEN expected)
        b"\x00\x00\x00\x08\x00",  # bank 0 pos 0 with the 08 middle byte
        b"\x00\x00\x00\x08\x07",  # bank 0 pos 7 (X-MODDED AMP HB?)
        b"\x60\x40\x00\x00\x00",  # try user slot 0 ("USER 1")
        b"\x60\x40\x09\x00\x00",  # try user slot 9 ("USER 10" - U10-1?)
        b"\x00\x00\x00\x00\x00",  # restore to NATURAL AMP HB at end
    ]

    try:
        for p in probes:
            write_select_then_read_name(out, sniffer, p)
    finally:
        time.sleep(0.5)
        out.close()
        sniffer.close()
    print(f"log -> {log}")


if __name__ == "__main__":
    main()
