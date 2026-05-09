"""For the effect currently in chain slot 0, probe each visible knob:
write a set of test raw values and capture BTS-displayed strings.

Output: per-knob enum map + range info. Restores user's snapshot at end.

Usage:
    python tools/probe_current_effect.py
    python tools/probe_current_effect.py --tag MY_PHASER

Run with the effect you want to map loaded in BTS slot 0.
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

# Test values to probe: covers small enums (0..15) and numeric extents.
TEST_VALUES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                20, 30, 50, 75, 100, 127]


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


def collect_knob_pairs(win, win_l, win_t):
    """Walk BTS UIA tree; return list of (label, value_str) for each knob,
    plus (label, value_str) for each dropdown."""
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

    # Dropdowns (y≈494)
    dd_band = sorted([e for e in elements if 480 <= e[1] <= 520],
                     key=lambda e: e[0])
    dropdowns = []
    i = 0
    while i < len(dd_band) - 1:
        if dd_band[i+1][0] - dd_band[i][0] < 200:
            dropdowns.append((dd_band[i][2], dd_band[i+1][2]))
            i += 2
        else:
            i += 1

    # Knob rows (cluster)
    knob_elements = [e for e in elements if not (480 <= e[1] <= 520)]
    rows = cluster_rows(knob_elements, y_tol=10)
    knobs = []  # (label, value_str)
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
                    if lbl: knobs.append((lbl[2], vn, vx))
                used.add(j)
                break
            elif diff > 95:
                break
    return dropdowns, knobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="effect")
    ap.add_argument("--out", default="captures/bts_knob_probe")
    ap.add_argument("--values", default=None,
                    help="comma-separated test values; default uses TEST_VALUES")
    args = ap.parse_args()

    test_vals = TEST_VALUES if args.values is None else \
                [int(v) for v in args.values.split(",")]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    if out_idx is None or in_idx is None:
        print("no GX-10 port"); return 2
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
        print("BTS not found"); return 2

    try:
        # Find slot-0 head FxItem
        out.send_sysex(midi_send.build_rq1(CHAIN_LIST_BASE, 0x32))
        chain = get(CHAIN_LIST_BASE, 0.5)
        if chain is None or chain[0] == 0:
            print("no effect in slot 0"); return 2
        head_fx = chain[0] - 1
        base = FXITEM_BASE + head_fx * FXITEM_STRIDE

        # Snapshot
        out.send_sysex(midi_send.build_rq1(base, 0x140))
        snap = get(base, 0.6)
        if snap is None:
            print("no FxItem read"); return 2
        type_byte = snap[0]
        (out_dir / f"{args.tag}_snap.bin").write_bytes(snap)

        # Get initial BTS state for labels + addresses
        win_l = win.BoundingRectangle.left
        win_t = win.BoundingRectangle.top
        dropdowns0, knobs0 = collect_knob_pairs(win, win_l, win_t)
        if not knobs0:
            print("BTS shows no knobs (empty chain or wrong slot)"); return 2

        print(f"Probing FxItem #{head_fx} TYPE=0x{type_byte:02X}")
        print(f"  initial dropdowns: {dropdowns0}")
        print(f"  initial knobs: {len(knobs0)} found")
        for lab, val, vx in knobs0:
            print(f"    {lab}: {val} (x={vx})")
        print()

        # Use existing catalog to map BTS labels to addresses.
        catalog_path = Path(__file__).parent.parent / "captures/bts_typebar_resweep_v2/catalog_visual_extraction.json"
        catalog = {}
        if catalog_path.exists():
            try: catalog = json.loads(catalog_path.read_text())
            except Exception: pass
        entry = catalog.get(f"0x{type_byte:02X}", {})
        cat_labels = entry.get("address_to_label") or \
                     entry.get("address_to_label_row1") or {}
        if not cat_labels and entry.get("_layout"):
            ref = catalog.get(entry["_layout"], {})
            cat_labels = {k: v for k, v in ref.items()
                          if k.startswith("0x") and isinstance(v, str)}

        # Build address → label by combining catalog with BTS-shown labels.
        # The catalog is the authoritative source for which address corresponds
        # to which knob name. (BTS labels per knob match catalog entries by name.)
        label_to_addr = {}
        catalog_labels_by_short = {}
        for cat_addr_hex, lab in cat_labels.items():
            short = lab.split(" (")[0]
            offset = int(cat_addr_hex, 16) - FXITEM_BASE
            live_addr = base + offset
            catalog_labels_by_short[short] = live_addr
        for lab, val, vx in knobs0:
            if lab in catalog_labels_by_short:
                label_to_addr[lab] = catalog_labels_by_short[lab]

        print(f"  catalog had {len(cat_labels)} addr->label entries, {len(catalog_labels_by_short)} short-keys")
        print(f"  short keys: {list(catalog_labels_by_short.keys())}")
        print(f"  BTS labels: {[lab for lab, _, _ in knobs0]}")
        print(f"  catalog matched {len(label_to_addr)}/{len(knobs0)} knob labels:")
        for lab, addr in label_to_addr.items():
            print(f"    {lab}: 0x{addr:08X}")
        print()

        # Step 2: For each identified knob, probe with test values
        knob_data = {}
        for label, addr in label_to_addr.items():
            offset = addr - base
            results = {}
            for tv in test_vals:
                dt1(addr, encode_4nibble(tv))
                time.sleep(0.15)
                _, current_knobs = collect_knob_pairs(win, win_l, win_t)
                # Find this label's value in BTS
                for lab2, val2, _vx in current_knobs:
                    if lab2 == label:
                        results[tv] = val2
                        break
            knob_data[label] = {
                "address_at_fxitem0": f"0x{FXITEM_BASE + offset:08X}",
                "raw_to_display": results
            }
            print(f"  {label}: {results}")

        # Restore
        for off in range(min(3, len(snap))):
            dt1(base + off, bytes([snap[off]]))
        for offset in range(0x03, min(len(snap) - 3, 0x7C), 0x04):
            p = snap[offset:offset+4]
            if len(p) != 4 or any(b > 0x7F for b in p): continue
            dt1(base + offset, p)
        time.sleep(0.3)
        out.send_sysex(midi_send.build_rq1(base, 0x140))
        after = get(base, 1.0)
        verified = (after is not None and after[:0x80] == snap[:0x80])

        # Save catalog entry
        result = {
            "type_byte": f"0x{type_byte:02X}",
            "fxitem_index": head_fx,
            "dropdowns_initial": dropdowns0,
            "knobs": knob_data,
            "n_knobs_extracted": len(knob_data),
            "n_knobs_visible": len(knobs0),
            "restore_verified": verified,
        }
        out_path = out_dir / f"{args.tag}_TYPE{type_byte:02X}.json"
        out_path.write_text(json.dumps(result, indent=2))
        print(f"\nWrote {out_path}")
        print(f"  restore: {'VERIFIED' if verified else 'mismatch'}")
    finally:
        try: out.close()
        except Exception: pass
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
