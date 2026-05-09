"""Sequential per-effect validator.

For each effect TYPE in 0x00..0x52:
  1. Switch FxItem #0 to that effect (sub-type 0)
  2. Write distinctive values 1, 2, 3, 4, … to as many knob slots as
     typebar_full says the effect has
  3. Print expected label list
  4. Pause for user input: y if labels show 1, 2, 3, 4, … in order;
     n + actual reading otherwise. q to quit early.
  5. Save result, move on

Snapshots FxItem #0 first. After exit (graceful or quit), runs the
restore. Resumable via --start-from.

Run yourself (interactive):
    python tools/validate_all_effects.py
    # answer y / n / "actual: 3,4,1,2" / q at each prompt
"""
from __future__ import annotations
import argparse
import glob
import json
import queue
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


FXITEM0_BASE = 0x10001100
SUB_TYPE_ADDR = 0x10001103


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def load_typebar() -> dict[int, dict]:
    """type_byte -> {name, knobs: [{address, name, ...}, ...]}"""
    out = {}
    for f in sorted(glob.glob("captures/typebar_full/page*/*/summary.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        triplet = d.get("triplet_at_10001100", "")
        if len(triplet) < 2:
            continue
        type_byte = int(triplet[:2], 16)
        out[type_byte] = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=f"captures/bts_validate_all/run_{datetime.now():%Y%m%d_%H%M%S}.json")
    ap.add_argument("--start-from", type=lambda x: int(x, 0), default=0x00)
    ap.add_argument("--end-at", type=lambda x: int(x, 0), default=0x52)
    ap.add_argument("--skip", type=lambda x: [int(t, 0) for t in x.split(",") if t],
                    default=[], help="comma-separated TYPE bytes to skip")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    typebar = load_typebar()
    print(f"loaded {len(typebar)} effects from typebar_full reference")

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    if out_idx is None or in_idx is None:
        print("ERROR: no GX-10 port"); return 2
    out = midi_send.MidiOut(out_idx)
    sn_log = out_path.parent / f"{out_path.stem}_sniff.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    sniffer.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    # Silence the sniffer's stdout (it prints every MIDI clock pulse F8).
    # Keep the JSONL log file but suppress console output.
    def silent_emit(obj):
        import json as _j
        obj.setdefault("t", round(sniffer._ts(), 6))
        obj.setdefault("label", sniffer.label)
        sniffer.log_fp.write(_j.dumps(obj, ensure_ascii=False) + "\n")
        if obj.get("kind") == "sysex":
            try: q.put(bytes.fromhex(obj["hex"]))
            except: pass
    sniffer._emit = silent_emit

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
                if p and p[0] == addr:
                    return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.04)

    results = []
    snapshot = None

    try:
        # 1. Snapshot
        print("\nsnapshotting FxItem #0 ...")
        snapshot = rq1(FXITEM0_BASE, 0x140, 1.5)
        if snapshot is None:
            print("ERROR: no snapshot"); return 2
        print(f"  {len(snapshot)} bytes; head: {snapshot[:8].hex()}")
        # Save snapshot for emergency restore
        Path("captures/bts_validate_all/_emergency_snapshot.bin").parent.mkdir(parents=True, exist_ok=True)
        Path("captures/bts_validate_all/_emergency_snapshot.bin").write_bytes(snapshot)
        original_type = snapshot[0]

        # 2. Editor-attach
        dt1(0x7F000001, bytes([0x01]))
        dt1(0x7F000001, bytes([0x01]))

        # 3. Per-effect loop
        for t in range(args.start_from, args.end_at + 1):
            if t in args.skip:
                continue
            tbf = typebar.get(t)
            effect_name = tbf.get("name") if tbf else "?"
            knobs = tbf.get("knobs", []) if tbf else []
            knob_addrs = []
            for k in knobs:
                addr = k.get("address")
                name = k.get("name_manual_v2") or k.get("name_manual") or "?"
                if addr:
                    knob_addrs.append((int(addr, 16), name))

            # If typebar_full has no info, write to first 8 standard slots
            if not knob_addrs:
                knob_addrs = [(0x10001107 + i * 4, f"P{i+2}") for i in range(8)]

            # 4. Switch effect
            dt1(FXITEM0_BASE, bytes([t]))
            time.sleep(0.15)
            dt1(SUB_TYPE_ADDR, encode_4nibble(0))  # sub-type 0
            time.sleep(0.05)

            # 5. Write distinctive values 1..N to typebar_full's claimed knob addresses
            for i, (addr, name) in enumerate(knob_addrs):
                val = i + 1   # 1, 2, 3, 4, ...
                if val > 99:
                    break
                dt1(addr, encode_4nibble(val))

            # 6. Print expected
            print(f"\n=== TYPE 0x{t:02X}: {effect_name} ({len(knob_addrs)} knobs) ===")
            for i, (addr, name) in enumerate(knob_addrs):
                print(f"  expected: {name:18s} (addr 0x{addr:08X}) = {i+1}")

            # 7. Ask user
            try:
                resp = input("   Match (y/n + actual / q)? ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\ninterrupted"); break
            if resp.lower() == "q":
                break

            results.append({
                "type_byte": f"0x{t:02X}",
                "effect_name": effect_name,
                "expected_in_order": [name for _, name in knob_addrs],
                "expected_addrs": [f"0x{a:08X}" for a, _ in knob_addrs],
                "user_response": resp,
            })
            # Persist progress
            out_path.write_text(json.dumps(results, indent=2))

        print(f"\nrestoring FxItem #0 to original (TYPE 0x{original_type:02X})...")
        for off in range(min(3, len(snapshot))):
            dt1(FXITEM0_BASE + off, bytes([snapshot[off]]))
        for offset in range(0x03, min(len(snapshot) - 3, 0x7C), 0x04):
            payload = snapshot[offset:offset + 4]
            if len(payload) != 4 or any(b > 0x7F for b in payload):
                continue
            dt1(FXITEM0_BASE + offset, payload)
        time.sleep(0.2)
        after = rq1(FXITEM0_BASE, 0x140, 1.5)
        if after == snapshot:
            print("  restore VERIFIED")
        else:
            print("  WARNING: restore mismatch")

        # Clear editor-attach
        dt1(0x7F000001, bytes([0x00]))

    finally:
        out_path.write_text(json.dumps(results, indent=2))
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass
        print(f"\nresults saved to: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
