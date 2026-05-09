"""Sweep sub-types for one or more effect TYPEs and capture per-sub-type
default param layouts.

Use case: WAH (TYPE 0x35) has 6 sub-types selected via Param 1 (byte at
0x10001103). Each sub-type may expose a different set of knobs / different
labels. Write the sub-type byte, read back the block, identify which
4-byte slots have non-default values.

Snapshots FxItem #0 first; restores at the end.
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
    ap.add_argument("--effect-type", type=lambda x: int(x, 0), required=True,
                    help="effect category byte to put at 0x10001100 (e.g. 0x35 WAH, 0x08 COMP)")
    ap.add_argument("--effect-name", required=True)
    ap.add_argument("--sub-min", type=int, default=0)
    ap.add_argument("--sub-max", type=int, default=5)
    ap.add_argument("--out", default="captures/bts_subtype_sweep")
    ap.add_argument("--port", default="GX-10")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_idx, _ = midi_send.find_output_port(args.port)
    in_idx, _ = midi_sniff.find_port(args.port)
    if out_idx is None or in_idx is None:
        print("ERROR: missing port"); return 2
    out = midi_send.MidiOut(out_idx)

    q: "queue.Queue[bytes]" = queue.Queue()
    sn_log = out_dir / f"sniff_{args.effect_name}.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    sniffer.open()
    orig_emit = sniffer._emit
    def emit(obj):
        if obj.get("kind") == "sysex":
            try:
                q.put(bytes.fromhex(obj["hex"]))
            except Exception:
                pass
        return orig_emit(obj)
    sniffer._emit = emit

    def drain(secs=0.05):
        time.sleep(secs)
        msgs = []
        while not q.empty():
            try:
                msgs.append(q.get_nowait())
            except Exception:
                break
        return msgs

    def rq1(addr, size, timeout=0.8):
        drain(0)
        out.send_sysex(midi_send.build_rq1(addr, size))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg in drain(0.02):
                p = parse_dt1(msg)
                if p and p[0] == addr:
                    return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.04)

    try:
        # 1. Snapshot
        print(f"snapshotting FxItem #0...", flush=True)
        snapshot = rq1(FXITEM0_BASE, 0x140, timeout=1.5)
        if snapshot is None:
            print("ERROR: no snapshot"); return 2
        print(f"  {len(snapshot)} bytes; head={snapshot[:8].hex()}")
        (out_dir / f"snapshot_before_{args.effect_name}.bin").write_bytes(snapshot)

        # 2. Editor-attach
        dt1(0x7F000001, bytes([0x01]))
        dt1(0x7F000001, bytes([0x01]))

        # 3. Set effect TYPE
        if snapshot[0] != args.effect_type:
            print(f"setting TYPE byte 0x{args.effect_type:02X} ({args.effect_name})", flush=True)
            dt1(FXITEM0_BASE, bytes([args.effect_type]))
            time.sleep(0.2)

        # 4. Per-sub-type sweep
        layouts = []
        for sub in range(args.sub_min, args.sub_max + 1):
            print(f"  sub-type {sub} ...", flush=True)
            dt1(0x10001103, encode_4nibble(sub))
            time.sleep(0.2)
            block = rq1(FXITEM0_BASE, 0x140, timeout=0.8)
            if block is None:
                print(f"    no reply"); continue
            # Decode each FX-Param slot (offsets 0x03, 0x07, ...) up to offset 0x53
            # (Param 21 — past the catalog max).
            params = []
            for n in range(1, 22):
                offset = 0x03 + (n - 1) * 4
                if offset + 4 > len(block):
                    break
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
            print(f"    head: {block[:24].hex()}")
            layouts.append({
                "sub_type": sub,
                "block_hex": block.hex(),
                "params_1_to_21": params,
            })

        # 5. Restore (per-param)
        print("restoring...", flush=True)
        for off in range(min(3, len(snapshot))):
            dt1(FXITEM0_BASE + off, bytes([snapshot[off]]))
        for offset in range(0x03, min(len(snapshot) - 3, 0x7C), 0x04):
            payload = snapshot[offset:offset + 4]
            if len(payload) != 4 or any(b > 0x7F for b in payload):
                continue
            dt1(FXITEM0_BASE + offset, payload)
        time.sleep(0.2)

        # 6. Verify
        after = rq1(FXITEM0_BASE, 0x140, timeout=1.5)
        if after == snapshot:
            print(f"restore VERIFIED")
        else:
            diffs = sum(1 for i in range(min(len(after or b''), len(snapshot)))
                        if (after or b'')[i] != snapshot[i])
            print(f"restore mismatch ({diffs} bytes differ)")

        # 7. Clear editor-attach
        dt1(0x7F000001, bytes([0x00]))

    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass

    # Save analysis
    summary = {
        "effect_type": f"0x{args.effect_type:02X}",
        "effect_name": args.effect_name,
        "sub_range": [args.sub_min, args.sub_max],
        "snapshot_hex": snapshot.hex(),
        "layouts": layouts,
    }
    (out_dir / f"{args.effect_name}_subtypes.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out_dir / f'{args.effect_name}_subtypes.json'}")

    # Pretty diff: which 4-byte slots vary across sub-types?
    print(f"\n=== {args.effect_name} per-sub-type knob slots ===")
    print(f"slot     ", end="")
    for L in layouts:
        print(f"  sub{L['sub_type']:>1d} ", end="")
    print()
    if layouts:
        n_slots = len(layouts[0]["params_1_to_21"])
        for i in range(n_slots):
            param_n = layouts[0]["params_1_to_21"][i]["n"]
            addr = layouts[0]["params_1_to_21"][i]["addr"]
            vals = [L["params_1_to_21"][i]["default_disp"] for L in layouts]
            # Highlight slots where values vary across sub-types
            varies = len(set(vals)) > 1
            mark = "*" if varies else " "
            row = f"P{param_n:2d} {addr}  {mark}"
            for v in vals:
                row += f"  {v:>4d}"
            print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
