"""Drag-and-drop reliability test, run-many-effects variant.

For each candidate drag strategy:
  1. restore_baseline ONCE  (clean U10-1, fresh TS)
  2. drag effects 0..N-1 from the typebar onto slot 0 in sequence
     (subsequent drops replace the previous effect)
  3. After each drag: take a screenshot and capture USBPcap; the drag
     is counted as successful iff the captured DT1 includes the
     expected effect-type byte at 0x10001100.

Outputs per-strategy results table and saves a screenshot of every drag.
"""
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image, ImageGrab
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from effect_catalog import (PAGE_0, HEX_Y, SLOT0_X, SLOT0_Y, hex_x_pos)
from map_all_effects import (restore_baseline, usbpcap_start, usbpcap_stop,
                              analyze_drag_pcap, take_screenshot)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "captures" / "drag_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# We test the first 20 effects on page 0. Their byte values at
# 0x10001100 are derived from previous drag captures.
EFFECTS_UNDER_TEST = [
    ("COMP",       0x08),
    ("X-COMP",     0x09),
    ("BOOST",      0x24),
    ("OD",         0x25),
    ("X-OD",       0x2B),
    ("DIST",       0x27),
    ("X-DIST",     0x2D),
    ("METAL",      0x2E),
    ("FUZZ",       0x29),
    ("AMP",        0x02),
    ("PEQ",        0x14),
    ("GEQ",        0x15),
    ("CHO",        0x04),
    ("CHO_PRIME",  0x06),
    ("FL",         0x16),
    ("FL_PRIME",   0x18),
    ("PH",         0x37),
    ("PH_SCRIPT",  0x3B),
    ("PH_PRIME",   0x39),
    ("CLASS_VIBE", 0x07),
]
MID_Y = 240


# ---------------------------------------------------------------- Win32 mouse
user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send_input(flags, dx_screen=0, dy_screen=0):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi = MOUSEINPUT(dx_screen, dy_screen, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _abs_screen(x_px, y_px):
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    return int(x_px * 65535 / (sw - 1)), int(y_px * 65535 / (sh - 1))


def w_move(x, y):
    ax, ay = _abs_screen(x, y)
    _send_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)


def w_down(): _send_input(MOUSEEVENTF_LEFTDOWN)


def w_up(): _send_input(MOUSEEVENTF_LEFTUP)


# ---------------------------------------------------------------- strategies
def strat_pyautogui_long_hold(src, mid1, mid2, dst):
    pyautogui.moveTo(src[0], src[1], duration=0.2)
    time.sleep(0.3)
    pyautogui.mouseDown()
    time.sleep(1.5)
    pyautogui.moveTo(mid1[0], mid1[1], duration=0.5)
    pyautogui.moveTo(mid2[0], mid2[1], duration=0.5)
    pyautogui.moveTo(dst[0], dst[1], duration=0.3)
    time.sleep(0.4)
    pyautogui.mouseUp()


def strat_pyautogui_double_click(src, mid1, mid2, dst):
    pyautogui.moveTo(src[0], src[1], duration=0.2)
    time.sleep(0.2)
    pyautogui.click(src[0], src[1])
    time.sleep(0.10)
    pyautogui.mouseDown()
    time.sleep(0.15)
    pyautogui.moveTo(mid1[0], mid1[1], duration=0.4)
    pyautogui.moveTo(mid2[0], mid2[1], duration=0.4)
    pyautogui.moveTo(dst[0], dst[1], duration=0.3)
    time.sleep(0.4)
    pyautogui.mouseUp()


def strat_pyautogui_dragto(src, mid1, mid2, dst):
    pyautogui.moveTo(src[0], src[1], duration=0.2)
    time.sleep(0.3)
    pyautogui.dragTo(dst[0], dst[1], duration=1.0, button="left")


def strat_win32_long_hold(src, mid1, mid2, dst):
    w_move(*src); time.sleep(0.3); w_down(); time.sleep(1.5)
    for x, y in (mid1, mid2, dst):
        w_move(x, y); time.sleep(0.3)
    time.sleep(0.4); w_up()


def strat_win32_double_click(src, mid1, mid2, dst):
    w_move(*src); time.sleep(0.2)
    w_down(); time.sleep(0.05); w_up(); time.sleep(0.10)
    w_down(); time.sleep(0.15)
    for x, y in (mid1, mid2, dst):
        w_move(x, y); time.sleep(0.3)
    time.sleep(0.3); w_up()


def strat_win32_step_move(src, mid1, mid2, dst):
    """Win32 with many small move steps along the path."""
    w_move(*src); time.sleep(0.3)
    w_down(); time.sleep(0.5)

    def step(p_from, p_to, n=20, gap=0.025):
        for i in range(1, n + 1):
            x = p_from[0] + (p_to[0] - p_from[0]) * i // n
            y = p_from[1] + (p_to[1] - p_from[1]) * i // n
            w_move(x, y); time.sleep(gap)

    step(src, mid1)
    step(mid1, mid2)
    step(mid2, dst)
    time.sleep(0.3); w_up()


STRATEGIES = [
    ("pyautogui_long_hold",    strat_pyautogui_long_hold),
    ("pyautogui_double_click", strat_pyautogui_double_click),
    ("pyautogui_dragto",       strat_pyautogui_dragto),
    ("win32_long_hold",        strat_win32_long_hold),
    ("win32_double_click",     strat_win32_double_click),
    ("win32_step_move",        strat_win32_step_move),
]


def run_drag(strategy_fn, hex_x_local: int, slot_x_local: int = SLOT0_X,
              slot_y_local: int = SLOT0_Y):
    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.2)
    src = focus_ts.screen_xy(hwnd, hex_x_local, HEX_Y)
    mid1 = focus_ts.screen_xy(hwnd, hex_x_local, MID_Y)
    mid2 = focus_ts.screen_xy(hwnd, slot_x_local, MID_Y)
    dst = focus_ts.screen_xy(hwnd, slot_x_local, slot_y_local)
    strategy_fn(src, mid1, mid2, dst)


def run_strategy(name: str, strategy_fn) -> dict:
    """Execute the strategy on 20 effects; return per-effect success dict."""
    print(f"\n=== STRATEGY: {name} ===", flush=True)
    strategy_dir = OUT_DIR / name
    strategy_dir.mkdir(parents=True, exist_ok=True)
    restore_baseline()
    time.sleep(0.5)

    results = {}
    for idx, (eff_name, expected_byte) in enumerate(EFFECTS_UNDER_TEST):
        hex_x = hex_x_pos(idx)
        pcap = strategy_dir / f"{idx:02d}_{eff_name}.pcap"
        png = strategy_dir / f"{idx:02d}_{eff_name}.png"
        cap = usbpcap_start(pcap)
        time.sleep(1.0)
        try:
            run_drag(strategy_fn, hex_x)
            time.sleep(1.2)
        finally:
            usbpcap_stop(cap)
        take_screenshot(png)
        # Verify the captured DT1 has the expected effect-type byte
        info = analyze_drag_pcap(pcap)
        triplet = info.get("triplet_at_10001100")
        ok = (triplet is not None
              and triplet[:2].upper() == f"{expected_byte:02X}")
        marker = "OK  " if ok else "FAIL"
        print(f"  [{marker}] {idx:2d} {eff_name:12s} expected={expected_byte:02X} "
              f"got={triplet}", flush=True)
        results[eff_name] = {"ok": ok, "triplet": triplet,
                              "expected": f"{expected_byte:02X}"}
    return results


def main():
    summary = {}
    for name, fn in STRATEGIES:
        try:
            res = run_strategy(name, fn)
            ok = sum(1 for r in res.values() if r["ok"])
            summary[name] = {"ok": ok, "total": len(res), "details": res}
        except Exception as e:
            print(f"  ERROR in {name}: {e}")
            import traceback; traceback.print_exc()
            summary[name] = {"error": str(e)}

    print("\n=== SUMMARY ===")
    for name, s in summary.items():
        if "error" in s:
            print(f"  {name:<30}: ERROR  {s['error']}")
        else:
            ok, tot = s["ok"], s["total"]
            print(f"  {name:<30}: {ok}/{tot}  ({100*ok//tot}%)")

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
