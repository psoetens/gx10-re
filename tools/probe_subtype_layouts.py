"""SysEx-only test for sub-type-dependent knob layouts.

For a TYPE byte (e.g. 0x1A HARM), cycle Param 1 (sub-type) 0..N and
read back the FxItem block at each. Identifies which 4-byte slots
have NEW non-zero defaults at higher sub-types ⇒ those are the
"expanded" knobs added when sub-type increases.

No BTS needed — pure SysEx round-trip.
"""
from __future__ import annotations
import argparse
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", type=lambda x: int(x, 0), required=True,
                    help="effect TYPE byte (e.g. 0x1A HARM)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--sub-max", type=int, default=4)
    ap.add_argument("--out", default="captures/bts_subtype_layout")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / f"{args.name}_sniff.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    q: "queue.Queue[bytes]" = queue.Queue()
    id_events: list = []   # parallel list for require_alive_raw
    def silent(o):
        import json as _j
        o.setdefault("t", round(sniffer._ts(), 6))
        o.setdefault("label", sniffer.label)
        sniffer.log_fp.write(_j.dumps(o, ensure_ascii=False) + "\n")
        if o.get("kind") == "sysex":
            try:
                raw = bytes.fromhex(o["hex"])
                q.put(raw); id_events.append(raw)
            except: pass
    sniffer._emit = silent
    sniffer.open()
    time.sleep(0.3)
    require_alive_raw(out, id_events)

    def drain(secs=0.05):
        time.sleep(secs); msgs = []
        while not q.empty():
            try: msgs.append(q.get_nowait())
            except: break
        return msgs

    def rq1(addr, size, timeout=1.0):
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
        # Snapshot current FxItem #0
        snap = rq1(FXITEM0_BASE, 0x140, 1.5)
        if snap is None:
            print("ERROR: no snapshot"); return 2
        (out_dir / f"{args.name}_snapshot.bin").write_bytes(snap)
        print(f"snapshot: {len(snap)} bytes; original TYPE = 0x{snap[0]:02X}")

        dt1(0x7F000001, bytes([0x01]))  # editor-attach (idempotent)

        # Set TYPE byte
        dt1(FXITEM0_BASE, bytes([args.type]))
        time.sleep(0.2)

        # Cycle sub-type
        per_sub = {}
        for sub in range(args.sub_max + 1):
            dt1(FXITEM0_BASE + 0x03, encode_4nibble(sub))
            time.sleep(0.3)
            block = rq1(FXITEM0_BASE, 0x140, 1.0)
            if block is None:
                print(f"  sub {sub}: no reply")
                continue
            params = []
            for n in range(1, 33):
                offset = 0x03 + (n - 1) * 4
                if offset + 4 > len(block): break
                p = block[offset:offset + 4]
                raw = ((p[0] & 0xF) << 12) | ((p[1] & 0xF) << 8) | \
                      ((p[2] & 0xF) << 4) | (p[3] & 0xF)
                disp = raw - 0x8000
                params.append({
                    "n": n, "offset": f"0x{offset:02X}",
                    "addr": f"0x{(FXITEM0_BASE + offset):08X}",
                    "default_hex": p.hex(),
                    "default_disp": disp,
                })
            per_sub[f"sub_{sub}"] = params
            print(f"  sub {sub}: head = {block[:24].hex()}")

        # Restore
        for off in range(min(3, len(snap))):
            dt1(FXITEM0_BASE + off, bytes([snap[off]]))
        for offset in range(0x03, min(len(snap) - 3, 0x7C), 0x04):
            p = snap[offset:offset + 4]
            if len(p) != 4 or any(b > 0x7F for b in p): continue
            dt1(FXITEM0_BASE + offset, p)
        time.sleep(0.2)
        after = rq1(FXITEM0_BASE, 0x140, 1.5)
        if after == snap:
            print("  restore VERIFIED")
        else:
            print("  WARNING: restore mismatch")

        dt1(0x7F000001, bytes([0x00]))

        # Compare layouts: which slots vary across sub-types?
        print(f"\n=== {args.name} sub-type variations ===")
        if per_sub:
            sub_keys = sorted(per_sub.keys())
            n_params = len(per_sub[sub_keys[0]])
            print(f"slot        addr       ", end="")
            for k in sub_keys:
                print(f"  {k:>6s}", end="")
            print()
            for i in range(n_params):
                vals = [per_sub[k][i]["default_disp"] for k in sub_keys]
                if len(set(vals)) > 1:  # varies
                    p = per_sub[sub_keys[0]][i]
                    row = f"P{p['n']:2d} (off {p['offset']})  {p['addr']}  "
                    for v in vals:
                        row += f"  {v:>6d}"
                    row += "  *"
                    print(row)

        Path(out_dir / f"{args.name}_summary.json").write_text(
            json.dumps({"type_byte": f"0x{args.type:02X}", "name": args.name,
                        "per_sub": per_sub}, indent=2))
        print(f"\nSummary: {out_dir / f'{args.name}_summary.json'}")
    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
