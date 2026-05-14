"""Open a single TS dialog (passed as arg), screenshot it, capture USBPcap.

This script intentionally keeps each capture in isolation: restore_baseline
runs first to ensure no previous dialog is open, then opens just one
dialog, screenshots, and exits. The dialog stays open at exit (no need
to close it) since the next run will restart TS anyway.

Usage:  python capture_one_menu.py <NAME>
where NAME is one of: CTL_EXP, IN_OUT, WRITE, MENU, TUNER
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from map_all_effects import (usbpcap_start, usbpcap_stop, take_screenshot,
                              restore_baseline)
from explore_all_effects import click

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "menus_v3"
OUT.mkdir(parents=True, exist_ok=True)

DIALOGS = {
    "CTL_EXP": (1145, 110),
    "IN_OUT":  (1270, 110),
    "WRITE":   (1405, 110),
    "MENU":    (605, 60),
    "TUNER":   (482, 60),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in DIALOGS:
        print(f"usage: {sys.argv[0]} <NAME>  where NAME in {list(DIALOGS)}")
        sys.exit(2)
    name = sys.argv[1]
    x, y = DIALOGS[name]

    restore_baseline()
    time.sleep(0.5)

    pcap = OUT / f"{name}.pcap"
    if pcap.exists():
        pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists():
        jsonl.unlink()

    cap = usbpcap_start(pcap)
    time.sleep(1.5)
    try:
        # Note start time for the open click
        print(f"[{name}] opening dialog at ({x}, {y})")
        click(x, y)
        time.sleep(2.0)
        take_screenshot(OUT / f"{name}_open.png")
        # Capture for an additional 1s to catch any deferred RQ1/DT1
        time.sleep(1.0)
    finally:
        usbpcap_stop(cap)
    print(f"[{name}] done — pcap: {pcap}")


if __name__ == "__main__":
    main()
