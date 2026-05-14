"""
End-to-end mapper: for every effect across all 3 type-bar pages, drag it
onto chain slot 0 (with USBPcap recording), screenshot the result, then
sweep each knob with click+arrow keys to record:
  - the byte address Tone Studio writes for each knob
  - the min/max byte values (range)

State preserved between iterations:
  captures/typebar_full/index.json   - per-effect record
  captures/typebar_full/<page>/<idx>_<name>/
       drag.pcap     - the drag command sequence
       drag.png      - screenshot showing the loaded effect + knobs
       knob_<i>.pcap - per-knob arrow-sweep
       knob_<i>.json - {addr, min, max, value byte position}
       summary.json  - per-effect aggregate

The main loop is interruptible/resumable: if drag.pcap exists for an entry,
we skip its drag step. Same for knob_<i>.pcap.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image, ImageGrab
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from effect_catalog import PAGE_0, PAGE_1, PAGE_2, HEX_Y, SLOT0_X, SLOT0_Y
from find_hex_centers import find_hexes
import scroll_typebar

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0


# --- Win32 SendInput (low-level mouse) ----------------------------------
# Empirically the only mouse-injection mechanism that produces reliable
# drag-and-drop in Tone Studio. pyautogui (mouse_event API) and
# pyautogui.dragTo fail intermittently after the first successful drag.
_user32 = ctypes.windll.user32

_INPUT_MOUSE = 0
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send_input(flags, dx_screen=0, dy_screen=0):
    inp = _INPUT()
    inp.type = _INPUT_MOUSE
    inp.u.mi = _MOUSEINPUT(dx_screen, dy_screen, 0, flags, 0, None)
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _abs_screen(x_px, y_px):
    sw = _user32.GetSystemMetrics(0)
    sh = _user32.GetSystemMetrics(1)
    return int(x_px * 65535 / (sw - 1)), int(y_px * 65535 / (sh - 1))


def win32_move_to(x_px, y_px):
    ax, ay = _abs_screen(x_px, y_px)
    _send_input(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, ax, ay)


def win32_left_down():
    _send_input(_MOUSEEVENTF_LEFTDOWN)


def win32_left_up():
    _send_input(_MOUSEEVENTF_LEFTUP)

ROOT = Path(__file__).parent.parent
TYPEBAR_DIR = ROOT / "captures" / "typebar_full"


def usbpcap_start(out_pcap: Path):
    out_pcap.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [r"C:\Program Files\USBPcap\USBPcapCMD.exe",
         "-d", r"\\.\USBPcap1",
         "-o", str(out_pcap),
         "-A", "--inject-descriptors",
         "-b", "16777216",   # 16 MiB capture buffer (default 1 MiB)
         "-s", "65535"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def usbpcap_stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(0.3)


def take_screenshot(out: Path):
    hwnd = focus_ts.focus_tone_studio()
    rect = focus_ts.get_window_rect(hwnd)
    img = ImageGrab.grab(bbox=(max(0, rect[0]), max(0, rect[1]),
                               rect[2], rect[3]))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return img


def drag_effect(hex_x: int, slot_x: int = SLOT0_X, slot_y: int = SLOT0_Y):
    """Drag from (hex_x, HEX_Y) to (slot_x, slot_y) via a 3-segment path.

    Uses Win32 SendInput (low-level mouse). Empirically the only
    mechanism that drags reliably more than once in a row in Tone Studio.
    pyautogui (mouse_event-based) succeeds for the first drag, then fails
    on subsequent drags until TS is restarted.

    Path: hex -> down to y=240 (below the scroll bar) -> sideways ->
    down to slot. Avoids triggering accidental scroll-bar drag.
    """
    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.2)
    src_x, src_y = focus_ts.screen_xy(hwnd, hex_x, HEX_Y)
    mid1_x, mid1_y = focus_ts.screen_xy(hwnd, hex_x, 240)
    mid2_x, mid2_y = focus_ts.screen_xy(hwnd, slot_x, 240)
    dst_x, dst_y = focus_ts.screen_xy(hwnd, slot_x, slot_y)
    win32_move_to(src_x, src_y)
    time.sleep(0.3)
    win32_left_down()
    # Long hold: TS's drag-detect requires a sustained press before motion.
    time.sleep(1.5)
    for tx, ty in ((mid1_x, mid1_y), (mid2_x, mid2_y), (dst_x, dst_y)):
        win32_move_to(tx, ty)
        time.sleep(0.3)
    time.sleep(0.4)
    win32_left_up()
    time.sleep(1.5)


def clear_slot0():
    """Drag the effect currently at SLOT0 out of the chain. Used after
    DIV_MIX (the only effect that doesn't accept drag-over replacement)."""
    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.2)
    src_x, src_y = focus_ts.screen_xy(hwnd, SLOT0_X, SLOT0_Y)
    dst_x, dst_y = focus_ts.screen_xy(hwnd, SLOT0_X, 900)
    win32_move_to(src_x, src_y)
    time.sleep(0.3)
    win32_left_down()
    time.sleep(1.5)
    win32_move_to(dst_x, dst_y)
    time.sleep(0.6)
    win32_left_up()
    time.sleep(1.0)


def restore_baseline():
    """Kill TS, restore U10-1 INIT, relaunch TS, wait for handshake."""
    subprocess.run(["powershell", "-Command",
                    "Get-Process -Name 'BOSS TONE STUDIO for GX-10','msedgewebview2' -ErrorAction SilentlyContinue | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(2.5)
    subprocess.run(["python", str(Path(__file__).parent / "restore_snapshot.py"),
                    str(ROOT / "snapshots/u10-1_init.json"),
                    "--gap", "0.020"], capture_output=True, check=True)
    time.sleep(1.0)
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])
    time.sleep(11.0)
    focus_ts.maximize_tone_studio()
    time.sleep(0.5)


def detect_knobs(screenshot: Image.Image):
    """Find knob centers by detecting the white labels under each knob.

    Knob layout depends on whether the effect has a TYPE / SP TYPE row:
      - With TYPE row:    Row 1 knobs y=590 labels y=634, Row 2 y=710/755
      - Without TYPE row: Row 1 knobs y=540 labels y=585, Row 2 y=660/705

    We auto-detect which layout based on whether the TYPE label row at
    y=494 has white text. Then scan only the matching label rows so we
    don't pick up stray clusters between rows.
    """
    # Detect TYPE row
    has_type_row = False
    for x in range(230, 290):
        for y in range(488, 502):
            try:
                r, g, b = screenshot.getpixel((x, y))[:3]
            except Exception:
                continue
            if r > 180 and g > 180 and b > 180:
                has_type_row = True
                break
        if has_type_row:
            break

    if has_type_row:
        # Row 3 (HARM USER scale HR1) sits at y~830 with labels y~880.
        # Row 4 (HARM USER scale HR2 in 2 VOICE) at y~950 / labels y~1000.
        rows = ((590, 634), (710, 755), (830, 880), (950, 1000))
    else:
        rows = ((540, 585), (660, 705), (780, 830), (900, 950))

    knobs = []
    for knob_y, label_y in rows:
        # Scan label row for white pixel clusters.
        in_text = False
        starts = []
        ends = []
        for x in range(240, 1900):
            r, g, b = screenshot.getpixel((x, label_y))[:3]
            white = (r > 180 and g > 180 and b > 180)
            if white and not in_text:
                starts.append(x)
                in_text = True
            elif not white and in_text:
                ends.append(x - 1)
                in_text = False
        if in_text:
            ends.append(1900)
        # Each knob's label column contains MULTIPLE letter-clusters, but they
        # all fall within a ~100 px window centered on the knob. Group nearby
        # text clusters: any clusters within 110 px of each other belong to
        # the same knob's label.
        clusters = list(zip(starts, ends))
        if not clusters:
            continue
        groups = [[clusters[0]]]
        for s, e in clusters[1:]:
            last_e = groups[-1][-1][1]
            if s - last_e < 30:
                groups[-1].append((s, e))
            else:
                groups.append([(s, e)])
        for grp in groups:
            gx_min = grp[0][0]
            gx_max = grp[-1][1]
            cx = (gx_min + gx_max) // 2
            knobs.append((cx, knob_y))
    return knobs


def sweep_one_knob(knob_x, knob_y, out_pcap: Path, presses: int = 200,
                   gap: float = 0.020):
    """Click a knob then arrow up + down to find min/max byte range."""
    cap = usbpcap_start(out_pcap)
    time.sleep(0.8)
    try:
        hwnd = focus_ts.focus_tone_studio()
        time.sleep(0.2)
        sx, sy = focus_ts.screen_xy(hwnd, knob_x, knob_y)
        pyautogui.click(sx, sy)
        time.sleep(0.3)
        for _ in range(presses):
            pyautogui.press("down")
            time.sleep(gap)
        time.sleep(0.4)
        for _ in range(presses * 2):
            pyautogui.press("up")
            time.sleep(gap)
        time.sleep(0.6)
    finally:
        usbpcap_stop(cap)


def analyze_drag_pcap(pcap: Path) -> dict:
    """Extract type triplet at 0x10001100 from the drag DT1s."""
    jsonl = pcap.with_suffix(".jsonl")
    subprocess.run(["python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
                    str(pcap), "--out", str(jsonl)],
                   capture_output=True, check=True)
    triplet = None
    n_dt1 = 0
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if (ev.get("kind") != "sysex" or ev.get("dir") != "host->dev"):
                continue
            raw = bytes.fromhex(ev["hex"])
            if (len(raw) < 16 or raw[0] != 0xF0 or raw[-1] != 0xF7
                    or raw[8] != 0x12):
                continue
            n_dt1 += 1
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            if addr == 0x10001100 and len(payload) == 3:
                triplet = payload.hex().upper()
            elif addr == 0x10001100 and len(payload) == 1 and triplet is None:
                triplet = (payload + b"\x00\x00").hex().upper()
    return {"n_dt1": n_dt1, "triplet_at_10001100": triplet}


def analyze_knob_pcap(pcap: Path) -> dict:
    """Extract dominant DT1 address + value range."""
    jsonl = pcap.with_suffix(".jsonl")
    subprocess.run(["python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
                    str(pcap), "--out", str(jsonl)],
                   capture_output=True, check=True)
    by_addr = {}
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex" or ev.get("dir") != "host->dev":
                continue
            raw = bytes.fromhex(ev["hex"])
            if (len(raw) < 16 or raw[0] != 0xF0 or raw[-1] != 0xF7
                    or raw[8] != 0x12):
                continue
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            by_addr.setdefault(addr, []).append(payload)
    if not by_addr:
        return {"address": None, "n_dt1": 0}
    dom_addr = max(by_addr.keys(), key=lambda a: len(by_addr[a]))
    payloads = by_addr[dom_addr]
    values = [p[-1] for p in payloads]
    return {
        "address": f"{dom_addr:08X}",
        "first_payload": payloads[0].hex().upper(),
        "value_byte_offset": "last",
        "min": min(values),
        "max": max(values),
        "n_dt1": len(payloads),
    }


def process_one_effect(page: int, idx: int, name: str, color: tuple,
                        hex_x: int, knob_sweep: bool = True,
                        max_retries: int = 3, prev_name: str = ""):
    """Drag this effect onto slot 0, screenshot, sweep knobs. Skip if done.

    Retries on drag failure (no DT1 captured). Always re-scrolls and
    re-detects the hex position before each attempt.
    """
    out_dir = TYPEBAR_DIR / f"page{page}" / f"{idx:02d}_{name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    drag_pcap = out_dir / "drag.pcap"
    drag_png = out_dir / "drag.png"

    # If we already have a valid drag pcap, skip the drag step.
    def _drag_is_valid():
        if not drag_pcap.exists() or drag_pcap.stat().st_size < 4000:
            return False
        # Quick analysis: did it write to 0x10001100?
        info = analyze_drag_pcap(drag_pcap)
        return info.get("triplet_at_10001100") is not None

    # In knob_sweep mode the effect must be physically loaded in TS for
    # the knob clicks to address the right effect. If sweep hasn't been
    # done yet (no knob_done.flag), force a fresh drag.
    knob_done_flag = out_dir / "knob_done.flag"
    needs_load_for_sweep = knob_sweep and not knob_done_flag.exists()
    needs_drag = not _drag_is_valid() or needs_load_for_sweep

    if needs_drag:
        # DIV_MIX is the only effect that doesn't accept drag-over
        # replacement. If the previous effect was DIV_MIX, drag it out
        # of slot 0 first so this drag has a clean target.
        if prev_name == "DIV_MIX":
            clear_slot0()
        # Re-locate hex once (scroll + detect)
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

        if not _drag_is_valid():
            # First-time capture or recovery: record fresh pcap with retries.
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
                finally:
                    usbpcap_stop(cap)

                if _drag_is_valid():
                    break
                print(f"  retry {attempt+1}/{max_retries} for {name}")

            take_screenshot(drag_png)
        else:
            # Pcap already valid; just need the effect physically loaded
            # in TS for the knob sweep. Drag without recording.
            drag_effect(hex_x_actual, SLOT0_X, SLOT0_Y)

    # Analyze drag pcap
    drag_info = analyze_drag_pcap(drag_pcap)

    knobs_data = []
    if knob_sweep:
        # Detect knobs in screenshot
        img = Image.open(drag_png)
        knobs = detect_knobs(img)
        for ki, (kx, ky) in enumerate(knobs):
            knob_pcap = out_dir / f"knob_{ki:02d}_{kx}_{ky}.pcap"
            if not knob_pcap.exists() or knob_pcap.stat().st_size < 2000:
                sweep_one_knob(kx, ky, knob_pcap, presses=130, gap=0.020)
            info = analyze_knob_pcap(knob_pcap)
            info["knob_x"] = kx
            info["knob_y"] = ky
            knobs_data.append(info)
        # Mark sweep complete if every detected knob produced data
        if knobs and all(k.get("address") for k in knobs_data):
            knob_done_flag.touch()

    summary = {
        "page": page, "idx": idx, "name": name, "color": color,
        "hex_x": hex_x,
        **drag_info,
        "knobs": knobs_data,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-page", type=int, default=0)
    ap.add_argument("--end-page", type=int, default=2)
    ap.add_argument("--limit-per-page", type=int, default=None)
    ap.add_argument("--no-knobs", action="store_true",
                    help="only drag-capture, skip knob sweep (faster)")
    args = ap.parse_args()

    TYPEBAR_DIR.mkdir(parents=True, exist_ok=True)

    pages = [PAGE_0, PAGE_1, PAGE_2]
    restore_baseline()

    all_records = []
    prev_name = ""
    for page in range(args.start_page, args.end_page + 1):
        items = pages[page]
        if args.limit_per_page:
            items = items[:args.limit_per_page]
        for idx, (name, color) in enumerate(items):
            from effect_catalog import hex_x_pos
            hex_x = hex_x_pos(idx)
            print(f"\n=== page {page} idx {idx:2d} {name} ===")
            try:
                rec = process_one_effect(page, idx, name, color, hex_x,
                                         knob_sweep=not args.no_knobs,
                                         prev_name=prev_name)
                prev_name = name
                if rec:
                    all_records.append(rec)
                    print(f"  triplet: {rec.get('triplet_at_10001100')}")
                    if rec.get("knobs"):
                        for k in rec["knobs"]:
                            print(f"    knob {k.get('knob_x')},{k.get('knob_y')} -> "
                                  f"{k.get('address')}  range {k.get('min')}-{k.get('max')}")
            except Exception as e:
                print(f"  ERROR: {e}")

    (TYPEBAR_DIR / "all_effects.json").write_text(json.dumps(all_records, indent=2))
    print(f"\n=== DONE: {len(all_records)} effects mapped ===")


if __name__ == "__main__":
    main()
