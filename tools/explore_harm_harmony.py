"""HARM/HARM_BASS HARMONY-knob layout exploration.

Per user: setting HARMONY to USER reveals additional knobs much lower
in the GUI. The HARMONY knob has enum values (e.g. -2oct, -14th, ...,
USER, ...). The default layout never reaches USER, so we missed those
extra knobs in the per-TYPE pass.

Strategy (similar to AMP SP_TYPE):
  1. Load effect, set TYPE=0 (1 VOICE) — actually try each TYPE.
  2. Reset HARMONY knob to min (press DOWN many times after focus).
  3. Step UP one at a time; for each step, screenshot + detect knobs.
  4. Stop when 5 consecutive screenshots have identical knob layout
     (indicates we reached max and are clamped).
  5. Group HARMONY values by layout signature.
  6. For each layout group containing knob positions not already in
     summary.knobs/knobs_extra, sweep those new knobs.
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

# HARMONY knob is the FIRST knob in HARM's default layout — knob_idx=0,
# at window-local (310, 590). Confirmed from summary.json.
HARMONY_X = 310
HARMONY_Y = 590

# Maximum cycle attempts when stepping UP from min. HARMONIST HARMONY
# has 30 values per the manual (-2OCT, intervals, +2OCT, USER). USER is
# one specific value among many — early-stop on signature stability is
# wrong because most intervals share the same layout. Iterate the full
# range; STABLE threshold here is only used as final guard.
MAX_STEPS = 35
STABLE_STEPS_TO_STOP = 999  # disabled; iterate full MAX_STEPS


def _knob_layout_sig(knobs):
    return tuple(sorted((k[0], k[1]) for k in knobs))


def cycle_harmony(eff_dir: Path, prefix: str = "harm"):
    """Set HARMONY to min, then step UP one at a time. Returns list of
    (step_index, knobs) per step."""
    # Focus + reset to min
    click_focus_knob(HARMONY_X, HARMONY_Y)
    time.sleep(0.2)
    # Saturate down. HARMONY enum has ~30 values; 35 presses is enough
    # without risking focus drift from over-press.
    for _ in range(35):
        pyautogui.press("down")
        time.sleep(0.020)
    time.sleep(0.4)

    layouts = []
    last_sig = None
    same_count = 0
    for step in range(MAX_STEPS):
        png = eff_dir / f"{prefix}_layout_{step:02d}.png"
        take_screenshot(png)
        knobs = detect_knobs(Image.open(png))
        sig = _knob_layout_sig(knobs)
        layouts.append((step, knobs))
        print(f"    HARMONY step={step:2d}: {len(knobs)} knobs sig_hash={hash(sig) & 0xFFFF:04x}")
        if sig == last_sig:
            same_count += 1
            if same_count >= STABLE_STEPS_TO_STOP:
                # Strip trailing duplicates
                layouts = layouts[:-STABLE_STEPS_TO_STOP + 1]
                print(f"    layout stable at step {step - STABLE_STEPS_TO_STOP + 1}, stopping")
                break
        else:
            same_count = 0
            last_sig = sig
        # Step up one
        pyautogui.press("up")
        time.sleep(0.05)
    return layouts


def set_harmony_value(target_step: int):
    """Reset HARMONY to min, then step UP `target_step` times."""
    click_focus_knob(HARMONY_X, HARMONY_Y)
    time.sleep(0.2)
    for _ in range(35):
        pyautogui.press("down"); time.sleep(0.020)
    time.sleep(0.3)
    for _ in range(target_step):
        pyautogui.press("up"); time.sleep(0.05)
    time.sleep(0.3)


def set_harm_type_to_2voice():
    """Drive HARM TYPE dropdown to 2 (2 STEREO) so both HR1 and HR2
    user-scale rows are exposed when HARMONY=USER."""
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


def explore_harm_harmony(page: int, idx: int, name: str):
    eff_dir = TYPEBAR / f"page{page}" / f"{idx:02d}_{name}"
    summary_path = eff_dir / "summary.json"
    if not summary_path.exists():
        print(f"  no summary.json for {name}, skip")
        return
    summary = json.loads(summary_path.read_text())

    flag = eff_dir / "harmony_layout_done.flag"
    if flag.exists():
        print(f"  {name}: harmony_layout already done")
        return

    print(f"\n=== {name} (page {page}, idx {idx}) — HARMONY layout cycle ===")

    ensure_loaded(page, idx, name, "", eff_dir, max_retries=3)

    # Set TYPE=2 (2 STEREO/2 VOICE) so HARMONY=USER exposes the full
    # 24-knob USER SCALE editor (HR1:C..HR1:B + HR2:C..HR2:B).
    print("  setting TYPE=2 (2 voice)")
    set_harm_type_to_2voice()
    time.sleep(0.3)

    layouts = cycle_harmony(eff_dir, prefix="harm")

    # Group by layout signature
    from collections import defaultdict
    by_sig = defaultdict(list)
    for step, knobs in layouts:
        sig = _knob_layout_sig(knobs)
        by_sig[sig].append(step)
    print(f"  unique layouts across HARMONY values: {len(by_sig)}")
    for sig, steps in by_sig.items():
        print(f"    {len(sig)} knobs at HARMONY steps {steps}")

    # Existing knob positions: from summary.knobs + knobs_extra
    existing_positions = {(k["knob_x"], k["knob_y"])
                          for k in summary.get("knobs", [])}
    for k in summary.get("knobs_extra", []):
        existing_positions.add((k["knob_x"], k["knob_y"]))

    new_records = []
    for sig, steps in by_sig.items():
        new_positions = [p for p in sig if p not in existing_positions]
        if not new_positions:
            print(f"    HARMONY layout {steps[0]}: all knobs already known")
            continue
        print(f"    HARMONY layout {steps[0]}: sweeping {len(new_positions)} new knobs at positions {new_positions}")
        set_harmony_value(steps[0])
        time.sleep(0.5)
        up_pcap = eff_dir / f"harm_newknobs_step{steps[0]:02d}_up.pcap"
        down_pcap = eff_dir / f"harm_newknobs_step{steps[0]:02d}_down.pcap"
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
                "first_seen_at_harmony_step": steps[0],
            })

    summary["per_harmony_layouts"] = [
        {"harmony_step": step,
         "visible_knob_positions": [list(k) for k in knobs]}
        for step, knobs in layouts
    ]
    summary["harmony_layout_groups"] = [
        {"harmony_steps": steps,
         "n_knobs": len(sig),
         "positions": [list(p) for p in sig]}
        for sig, steps in by_sig.items()
    ]
    if new_records:
        summary.setdefault("knobs_extra", []).extend(new_records)
    summary_path.write_text(json.dumps(summary, indent=2, default=list))
    flag.touch()
    print(f"  done: {len(layouts)} HARMONY steps, "
          f"{len(by_sig)} unique groups, {len(new_records)} new knobs")


def main():
    restore_baseline()
    for page, idx, name in [(0, 29, "HARM"), (2, 13, "HARM_BASS")]:
        try:
            explore_harm_harmony(page, idx, name)
        except Exception as e:
            print(f"  ERROR on {name}: {e}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
