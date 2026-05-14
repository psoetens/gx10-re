"""
Click ONE Tone Studio menu, wait, then ESC. For per-menu USBPcap captures.

Usage:
    python drive_one_menu.py --menu LIBRARIAN
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import uiautomation as auto
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

TARGET = "BOSS TONE STUDIO for GX-10"

MENUS = {
    "EDITOR":        (240, 60),
    "LIBRARIAN":     (320, 60),
    "TONE_EXCHANGE": (399, 60),
    "TUNER":         (482, 60),
    "IR_LOADER":     (542, 60),
    "MENU":          (605, 60),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", required=True, choices=list(MENUS))
    ap.add_argument("--dwell", type=float, default=4.0)
    ap.add_argument("--escape", action="store_true",
                    help="press Esc twice after dwell to close any modal")
    args = ap.parse_args()

    win = auto.WindowControl(searchDepth=1, Name=TARGET)
    if not win.Exists(maxSearchSeconds=5):
        print("window not found", file=sys.stderr); sys.exit(2)
    r = win.BoundingRectangle
    x, y = MENUS[args.menu]
    sx, sy = r.left + x, r.top + y
    print(f"clicking {args.menu} at screen ({sx},{sy})", file=sys.stderr)
    pyautogui.click(sx, sy)
    time.sleep(args.dwell)
    if args.escape:
        pyautogui.press("escape")
        time.sleep(0.5)
        pyautogui.press("escape")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
