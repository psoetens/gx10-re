"""Capture the actual WRITE-to-user-slot bulk transaction.

The WRITE dialog has:
  WRITE title (top)
  MEMORY: dropdown selecting target slot U01-1 .. U16-3
  MEMORY NAME: text input with current name
  CANCEL button (bottom-left ~879, 692)
  WRITE button (bottom-right ~1038, 692)

We don't change the slot — just leave the dialog's default (U03-1)
and click WRITE. Capture the bulk DT1 stream that follows.
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


def cap_path(name):
    p = OUT / f"{name}.pcap"
    if p.exists():
        p.unlink()
    j = p.with_suffix(".jsonl")
    if j.exists():
        j.unlink()
    return p


def main():
    try:
        restore_baseline()
        time.sleep(0.5)
    except Exception as e:
        print(f"restore_baseline failed: {e}")

    p = cap_path("write_save_v2")
    proc = usbpcap_start(p)
    time.sleep(1.5)
    try:
        # Step 1: click WRITE button on top-right
        click(1405, 110)
        time.sleep(0.8)
        take_screenshot(OUT / "write_v2_step1_dropdown.png")
        # Step 2: click WRITE entry in the dropdown (~1397, 156)
        click(1397, 156)
        time.sleep(2.0)
        take_screenshot(OUT / "write_v2_step2_dialog.png")
        # Step 3: click WRITE button in the dialog (~1038, 692)
        click(1038, 692)
        time.sleep(3.0)
        take_screenshot(OUT / "write_v2_step3_done.png")
        # Wait for bulk transfer to settle
        time.sleep(2.0)
    finally:
        usbpcap_stop(proc)
    print(f"done: {p}")


if __name__ == "__main__":
    main()
