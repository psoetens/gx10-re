"""For the effect currently in slot 0, find every dropdown and every
enum-style knob (BTS-shows non-numeric value), and probe each through
raw values 0..N to build the {raw: display_string} map.

Used to capture the canonical enum orderings (which the device firmware
defines and the manual may not match).

Usage:
    python tools/probe_enums.py --tag PHASER

Run once per effect with that effect dragged into BTS slot 0.
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
SUB_TYPE_OFFSET = 0x03
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
    """Return (dropdowns, knob_pairs). Each as list of dicts."""
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

    # Dropdowns
    dd_band = sorted([e for e in elements
                      if DROPDOWN_Y_BAND[0] <= e[1] <= DROPDOWN_Y_BAND[1]],
                     key=lambda e: e[0])
    dropdowns = []
    i = 0
    while i < len(dd_band) - 1:
        if dd_band[i+1][0] - dd_band[i][0] < 200:
            dropdowns.append({"label": dd_band[i][2], "value": dd_band[i+1][2],
                              "x": dd_band[i][0]})
            i += 2
        else:
            i += 1

    # Knob row pairs (cluster non-dropdown elements)
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
                    if lbl:
                        knobs.append({"label": lbl[2], "value": vn, "x": vx})
                used.add(j)
                break
            elif diff > 95:
                break
    return dropdowns, knobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", default="captures/bts_enum_probe")
    ap.add_argument("--max-raw", type=int, default=30,
                    help="probe raw values 0..max-raw for each enum")
    ap.add_argument("--settle-ms", type=int, default=200,
                    help="ms to wait between SysEx write and UIA read")
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
        print("BTS not found"); return 2
    win_l = win.BoundingRectangle.left
    win_t = win.BoundingRectangle.top

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

        # Collect initial state
        dropdowns0, knobs0 = collect_panel(win, win_l, win_t)
        print(f"Probing FxItem #{head_fx} TYPE=0x{type_byte:02X}")
        print(f"  dropdowns: {[(d['label'], d['value']) for d in dropdowns0]}")
        print(f"  knobs: {len(knobs0)} found")

        # Probe ALL knobs that have a catalog address (enum values can hide
        # behind knobs currently showing numbers).
        enum_knobs = list(knobs0)
        print(f"  probing all {len(enum_knobs)} knobs for enum/numeric mapping")
        print()

        results = {
            "type_byte": f"0x{type_byte:02X}",
            "fxitem_index": head_fx,
            "dropdowns": {},
            "enum_knobs": {},
        }

        # Catalog lookup for address per label (so we know which addr to probe)
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
        # Build label_short -> live_addr
        label_addr = {}
        for cat_addr, lab in cat_labels.items():
            short = lab.split(" (")[0]
            offset = int(cat_addr, 16) - FXITEM_BASE
            label_addr[short] = base + offset

        # Probe DROPDOWNS — TYPE sub-type at offset 0x03 (also any extra ones)
        # For dropdowns, the address is harder to know. Common: TYPE = 0x10001103.
        # AMP-style SP TYPE may be at offset 0x47 or similar.
        # Strategy: try TYPE at offset 0x03 first; for additional dropdowns use
        # catalog (if labeled "TYPE/SP TYPE/etc"). Otherwise skip.
        # For now we explicitly probe offset 0x03 (sub-type byte).
        if dropdowns0:
            sub_addr = base + SUB_TYPE_OFFSET
            sub_label = dropdowns0[0]["label"]
            print(f"  probing dropdown '{sub_label}' at 0x{sub_addr:08X}:")
            seen_strings = []
            for raw in range(args.max_raw + 1):
                dt1(sub_addr, encode_4nibble(raw))
                time.sleep(args.settle_ms / 1000.0)
                _, _ = collect_panel(win, win_l, win_t)  # warm-up read
                dd, _ = collect_panel(win, win_l, win_t)
                if dd:
                    val = dd[0]["value"]
                    seen_strings.append((raw, val))
                    print(f"    raw={raw:>3d} -> {val!r}")
                    # Stop if we see a repeat (max reached, device clamps)
                    if len(seen_strings) >= 3 and \
                       seen_strings[-1][1] == seen_strings[-2][1] == seen_strings[-3][1]:
                        # Clamping detected; remove the last 2 duplicates
                        seen_strings = seen_strings[:-2]
                        print(f"    clamp detected at raw={raw}")
                        break
            results["dropdowns"][sub_label] = {
                "address": f"0x{(FXITEM_BASE + SUB_TYPE_OFFSET):08X}",
                "raw_to_display": {str(r): v for r, v in seen_strings}
            }

        # Probe each KNOB (potentially enum or numeric)
        for ek in enum_knobs:
            lab = ek["label"]
            addr = label_addr.get(lab)
            if not addr:
                print(f"  knob '{lab}': no catalog address; skipping")
                continue
            print(f"  probing '{lab}' at 0x{addr:08X}:")
            seen = []
            for raw in range(args.max_raw + 1):
                dt1(addr, encode_4nibble(raw))
                time.sleep(args.settle_ms / 1000.0)
                _, knobs = collect_panel(win, win_l, win_t)
                cur = next((k["value"] for k in knobs if k["label"] == lab), None)
                if cur is None:
                    continue
                seen.append((raw, cur))
                if len(seen) >= 3 and \
                   seen[-1][1] == seen[-2][1] == seen[-3][1]:
                    seen = seen[:-2]
                    print(f"    clamp detected at raw={raw}; max raw used = {seen[-1][0]}")
                    break
            # Classify: numeric (display matches raw or simple formula) vs enum
            offset = addr - base
            kind = "enum"
            # Heuristic: if at least 80% of values parse as int and follow raw,
            # it's numeric (not interesting for enum catalog). Otherwise enum.
            n_numeric = 0
            for r, v in seen:
                v = v.strip()
                try: int(v); n_numeric += 1; continue
                except ValueError: pass
                if v.startswith("+") or v.startswith("-"):
                    try: int(v[1:]); n_numeric += 1
                    except ValueError: pass
            if seen and n_numeric / len(seen) > 0.7:
                kind = "numeric"
            print(f"    -> {kind}, {len(seen)} values: "
                  f"{[(r, v) for r, v in seen[:6]]}{'...' if len(seen) > 6 else ''}")
            results["enum_knobs"][lab] = {
                "address": f"0x{(FXITEM_BASE + offset):08X}",
                "kind": kind,
                "raw_to_display": {str(r): v for r, v in seen}
            }

        # Restore
        print("\n  restoring snapshot ...")
        for off in range(min(3, len(snap))):
            dt1(base + off, bytes([snap[off]]))
        for offset in range(0x03, min(len(snap) - 3, 0x7C), 0x04):
            p = snap[offset:offset+4]
            if len(p) != 4 or any(b > 0x7F for b in p): continue
            dt1(base + offset, p)
        time.sleep(0.3)

        out_path = out_dir / f"{args.tag}_TYPE{type_byte:02X}.json"
        out_path.write_text(json.dumps(results, indent=2))
        print(f"  wrote {out_path}")
    finally:
        try: out.close()
        except Exception: pass
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
