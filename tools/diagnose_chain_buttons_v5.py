"""v5 — try a more 'human-like' click on action buttons:
  - move mouse via 8 intermediate waypoints (instead of teleport)
  - hover at target for 250ms before mousedown
  - hold mousedown for 200ms (instead of 80ms) so WebView2 registers
    the press cleanly
  - large post-up settle (1500ms)

Hypothesis: BTS WebView2 buttons might not register short instant clicks
from win32 SendInput; a slower, more deliberate click sequence with
mouse-movement before press could match what real users produce.

Also: avoid re-focusing TS between clicks (was happening in click()).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import pyautogui
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from map_all_effects import (usbpcap_start, usbpcap_stop, take_screenshot,
                             win32_move_to, win32_left_down, win32_left_up)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "chain_buttons"
OUT.mkdir(parents=True, exist_ok=True)


def smooth_move(hwnd, fx, fy, tx, ty, steps=8, total_ms=300):
    """Linear interpolated mouse move from window-local (fx,fy) to (tx,ty)
    over `total_ms` ms in `steps` increments."""
    delay = (total_ms / 1000.0) / steps
    sx0, sy0 = focus_ts.screen_xy(hwnd, fx, fy)
    sx1, sy1 = focus_ts.screen_xy(hwnd, tx, ty)
    for i in range(1, steps + 1):
        x = int(sx0 + (sx1 - sx0) * i / steps)
        y = int(sy0 + (sy1 - sy0) * i / steps)
        win32_move_to(x, y)
        time.sleep(delay)


def deliberate_click(hwnd, dx, dy, prev_xy=None, hold_ms=200, hover_ms=300):
    """Move smoothly to (dx,dy), hover, hold mousedown for hold_ms, release."""
    if prev_xy is None:
        prev_xy = (dx - 60, dy)  # arrive from the left
    smooth_move(hwnd, prev_xy[0], prev_xy[1], dx, dy, steps=8, total_ms=200)
    time.sleep(hover_ms / 1000.0)
    win32_left_down()
    time.sleep(hold_ms / 1000.0)
    win32_left_up()
    time.sleep(0.4)


def main():
    print("Launching BTS...")
    subprocess.run(["powershell", "-Command",
                    "Get-Process -Name 'BOSS TONE STUDIO for GX-10','msedgewebview2' "
                    "-ErrorAction SilentlyContinue | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(2.5)
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])
    time.sleep(11.0)
    hwnd = focus_ts.maximize_tone_studio()
    time.sleep(1.5)
    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.5)

    pcap = OUT / "diag_v5.pcap"
    if pcap.exists(): pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists(): jsonl.unlink()

    cap = usbpcap_start(pcap)
    time.sleep(1.5)
    markers = []

    BTN_DELETE = (582, 109)
    BTN_INSERT = (685, 109)
    BTN_OVERWRITE = (786, 109)
    TYPEBAR_COMP = (255, 155)
    CHAIN_SLOT0 = (290, 312)

    try:
        # Switch to PRESET tab
        deliberate_click(hwnd, 56, 108); time.sleep(0.8)
        # Load first preset
        deliberate_click(hwnd, 80, 145); time.sleep(2.5)
        take_screenshot(OUT / "v5_00_baseline.png")

        # ===== PHASE A =====
        print("\n=== PHASE A: typebar->INSERT ===")
        print(f"  click typebar COMP {TYPEBAR_COMP}")
        deliberate_click(hwnd, *TYPEBAR_COMP); time.sleep(1.0)
        take_screenshot(OUT / "v5_01_after_typebar.png")

        # Now INSERT — using deliberate click w/ hover
        t = time.time()
        print(f"  click INSERT {BTN_INSERT}")
        deliberate_click(hwnd, *BTN_INSERT,
                         prev_xy=TYPEBAR_COMP,
                         hold_ms=200, hover_ms=300)
        markers.append(("INSERT_v5", t))
        time.sleep(2.5)
        take_screenshot(OUT / "v5_02_after_INSERT.png")

        # Re-arm typebar then OVERWRITE
        print(f"  click typebar COMP again {TYPEBAR_COMP}")
        deliberate_click(hwnd, *TYPEBAR_COMP); time.sleep(1.0)
        t = time.time()
        print(f"  click OVERWRITE {BTN_OVERWRITE}")
        deliberate_click(hwnd, *BTN_OVERWRITE,
                         prev_xy=TYPEBAR_COMP,
                         hold_ms=200, hover_ms=300)
        markers.append(("OVERWRITE_v5", t))
        time.sleep(2.5)
        take_screenshot(OUT / "v5_03_after_OVERWRITE.png")

        # ===== PHASE B =====
        print("\n=== PHASE B: chain->DELETE ===")
        # Reload preset to reset
        deliberate_click(hwnd, 80, 145); time.sleep(2.5)
        print(f"  click chain slot0 {CHAIN_SLOT0}")
        deliberate_click(hwnd, *CHAIN_SLOT0); time.sleep(1.0)
        take_screenshot(OUT / "v5_04_after_chain.png")

        t = time.time()
        print(f"  click DELETE {BTN_DELETE}")
        deliberate_click(hwnd, *BTN_DELETE,
                         prev_xy=CHAIN_SLOT0,
                         hold_ms=200, hover_ms=300)
        markers.append(("DELETE_v5", t))
        time.sleep(2.5)
        take_screenshot(OUT / "v5_05_after_DELETE.png")
    finally:
        usbpcap_stop(cap)

    subprocess.run([sys.executable,
                    str(Path(__file__).parent / "pcap_to_jsonl.py"),
                    str(pcap), "--out", str(jsonl)], check=True)

    events = []
    with jsonl.open() as f:
        for line in f:
            try: ev = json.loads(line)
            except Exception: continue
            if ev.get("kind") != "sysex": continue
            raw = bytes.fromhex(ev["hex"])
            if len(raw) < 14: continue
            cmd = raw[8]
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            events.append({"ts": ev.get("ts", 0), "dir": ev.get("dir"),
                           "cmd": cmd, "addr": addr,
                           "payload": payload.hex().upper()})

    print(f"\n=== USBPcap summary ({len(events)} sysex events) ===")
    for name, t_click in markers:
        in_win = [e for e in events if t_click <= e["ts"] <= t_click + 4.0]
        host_w = sum(1 for e in in_win if e["dir"] == "host->dev" and e["cmd"] == 0x12)
        host_r = sum(1 for e in in_win if e["dir"] == "host->dev" and e["cmd"] == 0x11)
        dev_w = sum(1 for e in in_win if e["dir"] == "dev->host" and e["cmd"] == 0x12)
        bucket = ("A: TS-silent" if host_w == 0 and host_r == 0
                  else "B: TS-sends, dev-silent" if dev_w == 0
                  else "C: TS-sends, dev-replies")
        print(f"  [{name:18s}]  host_w={host_w:3d}  host_r={host_r:3d}  "
              f"dev_w={dev_w:3d}  -> {bucket}")
        for e in in_win[:6]:
            cn = {0x11: "RQ1", 0x12: "DT1"}.get(e["cmd"], hex(e["cmd"]))
            pl = e["payload"][:40]
            print(f"    {e['dir']:9s} {cn} 0x{e['addr']:08X} {pl}")


if __name__ == "__main__":
    main()
