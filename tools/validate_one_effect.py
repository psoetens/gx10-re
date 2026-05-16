"""Validate one effect's knob name→address mapping.

Sets FxItem #0 to the requested effect TYPE (sub-type 0), writes
distinctive values 1, 2, 3, 4, ... to as many knob addresses as
typebar_full says the effect has, prints the expected mapping.

Does NOT restore — caller is responsible for chaining writes.
The original FxItem #0 snapshot is saved on the first call to
captures/bts_validate_all/_emergency_snapshot.bin (kept stable
across calls so the final restore can use it).

Usage:
    python tools/validate_one_effect.py --type 0x08
"""
from __future__ import annotations
import argparse
import glob
import json
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
from device_id import require_alive_raw


FXITEM0_BASE = 0x10001100
SUB_TYPE_ADDR = 0x10001103
SNAP = Path("captures/bts_validate_all/_emergency_snapshot.bin")


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def load_typebar_for(type_byte: int):
    for f in sorted(glob.glob("captures/typebar_full/page*/*/summary.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        triplet = d.get("triplet_at_10001100", "")
        if len(triplet) >= 2 and int(triplet[:2], 16) == type_byte:
            return d
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--sub-type", type=int, default=0)
    args = ap.parse_args()

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    sn_log = SNAP.parent / "sniff.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    q: "queue.Queue[bytes]" = queue.Queue()
    id_events: list = []
    def silent_emit(obj):
        import json as _j
        obj.setdefault("t", round(sniffer._ts(), 6))
        obj.setdefault("label", sniffer.label)
        sniffer.log_fp.write(_j.dumps(obj, ensure_ascii=False) + "\n")
        if obj.get("kind") == "sysex":
            try:
                raw = bytes.fromhex(obj["hex"])
                q.put(raw); id_events.append(raw)
            except: pass
    sniffer._emit = silent_emit
    sniffer.open()
    time.sleep(0.3)
    require_alive_raw(out, id_events)

    def drain(secs=0.05):
        time.sleep(secs); msgs = []
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
                if p and p[0] == addr: return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.04)

    try:
        # Snapshot once and reuse for subsequent calls
        if not SNAP.exists():
            print("first run — capturing emergency snapshot...")
            snap = rq1(FXITEM0_BASE, 0x140, 1.5)
            if snap is None:
                print("ERROR: no snapshot"); return 2
            SNAP.write_bytes(snap)
            print(f"  saved snapshot ({len(snap)} bytes; type=0x{snap[0]:02X})")

        dt1(0x7F000001, bytes([0x01]))   # editor-attach (idempotent)
        dt1(0x7F000001, bytes([0x01]))

        tbf = load_typebar_for(args.type)
        effect_name = tbf.get("name") if tbf else "?"
        knobs = tbf.get("knobs", []) if tbf else []
        knob_addrs = []
        for k in knobs:
            addr = k.get("address")
            name = k.get("name_manual_v2") or k.get("name_manual") or "?"
            if addr:
                knob_addrs.append((int(addr, 16), name))
        if not knob_addrs:
            # Fallback: write to first 8 standard slots
            knob_addrs = [(0x10001107 + i * 4, f"P{i+2}") for i in range(8)]

        # Switch effect + sub-type
        dt1(FXITEM0_BASE, bytes([args.type]))
        time.sleep(0.15)
        dt1(SUB_TYPE_ADDR, encode_4nibble(args.sub_type))
        time.sleep(0.05)

        # Write 1..N to claimed addresses
        for i, (addr, name) in enumerate(knob_addrs):
            val = i + 1
            if val > 99: break
            dt1(addr, encode_4nibble(val))

        # Verify writes
        time.sleep(0.1)
        block = rq1(FXITEM0_BASE, 0x140, 1.5)
        actual_type = block[0] if block else None

        print(f"\n=== TYPE 0x{args.type:02X}  {effect_name}  (sub-type {args.sub_type}) ===")
        print(f"  device stored TYPE: 0x{actual_type:02X}"
              f"{'   ← CLAMPED!' if actual_type != args.type else ''}")
        print(f"\n  expected on device LCD labels (in this order, value=position):")
        for i, (addr, name) in enumerate(knob_addrs):
            print(f"    {i+1}. {name:18s} (addr 0x{addr:08X})  expected display = {i+1}")
        print()
    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
