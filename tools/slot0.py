"""Show what's in BTS chain slot 0. Run as:
    python tools/slot0.py

Reads CHAIN_LIST + FxItem at chain head via SysEx, then walks BTS's
UIA tree to extract the displayed labels + value strings (so enum
values print as their proper names instead of raw numbers).
"""
from __future__ import annotations
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
CATALOG_PATH = Path(__file__).parent.parent / "captures/bts_typebar_resweep_v2/catalog_visual_extraction.json"

# UIA y-bands inside the slot-detail panel (window-local).
# Generous bands to handle effects with multiple knob rows.
VALUE_ROWS = [(580, 615), (700, 720), (820, 840)]
LABEL_ROWS = [(630, 660), (750, 775), (870, 895)]
# Top of panel has TYPE / SP TYPE dropdowns at y≈494
DROPDOWN_Y_BAND = (485, 510)
# x range to scan inside the slot-detail panel (skip chain panel on left)
PANEL_X_MIN = 250
PANEL_X_MAX = 1450


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def decode4(p: bytes) -> int:
    raw = ((p[0] & 0xF) << 12) | ((p[1] & 0xF) << 8) | \
          ((p[2] & 0xF) << 4) | (p[3] & 0xF)
    return raw - 0x8000


def collect_text(win, win_l, win_t, max_y=900):
    """Walk BTS's UIA tree, return (x, y, name) for TextControls in
    the slot-detail panel area."""
    out = []
    def walk(ctrl, limit=[5000]):
        if limit[0] <= 0: return
        limit[0] -= 1
        try:
            if ctrl.ControlTypeName == "TextControl":
                name = ctrl.Name
                if name:
                    r = ctrl.BoundingRectangle
                    lx, ly = r.left - win_l, r.top - win_t
                    if PANEL_X_MIN <= lx <= PANEL_X_MAX and 480 <= ly <= max_y:
                        out.append((lx, ly, name))
            for child in ctrl.GetChildren():
                walk(child, limit)
        except Exception:
            pass
    walk(win)
    return out


def extract_knob_pairs(elements):
    """Pair each value-row TextControl with its nearest label-row
    TextControl. Returns list of (label, value_str) sorted screen left-to-right
    within each row.
    """
    pairs = []
    for vy_lo, vy_hi in VALUE_ROWS:
        values = sorted([(x, y, n) for (x, y, n) in elements
                         if vy_lo <= y <= vy_hi], key=lambda e: e[0])
        if not values: continue
        for ly_lo, ly_hi in LABEL_ROWS:
            if not (40 < ((ly_lo+ly_hi)/2 - (vy_lo+vy_hi)/2) < 90):
                continue
            labels = sorted([(x, y, n) for (x, y, n) in elements
                             if ly_lo <= y <= ly_hi], key=lambda e: e[0])
            if not labels: continue
            for vx, vy, vn in values:
                lbl = min(labels, key=lambda e: abs(e[0]-vx), default=None)
                if lbl: pairs.append((vx, vy, lbl[2], vn))
            break
    return pairs


def extract_dropdowns(elements):
    """Extract (label, value_str) pairs for the dropdown row at y≈494."""
    band = [(x, y, n) for (x, y, n) in elements
            if DROPDOWN_Y_BAND[0] <= y <= DROPDOWN_Y_BAND[1]]
    band.sort(key=lambda e: e[0])
    # Group as label-value-label-value pairs
    pairs = []
    i = 0
    while i < len(band) - 1:
        # Heuristic: a "label" (e.g. TYPE) followed by a "value" (e.g. TRANSPARENT)
        # within ~150 px of x.
        if band[i+1][0] - band[i][0] < 200:
            pairs.append((band[i][2], band[i+1][2]))
            i += 2
        else:
            i += 1
    return pairs


def main():
    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    if out_idx is None or in_idx is None:
        print("no GX-10 port"); return 2

    out = midi_send.MidiOut(out_idx)
    sn_log = Path("captures/_probe/slot0.jsonl")
    sn_log.parent.mkdir(parents=True, exist_ok=True)
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    sniffer.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    def silent(o):
        if o.get("kind") == "sysex":
            try: q.put(bytes.fromhex(o["hex"]))
            except Exception: pass
    sniffer._emit = silent

    def get(addr, timeout=0.4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                time.sleep(0.005); continue
            p = parse_dt1(msg)
            if p and p[0] == addr:
                return p[1]
        return None

    catalog = {}
    if CATALOG_PATH.exists():
        try: catalog = json.loads(CATALOG_PATH.read_text())
        except Exception: pass

    try:
        # 1. Read CHAIN_LIST
        out.send_sysex(midi_send.build_rq1(CHAIN_LIST_BASE, 0x32))
        chain = get(CHAIN_LIST_BASE, 0.5)
        if chain is None:
            print("no chain reply"); return 2
        top = chain[0]
        if top == 0:
            print("Chain is EMPTY (CHAIN TOP = 0).")
            return 0
        head_fx = top - 1

        # 2. Read FxItem block
        base = FXITEM_BASE + head_fx * FXITEM_STRIDE
        out.send_sysex(midi_send.build_rq1(base, 0x140))
        block = get(base, 0.6)
        if block is None:
            print(f"no FxItem read at #{head_fx}"); return 2
        type_byte = block[0]
        on_off = block[1]
        dup = block[2]

        entry = catalog.get(f"0x{type_byte:02X}", {})
        title = entry.get("title", "?")
        cat = entry.get("category", "?")
        labels = entry.get("address_to_label") or \
                 entry.get("address_to_label_row1") or {}
        if not labels and entry.get("_layout"):
            ref = catalog.get(entry["_layout"], {})
            labels = {k: v for k, v in ref.items()
                      if k.startswith("0x") and isinstance(v, str)}
            if entry.get("knob0") and "0x10001107" in labels:
                labels = dict(labels)
                labels["0x10001107"] = entry["knob0"]

        # 3. Print header FIRST so we always see it even if UIA hangs
        print(f"Slot 0  ->  FxItem #{head_fx}  base 0x{base:08X}")
        print(f"  TYPE  = 0x{type_byte:02X} = {title} ({cat})")
        print(f"  ON    = {'ON' if on_off else 'OFF'}    DupNum = {dup}")
        sys.stdout.flush()

        # 4. Walk BTS UIA tree (best-effort; may fail if BTS not foreground)
        bts_pairs = []
        bts_dropdowns = []
        all_elements = []
        try:
            win = auto.WindowControl(searchDepth=1, Name="BOSS TONE STUDIO for GX-10")
            if win.Exists(maxSearchSeconds=1):
                win_l = win.BoundingRectangle.left
                win_t = win.BoundingRectangle.top
                all_elements = collect_text(win, win_l, win_t)
                bts_dropdowns = extract_dropdowns(all_elements)
                bts_pairs = extract_knob_pairs(all_elements)
        except Exception as e:
            print(f"  (UIA query failed: {e!r})")

        # If --debug-tree, dump all elements
        if "--debug-tree" in sys.argv:
            print(f"  All UIA elements in panel area ({len(all_elements)}):")
            for x, y, n in sorted(all_elements, key=lambda e: (e[1], e[0])):
                print(f"    y={y:>3}  x={x:>4}  {n!r}")
            print()

        if bts_dropdowns:
            print(f"  Dropdowns (BTS UI):")
            for lab, val in bts_dropdowns:
                print(f"    {lab}: {val}")
        print()

        # 5. BTS UI knobs (source of truth — what the user sees right now)
        if bts_pairs:
            print(f"  Knobs (BTS UI, screen left-to-right by row):")
            current_row_y = -1
            for (vx, vy, label, value_str) in sorted(bts_pairs,
                                                      key=lambda e: (e[1], e[0])):
                if current_row_y >= 0 and vy - current_row_y > 30:
                    print()  # row separator
                current_row_y = vy
                print(f"    {label:<20s}  =  {value_str}")
            print()

        # 6. Per-address raw FxItem state with catalog labels (developer view)
        if "--addrs" in sys.argv or not bts_pairs:
            print(f"  Per-address (raw FxItem state):")
            print(f"  {'addr':<14}  {'param':>5}  {'raw':>4}  {'disp':>5}  {'catalog label'}")
            for n in range(1, 41):
                offset = 0x03 + (n - 1) * 4
                if offset + 4 > len(block): break
                p = block[offset:offset+4]
                if any(b > 0x7F for b in p):
                    continue
                raw = decode4(p) + 0x8000
                disp = decode4(p)
                addr_hex = f"0x{base + offset:08X}"
                norm = f"0x{FXITEM_BASE + offset:08X}"
                label = labels.get(norm, "")
                if p == b"\x08\x00\x00\x00" and not label:
                    continue
                label_short = label.split(" (")[0]
                print(f"  {addr_hex}  P{n:>2}  {raw:04X}  {disp:>5d}  {label_short}")

    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        try: out.close()
        except Exception: pass
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
