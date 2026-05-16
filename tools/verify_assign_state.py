"""Comprehensive verification: write the assign, then read EVERYTHING that
might affect what the device displays for the assign category.

Reads:
  - Assign #1 row  (0x10000200)
  - Chain linked-list (0x10000F0C, 50 bytes)
  - FxItem storage slot TYPE bytes (0..19) at 0x10001100, 1300, ..., 0x10003700

So we can see exactly what's at each chain position.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
from device_id import require_alive_raw
from fx_type_enum import FX_TYPE_NAME


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def encode_4nib(v):
    return bytes([(v >> 12) & 0xF, (v >> 8) & 0xF,
                  (v >> 4) & 0xF, v & 0xF])


def write_assign_fbf(out, base, target_fx_item, target_idx, source_byte,
                       mode_toggle=True, target_min=0, target_max=1):
    out.send_sysex(build_dt1(base + 0x00, b"\x01"))
    out.send_sysex(build_dt1(base + 0x01, bytes([target_fx_item])))
    out.send_sysex(build_dt1(base + 0x02, encode_4nib(target_idx)))
    out.send_sysex(build_dt1(base + 0x06, encode_4nib(target_min + 0x8000)))
    out.send_sysex(build_dt1(base + 0x0A, encode_4nib(target_max + 0x8000)))
    out.send_sysex(build_dt1(base + 0x0E, bytes([source_byte])))
    out.send_sysex(build_dt1(base + 0x0F, b"\x00" if mode_toggle else b"\x01"))
    out.send_sysex(build_dt1(base + 0x15, encode_4nib(0)))
    out.send_sysex(build_dt1(base + 0x19, encode_4nib(16383)))
    out.send_sysex(build_dt1(base + 0x1D, b"\x00"))
    out.send_sysex(build_dt1(base + 0x1E, b"\x00"))
    out.send_sysex(build_dt1(base + 0x1F, encode_4nib(0)))
    out.send_sysex(build_dt1(base + 0x23, encode_4nib(16383)))
    out.send_sysex(build_dt1(base + 0x27, b"\x00"))
    out.send_sysex(build_dt1(base + 0x28, b"\x00"))
    out.send_sysex(build_dt1(base + 0x29, b"\x00\x00"))
    out.send_sysex(build_dt1(base + 0x2B, b"\x00\x00"))


def read_addr(out, events, lock, addr, size, timeout=0.6):
    with lock:
        events.clear()
    out.send_sysex(build_rq1(addr, size))
    deadline = time.time() + timeout
    while time.time() < deadline:
        with lock:
            for e in list(events):
                r = parse_dt1(e)
                if r and r[0] == addr:
                    return r[1]
        time.sleep(0.02)
    return None


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
    time.sleep(0.4)
    require_alive_raw(out, events, lock)

    BASE = 0x10000200

    # 1. Write Assign #1 = REV ON/OFF on CC#64
    print("Writing Assign #1: TARGET_FX_ITEM=2, TARGET=1 (ON/OFF), SOURCE=CC#64...")
    write_assign_fbf(out, BASE, target_fx_item=2, target_idx=1,
                       source_byte=52, mode_toggle=True)
    time.sleep(0.5)

    # 2. Read assign back
    print("\nAssign #1 read-back:")
    p = read_addr(out, events, lock, BASE, 0x2D)
    if p:
        target = ((p[0x02] & 0xF) << 12 | (p[0x03] & 0xF) << 8
                  | (p[0x04] & 0xF) << 4 | (p[0x05] & 0xF))
        print(f"  SW={p[0x00]} TARGET_FX_ITEM={p[0x01]} TARGET={target} "
              f"SOURCE={p[0x0E]} MODE={p[0x0F]}")

    # 3. Read chain linked-list
    print("\nChain linked-list (0x10000F0C, 50 bytes):")
    cl = read_addr(out, events, lock, 0x10000F0C, 50)
    if cl:
        # byte 0 = TOP+1; bytes 1..49 = NEXT[0..48]+1
        chain = []
        cur = cl[0] - 1 if cl[0] != 0 else -1
        order = []
        while cur >= 0 and len(order) < 25:  # safety
            order.append(cur)
            nxt = cl[1 + cur] - 1 if cl[1 + cur] != 0 else -1
            cur = nxt
        print(f"  TOP byte: {cl[0]}  -> first FxItem storage slot #{cl[0]-1}")
        print(f"  NEXT bytes 1..6: {cl[1:7].hex().upper()}")
        print(f"  Chain order (storage slots): {order}")

    # 4. Read FxItem TYPE bytes for slots 0..3
    print("\nFxItem storage slot TYPE bytes:")
    for slot in range(4):
        addr = 0x10001100 + slot * 0x200
        r = read_addr(out, events, lock, addr, 1)
        if r:
            t = r[0]
            name = FX_TYPE_NAME.get(t, "(unknown)")
            print(f"  Slot #{slot} (0x{addr:08X}) TYPE = 0x{t:02X} ({t}) = {name}")

    print("\nInterpretation:")
    print("  TARGET_FX_ITEM=2 should point at storage slot #2.")
    print("  If slot #2 has TYPE=REVERB(0x3E), the device should show 'REVERB'")
    print("  for the Assign #1 category. If slot #2 is something else,")
    print("  the chain edit didn't fully take effect.")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
