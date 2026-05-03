"""v4 — verify exact click coords by overlaying markers on screenshots,
and explicitly probe button-enable state before/after each interaction.

Strategy:
  1. Launch TS, load preset.
  2. Take a clean baseline screenshot.
  3. Detect INSERT/DELETE/OVERWRITE button locations by scanning for
     bright "DELETE" / "INSERT" / "OVERWRITE" text glyphs in the top
     button row — record both their centers AND their enabled/disabled
     state (enabled = bright white text, disabled = grey text).
  4. PHASE A: typebar selection
     - Click on a typebar effect (try multiple coords if first fails).
     - Re-screenshot. Verify INSERT/OVERWRITE switch from disabled→enabled.
     - With USBPcap running, click INSERT. Verify chain hexes changed.
  5. PHASE B: chain selection
     - Click on a chain hex with an effect.
     - Re-screenshot. Verify DELETE switches from disabled→enabled.
     - With USBPcap running, click DELETE. Verify chain shortened.

Also overlay red dots on a debug copy of every screenshot at every
click coord, so we can visually confirm the click landed where intended.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import pyautogui
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from map_all_effects import (usbpcap_start, usbpcap_stop, take_screenshot)
from explore_all_effects import click

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "chain_buttons"
OUT.mkdir(parents=True, exist_ok=True)


def mark_clicks(src: Path, dest: Path, points, labels=None):
    """Copy src to dest with red circles at each click point."""
    img = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(img)
    for i, (x, y) in enumerate(points):
        # Red circle, radius 12, with white outer ring
        draw.ellipse((x - 14, y - 14, x + 14, y + 14), outline="white", width=3)
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), outline="red", width=3)
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill="red")
        if labels:
            draw.text((x + 16, y - 8), str(labels[i]), fill="yellow")
    img.save(dest)


def sample_color(img: Image.Image, x: int, y: int, n: int = 3):
    """Get average RGB in an n×n box around (x, y)."""
    pix = img.load()
    rs, gs, bs, c = 0, 0, 0, 0
    for dy in range(-n, n + 1):
        for dx in range(-n, n + 1):
            xx, yy = x + dx, y + dy
            if 0 <= xx < img.width and 0 <= yy < img.height:
                p = pix[xx, yy]
                rs += p[0]; gs += p[1]; bs += p[2]; c += 1
    return (rs // c, gs // c, bs // c)


def button_state(img: Image.Image, x: int, y: int):
    """Returns 'enabled' (white text >200) or 'disabled' (grey ~110) by
    sampling the button text region."""
    r, g, b = sample_color(img, x, y, n=8)
    avg = (r + g + b) / 3
    if avg > 180:
        return "enabled", avg
    if avg < 130:
        return "disabled", avg
    return "ambiguous", avg


def main():
    print("Launching BTS...")
    subprocess.run(["powershell", "-Command",
                    "Get-Process -Name 'BOSS TONE STUDIO for GX-10','msedgewebview2' "
                    "-ErrorAction SilentlyContinue | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(2.5)
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])
    time.sleep(11.0)
    focus_ts.maximize_tone_studio()
    time.sleep(1.5)

    pcap = OUT / "diag_v4.pcap"
    if pcap.exists(): pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists(): jsonl.unlink()

    cap = usbpcap_start(pcap)
    time.sleep(1.5)
    markers = []

    # Coords (window-local). Buttons should be at y=109 area.
    # From v3 analysis we know:
    BTN_DELETE = (582, 109)
    BTN_INSERT = (685, 109)
    BTN_OVERWRITE = (786, 109)
    # Typebar effects: try COMP at left of typebar at y~155
    TYPEBAR_COMP = (255, 155)
    # Chain hex slot 0: confirmed from screenshot at ~(290, 312)
    CHAIN_SLOT0 = (290, 312)

    try:
        # Switch to PRESET tab
        click(56, 108); time.sleep(0.8)
        # Load first preset
        click(80, 145); time.sleep(2.5)
        baseline = OUT / "v4_00_baseline.png"
        take_screenshot(baseline)
        # Mark button locations on the baseline
        mark_clicks(baseline, OUT / "v4_00_baseline_marked.png",
                    [BTN_DELETE, BTN_INSERT, BTN_OVERWRITE,
                     TYPEBAR_COMP, CHAIN_SLOT0],
                    ["DEL", "INS", "OVR", "tb-COMP", "chain0"])

        img = Image.open(baseline)
        for label, (x, y) in [("DELETE", BTN_DELETE),
                              ("INSERT", BTN_INSERT),
                              ("OVERWRITE", BTN_OVERWRITE)]:
            s, avg = button_state(img, x, y)
            print(f"  baseline {label:10s} state={s}  avg={avg:.1f}")

        # ===== PHASE A: typebar select =====
        print("\n=== PHASE A ===")
        print(f"Click typebar at {TYPEBAR_COMP}...")
        click(*TYPEBAR_COMP); time.sleep(1.2)
        sel_a = OUT / "v4_01_after_typebar.png"
        take_screenshot(sel_a)
        mark_clicks(sel_a, OUT / "v4_01_after_typebar_marked.png",
                    [BTN_DELETE, BTN_INSERT, BTN_OVERWRITE, TYPEBAR_COMP],
                    ["DEL", "INS", "OVR", "click"])
        img = Image.open(sel_a)
        for label, (x, y) in [("DELETE", BTN_DELETE),
                              ("INSERT", BTN_INSERT),
                              ("OVERWRITE", BTN_OVERWRITE)]:
            s, avg = button_state(img, x, y)
            print(f"  after-typebar {label:10s} state={s}  avg={avg:.1f}")

        # Now click INSERT
        t = time.time()
        print(f"\nClick INSERT at {BTN_INSERT}...")
        click(*BTN_INSERT); time.sleep(2.5)
        take_screenshot(OUT / "v4_02_after_INSERT.png")
        markers.append(("INSERT_after_typebar", t))
        time.sleep(0.5)

        # Click OVERWRITE
        t = time.time()
        print(f"Click OVERWRITE at {BTN_OVERWRITE}...")
        click(*BTN_OVERWRITE); time.sleep(2.5)
        take_screenshot(OUT / "v4_03_after_OVERWRITE.png")
        markers.append(("OVERWRITE_after_typebar", t))
        time.sleep(0.5)

        # ===== PHASE B: chain select =====
        # Reload preset to clear state
        print("\n=== PHASE B ===")
        click(80, 145); time.sleep(2.5)
        print(f"Click chain slot at {CHAIN_SLOT0}...")
        click(*CHAIN_SLOT0); time.sleep(1.2)
        sel_b = OUT / "v4_04_after_chain.png"
        take_screenshot(sel_b)
        mark_clicks(sel_b, OUT / "v4_04_after_chain_marked.png",
                    [BTN_DELETE, BTN_INSERT, BTN_OVERWRITE, CHAIN_SLOT0],
                    ["DEL", "INS", "OVR", "click"])
        img = Image.open(sel_b)
        for label, (x, y) in [("DELETE", BTN_DELETE),
                              ("INSERT", BTN_INSERT),
                              ("OVERWRITE", BTN_OVERWRITE)]:
            s, avg = button_state(img, x, y)
            print(f"  after-chain {label:10s} state={s}  avg={avg:.1f}")

        t = time.time()
        print(f"\nClick DELETE at {BTN_DELETE}...")
        click(*BTN_DELETE); time.sleep(2.5)
        take_screenshot(OUT / "v4_05_after_DELETE.png")
        markers.append(("DELETE_after_chain", t))
        time.sleep(0.5)

        time.sleep(1.0)
    finally:
        usbpcap_stop(cap)

    # Convert and analyze
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
        print(f"  [{name:25s}]  host_w={host_w:3d}  host_r={host_r:3d}  "
              f"dev_w={dev_w:3d}  -> {bucket}")
        for e in in_win[:6]:
            cn = {0x11: "RQ1", 0x12: "DT1"}.get(e["cmd"], hex(e["cmd"]))
            pl = e["payload"][:40]
            print(f"    {e['dir']:9s} {cn} 0x{e['addr']:08X} {pl}")


if __name__ == "__main__":
    main()
