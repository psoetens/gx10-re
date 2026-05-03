"""Capture FUNCTION dropdown changes for each controller in CTL/EXP.

Goal: confirm the per-controller addresses (one DT1 each).

Coordinates of each FUNCTION dropdown's chevron:
  ▼ (DOWN row)      — y=300
  ▲ (UP row)        — y=332
  MANUAL ▼          — y=365
  MANUAL ▲          — y=397
  CURNUM            — y=430
  (gap)
  CTL1              — y=528
  CTL2              — y=559
  CTL3              — y=591
  (gap)
  EXP1 SW           — y=657
  EXP1 PEDAL        — y=690
  EXP2              — y=722

Each is at x=730. Cycling each via Down+Enter once produces a single
DT1 at the controller's address.
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
OUT = ROOT / "captures" / "flows"
OUT.mkdir(parents=True, exist_ok=True)

CONTROLLERS = [
    ("DOWN_SW", 730, 300),
    ("UP_SW", 730, 332),
    ("MANUAL_DOWN", 730, 365),
    ("MANUAL_UP", 730, 397),
    ("CURNUM", 730, 430),
    ("CTL1", 730, 528),
    ("CTL2", 730, 559),
    ("CTL3", 730, 591),
    ("EXP1_SW", 730, 657),
    ("EXP1_PEDAL", 730, 690),
    ("EXP2", 730, 722),
]


def main():
    try:
        restore_baseline(); time.sleep(0.5)
    except Exception as e: print(f"restore: {e}")

    pcap = OUT / "ctl_exp_per_controller.pcap"
    if pcap.exists(): pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists(): jsonl.unlink()

    proc = usbpcap_start(pcap)
    time.sleep(1.5)
    try:
        # Open CTL/EXP
        click(1145, 110)
        time.sleep(2.0)
        # For each controller, click its dropdown, press Down, Enter
        for name, x, y in CONTROLLERS:
            click(x, y); time.sleep(0.4)
            pyautogui.press("down"); time.sleep(0.15)
            pyautogui.press("enter"); time.sleep(0.4)
            print(f"[{name}] cycled at ({x},{y})")
        take_screenshot(OUT / "ctl_per_controller_after.png")
        # Close
        click(1559, 992); time.sleep(1.0)
    finally:
        usbpcap_stop(proc)
    print(f"done: {pcap}")


if __name__ == "__main__":
    main()
