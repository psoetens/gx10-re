"""For the effect currently in BTS slot 0, write the SAME raw value
to ALL knobs simultaneously (bulk write triggers BTS UI refresh,
unlike single-knob writes), then capture every BTS-displayed
(label, value) pair. Cycle raw 0..N to build the full enum/numeric
map per knob.

Usage:
    python tools/probe_bulk_enums.py --tag PHASER --max-raw 20

If BTS becomes unresponsive, kill BTS + python via:
    Get-Process | Where {$_.ProcessName -like "*BOSS*" -or
        $_.ProcessName -like "*msedgewebview*"} | Stop-Process -Force
    Start-Process "C:\\Program Files (x86)\\BOSS\\..."
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


def cluster_rows(elements, y_tol=10):
    if not elements: return []
    elements = sorted(elements, key=lambda e: e[1])
    clusters = []
    cur = [elements[0]]
    for el in elements[1:]:
        if el[1] - cur[-1][1] <= y_tol:
            cur.append(el)
        else:
            clusters.append(sorted(cur, key=lambda e: e[0]))
            cur = [el]
    clusters.append(sorted(cur, key=lambda e: e[0]))
    clusters.sort(key=lambda c: sum(e[1] for e in c) / len(c))
    return clusters


def collect_panel(win, win_l, win_t):
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
                    if 250 <= lx <= 1450 and 480 <= ly <= 900:
                        elements.append((lx, ly, name))
            for child in ctrl.GetChildren():
                walk(child, limit)
        except Exception: pass
    walk(win)

    dd_band = sorted([e for e in elements
                      if DROPDOWN_Y_BAND[0] <= e[1] <= DROPDOWN_Y_BAND[1]],
                     key=lambda e: e[0])
    dropdowns = []
    i = 0
    while i < len(dd_band) - 1:
        if dd_band[i+1][0] - dd_band[i][0] < 200:
            dropdowns.append((dd_band[i][2], dd_band[i+1][2]))
            i += 2
        else:
            i += 1

    knob_elts = [e for e in elements
                 if not (DROPDOWN_Y_BAND[0] <= e[1] <= DROPDOWN_Y_BAND[1])]
    rows = cluster_rows(knob_elts, y_tol=10)
    knobs = []
    used = set()
    for i, vrow in enumerate(rows):
        if i in used: continue
        v_y = sum(e[1] for e in vrow) / len(vrow)
        for j in range(i+1, len(rows)):
            l_y = sum(e[1] for e in rows[j]) / len(rows[j])
            diff = l_y - v_y
            if 35 <= diff <= 95:
                for vx, vy, vn in vrow:
                    lbl = min(rows[j], key=lambda e: abs(e[0]-vx),
                              default=None)
                    if lbl: knobs.append((lbl[2], vn))
                used.add(j)
                break
            elif diff > 95:
                break
    return dropdowns, knobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--max-raw", type=int, default=15)
    ap.add_argument("--settle-ms", type=int, default=500)
    ap.add_argument("--out", default="captures/bts_bulk_enum")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / f"{args.tag}_sniff.jsonl"
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
        print("BTS not found"); os._exit(1)
    win_l = win.BoundingRectangle.left
    win_t = win.BoundingRectangle.top

    try:
        # Find slot 0's FxItem
        out.send_sysex(midi_send.build_rq1(CHAIN_LIST_BASE, 0x32))
        chain = get(CHAIN_LIST_BASE, 0.5)
        if chain is None or chain[0] == 0:
            print("no effect in slot 0"); os._exit(1)
        head_fx = chain[0] - 1
        base = FXITEM_BASE + head_fx * FXITEM_STRIDE

        # Snapshot
        out.send_sysex(midi_send.build_rq1(base, 0x140))
        snap = get(base, 0.6)
        if snap is None:
            print("no FxItem read"); os._exit(1)
        type_byte = snap[0]
        (out_dir / f"{args.tag}_snap.bin").write_bytes(snap)

        # Initial state
        dropdowns0, knobs0 = collect_panel(win, win_l, win_t)
        print(f"FxItem #{head_fx} TYPE=0x{type_byte:02X}")
        print(f"  initial dropdowns: {dropdowns0}")
        print(f"  initial knobs: {[lab for lab, _ in knobs0]}")
        print(f"  probing raw 0..{args.max_raw} (bulk-write all knobs each iter)")
        print()

        # Bulk-write Param 1 (sub-type) AND Params 2..19 each iteration.
        # This forces BTS to refresh on every iteration.
        knob_offsets = list(range(0x03, 0x50, 0x04))  # Param 1..19

        # Per knob/dropdown, accumulate {raw: BTS_value_str}
        per_knob = {}  # label -> {raw: str}
        per_dropdown = {}  # label -> {raw: str}

        for raw_v in range(args.max_raw + 1):
            # Bulk-write all params (sub-type + knobs) to this raw value
            for offset in knob_offsets:
                addr = base + offset
                dt1(addr, encode_4nibble(raw_v))
            time.sleep(args.settle_ms / 1000.0)

            # Capture BTS state — both dropdowns and knobs
            dropdowns_now, knobs_now = collect_panel(win, win_l, win_t)
            for lab, val in dropdowns_now:
                per_dropdown.setdefault(lab, {})[raw_v] = val
            for lab, val in knobs_now:
                per_knob.setdefault(lab, {})[raw_v] = val

        # Print summary
        if per_dropdown:
            print(f"  Dropdowns (sub-type bytes):")
            for lab in sorted(per_dropdown.keys()):
                vals = per_dropdown[lab]
                unique = list(dict.fromkeys(vals.values()))
                print(f"    {lab}: {len(unique)} unique values")
                for r, v in vals.items():
                    print(f"      raw={r:>3d} -> {v!r}")
        print(f"  Per-knob raw -> display map:")
        for lab in sorted(per_knob.keys()):
            vals = per_knob[lab]
            n = len(vals)
            unique = list(dict.fromkeys(vals.values()))
            kind = "enum" if len(unique) <= 10 and \
                   any(not v.lstrip("+-").isdigit() for v in unique if v.strip()) \
                   else "numeric"
            print(f"    {lab}: {kind}, {n} samples, unique={len(unique)}")
            for r, v in vals.items():
                print(f"      raw={r:>3d} -> {v!r}")

        # Restore
        print("\n  restoring snapshot ...")
        for off in range(min(3, len(snap))):
            dt1(base + off, bytes([snap[off]]))
        for offset in range(0x03, min(len(snap) - 3, 0x7C), 0x04):
            p = snap[offset:offset+4]
            if len(p) != 4 or any(b > 0x7F for b in p): continue
            dt1(base + offset, p)
        time.sleep(0.3)

        result = {
            "type_byte": f"0x{type_byte:02X}",
            "tag": args.tag,
            "fxitem_index": head_fx,
            "dropdowns_initial": [list(d) for d in dropdowns0],
            "max_raw_probed": args.max_raw,
            "dropdowns": {
                lab: {"raw_to_display": {str(k): v for k, v in vals.items()}}
                for lab, vals in per_dropdown.items()
            },
            "per_knob": {
                lab: {
                    "raw_to_display": {str(k): v for k, v in vals.items()}
                } for lab, vals in per_knob.items()
            },
        }
        out_path = out_dir / f"{args.tag}_TYPE{type_byte:02X}.json"
        out_path.write_text(json.dumps(result, indent=2))
        print(f"  wrote {out_path}")
    finally:
        try: out.close()
        except Exception: pass
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
