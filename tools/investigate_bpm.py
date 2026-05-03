"""Investigate the byte encoding of the BPM knob.

Per user: BPM range is 40-250, all BPM-style knobs use the same mapping.

Strategy:
  1. Load CHO into slot 0 (its rightmost knob is BPM with display 40-250).
  2. Click BPM knob to focus.
  3. Saturate UP (200 ups) → device clamps at BPM 250.
  4. Take a screenshot, confirm display shows 250.
  5. Press DOWN 1 time → BPM = 249. Capture DT1.
  6. Press DOWN 200 → BPM saturates at 40. Take screenshot.
  7. Press UP 1 → BPM = 41. Capture DT1.

The captured DT1 payloads at 250→249 transition and 40→41 transition
let us reverse the encoding (which bytes change, by how much).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image, ImageGrab
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from map_all_effects import (usbpcap_start, usbpcap_stop, take_screenshot,
                              restore_baseline)
from explore_all_effects import click_focus_knob, ensure_loaded

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "captures" / "bpm_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TYPEBAR = ROOT / "captures" / "typebar_full"


def main():
    """Loads CHO into slot 0 first, then drives BPM knob through full
    range capturing every up/down press as a separate DT1 event so we
    can decode the byte-to-display-value mapping (BPM range 40-250)."""
    BPM_X, BPM_Y = 1269, 590

    # Load CHO fresh
    restore_baseline()
    cho_dir = TYPEBAR / "page0" / "12_CHO"
    ensure_loaded(0, 12, "CHO", "", cho_dir, max_retries=3)
    time.sleep(0.5)

    out_pcap = OUT_DIR / "bpm_sweep.pcap"
    cap = usbpcap_start(out_pcap)
    time.sleep(1.0)
    try:
        # Saturate UP (drives BPM to 250)
        click_focus_knob(BPM_X, BPM_Y)
        for _ in range(250):
            pyautogui.press("up"); time.sleep(0.020)
        time.sleep(0.5)
        take_screenshot(OUT_DIR / "after_up.png")

        # Now DOWN to min (40), capture every transition
        for _ in range(220):
            pyautogui.press("down"); time.sleep(0.025)
        time.sleep(0.5)
        take_screenshot(OUT_DIR / "after_down.png")

        # Saturate DOWN one more time to confirm clamping at 40
        for _ in range(50):
            pyautogui.press("down"); time.sleep(0.020)
        time.sleep(0.4)
    finally:
        usbpcap_stop(cap)

    # Analyze
    jsonl = out_pcap.with_suffix(".jsonl")
    subprocess.run(["python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
                    str(out_pcap), "--out", str(jsonl)], capture_output=True)

    bpm_addr_events = []
    with jsonl.open() as f:
        for line in f:
            try: ev = json.loads(line)
            except: continue
            if ev.get("kind") != "sysex" or ev.get("dir") != "host->dev": continue
            raw = bytes.fromhex(ev["hex"])
            if len(raw) < 16 or raw[8] != 0x12: continue
            addr = int.from_bytes(raw[9:13], "big")
            if addr != 0x10000F02: continue
            payload = raw[13:-2]
            bpm_addr_events.append(payload.hex().upper())

    print(f"BPM events captured: {len(bpm_addr_events)}")
    print("First 20 (after UP saturate, going DOWN):")
    for p in bpm_addr_events[:20]:
        b = bytes.fromhex(p)
        print(f"  payload={p}  bytes={[hex(x) for x in b]}")
    print("Last 20 (near min):")
    for p in bpm_addr_events[-20:]:
        b = bytes.fromhex(p)
        print(f"  payload={p}  bytes={[hex(x) for x in b]}")


if __name__ == "__main__":
    main()
