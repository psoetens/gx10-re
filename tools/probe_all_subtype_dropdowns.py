"""For each effect TYPE 0x00..0x52, probe its sub-type dropdown
(byte at offset 0x03) by cycling raw values 0..30 and capturing
BTS-displayed dropdown text.

Sub-type byte writes reliably trigger BTS UI refresh (unlike
per-knob writes), so this works for all effects in one pass.

Output: captures/bts_subtype_enum/all_dropdowns.json
  { "0xTT": { "type_name": "EFFECT_NAME",
              "subtype_label": "TYPE/STAGE/MODE/etc",
              "raw_to_display": { "0": "...", "1": "...", ... } } }

Run with BTS open and any effect dragged into chain slot 0.
"""
from __future__ import annotations
import argparse
import json
import os
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import uiautomation as auto

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


CHAIN_LIST_BASE = 0x10000F0C
FXITEM_BASE = 0x10001100
FXITEM_STRIDE = 0x200
DROPDOWN_Y_BAND = (480, 520)


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def collect_dropdowns(win, win_l, win_t):
    """Walk BTS UIA tree; return list of {"label","value"} for dropdowns
    in y=480-520 band."""
    elements = []
    def walk(ctrl, limit=[5000]):
        if limit[0] <= 0: return
        limit[0] -= 1
        try:
            if ctrl.ControlTypeName == "TextControl":
                name = ctrl.Name
                if name:
                    r = ctrl.BoundingRectangle
                    lx, ly = r.left - win_l, r.top - win_t
                    if 250 <= lx <= 1450 and \
                       DROPDOWN_Y_BAND[0] <= ly <= DROPDOWN_Y_BAND[1]:
                        elements.append((lx, ly, name))
            for child in ctrl.GetChildren():
                walk(child, limit)
        except Exception: pass
    walk(win)
    elements.sort(key=lambda e: e[0])
    pairs = []
    i = 0
    while i < len(elements) - 1:
        if elements[i+1][0] - elements[i][0] < 200:
            pairs.append({"label": elements[i][2], "value": elements[i+1][2]})
            i += 2
        else:
            i += 1
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type-min", type=lambda x: int(x, 0), default=0x00)
    ap.add_argument("--type-max", type=lambda x: int(x, 0), default=0x52)
    ap.add_argument("--max-sub", type=int, default=20,
                    help="cycle sub-type 0..max-sub (with clamp detection)")
    ap.add_argument("--settle-ms", type=int, default=400)
    ap.add_argument("--out", default="captures/bts_subtype_enum")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / "sniff.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    sniffer.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    def silent(o):
        if o.get("kind") == "sysex":
            try: q.put(bytes.fromhex(o["hex"]))
            except: pass
    sniffer._emit = silent

    def get(addr, timeout=0.4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: msg = q.get_nowait()
            except queue.Empty: time.sleep(0.005); continue
            p = parse_dt1(msg)
            if p and p[0] == addr: return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.04)

    win = auto.WindowControl(searchDepth=1, Name="BOSS TONE STUDIO for GX-10")
    if not win.Exists(maxSearchSeconds=2):
        print("BTS not found"); return 2
    win_l = win.BoundingRectangle.left
    win_t = win.BoundingRectangle.top

    # Find chain slot 0's FxItem
    out.send_sysex(midi_send.build_rq1(CHAIN_LIST_BASE, 0x32))
    chain = get(CHAIN_LIST_BASE, 0.5)
    if chain is None or chain[0] == 0:
        print("no effect in slot 0; drag any effect into slot 0 first")
        os._exit(1)
    head_fx = chain[0] - 1
    base = FXITEM_BASE + head_fx * FXITEM_STRIDE

    # Snapshot
    out.send_sysex(midi_send.build_rq1(base, 0x140))
    snap = get(base, 0.6)
    if snap is None:
        print("no FxItem read"); os._exit(1)
    (out_dir / "snapshot.bin").write_bytes(snap)
    print(f"slot 0 FxItem #{head_fx}, original TYPE 0x{snap[0]:02X}")
    print()

    catalog_path = Path(__file__).parent.parent / "captures/bts_typebar_resweep_v2/catalog_visual_extraction.json"
    catalog = {}
    if catalog_path.exists():
        try: catalog = json.loads(catalog_path.read_text())
        except Exception: pass

    all_results = {}
    out_path = out_dir / "all_dropdowns.json"

    try:
        # Editor-attach (idempotent)
        dt1(0x7F000001, bytes([0x01]))

        for t in range(args.type_min, args.type_max + 1):
            # Set TYPE byte
            dt1(base, bytes([t]))
            time.sleep(args.settle_ms / 1000.0)
            # Reset Param 1 (sub-type) to 0
            dt1(base + 0x03, encode_4nibble(0))
            time.sleep(args.settle_ms / 1000.0)

            # Initial UIA read
            dropdowns0 = collect_dropdowns(win, win_l, win_t)
            tname = catalog.get(f"0x{t:02X}", {}).get("title", "?")

            if not dropdowns0:
                print(f"  TYPE 0x{t:02X} ({tname}): no dropdown — skip")
                all_results[f"0x{t:02X}"] = {
                    "type_name": tname, "no_dropdown": True
                }
                out_path.write_text(json.dumps(all_results, indent=2))
                continue

            sub_label = dropdowns0[0]["label"]
            print(f"  TYPE 0x{t:02X} ({tname}) — dropdown '{sub_label}':", end="", flush=True)

            seen = []
            for raw in range(args.max_sub + 1):
                dt1(base + 0x03, encode_4nibble(raw))
                time.sleep(args.settle_ms / 1000.0)
                dd = collect_dropdowns(win, win_l, win_t)
                if not dd:
                    continue
                val = dd[0]["value"]
                seen.append((raw, val))
                # Clamp detect
                if len(seen) >= 3 and \
                   seen[-1][1] == seen[-2][1] == seen[-3][1]:
                    seen = seen[:-2]
                    break

            unique_vals = list(dict.fromkeys(v for _, v in seen))
            print(f" {len(unique_vals)} unique values", flush=True)
            for raw, val in seen:
                print(f"    raw={raw:>3d} -> {val!r}")
            all_results[f"0x{t:02X}"] = {
                "type_name": tname,
                "subtype_label": sub_label,
                "raw_to_display": {str(r): v for r, v in seen},
            }
            out_path.write_text(json.dumps(all_results, indent=2))

        # Restore
        print("\nrestoring snapshot ...")
        for off in range(min(3, len(snap))):
            dt1(base + off, bytes([snap[off]]))
        for offset in range(0x03, min(len(snap) - 3, 0x7C), 0x04):
            p = snap[offset:offset+4]
            if len(p) != 4 or any(b > 0x7F for b in p): continue
            dt1(base + offset, p)
        time.sleep(0.3)

        dt1(0x7F000001, bytes([0x00]))
    finally:
        try: out.close()
        except Exception: pass
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
