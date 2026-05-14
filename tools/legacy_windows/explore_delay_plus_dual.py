"""DELAY_PLUS DUAL extra-dropdowns exploration.

At TYPE=5 (DUAL), the DELAY_PLUS effect exposes three additional
dropdowns next to TYPE: MODE, L.TYPE, R.TYPE. The per-TYPE pass
already captured the 16 knobs visible at DUAL but did not enumerate
these enum dropdowns or capture the byte changes their popups generate.

Strategy:
  1. Load DELAY_PLUS, set TYPE=5 (DUAL).
  2. For each of MODE / L.TYPE / R.TYPE:
       - Probe via popup (Home+Enter, then step+Enter until clamped).
       - Capture USBPcap during cycling.
       - Decode the address and enum_max (number of values).
  3. Save to summary.json under "delay_plus_dual_dropdowns".

Click coordinates derived from type_layout_05.png label-pixel scan:
  TYPE   label center ~297, click x=350 (existing)
  MODE   label center ~565, click x=620
  L.TYPE label center ~858, click x=910
  R.TYPE label center ~1150, click x=1200
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from map_all_effects import (usbpcap_start, usbpcap_stop, take_screenshot,
                              restore_baseline)
from explore_all_effects import (
    click, click_focus_knob, ensure_loaded, analyze_type_pcap,
    TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y, reset_to_min, step_to_next, text_hash,
)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"
DUAL_DIR = TYPEBAR / "page1" / "04_DELAY_PLUS"

DROPDOWN_Y = 494
DROPDOWNS = [
    ("MODE",   620),
    ("L_TYPE", 910),
    ("R_TYPE", 1200),
]

# Crop region (left, top, right, bottom) for each dropdown's value text
CROP_HEIGHT = (480, 510)
DROPDOWN_CROPS = {
    "MODE":   (480, 480, 660, 510),
    "L_TYPE": (770, 480, 950, 510),
    "R_TYPE": (1060, 480, 1240, 510),
}


def cycle_dropdown_via_popup(name: str, click_x: int,
                              out_pcap: Path, max_steps: int = 64):
    """Probe a dropdown by Home+Enter (reset to 0), then Down+Enter
    repeatedly until the dropdown's text stabilizes (clamped at max).
    Capture USBPcap throughout. Return (n_values, payloads_list)."""
    if out_pcap.exists():
        out_pcap.unlink()
    jsonl = out_pcap.with_suffix(".jsonl")
    if jsonl.exists():
        jsonl.unlink()

    cap = usbpcap_start(out_pcap)
    time.sleep(1.0)
    payloads_seen = []
    try:
        # Reset to 0
        reset_to_min(click_x, DROPDOWN_Y)
        time.sleep(0.4)
        crop = DROPDOWN_CROPS[name]
        png = DUAL_DIR / f"dual_{name}_step_00.png"
        take_screenshot(png)
        last_hash = text_hash(Image.open(png), crop)
        same_count = 0
        n = 1
        for step in range(1, max_steps + 1):
            step_to_next(click_x, DROPDOWN_Y)
            time.sleep(0.35)
            png = DUAL_DIR / f"dual_{name}_step_{step:02d}.png"
            take_screenshot(png)
            h = text_hash(Image.open(png), crop)
            if h == last_hash:
                same_count += 1
                if same_count >= 2:
                    break
            else:
                last_hash = h; same_count = 0
                n = step + 1
    finally:
        usbpcap_stop(cap)
    print(f"  {name}: {n} unique values")
    return n


def explore_dual():
    eff_dir = DUAL_DIR
    summary_path = eff_dir / "summary.json"
    summary = json.loads(summary_path.read_text())

    flag = eff_dir / "dual_dropdowns_done.flag"
    if flag.exists():
        print("DELAY_PLUS DUAL: already done")
        return

    print("=== DELAY_PLUS DUAL extra dropdowns ===")
    ensure_loaded(1, 4, "DELAY_PLUS", "", eff_dir, max_retries=3)

    # Set TYPE=5 (DUAL): reset then 5 step_to_next
    print("  setting TYPE=5 (DUAL)")
    reset_to_min(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)
    for _ in range(5):
        step_to_next(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)
    time.sleep(0.6)

    results = {}
    for name, click_x in DROPDOWNS:
        out_pcap = eff_dir / f"dual_{name}.pcap"
        n_values = cycle_dropdown_via_popup(name, click_x, out_pcap)
        # Find the changing address from the pcap
        events = analyze_type_pcap(out_pcap)
        addr_freq = {}
        for addr, _ in events:
            addr_freq[addr] = addr_freq.get(addr, 0) + 1
        # Pick most-frequent address, ignoring TYPE address (10001103)
        candidates = sorted(addr_freq.items(), key=lambda x: -x[1])
        addr_picked = None
        for a, f in candidates:
            if a != "10001103":
                addr_picked = a; break
        results[name] = {
            "n_values": n_values,
            "address": addr_picked,
            "click_x": click_x,
        }
        print(f"  {name}: {n_values} values, address={addr_picked}")

    summary["delay_plus_dual_dropdowns"] = results
    summary_path.write_text(json.dumps(summary, indent=2, default=list))
    flag.touch()
    print(f"  done: {len(results)} dropdowns enumerated")


def main():
    restore_baseline()
    try:
        explore_dual()
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
