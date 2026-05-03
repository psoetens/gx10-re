"""Capture USB MIDI traffic when each Tone Studio menu/dialog is opened.

When TS opens a settings dialog (IN/OUT, CTL/EXP, WRITE, MENU), it
issues RQ1 reads to populate the dialog with current device values.
The device replies with DT1s holding the configured settings. By
capturing both, we identify the SysEx addresses backing each
dialog's controls.

Strategy:
  1. restore_baseline (clean state).
  2. Start one big USBPcap capture.
  3. For each dialog: click the toolbar button, hold 1.5s, ESC to close.
  4. Stop capture, dump JSONL, summarize per-dialog read region.

Click coordinates (window-local, derived from screenshots):
  TUNER toolbar:     (482, 60)
  MENU toolbar:      (605, 60)
  CTL/EXP:           (1145, 110)
  IN/OUT SETTINGS:   (1270, 110)
  WRITE:             (1405, 110)
"""
import json
import subprocess
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
OUT = ROOT / "captures" / "menus_v2"
OUT.mkdir(parents=True, exist_ok=True)

DIALOGS = [
    ("CTL_EXP", 1145, 110),
    ("IN_OUT", 1270, 110),
    ("WRITE", 1405, 110),
    ("MENU", 605, 60),
    ("TUNER", 482, 60),
]


def open_close_dialog(name, x, y, settle=2.0):
    """Click the dialog button, screenshot, then click CLOSE button."""
    print(f"[{name}] click ({x},{y})")
    click(x, y)
    time.sleep(settle)
    take_screenshot(OUT / f"{name}_open.png")
    # CLOSE button at bottom-right of each dialog: ~(1366, 951)
    print(f"[{name}] click CLOSE")
    click(1366, 951)
    time.sleep(0.8)
    # Belt-and-braces: ESC and a click in the empty canvas
    pyautogui.press("escape")
    time.sleep(0.4)
    click(1750, 450)
    time.sleep(0.6)


def main():
    restore_baseline()
    time.sleep(0.5)

    pcap = OUT / "menus_capture.pcap"
    if pcap.exists():
        pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists():
        jsonl.unlink()

    cap = usbpcap_start(pcap)
    time.sleep(1.5)
    try:
        markers = []
        for name, x, y in DIALOGS:
            t0 = time.time()
            open_close_dialog(name, x, y)
            markers.append((name, t0))
        # Final settle
        time.sleep(0.6)
    finally:
        usbpcap_stop(cap)
        # The usbpcap_stop helper auto-converts to JSONL via pcap_to_jsonl
    print("\nMarkers (relative seconds from cap start):")
    for name, t in markers:
        print(f"  {name}: {t:.2f}")
    print(f"\npcap: {pcap}")
    print(f"jsonl: {jsonl}")


if __name__ == "__main__":
    main()
