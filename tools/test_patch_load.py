"""Single-shot test of the patch-load flow.

Plan:
  1. Subscribe (DT1 0x7F000001 = 1) so the device pushes notifications.
  2. Read current memory # (RQ1 0x00000000) and current name (RQ1 0x10000000).
  3. Write memory # 200 to PatchSelect (DT1 0x00000000 = 00 00 0C 08).
  4. Listen for ~2s. Log every DT1 the device emits — especially any
     at 0x10000000 (the bulk patch dump) and any at 0x00000000
     (PatchSelect normalised echo).
  5. Read 0x10000000 NAME. Did it change?
  6. Restore original memory #.

This tells us:
  - Whether writes to 0x00000000 trigger any device-side notification.
  - How long the load actually takes.
  - What the bulk patch dump looks like.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
from device_id import require_alive_raw


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def encode_n(n):
    return bytes([(n >> 12) & 0xF, (n >> 8) & 0xF,
                  (n >> 4) & 0xF, n & 0xF])


def decode_n(b):
    return ((b[0] & 0xF) << 12) | ((b[1] & 0xF) << 8) | \
           ((b[2] & 0xF) << 4) | (b[3] & 0xF)


def main():
    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    s = midi_sniff.Sniffer(in_idx, Path("__nul__.jsonl"), in_name)

    def emit(o):
        if o.get("kind") == "sysex":
            try:
                with lock:
                    events.append((time.time(), bytes.fromhex(o["hex"])))
            except Exception:
                pass
    s._emit = emit
    s.open()
    out_idx, _ = find_output_port("GX-10")
    out = MidiOut(out_idx)
    time.sleep(0.3)

    require_alive_raw(out, events, lock=lock)

    # 1. Subscribe
    out.send_sysex(build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.2)

    # 2. Read original state
    print("== before ==")
    out.send_sysex(build_rq1(0x00000000, 4))
    out.send_sysex(build_rq1(0x10000000, 16))
    time.sleep(0.5)

    with lock:
        snap = list(events)
        events.clear()

    original_n = -1
    original_name = ""
    for ts, e in snap:
        p = parse_dt1(e)
        if not p:
            continue
        if p[0] == 0x00000000 and len(p[1]) >= 4:
            original_n = decode_n(p[1])
            print(f"  PatchSelect = {p[1].hex().upper()} = {original_n}")
        elif p[0] == 0x10000000 and len(p[1]) >= 16:
            original_name = "".join(chr(b) if 32 <= b <= 126 else "?"
                                     for b in p[1][:16])
            print(f"  Name(0x10000000)= '{original_name}'")

    # 3. Write memory # 200 (P01-1)
    print("\n== writing PatchSelect = 200 (P01-1) ==")
    target_bytes = encode_n(200)
    out.send_sysex(build_dt1(0x00000000, target_bytes))
    t_write = time.time()

    # 4. Listen for 3s and log everything
    print("  listening 3.0s for device-side responses...\n")
    time.sleep(3.0)

    with lock:
        snap = list(events)
        events.clear()

    print(f"== {len(snap)} sysex events received during listen window ==")
    addr_first_ts = {}
    addr_count = {}
    for ts, e in snap:
        p = parse_dt1(e)
        if not p:
            continue
        addr, payload = p
        addr_count[addr] = addr_count.get(addr, 0) + 1
        if addr not in addr_first_ts:
            addr_first_ts[addr] = (ts - t_write, payload)
    for addr in sorted(addr_count, key=lambda a: addr_first_ts[a][0]):
        dt, payload = addr_first_ts[addr]
        print(f"  +{dt*1000:6.1f}ms  0x{addr:08X}  hits={addr_count[addr]:3d}  "
              f"first={payload.hex().upper()[:48]}")

    # 5. Read NAME again
    print("\n== after ==")
    out.send_sysex(build_rq1(0x00000000, 4))
    out.send_sysex(build_rq1(0x10000000, 16))
    time.sleep(0.5)
    with lock:
        snap = list(events)
        events.clear()
    new_n = -1
    new_name = ""
    for ts, e in snap:
        p = parse_dt1(e)
        if not p:
            continue
        if p[0] == 0x00000000 and len(p[1]) >= 4:
            new_n = decode_n(p[1])
            print(f"  PatchSelect = {p[1].hex().upper()} = {new_n}")
        elif p[0] == 0x10000000 and len(p[1]) >= 16:
            new_name = "".join(chr(b) if 32 <= b <= 126 else "?"
                                for b in p[1][:16])
            print(f"  Name(0x10000000)= '{new_name}'")

    if new_n == 200 and new_name != original_name:
        print("\nWRITE TOOK EFFECT — patch-load works.")
    elif new_n == 200 and new_name == original_name:
        print(f"\nPatchSelect updated, but Name(0x10000000) unchanged "
              f"— bulk emit may not include the name addr, or memory_temp "
              f"isn't auto-refreshed by patch-select writes.")
    elif new_n != 200:
        print(f"\nPatchSelect did NOT change to 200 (still {new_n}). "
              f"Write was rejected.")

    # 6. Restore
    if original_n >= 0:
        print(f"\nRestoring PatchSelect = {original_n}")
        out.send_sysex(build_dt1(0x00000000, encode_n(original_n)))
        time.sleep(0.3)

    # Unsubscribe
    out.send_sysex(build_dt1(0x7F000001, b"\x00"))
    time.sleep(0.2)

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
