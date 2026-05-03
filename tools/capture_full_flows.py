"""Capture the remaining MIDI flows that complete the GX-10 API surface.

Each capture is a separate USBPcap session so addresses can be
attributed to a specific user action.

Flows:
  1. PRESET LOAD: click a different patch in the left rail, capture
     bulk DT1 stream from device.
  2. WRITE: open WRITE menu → click WRITE → in dialog, click WRITE
     button → capture host's bulk DT1 to user-patch slot.
  3. INITIALIZE: open WRITE menu → click INITIALIZE → confirm.
  4. TUNER MODES: click each of MONO / POLY / TT MODE in tuner dialog.
  5. CTL/EXP FUNCTION CYCLE: in CTL/EXP dialog, cycle CTL1 FUNCTION
     dropdown through all 17 values. Captures the byte→enum mapping.
  6. MENU SIDEBAR TABS: PLAY OPTION, MIDI SETTINGS, USB SETTINGS,
     DEVICE SETTINGS — toggle one setting in each.
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
from explore_all_effects import click, click_focus_knob

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


def flow_preset_load():
    """Click a different preset in the left rail. Capture bulk DT1
    stream from device (TS issues RQ1 to read the new patch)."""
    p = cap_path("preset_load")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        # Left rail patch slots are at x~80, y starting ~140 with stride ~50
        # P02-1 is currently selected. Click P03-1 (NEO SOUL) at y~445
        click(80, 445)
        time.sleep(2.0)
        take_screenshot(OUT / "preset_load_after.png")
        # Wait for bulk DT1 stream
        time.sleep(2.5)
    finally:
        usbpcap_stop(proc)


def flow_write_save():
    """Click WRITE button → click WRITE in the dropdown → in the
    write dialog, pick slot 1 and click WRITE."""
    p = cap_path("write_save")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        # Open WRITE menu
        click(1405, 110)
        time.sleep(0.8)
        # Click WRITE entry in dropdown (1397, 156)
        click(1397, 156)
        time.sleep(2.0)
        take_screenshot(OUT / "write_dialog.png")
        # In the WRITE dialog, click the WRITE confirm button (TBD coords)
        # The dialog has slot grid + name field + WRITE button at bottom-right
        click(1500, 985)  # likely WRITE confirm
        time.sleep(2.0)
        take_screenshot(OUT / "write_after.png")
        time.sleep(1.0)
    finally:
        usbpcap_stop(proc)


def flow_initialize():
    """Click WRITE → INITIALIZE."""
    p = cap_path("initialize")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        click(1405, 110)
        time.sleep(0.8)
        # INITIALIZE entry in dropdown at (1397, 215)
        click(1413, 215)
        time.sleep(1.0)
        take_screenshot(OUT / "initialize_confirm.png")
        # Confirm dialog if any (press Enter)
        pyautogui.press("enter")
        time.sleep(1.5)
        take_screenshot(OUT / "initialize_after.png")
    finally:
        usbpcap_stop(proc)


def flow_tuner_modes():
    """Open tuner, click each of MONO/POLY/TT MODE."""
    p = cap_path("tuner_modes")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        click(482, 60)
        time.sleep(2.0)
        # MONO at (852, 290), POLY at (959, 290), TT MODE at (1066, 290)
        click(852, 290); time.sleep(0.8)
        take_screenshot(OUT / "tuner_mono.png")
        click(959, 290); time.sleep(0.8)
        take_screenshot(OUT / "tuner_poly.png")
        click(1066, 290); time.sleep(0.8)
        take_screenshot(OUT / "tuner_tt.png")
        # Close
        click(1259, 928); time.sleep(0.8)
    finally:
        usbpcap_stop(proc)


def flow_ctl_exp_cycle():
    """In CTL/EXP, click CTL1 FUNCTION dropdown and step through 17 values."""
    p = cap_path("ctl_exp_function_cycle")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        click(1145, 110)
        time.sleep(2.0)
        # Click CTL1 FUNCTION dropdown at (730, 528)
        click(730, 528)
        time.sleep(0.4)
        # Press Home then Enter to set to first value (OFF)
        pyautogui.press("home"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.4)
        # Now cycle: click → Down → Enter, 20 times
        for i in range(20):
            click(730, 528); time.sleep(0.4)
            pyautogui.press("down"); time.sleep(0.15)
            pyautogui.press("enter"); time.sleep(0.4)
        take_screenshot(OUT / "ctl_exp_after_cycle.png")
        # Close
        click(1559, 992); time.sleep(0.8)
    finally:
        usbpcap_stop(proc)


def flow_menu_tabs():
    """Open MENU and toggle one setting in each sidebar tab."""
    p = cap_path("menu_tabs")
    proc = usbpcap_start(p)
    time.sleep(1.2)
    try:
        click(605, 60)
        time.sleep(2.0)

        # HARDWARE SETTINGS already covered. Click PLAY OPTION at (459, 280)
        click(459, 280)
        time.sleep(1.0)
        take_screenshot(OUT / "menu_play_option_open.png")
        # Try clicking the first toggle in PLAY OPTION (probably top-left of right pane)
        click(890, 385); time.sleep(0.4)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # MIDI SETTINGS at (459, 320)
        click(459, 320); time.sleep(1.0)
        take_screenshot(OUT / "menu_midi_open.png")
        click(890, 385); time.sleep(0.4)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # USB SETTINGS at (459, 400)
        click(459, 400); time.sleep(1.0)
        take_screenshot(OUT / "menu_usb_open.png")
        click(890, 385); time.sleep(0.4)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # DEVICE SETTINGS at (459, 480)
        click(459, 480); time.sleep(1.0)
        take_screenshot(OUT / "menu_device_open.png")
        click(890, 385); time.sleep(0.4)
        pyautogui.press("down"); time.sleep(0.2)
        pyautogui.press("enter"); time.sleep(0.5)

        # Close
        click(1485, 970); time.sleep(0.8)
    finally:
        usbpcap_stop(proc)


def main():
    flows = [
        ("write_save", flow_write_save),
        ("initialize", flow_initialize),
        ("tuner_modes", flow_tuner_modes),
        ("ctl_exp_cycle", flow_ctl_exp_cycle),
        ("menu_tabs", flow_menu_tabs),
        # preset_load already captured; skip to leave time for the rest
    ]
    for name, fn in flows:
        print(f"\n=== {name} ===")
        try:
            restore_baseline()
            time.sleep(0.5)
        except Exception as e:
            print(f"  restore_baseline failed: {e} — continuing anyway")
        try:
            fn()
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()
        time.sleep(1.0)
    print("\nAll flows captured. See", OUT)


if __name__ == "__main__":
    main()
