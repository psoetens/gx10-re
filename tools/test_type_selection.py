"""Focused test for TYPE / SP TYPE dropdown selection.

Per user observation: click on the TYPE dropdown opens a popup; arrows up/down
navigate (without committing); Enter commits the highlighted item and emits
the DT1 to the device. SP TYPE behaves the same way.

This script:
  1. Loads AMP (or argv[1]) into slot 0 (relies on existing drag.pcap or
     re-drags from typebar).
  2. Records USBPcap while it cycles every TYPE value 0..N via:
        click → home → N arrows-down → Enter
  3. Prints which DT1s were observed for each TYPE value.

Outputs:
  captures/type_test/<effect>/probe_type.pcap
  captures/type_test/<effect>/probe_sp_type.pcap (if SP TYPE present)
  captures/type_test/<effect>/log.txt
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
from map_all_effects import (usbpcap_start, usbpcap_stop, drag_effect,
                             restore_baseline, take_screenshot)
from effect_catalog import (PAGE_0, PAGE_1, PAGE_2, HEX_Y,
                             SLOT0_X, SLOT0_Y, hex_x_pos)
from find_hex_centers import find_hexes
import scroll_typebar

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
TYPEBAR_DIR = ROOT / "captures" / "typebar_full"
OUT_DIR = ROOT / "captures" / "type_test"

TYPE_DROPDOWN_X = 350
TYPE_DROPDOWN_Y = 494
SP_TYPE_DROPDOWN_X = 720
SP_TYPE_DROPDOWN_Y = 494


def click(dx: int, dy: int):
    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.15)
    sx, sy = focus_ts.screen_xy(hwnd, dx, dy)
    pyautogui.click(sx, sy)
    time.sleep(0.45)


def reset_to_min(dx: int, dy: int):
    """Open popup, press Home, Enter — sets value to 0."""
    click(dx, dy)
    pyautogui.press("home")
    time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(0.5)


def step_to_next(dx: int, dy: int):
    """Open popup, press Down once (popup remembers current position),
    Enter — advances current value by 1."""
    click(dx, dy)
    pyautogui.press("down")
    time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(0.4)


def discover_max(dx: int, dy: int):
    """Open popup, End, Enter — commits max value."""
    click(dx, dy)
    pyautogui.press("end")
    time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(0.5)


def find_effect_in_catalog(name: str):
    for page_idx, lst in enumerate([PAGE_0, PAGE_1, PAGE_2]):
        for idx, (n, color) in enumerate(lst):
            if n == name:
                return page_idx, idx, color
    return None


def load_effect(page: int, idx: int):
    """Drag the effect at (page, idx) onto slot 0 in TS."""
    scroll_typebar.scroll_to_page(page)
    time.sleep(0.5)
    hwnd = focus_ts.focus_tone_studio()
    rect = focus_ts.get_window_rect(hwnd)
    tmp_img = ImageGrab.grab(bbox=(max(0, rect[0]), max(0, rect[1]),
                                   rect[2], rect[3]))
    tmp_path = OUT_DIR / "_pre.png"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_img.save(tmp_path, "PNG")
    centers, _ = find_hexes(str(tmp_path))
    if idx >= len(centers):
        raise RuntimeError(f"only {len(centers)} hexes found")
    drag_effect(centers[idx], SLOT0_X, SLOT0_Y)
    time.sleep(1.0)


def analyze(pcap: Path):
    """Return list of (addr_hex, value) for every host->dev DT1."""
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


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "AMP"
    max_to_test = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    found = find_effect_in_catalog(name)
    if not found:
        print(f"effect {name} not in catalog")
        return
    page, idx, color = found
    eff_dir = OUT_DIR / name
    eff_dir.mkdir(parents=True, exist_ok=True)

    log_lines = []
    def log(s):
        print(s)
        log_lines.append(s)

    log(f"=== {name} (page {page}, idx {idx}) ===")
    restore_baseline()
    load_effect(page, idx)

    # Take a snapshot of the loaded effect before probing.
    take_screenshot(eff_dir / "loaded.png")

    # Cycle TYPE via popup, screenshot at each step AND record USBPcap
    # so we can map popup-index → byte value via captured DT1.
    TYPE_TEXT_CROP = (290, 480, 540, 510)
    SP_TYPE_TEXT_CROP = (600, 480, 770, 510)

    def text_hash(im):
        return im.crop(TYPE_TEXT_CROP).tobytes()

    def text_hash_sp(im):
        return im.crop(SP_TYPE_TEXT_CROP).tobytes()

    type_pcap = eff_dir / "probe_type.pcap"
    cap = usbpcap_start(type_pcap)
    time.sleep(1.0)
    try:
        log(f"  reset TYPE to 0...")
        reset_to_min(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)
        take_screenshot(eff_dir / "type_00.png")
        prev_hash = text_hash(Image.open(eff_dir / "type_00.png"))
        seen_hashes = {prev_hash: 0}
        max_value = 0

        for tv in range(1, max_to_test + 1):
            log(f"  step -> TYPE={tv}")
            step_to_next(TYPE_DROPDOWN_X, TYPE_DROPDOWN_Y)
            png = eff_dir / f"type_{tv:02d}.png"
            take_screenshot(png)
            h = text_hash(Image.open(png))
            if h in seen_hashes:
                prev = seen_hashes[h]
                log(f"    -> hash matches TYPE={prev} (wrap or clamp). max={tv-1}")
                max_value = tv - 1
                break
            seen_hashes[h] = tv
            max_value = tv
            prev_hash = h
        else:
            log(f"  reached max_to_test ({max_to_test}) without wrap; treating as max")
    finally:
        usbpcap_stop(cap)

    log(f"\n  TYPE max value detected: {max_value} (= {max_value+1} TYPE entries)")

    # Analyze captured DT1s — group by address
    events = analyze(type_pcap)
    log(f"  captured {len(events)} DT1s during TYPE cycling")
    by_addr = {}
    for addr, val in events:
        by_addr.setdefault(addr, []).append(val)
    for addr in sorted(by_addr):
        log(f"  addr {addr}: {len(by_addr[addr])} writes, first 3 payloads: {by_addr[addr][:3]}")

    # Now cycle SP TYPE if present (still on AMP)
    sp_pcap = eff_dir / "probe_sp_type.pcap"
    cap = usbpcap_start(sp_pcap)
    time.sleep(1.0)
    try:
        log(f"\n  reset SP TYPE to 0...")
        reset_to_min(SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y)
        take_screenshot(eff_dir / "sp_type_00.png")
        prev_h = text_hash_sp(Image.open(eff_dir / "sp_type_00.png"))
        seen = {prev_h: 0}
        sp_max = 0
        for tv in range(1, max_to_test + 1):
            log(f"  step -> SP TYPE={tv}")
            step_to_next(SP_TYPE_DROPDOWN_X, SP_TYPE_DROPDOWN_Y)
            png = eff_dir / f"sp_type_{tv:02d}.png"
            take_screenshot(png)
            h = text_hash_sp(Image.open(png))
            if h in seen:
                prev = seen[h]
                log(f"    -> hash matches SP TYPE={prev}. max={tv-1}")
                sp_max = tv - 1
                break
            seen[h] = tv
            sp_max = tv
            prev_h = h
    finally:
        usbpcap_stop(cap)
    log(f"  SP TYPE max value detected: {sp_max} (= {sp_max+1} entries)")
    sp_events = analyze(sp_pcap)
    log(f"  captured {len(sp_events)} DT1s during SP TYPE cycling")
    sp_by_addr = {}
    for addr, val in sp_events:
        sp_by_addr.setdefault(addr, []).append(val)
    for addr in sorted(sp_by_addr):
        log(f"  addr {addr}: {len(sp_by_addr[addr])} writes, first 3: {sp_by_addr[addr][:3]}")

    # Save log
    (eff_dir / "log.txt").write_text("\n".join(log_lines), encoding="utf-8")


if __name__ == "__main__":
    main()
