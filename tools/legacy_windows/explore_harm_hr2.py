"""HARM/HARM_BASS HR2 user-scale row exploration.

The first HARMONY-knob explorer captured the HR1 user-scale row (12
knobs at y=830) by setting TYPE=2 and cycling 1:HARMONY to USER.

To expose the HR2 row (additional 12 knobs at y~950), we need BOTH
1:HARMONY and 2:HARMONY set to USER. The 2:HARMONY knob sits at
position (310, 710) (first knob of row 2 in TYPE=2 layout).
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
                              detect_knobs, restore_baseline)
from explore_all_effects import (
    click, click_focus_knob, ensure_loaded, analyze_type_pcap,
    TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y, reset_to_min, step_to_next,
)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"


def saturate_knob_to_max(knob_x, knob_y, presses=35):
    click_focus_knob(knob_x, knob_y)
    time.sleep(0.2)
    # First reset to min then step UP (the enum max == USER for HARMONY)
    for _ in range(presses):
        pyautogui.press("down"); time.sleep(0.020)
    time.sleep(0.3)
    for _ in range(presses):
        pyautogui.press("up"); time.sleep(0.020)
    time.sleep(0.4)


def set_harm_type_to_2voice():
    reset_to_min(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)
    step_to_next(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)  # 0 -> 1
    step_to_next(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)  # 1 -> 2
    time.sleep(0.4)


def sweep_knobs_batched(knobs, out_pcap_up: Path, out_pcap_down: Path,
                         presses: int = 200):
    def _phase(out_pcap, direction):
        opposite = "up" if direction == "down" else "down"
        if out_pcap.exists():
            out_pcap.unlink()
        jsonl = out_pcap.with_suffix(".jsonl")
        if jsonl.exists():
            jsonl.unlink()
        cap = usbpcap_start(out_pcap)
        time.sleep(1.0)
        try:
            for kx, ky in knobs:
                click_focus_knob(kx, ky)
                pyautogui.press(opposite)
                time.sleep(0.04)
                pyautogui.press(direction)
                time.sleep(0.04)
                for _ in range(presses):
                    pyautogui.press(direction)
                    time.sleep(0.015)
                time.sleep(0.10)
        finally:
            usbpcap_stop(cap)
    _phase(out_pcap_up, "up")
    time.sleep(0.4)
    _phase(out_pcap_down, "down")


def explore_harm_hr2(page: int, idx: int, name: str):
    eff_dir = TYPEBAR / f"page{page}" / f"{idx:02d}_{name}"
    summary_path = eff_dir / "summary.json"
    if not summary_path.exists():
        print(f"  no summary.json for {name}, skip")
        return
    summary = json.loads(summary_path.read_text())

    flag = eff_dir / "hr2_layout_done.flag"
    if flag.exists():
        print(f"  {name}: hr2 already done")
        return

    print(f"\n=== {name} (page {page}, idx {idx}) — HR2 user scale ===")

    ensure_loaded(page, idx, name, "", eff_dir, max_retries=3)

    print("  setting TYPE=2 (2 voice)")
    set_harm_type_to_2voice()

    # 1:HARMONY at (310, 590) -> USER (max enum)
    print("  setting 1:HARMONY = USER")
    saturate_knob_to_max(310, 590, presses=35)

    # 2:HARMONY at (310, 710) -> USER
    print("  setting 2:HARMONY = USER")
    saturate_knob_to_max(310, 710, presses=35)

    png = eff_dir / "hr2_full_layout.png"
    take_screenshot(png)
    knobs = detect_knobs(Image.open(png))
    print(f"  detected {len(knobs)} knobs")

    existing_positions = {(k["knob_x"], k["knob_y"])
                          for k in summary.get("knobs", [])}
    for k in summary.get("knobs_extra", []):
        existing_positions.add((k["knob_x"], k["knob_y"]))

    new_positions = [tuple(k) for k in knobs if tuple(k) not in existing_positions]
    print(f"  {len(new_positions)} positions not yet known: {new_positions}")

    new_records = []
    if new_positions:
        up_pcap = eff_dir / "hr2_newknobs_up.pcap"
        down_pcap = eff_dir / "hr2_newknobs_down.pcap"
        sweep_knobs_batched(new_positions, up_pcap, down_pcap, presses=200)
        up_events = analyze_type_pcap(up_pcap)
        down_events = analyze_type_pcap(down_pcap)
        order = []
        seen = set()
        for addr, _ in down_events:
            if addr not in seen:
                seen.add(addr); order.append(addr)
        for ki, (kx, ky) in enumerate(new_positions):
            addr = order[ki] if ki < len(order) else None
            if not addr:
                continue
            d_vals = [int(p[-2:], 16) for a, p in down_events if a == addr]
            u_vals = [int(p[-2:], 16) for a, p in up_events if a == addr]
            all_vals = d_vals + u_vals
            new_records.append({
                "knob_x": kx, "knob_y": ky,
                "address": addr,
                "min": min(all_vals) if all_vals else None,
                "max": max(all_vals) if all_vals else None,
                "n_dt1_down": len(d_vals),
                "n_dt1_up": len(u_vals),
                "first_seen_at": "2:HARMONY=USER",
            })

    summary["hr2_full_positions"] = [list(k) for k in knobs]
    if new_records:
        summary.setdefault("knobs_extra", []).extend(new_records)
    summary_path.write_text(json.dumps(summary, indent=2, default=list))
    flag.touch()
    print(f"  done: {len(knobs)} knobs visible, {len(new_records)} new HR2 records")


def main():
    restore_baseline()
    for page, idx, name in [(0, 29, "HARM"), (2, 13, "HARM_BASS")]:
        try:
            explore_harm_hr2(page, idx, name)
        except Exception as e:
            print(f"  ERROR on {name}: {e}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
