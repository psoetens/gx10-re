"""
Full per-effect exploration: drag effect onto slot 0, then for each effect
that has a TYPE / SP TYPE dropdown, cycle through every value via the
popup-driven mechanism (click → Down → Enter), capturing USBPcap and
screenshots. Finally sweep knobs for each unique layout.

Mechanism for TYPE / SP TYPE:
  - Click on the dropdown's text area → popup opens. Popup remembers the
    last highlighted index between opens.
  - Press Home → highlights the first item; Enter commits → DT1 sent.
  - To advance one step: click → Down (popup remembers position) → Enter.
  - To detect max: when the dropdown TEXT pixels stop changing between
    consecutive steps, the device has clamped at max.

Per-effect output:
  captures/typebar_full/<page>/<idx>_<name>/
    drag.pcap, drag.png            — the drag and its screenshot
    probe_type.pcap, type_NN.png   — TYPE cycling capture + screenshots
    probe_sp_type.pcap, sp_type_NN.png — SP TYPE cycling
    knob_<i>_<x>_<y>.pcap          — knob sweeps for default layout
    layout_<sig>_knob_<i>.pcap     — knob sweeps for variant layouts
    summary.json                    — aggregated metadata
"""
import argparse
import json
import os
import subprocess
import sys
import time
import hashlib
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

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
TYPEBAR_DIR = ROOT / "captures" / "typebar_full"

# Window-local positions of the TYPE / SP TYPE dropdown UI. The labels
# sit on row y=494 directly below the effect's title bar, and the text
# of each dropdown's selected value occupies a fixed crop.
TYPE_LABEL_Y = 494
TYPE_LABEL_X_RANGE = (230, 290)
SP_TYPE_LABEL_X_RANGE = (550, 640)
TYPE_DROPDOWN_X = 350      # click target — over the text, away from chevron
TYPE_DROPDOWN_Y = 494
SP_TYPE_DROPDOWN_X = 720
SP_TYPE_DROPDOWN_Y = 494
TYPE_TEXT_CROP = (290, 480, 540, 510)
SP_TYPE_TEXT_CROP = (600, 480, 770, 510)


def has_label_at_row(img: Image.Image, y: int, x_range: tuple,
                      y_tol: int = 6) -> bool:
    """Check whether there's a white text label in `x_range` at rows
    near `y` (±y_tol). Used to detect TYPE / SP TYPE labels."""
    x0, x1 = x_range
    for yi in range(y - y_tol, y + y_tol + 1):
        for x in range(x0, x1):
            try:
                r, g, b = img.getpixel((x, yi))[:3]
            except Exception:
                continue
            if r > 180 and g > 180 and b > 180:
                return True
    return False


def has_type_dropdown(img: Image.Image) -> bool:
    return has_label_at_row(img, TYPE_LABEL_Y, TYPE_LABEL_X_RANGE)


def has_sp_type_dropdown(img: Image.Image) -> bool:
    return has_label_at_row(img, TYPE_LABEL_Y, SP_TYPE_LABEL_X_RANGE)


def click(dx: int, dy: int):
    """Single click via Win32 SendInput. pyautogui's mouse_event API is
    unreliable under sustained automation."""
    from map_all_effects import win32_move_to, win32_left_down, win32_left_up
    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.15)
    sx, sy = focus_ts.screen_xy(hwnd, dx, dy)
    win32_move_to(sx, sy)
    time.sleep(0.10)
    win32_left_down()
    time.sleep(0.08)
    win32_left_up()
    time.sleep(0.50)


def click_focus_knob(knob_x: int, knob_y: int):
    """Click a knob to focus it for keyboard input. Uses a deliberate
    move + click sequence with extra pauses, since fast clicks sometimes
    fail to focus knobs in TS (subsequent arrow keys go nowhere)."""
    from map_all_effects import win32_move_to, win32_left_down, win32_left_up
    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.15)
    sx, sy = focus_ts.screen_xy(hwnd, knob_x, knob_y)
    # Move first, settle, then click. Helps TS register hover before click.
    win32_move_to(sx, sy)
    time.sleep(0.20)
    win32_left_down()
    time.sleep(0.08)
    win32_left_up()
    time.sleep(0.30)


def reset_to_min(dx: int, dy: int):
    """Open popup, Home, Enter — sets value to popup index 0."""
    click(dx, dy)
    pyautogui.press("home")
    time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(0.5)


def step_to_next(dx: int, dy: int):
    """Open popup (popup remembers position), Down, Enter — advances by 1."""
    click(dx, dy)
    pyautogui.press("down")
    time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(0.4)


def text_hash(im: Image.Image, crop: tuple) -> bytes:
    return im.crop(crop).tobytes()


def cycle_dropdown(dx: int, dy: int, text_crop: tuple, max_iters: int,
                    out_dir: Path, prefix: str, pcap: Path):
    """Cycle a dropdown via popup, capturing pcap + per-step screenshots.

    Returns (max_value, list_of_screenshot_paths).
    """
    cap = usbpcap_start(pcap)
    time.sleep(1.0)
    screenshots = []
    try:
        reset_to_min(dx, dy)
        png0 = out_dir / f"{prefix}_00.png"
        take_screenshot(png0)
        screenshots.append(png0)
        seen = {text_hash(Image.open(png0), text_crop): 0}
        max_value = 0

        for tv in range(1, max_iters + 1):
            step_to_next(dx, dy)
            png = out_dir / f"{prefix}_{tv:02d}.png"
            take_screenshot(png)
            screenshots.append(png)
            h = text_hash(Image.open(png), text_crop)
            if h in seen:
                # Wrap or clamp detected
                max_value = tv - 1
                break
            seen[h] = tv
            max_value = tv
    finally:
        usbpcap_stop(cap)
    return max_value, screenshots


def analyze_type_pcap(pcap: Path) -> list:
    """Return a list of (addr_hex, payload_hex) for every host->dev DT1."""
    jsonl = pcap.with_suffix(".jsonl")
    subprocess.run(["python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
                    str(pcap), "--out", str(jsonl)], capture_output=True)
    out = []
    if not jsonl.exists():
        return out
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex" or ev.get("dir") != "host->dev":
                continue
            raw = bytes.fromhex(ev["hex"])
            if len(raw) < 16 or raw[8] != 0x12:
                continue
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            out.append((f"{addr:08X}", payload.hex().upper()))
    return out


def derive_dropdown_address_and_values(events: list) -> tuple:
    """From captured DT1s during cycling, find the dominant address and
    the ordered list of (popup-index → payload) writes."""
    if not events:
        return None, []
    by_addr = {}
    for addr, val in events:
        by_addr.setdefault(addr, []).append(val)
    # Dominant = most writes
    dom = max(by_addr.keys(), key=lambda a: len(by_addr[a]))
    return dom, by_addr[dom]


def sweep_knob(knob_x: int, knob_y: int, out_pcap: Path,
                presses: int = 130, gap: float = 0.020):
    """Click a knob and arrow up/down to capture parameter range."""
    cap = usbpcap_start(out_pcap)
    time.sleep(0.8)
    try:
        click(knob_x, knob_y)
        for _ in range(presses):
            pyautogui.press("down")
            time.sleep(gap)
        time.sleep(0.3)
        for _ in range(presses * 2):
            pyautogui.press("up")
            time.sleep(gap)
        time.sleep(0.5)
    finally:
        usbpcap_stop(cap)


def select_slot0():
    """Click the slot-0 hex to make TS focus that effect's editor panel.

    After a drag-drop into slot 0, TS sometimes leaves the editor panel
    showing the previously selected effect (a UI race). Clicking the
    chain hex forces the editor to refresh to the loaded effect.
    """
    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.15)
    sx, sy = focus_ts.screen_xy(hwnd, SLOT0_X, SLOT0_Y)
    pyautogui.click(sx, sy)
    time.sleep(0.6)


def ensure_loaded(page: int, idx: int, name: str, prev_name: str,
                   out_dir: Path, max_retries: int = 3):
    """Drag effect (page, idx) onto slot 0 with retries. Returns drag.pcap path."""
    drag_pcap = out_dir / "drag.pcap"
    drag_png = out_dir / "drag.png"

    def _drag_is_valid():
        if not drag_pcap.exists() or drag_pcap.stat().st_size < 4000:
            return False
        info = analyze_drag_pcap(drag_pcap)
        return info.get("triplet_at_10001100") is not None

    if prev_name == "DIV_MIX":
        clear_slot0()

    centers = []
    for _ in range(3):
        scroll_typebar.scroll_to_page(page)
        time.sleep(0.5)
        hwnd = focus_ts.focus_tone_studio()
        rect = focus_ts.get_window_rect(hwnd)
        tmp_img = ImageGrab.grab(bbox=(max(0, rect[0]), max(0, rect[1]),
                                       rect[2], rect[3]))
        tmp_path = out_dir / "_pre.png"
        tmp_img.save(tmp_path, "PNG")
        centers, _ = find_hexes(str(tmp_path))
        os.unlink(tmp_path)
        if len(centers) >= idx + 1:
            break
        time.sleep(0.5)
    if idx >= len(centers):
        print(f"  WARN: only {len(centers)} hexes after scroll, skipping {name}")
        return None
    hex_x_actual = centers[idx]

    # Always re-record the drag so we know it actually fired in this run.
    # On repeated failure, fall back to a full restore_baseline to clear
    # any sticky state, then retry.
    drag_succeeded = False
    for attempt in range(max_retries):
        if drag_pcap.exists():
            drag_pcap.unlink()
        jsonl = drag_pcap.with_suffix(".jsonl")
        if jsonl.exists():
            jsonl.unlink()
        cap = usbpcap_start(drag_pcap)
        time.sleep(1.0)
        try:
            drag_effect(hex_x_actual, SLOT0_X, SLOT0_Y)
            time.sleep(0.4)
            select_slot0()
        finally:
            usbpcap_stop(cap)
        if _drag_is_valid():
            drag_succeeded = True
            break
        print(f"  drag retry {attempt+1}/{max_retries} for {name}")
        # If we've already failed once, do a full TS restart before
        # the next attempt — the UI is stuck in a bad state.
        if attempt >= 1:
            print(f"  drag failed twice — restoring baseline before retry")
            restore_baseline()
            # Re-locate hex after restart (window may have moved)
            scroll_typebar.scroll_to_page(page)
            time.sleep(0.5)

    if not drag_succeeded:
        print(f"  GIVING UP on {name} after {max_retries} attempts")
        return None
    take_screenshot(drag_png)
    return drag_pcap


def explore_one_effect(page: int, idx: int, name: str, color: tuple,
                       hex_x: int, prev_name: str = "",
                       max_iters: int = 60):
    out_dir = TYPEBAR_DIR / f"page{page}" / f"{idx:02d}_{name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    explored_flag = out_dir / "explored.flag"
    if explored_flag.exists():
        print(f"  skip {name} (already explored)")
        return None

    drag_pcap = ensure_loaded(page, idx, name, prev_name, out_dir)
    if drag_pcap is None:
        print(f"  drag failed for {name} — skipping")
        return None
    drag_png = out_dir / "drag.png"
    drag_info = analyze_drag_pcap(drag_pcap)

    img = Image.open(drag_png)
    # Verify the editor refreshed: detect_knobs must find at least 1 knob.
    # If 0, restore_baseline and re-drag once more.
    initial_knobs = detect_knobs(img)
    if not initial_knobs:
        print(f"  WARN: 0 knobs detected after drag — restoring + retrying")
        restore_baseline()
        time.sleep(0.5)
        drag_pcap = ensure_loaded(page, idx, name, "", out_dir)
        if drag_pcap is None:
            return None
        img = Image.open(drag_png)
        initial_knobs = detect_knobs(img)
        if not initial_knobs:
            print(f"  STILL 0 knobs after restore — skipping")
            return None
        drag_info = analyze_drag_pcap(drag_pcap)

    has_type = has_type_dropdown(img)
    has_sp = has_sp_type_dropdown(img)
    print(f"  TYPE present: {has_type}, SP TYPE present: {has_sp}")

    type_addr = None
    type_max = -1
    type_payloads = []
    sp_type_addr = None
    sp_type_max = -1
    sp_type_payloads = []

    if has_type:
        pcap = out_dir / "probe_type.pcap"
        # Always re-cycle to get fresh data on each run (cheap).
        type_max, type_pngs = cycle_dropdown(
            TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y, TYPE_TEXT_CROP,
            max_iters, out_dir, "type", pcap)
        events = analyze_type_pcap(pcap)
        type_addr, type_payloads = derive_dropdown_address_and_values(events)
        print(f"  TYPE: addr={type_addr}, max={type_max}, "
              f"payloads={len(type_payloads)}")
        # Reset TYPE to 0 (default) so knob sweep happens at the
        # baseline parameter layout (e.g. CHO MONO, not DUAL).
        reset_to_min(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)
        time.sleep(0.5)

    if has_sp:
        pcap = out_dir / "probe_sp_type.pcap"
        sp_type_max, sp_pngs = cycle_dropdown(
            SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y, SP_TYPE_TEXT_CROP,
            max_iters, out_dir, "sp_type", pcap)
        events = analyze_type_pcap(pcap)
        sp_type_addr, sp_type_payloads = derive_dropdown_address_and_values(events)
        print(f"  SP TYPE: addr={sp_type_addr}, max={sp_type_max}, "
              f"payloads={len(sp_type_payloads)}")
        reset_to_min(SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y)
        time.sleep(0.5)

    # Re-detect knobs AFTER type/sp_type reset — layout may differ
    # between DEFAULT type and the last cycled type.
    take_screenshot(out_dir / "drag.png")
    img = Image.open(out_dir / "drag.png")

    # Sweep knobs for the DEFAULT layout (TYPE=0 + SP TYPE=0, the state
    # we're in right now after the cycling tests). Per user, knob layouts
    # are mostly stable across TYPE/SP TYPE values; we sweep the default
    # set and note any layout changes that might warrant follow-up.
    knobs = detect_knobs(img)

    # Two-phase batched sweep, ordered UP THEN DOWN so the down phase
    # explicitly captures the min byte (when starting at min, an immediate
    # down would emit no DT1, missing the min value):
    #   Phase 1 (all UP): per knob, click + 200 up → saturates each
    #     knob at max. After this, knobs are at MAX state.
    #   Phase 2 (all DOWN): per knob, click + 200 down → from MAX → MIN.
    #     Captures every value top-down INCLUDING the min byte (e.g.
    #     byte 0 for 0..15 knobs, byte 40 for BPM 40..250).
    knobs_all_up_pcap = out_dir / "knobs_all_up.pcap"
    knobs_all_down_pcap = out_dir / "knobs_all_down.pcap"

    def _phase(out_pcap, direction, presses=200):
        """For each knob: click, do a 2-key wiggle to capture the
        starting value (regardless of whether the knob was already at
        an extreme), then hammer `direction` to saturate.

        Wiggle = press <opposite>, press <direction>. This emits two
        DT1s: byte=current±1 then byte=current. So even if the knob
        started at min or max, we see the extreme byte explicitly."""
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
                # Wiggle: opposite-then-direction. Captures starting
                # byte as the second event (or first if already at the
                # extreme that opposite cannot move past).
                pyautogui.press(opposite)
                time.sleep(0.04)
                pyautogui.press(direction)
                time.sleep(0.04)
                # Now hammer in `direction` to saturate.
                for _ in range(presses):
                    pyautogui.press(direction)
                    time.sleep(0.015)
                time.sleep(0.10)
        finally:
            usbpcap_stop(cap)

    knob_records = []
    if knobs:
        _phase(knobs_all_up_pcap, "up", presses=200)
        time.sleep(0.4)
        take_screenshot(out_dir / "knobs_max.png")

        _phase(knobs_all_down_pcap, "down", presses=200)
        time.sleep(0.4)
        take_screenshot(out_dir / "knobs_min.png")
        print(f"  captured all-up + all-down sweeps and min/max screenshots")

        # Group DT1 events by address from each phase pcap
        down_events = analyze_type_pcap(knobs_all_down_pcap)
        up_events = analyze_type_pcap(knobs_all_up_pcap)

        def _group(events):
            by = {}
            for addr, payload in events:
                # value byte is last byte of payload
                v = int(payload[-2:], 16) if payload else None
                by.setdefault(addr, []).append((payload, v))
            return by

        down_by = _group(down_events)
        up_by = _group(up_events)

        # Each knob's address is derived from the FIRST address that
        # appears after its click. After phase 1 (up), knobs may all be
        # at max (no events from a knob that started at max). The down
        # phase forces every knob from max → min, so every knob produces
        # events. Use the down phase as the authoritative ordering.
        knob_addresses_in_order = []
        seen_addrs = set()
        for addr, payload in down_events:
            if addr not in seen_addrs:
                seen_addrs.add(addr)
                knob_addresses_in_order.append(addr)

        for ki, (kx, ky) in enumerate(knobs):
            addr = knob_addresses_in_order[ki] if ki < len(knob_addresses_in_order) else None
            if addr is None:
                knob_records.append({
                    "knob_idx": ki, "knob_x": kx, "knob_y": ky,
                    "address": None, "min": None, "max": None,
                    "n_dt1_down": 0, "n_dt1_up": 0,
                })
                continue
            d_vals = [v for _, v in down_by.get(addr, [])]
            u_vals = [v for _, v in up_by.get(addr, [])]
            all_vals = [v for v in d_vals + u_vals if v is not None]
            knob_records.append({
                "knob_idx": ki, "knob_x": kx, "knob_y": ky,
                "address": addr,
                "min": min(all_vals) if all_vals else None,
                "max": max(all_vals) if all_vals else None,
                "n_dt1_down": len(d_vals),
                "n_dt1_up": len(u_vals),
                "first_payload_down": down_by.get(addr, [(None,None)])[0][0],
            })
        print(f"  classified {len(knob_records)} knobs")
        for r in knob_records:
            print(f"    k{r['knob_idx']}: addr={r['address']} "
                  f"range={r['min']}-{r['max']} "
                  f"down={r['n_dt1_down']} up={r['n_dt1_up']}")

    summary = {
        "page": page, "idx": idx, "name": name, "color": color,
        "hex_x": hex_x, **drag_info,
        "has_type": has_type,
        "has_sp_type": has_sp,
        "type_address": type_addr,
        "type_max": type_max,
        "type_payloads": type_payloads,
        "sp_type_address": sp_type_addr,
        "sp_type_max": sp_type_max,
        "sp_type_payloads": sp_type_payloads,
        "knobs": knob_records,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2,
                                                     default=list))
    explored_flag.touch()
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-page", type=int, default=0)
    ap.add_argument("--end-page", type=int, default=2)
    ap.add_argument("--limit-per-page", type=int, default=None)
    ap.add_argument("--only-effect", help="run a single effect by name")
    ap.add_argument("--max-iters", type=int, default=60,
                    help="max popup steps per dropdown cycle")
    args = ap.parse_args()

    TYPEBAR_DIR.mkdir(parents=True, exist_ok=True)
    pages = [PAGE_0, PAGE_1, PAGE_2]
    restore_baseline()

    prev_name = ""
    all_records = []
    for page in range(args.start_page, args.end_page + 1):
        items = pages[page]
        if args.limit_per_page:
            items = items[:args.limit_per_page]
        for idx, (name, color) in enumerate(items):
            if args.only_effect and name != args.only_effect:
                continue
            hex_x = hex_x_pos(idx)
            print(f"\n=== page {page} idx {idx:2d} {name} ===")
            try:
                rec = explore_one_effect(page, idx, name, color, hex_x,
                                          prev_name=prev_name,
                                          max_iters=args.max_iters)
                if rec:
                    all_records.append(rec)
                    prev_name = name
                    if rec.get("has_type"):
                        print(f"    TYPE catalog: {rec['type_max']+1} entries "
                              f"@ {rec['type_address']}")
                    if rec.get("has_sp_type"):
                        print(f"    SP TYPE catalog: {rec['sp_type_max']+1} "
                              f"entries @ {rec['sp_type_address']}")
            except Exception as e:
                print(f"  ERROR: {e}")
                import traceback
                traceback.print_exc()

    (TYPEBAR_DIR / "all_effects_explored.json").write_text(
        json.dumps(all_records, indent=2, default=list))
    print(f"\n=== DONE: {len(all_records)} effects explored ===")


if __name__ == "__main__":
    main()
