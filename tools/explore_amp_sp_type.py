"""AMP/AMP_BASS SP_TYPE exploration.

Per user: SP_TYPE has 3 layout categories.
  - OFF and USER<N> (1..16):  no DIRECT MIX, MIC TYPE, MIC DISTANCE,
                              MIC POSITION, MIC LEVEL
  - 1x8" / 1x10" / etc.:      ALL knobs visible

For each AMP-style effect (AMP, AMP_BASS):
  1. Load the effect.
  2. Cycle SP_TYPE 0..max via popup. For each, screenshot + detect knobs.
  3. Group SP_TYPE values by knob-layout signature (positions tuple).
  4. For each unique layout, sweep any new knob positions (those not
     already in summary.knobs).
  5. Save: per_sp_type_layouts (signature → [sp_type values]).
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image, ImageGrab
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from map_all_effects import (usbpcap_start, usbpcap_stop, take_screenshot,
                              detect_knobs, restore_baseline)
from explore_all_effects import (
    SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y, SP_TYPE_TEXT_CROP,
    has_sp_type_dropdown,
    click, click_focus_knob,
    reset_to_min, step_to_next,
    ensure_loaded,
    text_hash, analyze_type_pcap,
)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"


def set_sp_type_value(target: int, current: int = -1):
    if current < 0 or current > target:
        reset_to_min(SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y)
        for _ in range(target):
            step_to_next(SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y)
    else:
        for _ in range(target - current):
            step_to_next(SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y)


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


def explore_amp_sp_types(page: int, idx: int, name: str):
    eff_dir = TYPEBAR / f"page{page}" / f"{idx:02d}_{name}"
    summary_path = eff_dir / "summary.json"
    if not summary_path.exists():
        print(f"  no summary.json for {name}, skip")
        return
    summary = json.loads(summary_path.read_text())
    sp_type_max = summary.get("sp_type_max", -1)
    if sp_type_max < 1:
        print(f"  {name} has no SP_TYPE, skip")
        return

    flag = eff_dir / "per_sp_type_done.flag"
    if flag.exists():
        print(f"  {name}: already done")
        return

    print(f"\n=== {name} (page {page}, idx {idx}) — SP_TYPE values: {sp_type_max+1} ===")

    ensure_loaded(page, idx, name, "", eff_dir, max_retries=3)

    # Cycle SP_TYPE values, recording knob layout per value
    layouts = []
    cur = -1
    for sv in range(sp_type_max + 1):
        set_sp_type_value(sv, cur)
        cur = sv
        time.sleep(0.4)
        png = eff_dir / f"sp_layout_{sv:02d}.png"
        take_screenshot(png)
        knobs = detect_knobs(Image.open(png))
        layouts.append((sv, knobs))
        print(f"    SP_TYPE={sv:2d}: {len(knobs)} knobs visible")

    # Group SP_TYPE values by layout signature
    from collections import defaultdict
    by_sig = defaultdict(list)
    for sv, knobs in layouts:
        sig = tuple(sorted((k[0], k[1]) for k in knobs))
        by_sig[sig].append(sv)

    print(f"  unique layouts: {len(by_sig)}")
    for sig, sv_list in by_sig.items():
        print(f"    {len(sig)} knobs visible at SP_TYPE={sv_list}")

    existing_positions = {(k["knob_x"], k["knob_y"])
                          for k in summary.get("knobs", [])}
    new_records = []
    for sig, sv_list in by_sig.items():
        new_positions = [p for p in sig if p not in existing_positions]
        if not new_positions:
            print(f"    layout {sv_list[0]}: all knobs already in summary")
            continue
        print(f"    layout {sv_list[0]}: sweeping {len(new_positions)} new knobs")
        # Set SP_TYPE to a value with this layout
        set_sp_type_value(sv_list[0], -1)
        time.sleep(0.5)
        up_pcap = eff_dir / f"sp_newknobs_{sv_list[0]:02d}_up.pcap"
        down_pcap = eff_dir / f"sp_newknobs_{sv_list[0]:02d}_down.pcap"
        sweep_knobs_batched(new_positions, up_pcap, down_pcap, presses=200)
        up_events = analyze_type_pcap(up_pcap)
        down_events = analyze_type_pcap(down_pcap)
        # Order by down phase
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
                "first_seen_at_sp_type": sv_list[0],
            })

    # Save layout map: sp_type → list of knob (x,y)
    summary["per_sp_type_layouts"] = [
        {"sp_type_value": sv,
         "visible_knob_positions": [list(k) for k in knobs]}
        for sv, knobs in layouts
    ]
    summary["sp_type_layout_groups"] = [
        {"sp_type_values": sv_list,
         "n_knobs": len(sig),
         "positions": [list(p) for p in sig]}
        for sig, sv_list in by_sig.items()
    ]
    if new_records:
        summary.setdefault("knobs_extra", []).extend(new_records)
    summary_path.write_text(json.dumps(summary, indent=2, default=list))
    flag.touch()
    print(f"  done: {len(layouts)} sp-type layouts, "
          f"{len(by_sig)} unique groups, {len(new_records)} new knobs")


def main():
    restore_baseline()
    for page, idx, name in [(0, 9, "AMP"), (2, 6, "AMP_BASS")]:
        try:
            explore_amp_sp_types(page, idx, name)
        except Exception as e:
            print(f"  ERROR on {name}: {e}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
