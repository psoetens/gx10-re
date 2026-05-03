"""Capture INITIALIZE and MENU sidebar tab interactions.

INITIALIZE: the WRITE → INITIALIZE button likely opens a confirmation
dialog. We click and press Enter to confirm.

MENU tabs: open MENU, click each sidebar tab, then click the topmost
control on each panel and toggle it via Down+Enter.
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


def flow_initialize_v2():
    p = cap_path("initialize_v2")
    proc = usbpcap_start(p)
    time.sleep(1.5)
    try:
        # Click WRITE dropdown
        click(1405, 110)
        time.sleep(0.8)
        # Click INITIALIZE entry (~1413, 215)
        click(1413, 215)
        time.sleep(1.5)
        take_screenshot(OUT / "initialize_v2_dialog.png")
        # If confirmation dialog appeared with a clickable INITIALIZE button:
        # Try clicking center of an OK/Initialize button — common positions
        # Press Enter to confirm
        pyautogui.press("enter")
        time.sleep(2.0)
        take_screenshot(OUT / "initialize_v2_after.png")
        time.sleep(1.0)
    finally:
        usbpcap_stop(proc)


def flow_menu_tabs_v2():
    p = cap_path("menu_tabs_v2")
    proc = usbpcap_start(p)
    time.sleep(1.5)
    try:
        # Open MENU
        click(605, 60)
        time.sleep(2.0)

        # HARDWARE SETTINGS — toggle EXP1 HOLD (already at OFF state perhaps)
        click(950, 547)
        time.sleep(0.5)

        # Click PLAY OPTION sidebar at (459, 280)
        click(459, 280)
        time.sleep(1.0)
        take_screenshot(OUT / "menu_v2_play_option.png")
        # Click first dropdown — likely top of right pane (890, 385) or similar
        # Actually the first PLAY OPTION setting is "PATCH CHANGE": MOMENT/SMOOTH dropdown
        click(950, 385)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # MIDI SETTINGS
        click(459, 320)
        time.sleep(1.0)
        take_screenshot(OUT / "menu_v2_midi.png")
        click(950, 385)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # MIDI PROGRAM MAP
        click(459, 360)
        time.sleep(1.0)
        take_screenshot(OUT / "menu_v2_midi_map.png")
        click(950, 385)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # USB SETTINGS
        click(459, 400)
        time.sleep(1.0)
        take_screenshot(OUT / "menu_v2_usb.png")
        click(950, 385)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # DEVICE SETTINGS
        click(459, 480)
        time.sleep(1.0)
        take_screenshot(OUT / "menu_v2_device.png")
        click(950, 385)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # Close
        click(1485, 970)
        time.sleep(0.8)
    finally:
        usbpcap_stop(proc)


def main():
    print("=== initialize ===")
    try:
        restore_baseline(); time.sleep(0.5)
    except Exception as e: print(f"  restore: {e}")
    flow_initialize_v2()
    time.sleep(1.0)

    print("\n=== menu_tabs_v2 ===")
    try:
        restore_baseline(); time.sleep(0.5)
    except Exception as e: print(f"  restore: {e}")
    flow_menu_tabs_v2()
    print("\nDone.")


if __name__ == "__main__":
    main()
