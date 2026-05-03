"""Open each menu dialog and TOGGLE values inside it, capturing the
DT1 traffic that TS sends to the device. This is what reveals each
setting's SysEx address.

For each dialog, we click each visible control and press an arrow key
once. The first DT1 emitted under that focused control is the address
backing that setting.

Note: dialog clicks use Win32-long-hold via `click()`. Knob focus uses
`click_focus_knob()` which is the same primitive but with longer settle.

Coordinates were derived from the screenshots in captures/menus_v3.
"""
import json
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
OUT = ROOT / "captures" / "menus_v4"
OUT.mkdir(parents=True, exist_ok=True)


def cap(name):
    """Yield-style context for a single capture file."""
    p = OUT / f"{name}.pcap"
    if p.exists():
        p.unlink()
    j = p.with_suffix(".jsonl")
    if j.exists():
        j.unlink()
    return p


# -------- IN/OUT SETTINGS --------
def capture_in_out():
    """Open IN/OUT, change INPUT, INPUT SENS, OUTPUT SELECT, GLOBAL EQ
    toggles + first knob in each row. Capture DT1s."""
    p = cap("IN_OUT_changes")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        # Open IN/OUT
        click(1270, 110)
        time.sleep(2.0)
        take_screenshot(OUT / "in_out_opened.png")

        # --- INPUT dropdown (GUITAR → BASS) ---
        # Click dropdown chevron at ~x=880, y=365
        click(880, 365)
        time.sleep(0.6)
        pyautogui.press("down")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(0.5)
        take_screenshot(OUT / "in_out_input_BASS.png")

        # Toggle back to GUITAR
        click(880, 365)
        time.sleep(0.6)
        pyautogui.press("up")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(0.5)

        # --- INPUT SENS knob at (1185, 360) ---
        click_focus_knob(1185, 360)
        time.sleep(0.3)
        for _ in range(3):
            pyautogui.press("up")
            time.sleep(0.05)
        time.sleep(0.4)

        # --- OUTPUT SELECT dropdown (next non-default) ---
        click(880, 525)
        time.sleep(0.6)
        pyautogui.press("down")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(0.5)
        take_screenshot(OUT / "in_out_output_changed.png")

        # Reset
        click(880, 525)
        time.sleep(0.6)
        pyautogui.press("up")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(0.5)

        # --- GLOBAL EQ ON button (toggle) ---
        click(1365, 610)
        time.sleep(0.6)

        # --- LOW GAIN knob (1st EQ knob) at (550, 700) ---
        click_focus_knob(550, 700)
        time.sleep(0.3)
        for _ in range(3):
            pyautogui.press("up")
            time.sleep(0.05)
        time.sleep(0.4)

        # --- LOW-MID FREQ knob (2nd) at (671, 700) ---
        click_focus_knob(671, 700)
        time.sleep(0.3)
        for _ in range(3):
            pyautogui.press("up"); time.sleep(0.05)
        time.sleep(0.4)

        take_screenshot(OUT / "in_out_after_changes.png")

        # Close
        click(1366, 951)
        time.sleep(1.0)
    finally:
        usbpcap_stop(proc)


# -------- CTL/EXP --------
def capture_ctl_exp():
    p = cap("CTL_EXP_changes")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        click(1145, 110)
        time.sleep(2.0)
        take_screenshot(OUT / "ctl_exp_opened.png")

        # Click DOWN dropdown (FUNCTION column, first row) at (730, 300)
        click(730, 300)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # Click MEMORY <-> SYSTEM toggle for "DOWN" (PREFERENCE col)
        click(1325, 300)
        time.sleep(0.6)
        click(1207, 300); time.sleep(0.6)  # back to MEMORY

        # CTL1 dropdown
        click(730, 528)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # EXP1 SW: WAH dropdown
        click(730, 657)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        take_screenshot(OUT / "ctl_exp_after_changes.png")

        # Close (CLOSE button at 1559, 992 for this dialog)
        click(1559, 992)
        time.sleep(1.0)
    finally:
        usbpcap_stop(proc)


# -------- MENU --------
def capture_menu():
    p = cap("MENU_changes")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        click(605, 60)  # MENU button
        time.sleep(2.0)
        take_screenshot(OUT / "menu_opened.png")

        # AUTO OFF dropdown (first visible setting)
        click(890, 385)
        time.sleep(0.6)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # EXP1 HOLD: ON
        click(950, 547)
        time.sleep(0.6)

        # EXP2 HOLD: ON
        click(950, 595)
        time.sleep(0.6)

        # Click PLAY OPTION tab at (459, 280)
        click(459, 280)
        time.sleep(0.8)
        take_screenshot(OUT / "menu_play_option.png")

        # Click MIDI SETTINGS tab at (459, 320)
        click(459, 320)
        time.sleep(0.8)
        take_screenshot(OUT / "menu_midi_settings.png")

        # Click USB SETTINGS tab at (459, 400)
        click(459, 400)
        time.sleep(0.8)
        take_screenshot(OUT / "menu_usb_settings.png")

        # Click DEVICE SETTINGS tab at (459, 480)
        click(459, 480)
        time.sleep(0.8)
        take_screenshot(OUT / "menu_device_settings.png")

        # Close
        click(1485, 970)
        time.sleep(1.0)
    finally:
        usbpcap_stop(proc)


def main():
    restore_baseline()
    time.sleep(0.5)

    print("=== IN/OUT ===")
    capture_in_out()
    time.sleep(1.0)

    restore_baseline()
    time.sleep(0.5)
    print("=== CTL/EXP ===")
    capture_ctl_exp()
    time.sleep(1.0)

    restore_baseline()
    time.sleep(0.5)
    print("=== MENU ===")
    capture_menu()
    print("\nAll captures done. See", OUT)


if __name__ == "__main__":
    main()
