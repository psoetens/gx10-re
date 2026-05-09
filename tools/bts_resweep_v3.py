"""v3 BTS resweep — uses pyautogui to click slot 0 in BTS's chain
panel between each TYPE switch, forcing BTS to re-pull from the
device and redraw the slot-detail panel.

Process per effect:
  1. Click on slot 1 in BTS chain (deselects slot 0)
  2. Click on slot 0 in BTS chain (re-selects, forces re-pull)
  3. SysEx: set TYPE byte + sub-type
  4. Click slot 0 again (forces BTS to re-pull AFTER the SysEx write)
  5. Wait
  6. Screenshot + UIA extract

For effects we previously got cleanly via v2 UIA, this just confirms.
For effects v2 missed (BTS UI lag), this should unlock them.
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
import pyautogui
import uiautomation as auto

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
import focus_ts


pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

FXITEM0_BASE = 0x10001100
SUB_TYPE_ADDR = 0x10001103

# Window-local coords of chain slots (per effect_catalog.SLOT0)
SLOT0_X = 285
SLOT0_Y = 312
SLOT1_X = 285  # 2nd chain hex — same x, different y
SLOT1_Y = 372

KNOB_AREA_X = 50
KNOB_AREA_Y = 460
KNOB_AREA_W = 1450
KNOB_AREA_H = 280   # taller — capture row 2 labels

VALUE_ROW_Y_BANDS = [(580, 605), (660, 685)]
LABEL_ROW_Y_BANDS = [(630, 655), (710, 740)]
KNOB_PANEL_X_MIN = 250
KNOB_PANEL_X_MAX = 1300


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def screenshot_window(hwnd, out_path: Path, x, y, w, h):
    l, t, _, _ = focus_ts.get_window_rect(hwnd)
    img = ImageGrab.grab(bbox=(l + x, t + y, l + x + w, t + y + h),
                         all_screens=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def click_window_local(hwnd, x_local, y_local):
    """Click at window-local coordinates."""
    sx, sy = focus_ts.screen_xy(hwnd, x_local, y_local)
    pyautogui.click(sx, sy)


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
        for ly_lo, ly_hi in LABEL_ROW_Y_BANDS:
            if abs(((vy_lo + vy_hi) / 2) - ((ly_lo + ly_hi) / 2)) > 100:
                continue
            labels = sorted([(x, y, n) for (x, y, n) in elements
                             if ly_lo <= y <= ly_hi], key=lambda e: e[0])
            if not labels: continue
            for vx, vy, vn in values:
                lbl = min(labels, key=lambda e: abs(e[0] - vx), default=None)
                if lbl is None: continue
                pairs.append((vx, lbl[2], vn))
            break
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="captures/bts_typebar_resweep_v3")
    ap.add_argument("--start-from", type=lambda x: int(x, 0), default=0x00)
    ap.add_argument("--end-at", type=lambda x: int(x, 0), default=0x52)
    ap.add_argument("--settle-ms", type=int, default=1000)
    ap.add_argument("--n-distinctive", type=int, default=12)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load name_by_type
    import glob
    name_by_type: dict[int, str] = {}
    for f in sorted(glob.glob("captures/typebar_full/page*/*/summary.json")):
        try: d = json.load(open(f))
        except Exception: continue
        triplet = d.get("triplet_at_10001100", "")
        if len(triplet) >= 2:
            name_by_type[int(triplet[:2], 16)] = d.get("name", "?")

    print("focusing BTS...")
    hwnd = focus_ts.focus_tone_studio()

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / "sniff.jsonl"
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

    catalog = {}

    try:
        snap = rq1(FXITEM0_BASE, 0x140, 1.5)
        if snap is None:
            print("ERROR: no snapshot"); return 2
        (out_dir / "_emergency_snapshot.bin").write_bytes(snap)
        print(f"snapshot: {len(snap)} bytes; original TYPE = 0x{snap[0]:02X}")

        dt1(0x7F000001, bytes([0x01]))
        dt1(0x7F000001, bytes([0x01]))

        for t in range(args.start_from, args.end_at + 1):
            name = name_by_type.get(t, f"unk_0x{t:02X}")
            slug = f"{t:02X}_{name}".replace("/", "_").replace(" ", "_")
            print(f"\n=== TYPE 0x{t:02X}: {name} ===")

            # 1. Set TYPE byte + sub-type via SysEx
            dt1(FXITEM0_BASE, bytes([t]))
            time.sleep(0.05)
            dt1(SUB_TYPE_ADDR, encode_4nibble(0))
            time.sleep(0.05)

            # 2. Force BTS to re-pull: click on slot 1 then back to slot 0
            try:
                focus_ts.focus_tone_studio()
                click_window_local(hwnd, SLOT1_X, SLOT1_Y)
                time.sleep(0.15)
                click_window_local(hwnd, SLOT0_X, SLOT0_Y)
                time.sleep(args.settle_ms / 1000.0)
            except Exception as e:
                print(f"  click failed: {e}")

            # 3. Screenshot default state
            try: focus_ts.focus_tone_studio()
            except Exception: pass
            time.sleep(0.1)
            win_l, win_t = win.BoundingRectangle.left, win.BoundingRectangle.top
            screenshot_window(hwnd, out_dir / f"{slug}_default.png",
                              KNOB_AREA_X, KNOB_AREA_Y, KNOB_AREA_W, KNOB_AREA_H)

            elements = collect_text_elements(win, win_l, win_t)
            default_pairs = extract_label_value_rows(elements)
            print(f"  default knobs: {len(default_pairs)}")

            # 4. Write distinctive values
            written: dict[int, int] = {}
            for i in range(args.n_distinctive):
                offset = 0x07 + i * 4
                if offset >= 0x80: break
                addr = FXITEM0_BASE + offset
                v = i + 1
                dt1(addr, encode_4nibble(v))
                written[v] = addr
            time.sleep(args.settle_ms / 1000.0)

            try: focus_ts.focus_tone_studio()
            except Exception: pass
            time.sleep(0.1)
            screenshot_window(hwnd, out_dir / f"{slug}_filled.png",
                              KNOB_AREA_X, KNOB_AREA_Y, KNOB_AREA_W, KNOB_AREA_H)

            # 5. UIA extract with retry
            filled_pairs = []
            for retry in range(3):
                elements = collect_text_elements(win, win_l, win_t)
                filled_pairs = extract_label_value_rows(elements)
                if filled_pairs: break
                time.sleep(0.5)
            print(f"  filled knobs:  {len(filled_pairs)} (retry={retry})")

            labels_by_addr = {}
            for (vx, label, value_str) in filled_pairs:
                v_str = value_str.strip()
                addr = None
                try:
                    n = int(v_str)
                    if n in written: addr = written[n]
                except ValueError:
                    pass
                if addr is None and v_str.startswith("+"):
                    try:
                        n = int(v_str[1:])
                        if n in written: addr = written[n]
                    except ValueError: pass
                if addr is not None:
                    labels_by_addr[f"0x{addr:08X}"] = label

            for addr, lab in sorted(labels_by_addr.items()):
                print(f"    {addr}  {lab}")

            catalog[f"0x{t:02X}"] = {
                "effect_name_typebar": name,
                "n_default_knobs": len(default_pairs),
                "n_filled_knobs": len(filled_pairs),
                "default_knobs": [{"label": l, "value": v, "x": x}
                                  for (x, l, v) in default_pairs],
                "filled_knobs": [{"label": l, "value": v, "x": x}
                                 for (x, l, v) in filled_pairs],
                "labels_by_addr": labels_by_addr,
            }
            (out_dir / "catalog.json").write_text(json.dumps(catalog, indent=2))

        # Restore
        print("\nrestoring FxItem #0 ...")
        for off in range(min(3, len(snap))):
            dt1(FXITEM0_BASE + off, bytes([snap[off]]))
        for offset in range(0x03, min(len(snap) - 3, 0x7C), 0x04):
            payload = snap[offset:offset + 4]
            if len(payload) != 4 or any(b > 0x7F for b in payload): continue
            dt1(FXITEM0_BASE + offset, payload)
        time.sleep(0.2)
        after = rq1(FXITEM0_BASE, 0x140, 1.5)
        if after == snap:
            print("  restore VERIFIED")
        else:
            print("  WARNING: restore mismatch")

        dt1(0x7F000001, bytes([0x00]))
    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass
    print(f"\nDONE. Catalog at {out_dir/'catalog.json'}")


if __name__ == "__main__":
    sys.exit(main())
