"""Capture MIDI SETTINGS, USB SETTINGS, DEVICE SETTINGS with correct
per-tab dropdown coordinates derived from each tab's actual layout."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from map_all_effects import (usbpcap_start, usbpcap_stop, take_screenshot,
                              restore_baseline)
from explore_all_effects import click, click_focus_knob

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

    pcap = cap("menu_midi_usb_device")
    proc = usbpcap_start(pcap)
    time.sleep(1.5)
    try:
        # Open MENU
        click(605, 60); time.sleep(2.0)

        # MIDI SETTINGS tab at sidebar y=320
        click(459, 320); time.sleep(1.0)
        # 5 dropdowns at x=1124: y=401, 449, 494, 539
        for y in [401, 449, 494, 539]:
            click(1124, y); time.sleep(0.5)
            pyautogui.press("down"); time.sleep(0.2)
            pyautogui.press("enter"); time.sleep(0.4)
        # CLOCK OUT toggle ON
        click(1185, 584); time.sleep(0.5)
        take_screenshot(OUT / "midi_settings_after.png")

        # USB SETTINGS tab at y=400
        click(459, 400); time.sleep(1.0)
        # 4 knobs at y=520: x=867, 1006, 1145, 1284
        for x in [867, 1006, 1145, 1284]:
            click_focus_knob(x, 520); time.sleep(0.3)
            pyautogui.press("up"); time.sleep(0.05)
            pyautogui.press("up"); time.sleep(0.4)
        # DIRECT MONITOR toggle: click ON
        click(1135, 662); time.sleep(0.5)
        # LOOP BACK toggle: click ON
        click(1135, 744); time.sleep(0.5)
        take_screenshot(OUT / "usb_settings_after.png")

        # DEVICE SETTINGS tab at y=480
        click(459, 480); time.sleep(1.0)
        take_screenshot(OUT / "device_settings_open.png")
        # Try clicking common dropdown coords
        for y in [343, 391, 438, 485, 532]:
            click(1119, y); time.sleep(0.4)
            pyautogui.press("down"); time.sleep(0.2)
            pyautogui.press("enter"); time.sleep(0.4)
        take_screenshot(OUT / "device_settings_after.png")

        # Close
        click(1485, 970); time.sleep(0.8)
    finally:
        usbpcap_stop(proc)
    print(f"done: {pcap}")


if __name__ == "__main__":
    main()
