"""Per-TYPE knob exploration for multi-type effects.

For each effect with TYPE >= 2 entries:
  1. Load it (uses existing drag.pcap or re-drags via drag_effect).
  2. For each TYPE value 0..max:
      - set TYPE via popup (Home+Enter for 0; subsequent: Down+Enter to step)
      - take screenshot (type_NN_layout.png)
      - detect knob positions
  3. Identify the union of knob positions across types (master set).
  4. For knob positions NOT yet swept (i.e. not in the existing
     summary.json["knobs"]), set TYPE to one where they are visible
     and sweep them (added to summary.json).
  5. Record per_type_layout: for each type value, the list of knob
     position keys (x_y) visible.

For AMP/AMP_BASS with SP_TYPE: additionally cycle SP_TYPE and record
per-SP layout (since SP_TYPE has 3 layout categories per user note —
OFF/USER<N> hide mic params; other configs show them).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image, ImageGrab
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from effect_catalog import (PAGE_0, PAGE_1, PAGE_2, HEX_Y,
                             SLOT0_X, SLOT0_Y, hex_x_pos)
from find_hex_centers import find_hexes
import scroll_typebar
from map_all_effects import (usbpcap_start, usbpcap_stop, drag_effect,
                              clear_slot0, restore_baseline, take_screenshot,
                              detect_knobs, analyze_drag_pcap,
                              analyze_knob_pcap)
from explore_all_effects import (
    TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y, TYPE_TEXT_CROP,
    SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y, SP_TYPE_TEXT_CROP,
    has_type_dropdown, has_sp_type_dropdown,
    click, click_focus_knob,
    reset_to_min, step_to_next,
    sweep_knob, ensure_loaded, select_slot0,
    text_hash, analyze_type_pcap,
)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"


def set_type_value(target: int, current: int = -1):
    """Drive TYPE dropdown to `target`. If current >= 0 and <= target,
    step Down (target - current) times. Otherwise reset to 0 first."""
    if current < 0 or current > target:
        # Reset and step up
        reset_to_min(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)
        for _ in range(target):
            step_to_next(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)
    else:
        for _ in range(target - current):
            step_to_next(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)


def per_type_explore(out_dir: Path, type_max: int, prefix: str = "type"):
    """Cycle through every TYPE value 0..type_max. For each, set the
    TYPE via popup, screenshot, detect knobs. Returns list of
    (type_value, [(kx, ky), ...]) layouts."""
    layouts = []
    cur = -1  # unknown
    for tv in range(type_max + 1):
        set_type_value(tv, cur_assumed_arg := cur)
        cur = tv
        time.sleep(0.4)
        png = out_dir / f"{prefix}_layout_{tv:02d}.png"
        take_screenshot(png)
        knobs = detect_knobs(Image.open(png))
        layouts.append((tv, knobs))
        print(f"    type={tv:2d}: {len(knobs)} knobs at {knobs[:3]}{'...' if len(knobs) > 3 else ''}")
    return layouts


def sweep_knobs_batched(knobs, out_pcap_up: Path, out_pcap_down: Path,
                         presses: int = 200):
    """Two-phase batched sweep: all-up then all-down with starting-state
    wiggle. Same logic as explore_all_effects but restricted to a given
    knob list (for sweeping NEW knobs at a non-default TYPE)."""
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
    time.sleep(0.4)


def explore_one_multi_type_effect(page: int, idx: int, name: str,
                                    has_sp: bool = False):
    eff_dir = TYPEBAR / f"page{page}" / f"{idx:02d}_{name}"
    summary_path = eff_dir / "summary.json"
    if not summary_path.exists():
        print(f"  no summary.json for {name}, skip")
        return
    summary = json.loads(summary_path.read_text())
    type_max = summary.get("type_max", -1)
    sp_type_max = summary.get("sp_type_max", -1)
    if type_max < 1:
        print(f"  {name} has only {type_max+1} types, skip")
        return

    print(f"\n=== per-TYPE explore: {name} (page {page}, idx {idx}, "
          f"types={type_max+1}, sp_types={sp_type_max+1 if has_sp else 0}) ===")

    # If a "per_type_done" flag exists, skip this effect.
    flag = eff_dir / "per_type_done.flag"
    if flag.exists():
        print(f"  already done, skip")
        return

    # Ensure effect is loaded (re-drag from typebar).
    ensure_loaded(page, idx, name, "", eff_dir, max_retries=3)

    # Cycle TYPEs and record per-type layout
    layouts = per_type_explore(eff_dir, type_max, prefix="type")

    # Build master knob set across all types
    master_knobs = set()
    for tv, knobs in layouts:
        for k in knobs:
            master_knobs.add(tuple(k))
    master_knobs_sorted = sorted(master_knobs, key=lambda p: (p[1], p[0]))
    print(f"  master knob set: {len(master_knobs_sorted)} positions")

    # Existing knobs from summary
    existing_knob_positions = {(k["knob_x"], k["knob_y"])
                                for k in summary.get("knobs", [])}
    new_positions = [p for p in master_knobs_sorted
                      if p not in existing_knob_positions]
    print(f"  new knob positions to sweep: {len(new_positions)}")

    # For each new position, find a TYPE where it's visible, set TYPE,
    # then sweep.
    new_knob_records = []
    if new_positions:
        # Group new positions by which type they appear in (pick any)
        positions_per_type = {}
        for tv, knobs in layouts:
            for p in knobs:
                if tuple(p) in {tuple(np) for np in new_positions}:
                    positions_per_type.setdefault(tv, []).append(tuple(p))

        # For each type group, set TYPE and sweep that group
        for tv, positions in sorted(positions_per_type.items()):
            print(f"    sweeping {len(positions)} new knobs at TYPE={tv}")
            set_type_value(tv, cur_assumed_arg := -1)  # always reset
            time.sleep(0.5)
            up_pcap = eff_dir / f"newknobs_type{tv:02d}_up.pcap"
            down_pcap = eff_dir / f"newknobs_type{tv:02d}_down.pcap"
            sweep_knobs_batched(positions, up_pcap, down_pcap, presses=200)
            # Analyze
            up_events = analyze_type_pcap(up_pcap)
            down_events = analyze_type_pcap(down_pcap)
            # Group by address, ordered by down phase
            from collections import OrderedDict
            order = []
            seen = set()
            for addr, _ in down_events:
                if addr not in seen:
                    seen.add(addr); order.append(addr)
            for ki, (kx, ky) in enumerate(positions):
                addr = order[ki] if ki < len(order) else None
                if not addr:
                    continue
                d_vals = [int(p[-2:], 16) for a, p in down_events if a == addr]
                u_vals = [int(p[-2:], 16) for a, p in up_events if a == addr]
                all_vals = d_vals + u_vals
                new_knob_records.append({
                    "knob_x": kx, "knob_y": ky,
                    "address": addr,
                    "min": min(all_vals) if all_vals else None,
                    "max": max(all_vals) if all_vals else None,
                    "n_dt1_down": len(d_vals),
                    "n_dt1_up": len(u_vals),
                    "first_seen_at_type": tv,
                })

    # Build per-type knob index list:
    # for each TYPE, list of indices into the master knob set
    master_index = {tuple(p): i for i, p in enumerate(master_knobs_sorted)}
    per_type_layout = []
    for tv, knobs in layouts:
        idxs = [master_index[tuple(k)] for k in knobs]
        per_type_layout.append({"type_value": tv, "knob_master_indices": idxs})

    # Update summary
    summary["per_type_layouts"] = per_type_layout
    summary["master_knob_positions"] = [list(p) for p in master_knobs_sorted]
    if new_knob_records:
        summary["knobs_extra"] = new_knob_records
    summary_path.write_text(json.dumps(summary, indent=2, default=list))
    flag.touch()
    print(f"  done: {len(layouts)} type-layouts, "
          f"{len(new_knob_records)} new knob records")


def main():
    # Skip AMP and AMP_BASS — user prefers to handle these separately
    # since their 23+9 TYPE values × SP_TYPE matrix is very expensive.
    multi_type_effects = [
        (0, 0, "COMP", False), (0, 2, "BOOST", False), (0, 3, "OD", False),
        (0, 5, "DIST", False), (0, 7, "METAL", False), (0, 8, "FUZZ", False),
        # (0, 9, "AMP", True),  # SKIP — done separately
        (0, 12, "CHO", False), (0, 16, "PH", False), (0, 18, "PH_PRIME", False),
        (0, 19, "CLASS_VIBE", False), (0, 28, "PS", False),
        (0, 29, "HARM", False),
        (1, 4, "DELAY_PLUS", False), (1, 5, "DELAY_ANALOG", False),
        (1, 9, "DELAY_TWIST", False), (1, 11, "REV", False),
        (1, 12, "REV_PLUS", False), (1, 15, "AC_RESO", False),
        (1, 23, "WAH", False), (1, 27, "DIV_MIX", False),
        (1, 28, "SEND_RETURN", False),
        (2, 3, "DIST_BASS", False),
        # (2, 6, "AMP_BASS", True),  # SKIP — done separately
        (2, 7, "CHO_BASS", False), (2, 10, "PH_BASS", False),
        (2, 11, "PH_PRIME_BASS", False), (2, 12, "PS_BASS", False),
        (2, 13, "HARM_BASS", False),
    ]

    restore_baseline()

    for page, idx, name, has_sp in multi_type_effects:
        try:
            explore_one_multi_type_effect(page, idx, name, has_sp=has_sp)
        except Exception as e:
            print(f"  ERROR on {name}: {e}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
