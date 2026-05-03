"""Capture MENU sidebar tabs with corrected dropdown coords.

From the captured PLAY OPTION screenshot, dropdown chevrons sit at
x ≈ 1119, NOT at x=950 as previously assumed.
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

    pcap = cap("menu_tabs_v3")
    proc = usbpcap_start(pcap)
    time.sleep(1.5)
    try:
        # Open MENU
        click(605, 60); time.sleep(2.0)
        # HARDWARE SETTINGS: AUTO OFF dropdown at (890, 385) — already captured
        # PLAY OPTION tab at sidebar y=280
        click(459, 280); time.sleep(1.0)

        # PLAY OPTION dropdowns at x≈1119:
        # BANK MODE @ y=343
        click(1119, 343); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)
        # BANK EXTENT MIN @ y=391
        click(1119, 391); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)
        # LOOP MODE - click STEREO toggle
        click(1180, 555); time.sleep(0.5)
        # REC ACTION dropdown
        click(1119, 603); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)
        # DELETE WARNING toggle ON
        click(953, 745); time.sleep(0.5)
        # OVERWRITE WARNING toggle ON
        click(1391, 745); time.sleep(0.5)
        take_screenshot(OUT / "menu_v3_play_after.png")

        # MIDI SETTINGS tab at y=320
        click(459, 320); time.sleep(1.0)
        take_screenshot(OUT / "menu_v3_midi_open.png")
        # Try clicking the first dropdown at conventional position (1119, 343)
        click(1119, 343); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)

        # USB SETTINGS at y=400
        click(459, 400); time.sleep(1.0)
        take_screenshot(OUT / "menu_v3_usb_open.png")
        click(1119, 343); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)

        # DEVICE SETTINGS at y=480
        click(459, 480); time.sleep(1.0)
        take_screenshot(OUT / "menu_v3_device_open.png")
        click(1119, 343); time.sleep(0.5)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)

        # Close
        click(1485, 970); time.sleep(0.8)
    finally:
        usbpcap_stop(proc)
    print(f"done: {pcap}")


if __name__ == "__main__":
    main()
