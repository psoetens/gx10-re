"""Capture labels for an effect by writing distinctive values directly
to a specific FxItem (not just FxItem #0).

Usage:
    python tools/capture_stuck_at_fxitem.py --fxitem 5 --tag AMP

Writes distinctive values to FxItem N's Param 2..13 slots, takes
screenshot, UIA-extracts. Caller must ensure BTS is currently showing
that FxItem (e.g. by clicking the right slot in BTS chain panel).
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


FXITEM_BASE = 0x10001100
FXITEM_STRIDE = 0x200
KNOB_AREA_X = 50
KNOB_AREA_Y = 425
KNOB_AREA_W = 1450
KNOB_AREA_H = 320

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fxitem", type=int, required=True,
                    help="FxItem index 0..19")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", default="captures/bts_typebar_extra")
    ap.add_argument("--no-restore", action="store_true",
                    help="don't restore the FxItem to its pre-write state")
    args = ap.parse_args()

    fxitem_base = FXITEM_BASE + args.fxitem * FXITEM_STRIDE
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"focusing BTS ...")
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
        print("ERROR: BTS not found"); return 2

    try:
        # Snapshot the FxItem
        block = rq1(fxitem_base, 0x140, 1.5)
        if block is None:
            print("ERROR: no FxItem read"); return 2
        type_byte = block[0]
        print(f"FxItem #{args.fxitem} (base 0x{fxitem_base:08X}) TYPE = 0x{type_byte:02X}")
        (out_dir / f"{args.tag}_fx{args.fxitem}_snapshot.bin").write_bytes(block)

        dt1(0x7F000001, bytes([0x01]))   # editor-attach
        dt1(0x7F000001, bytes([0x01]))

        # Set sub-type = 0
        dt1(fxitem_base + 0x03, encode_4nibble(0))
        time.sleep(0.2)

        # Write distinctive values
        written = {}
        for i in range(12):
            offset = 0x07 + i * 4
            if offset >= 0x80: break
            addr = fxitem_base + offset
            v = i + 1
            dt1(addr, encode_4nibble(v))
            written[v] = addr
        time.sleep(0.6)

        try: focus_ts.focus_tone_studio()
        except Exception: pass
        time.sleep(0.2)
        slug = f"{type_byte:02X}_{args.tag}_fx{args.fxitem}"
        out_path = out_dir / f"{slug}_filled.png"
        l, t, _, _ = focus_ts.get_window_rect(hwnd)
        ImageGrab.grab(bbox=(l + KNOB_AREA_X, t + KNOB_AREA_Y,
                             l + KNOB_AREA_X + KNOB_AREA_W,
                             t + KNOB_AREA_Y + KNOB_AREA_H),
                       all_screens=True).save(out_path)

        # UIA extract
        win_l, win_t = win.BoundingRectangle.left, win.BoundingRectangle.top
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
                        if KNOB_PANEL_X_MIN <= lx <= KNOB_PANEL_X_MAX:
                            elements.append((lx, ly, name))
                for child in ctrl.GetChildren():
                    walk(child, limit)
            except Exception: pass
        walk(win)

        pairs = []
        for vy_lo, vy_hi in VALUE_ROW_Y_BANDS:
            values = sorted([(x, y, n) for (x, y, n) in elements
                             if vy_lo <= y <= vy_hi], key=lambda e: e[0])
            if not values: continue
            for ly_lo, ly_hi in LABEL_ROW_Y_BANDS:
                if not (40 < ((ly_lo+ly_hi)/2 - (vy_lo+vy_hi)/2) < 90): continue
                labels = sorted([(x, y, n) for (x, y, n) in elements
                                 if ly_lo <= y <= ly_hi], key=lambda e: e[0])
                if not labels: continue
                for vx, vy, vn in values:
                    lbl = min(labels, key=lambda e: abs(e[0]-vx), default=None)
                    if lbl: pairs.append((vx, vy, lbl[2], vn))
                break
        print(f"  {len(pairs)} pairs found")

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
                # Normalize to FxItem-#0-relative address for the catalog
                offset = addr - fxitem_base
                norm_addr = FXITEM_BASE + offset
                labels_by_addr[f"0x{norm_addr:08X}"] = label

        result = {
            "fxitem": args.fxitem,
            "fxitem_base": f"0x{fxitem_base:08X}",
            "type_byte": f"0x{type_byte:02X}",
            "tag": args.tag,
            "n_pairs": len(pairs),
            "all_pairs": [{"x": x, "y": y, "label": l, "value": v}
                          for (x, y, l, v) in pairs],
            "labels_by_addr_at_fxitem0": labels_by_addr,
        }
        (out_dir / f"{slug}_labels.json").write_text(json.dumps(result, indent=2))
        for addr, lab in sorted(labels_by_addr.items()):
            print(f"    {addr}  {lab}")

        if not args.no_restore:
            print("restoring FxItem ...")
            for off in range(min(3, len(block))):
                dt1(fxitem_base + off, bytes([block[off]]))
            for offset in range(0x03, min(len(block) - 3, 0x7C), 0x04):
                p = block[offset:offset + 4]
                if len(p) != 4 or any(b > 0x7F for b in p): continue
                dt1(fxitem_base + offset, p)
            time.sleep(0.2)
            after = rq1(fxitem_base, 0x140, 1.5)
            if after == block:
                print("  restore VERIFIED")
            else:
                print("  WARNING: restore mismatch")
    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
