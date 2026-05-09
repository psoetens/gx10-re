"""Validate COMP (TYPE 0x08) knob name→address mapping.

Process:
1. Snapshot FxItem #0 (preserves whatever effect is currently loaded).
2. Switch FxItem #0 to COMP (TYPE 0x08, sub-type 0).
3. Write 5 distinctive values to Param 2..6 (offsets 0x07..0x17).
4. User reads device LCD labels in order; we decode the mapping.

NOT restored automatically — caller must run tools/restore_fxitem0.py
once user has read the values.
"""
from __future__ import annotations
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


FXITEM0_BASE = 0x10001100


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def main():
    out_dir = Path("captures/bts_comp_validation")
    out_dir.mkdir(parents=True, exist_ok=True)

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / "sniff.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    sniffer.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    orig = sniffer._emit
    def emit(o):
        if o.get("kind") == "sysex":
            try: q.put(bytes.fromhex(o["hex"]))
            except: pass
        return orig(o)
    sniffer._emit = emit

    def drain(secs=0.05):
        time.sleep(secs)
        msgs = []
        while not q.empty():
            try: msgs.append(q.get_nowait())
            except: break
        return msgs

    def rq1(addr, size, timeout=0.8):
        drain(0)
        out.send_sysex(midi_send.build_rq1(addr, size))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in drain(0.02):
                p = parse_dt1(m)
                if p and p[0] == addr:
                    return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.04)

    try:
        # 1. Snapshot
        snap = rq1(FXITEM0_BASE, 0x140, 1.5)
        if snap is None:
            print("ERROR: no snapshot"); return 2
        print(f"snapshot: {len(snap)} bytes; head: {snap[:8].hex()}")
        (out_dir / "snapshot_before.bin").write_bytes(snap)

        # 2. Editor-attach + set TYPE 0x08 (COMP), sub-type 0
        dt1(0x7F000001, bytes([0x01]))
        dt1(0x7F000001, bytes([0x01]))
        dt1(FXITEM0_BASE, bytes([0x08]))   # TYPE = COMP
        dt1(0x10001103, encode_4nibble(0))  # sub-type = 0
        time.sleep(0.2)

        # 3. Write distinctive values
        writes = [
            ("Param 2", 0x10001107, 1),
            ("Param 3", 0x1000110B, 2),
            ("Param 4", 0x1000110F, 3),
            ("Param 5", 0x10001113, 4),
            ("Param 6", 0x10001117, 5),
        ]
        print("\nwriting COMP test values:")
        for name, addr, val in writes:
            dt1(addr, encode_4nibble(val))
            print(f"  {name}  addr {addr:08X}  display={val}")

        # 4. Read back to confirm
        time.sleep(0.2)
        block = rq1(FXITEM0_BASE, 0x140, 1.5)
        if block:
            print(f"\nread-back head: {block[:32].hex()}")
            for n in range(1, 9):
                offset = 0x03 + (n - 1) * 4
                p = block[offset:offset + 4]
                raw = ((p[0] & 0xF) << 12) | ((p[1] & 0xF) << 8) | \
                      ((p[2] & 0xF) << 4) | (p[3] & 0xF)
                print(f"  Param {n} (off 0x{offset:02X}): {p.hex()} = display {raw - 0x8000}")
    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass

    print("\nNOW: read device labels in order. They should be (per typebar_full):")
    print("  SUSTAIN / ATTACK / LEVEL / TONE / DIRECT MIX")
    print("Tell me the values you see on each label.")
    print("Then run: python tools/restore_fxitem0.py --snapshot captures/bts_comp_validation/snapshot_before.bin")


if __name__ == "__main__":
    sys.exit(main())
