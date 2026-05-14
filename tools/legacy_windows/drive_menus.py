"""
Click each Tone Studio top-level menu item and pause between, so the
external USBPcap capture has clear time-boundaries between actions.

The label fifo records each click; when the JSONL converter joins the
USBPcap output to the labels via timestamps, we can attribute each
SysEx transfer to the menu it belonged to.
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

TARGET_NAME = "BOSS TONE STUDIO for GX-10"


def write_label(fifo: Path, msg: str):
    with fifo.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label-fifo", required=True)
    args = ap.parse_args()

    fifo = Path(args.label_fifo)
    fifo.parent.mkdir(parents=True, exist_ok=True)
    fifo.write_text("")

    win = auto.WindowControl(searchDepth=1, Name=TARGET_NAME)
    if not win.Exists(maxSearchSeconds=10):
        print(f"window {TARGET_NAME!r} not found", file=sys.stderr)
        sys.exit(2)
    r = win.BoundingRectangle
    origin = (r.left, r.top)
    print(f"window at {r.left},{r.top}", file=sys.stderr)

    def screen(x, y):
        return origin[0] + x, origin[1] + y

    def click(x, y):
        pyautogui.click(*screen(x, y))

    # Top toolbar items observed in screenshot ui_002.png
    menus = [
        ("EDITOR", 240, 60),
        ("LIBRARIAN", 320, 60),
        ("TONE_EXCHANGE", 399, 60),
        ("TUNER", 482, 60),
        ("IR_LOADER", 542, 60),
        ("MENU", 605, 60),
    ]

    write_label(fifo, "=== menu sweep start ===")
    time.sleep(1.0)

    for name, x, y in menus:
        write_label(fifo, f"click toolbar {name} ({x},{y})")
        click(x, y)
        time.sleep(2.5)
        write_label(fifo, f"settle after {name}")
        time.sleep(0.8)

    # Some menus may have opened modal dialogs / overlays — escape them
    write_label(fifo, "ESC to close any open modal")
    pyautogui.press("escape")
    time.sleep(0.5)
    pyautogui.press("escape")
    time.sleep(0.5)

    # Return to EDITOR view as a clean baseline
    write_label(fifo, "click EDITOR (return)")
    click(240, 60)
    time.sleep(1.5)
    write_label(fifo, "DONE")


if __name__ == "__main__":
    main()
