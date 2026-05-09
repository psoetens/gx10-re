"""Capture-on-demand: user drags an effect into BTS slot 0 (manually);
this tool then writes distinctive values via SysEx and screenshots +
UIA-extracts the result.

Per call, processes ONE effect:
  1. Read current FxItem #0 TYPE byte (so we know what user dropped)
  2. Set Param 1 sub-type = 0
  3. Wait
  4. Write distinctive values 1..12 to consecutive Param 2..13 slots
  5. Wait for BTS to redraw
  6. Take TALLER screenshot (covers row 1 + row 2 of knobs)
  7. UIA extract

Usage:
    # User drags AMP into BTS slot 0, then runs:
    python tools/bts_capture_and_label.py --tag AMP

    # Tool detects current TYPE byte = 0x02, applies writes,
    # saves: captures/bts_typebar_extra/02_AMP_filled_taller.png
    #        captures/bts_typebar_extra/02_AMP_labels.json
"""
from __future__ import annotations
import argparse
import json
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import ImageGrab
import uiautomation as auto

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
import focus_ts


FXITEM0_BASE = 0x10001100
SUB_TYPE_ADDR = 0x10001103
KNOB_AREA_X = 50
KNOB_AREA_Y = 425   # higher to capture effect title
KNOB_AREA_W = 1450
KNOB_AREA_H = 320   # taller to capture row 2 labels

# UIA y-bands — wider to catch both rows
VALUE_ROW_Y_BANDS = [(575, 605), (655, 685), (735, 765)]
LABEL_ROW_Y_BANDS = [(625, 660), (705, 740), (785, 815)]
KNOB_PANEL_X_MIN = 250
KNOB_PANEL_X_MAX = 1450


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def screenshot_window(hwnd, out_path, x, y, w, h):
    l, t, _, _ = focus_ts.get_window_rect(hwnd)
    img = ImageGrab.grab(bbox=(l + x, t + y, l + x + w, t + y + h),
                         all_screens=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def collect_text_elements(win, win_l, win_t):
    found = []
    def walk(ctrl, limit=[5000]):
        if limit[0] <= 0: return
        limit[0] -= 1
        try:
            if ctrl.ControlTypeName == "TextControl":
                name = ctrl.Name
                if name:
                    r = ctrl.BoundingRectangle
                    lx = r.left - win_l
                    ly = r.top - win_t
                    if KNOB_PANEL_X_MIN <= lx <= KNOB_PANEL_X_MAX:
                        found.append((lx, ly, name))
            for child in ctrl.GetChildren():
                walk(child, limit)
        except Exception:
            pass
    walk(win)
    return found


def extract_label_value_rows(elements):
    pairs = []
    for vy_lo, vy_hi in VALUE_ROW_Y_BANDS:
        values = sorted([(x, y, n) for (x, y, n) in elements
                         if vy_lo <= y <= vy_hi], key=lambda e: e[0])
        if not values: continue
        # Match label band ~50 px below
        for ly_lo, ly_hi in LABEL_ROW_Y_BANDS:
            if not (40 < ((ly_lo + ly_hi)/2 - (vy_lo + vy_hi)/2) < 90):
                continue
            labels = sorted([(x, y, n) for (x, y, n) in elements
                             if ly_lo <= y <= ly_hi], key=lambda e: e[0])
            if not labels: continue
            for vx, vy, vn in values:
                lbl = min(labels, key=lambda e: abs(e[0] - vx), default=None)
                if lbl is None: continue
                pairs.append((vx, vy, lbl[2], vn))
            break
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="filename prefix tag")
    ap.add_argument("--out", default="captures/bts_typebar_extra")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("focusing BTS ...")
    hwnd = focus_ts.focus_tone_studio()

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / f"{args.tag}_sniff.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    sniffer.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    def silent(o):
        import json as _j
        o.setdefault("t", round(sniffer._ts(), 6))
        o.setdefault("label", sniffer.label)
        sniffer.log_fp.write(_j.dumps(o, ensure_ascii=False) + "\n")
        if o.get("kind") == "sysex":
            try: q.put(bytes.fromhex(o["hex"]))
            except: pass
    sniffer._emit = silent

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

    win = auto.WindowControl(searchDepth=1, Name="BOSS TONE STUDIO for GX-10")
    if not win.Exists(maxSearchSeconds=5):
        print("ERROR: BTS window not found"); return 2

    try:
        # Read current TYPE byte
        block = rq1(FXITEM0_BASE, 0x140, 1.5)
        if block is None:
            print("ERROR: no FxItem #0 read"); return 2
        type_byte = block[0]
        print(f"current FxItem #0 TYPE: 0x{type_byte:02X}")
        # Save snapshot
        (out_dir / f"{args.tag}_snapshot.bin").write_bytes(block)

        # Editor-attach (idempotent)
        dt1(0x7F000001, bytes([0x01]))
        dt1(0x7F000001, bytes([0x01]))

        # Set sub-type = 0
        dt1(SUB_TYPE_ADDR, encode_4nibble(0))
        time.sleep(0.2)

        # Write distinctive values to Param 2..13
        written = {}
        for i in range(12):
            offset = 0x07 + i * 4
            if offset >= 0x80: break
            addr = FXITEM0_BASE + offset
            v = i + 1
            dt1(addr, encode_4nibble(v))
            written[v] = addr
        time.sleep(0.5)

        # Take taller screenshot
        try: focus_ts.focus_tone_studio()
        except Exception: pass
        time.sleep(0.2)
        slug = f"{type_byte:02X}_{args.tag}"
        screenshot_window(hwnd, out_dir / f"{slug}_filled.png",
                          KNOB_AREA_X, KNOB_AREA_Y, KNOB_AREA_W, KNOB_AREA_H)

        # UIA extract
        win_l, win_t = win.BoundingRectangle.left, win.BoundingRectangle.top
        elements = collect_text_elements(win, win_l, win_t)
        pairs = extract_label_value_rows(elements)
        print(f"  {len(pairs)} label/value pairs found")

        labels_by_addr = {}
        for (vx, vy, label, value_str) in pairs:
            v = value_str.strip()
            addr = None
            try:
                n = int(v); addr = written.get(n)
            except ValueError: pass
            if addr is None and v.startswith("+"):
                try:
                    n = int(v[1:]); addr = written.get(n)
                except ValueError: pass
            if addr:
                labels_by_addr[f"0x{addr:08X}"] = label

        result = {
            "type_byte": f"0x{type_byte:02X}",
            "tag": args.tag,
            "n_pairs": len(pairs),
            "all_pairs": [{"x": x, "y": y, "label": l, "value": v}
                          for (x, y, l, v) in pairs],
            "labels_by_addr": labels_by_addr,
        }
        (out_dir / f"{slug}_labels.json").write_text(json.dumps(result, indent=2))

        for addr, lab in sorted(labels_by_addr.items()):
            print(f"    {addr}  {lab}")

        # NOTE: no automatic restore. User can keep dragging for next effect,
        # or run tools/restore_fxitem0.py manually when done.
        print(f"\nSaved {slug}_filled.png + {slug}_labels.json")
        print("FxItem #0 NOT restored — drop next effect or run tools/restore_fxitem0.py.")

    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
