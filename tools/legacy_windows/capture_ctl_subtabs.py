"""Capture the CTL/EXP dialog's sub-tab interactions:
ASSIGN SETTINGS, KNOB SETTINGS, MEMORY MIDI.

Top tabs in the CTL/EXP dialog: 4 buttons across the top row at y=212:
  CONTROL FUNCTION (active by default)  — x≈381
  ASSIGN SETTINGS                        — x≈585
  KNOB SETTINGS                          — x≈787
  MEMORY MIDI                            — x≈989
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


def cap(name):
    p = OUT / f"{name}.pcap"
    if p.exists(): p.unlink()
    j = p.with_suffix(".jsonl")
    if j.exists(): j.unlink()
    return p


def main():
    try:
        restore_baseline(); time.sleep(0.5)
    except Exception as e: print(f"restore: {e}")

    pcap = cap("ctl_subtabs")
    proc = usbpcap_start(pcap)
    time.sleep(1.5)
    try:
        # Open CTL/EXP
        click(1145, 110); time.sleep(2.0)

        # ASSIGN SETTINGS tab
        click(585, 212); time.sleep(1.0)
        take_screenshot(OUT / "ctl_assign_settings.png")
        # Toggle SW (likely an OFF/ON at top)
        click(1119, 343); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)

        # KNOB SETTINGS tab
        click(787, 212); time.sleep(1.0)
        take_screenshot(OUT / "ctl_knob_settings.png")
        click(1119, 343); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)

        # MEMORY MIDI tab
        click(989, 212); time.sleep(1.0)
        take_screenshot(OUT / "ctl_memory_midi.png")
        click(1119, 343); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)

        # Close
        click(1559, 992); time.sleep(0.8)
    finally:
        usbpcap_stop(proc)
    print(f"done: {pcap}")


if __name__ == "__main__":
    main()
