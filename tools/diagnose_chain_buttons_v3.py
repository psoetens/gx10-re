"""Diagnose chain buttons with the right pre-conditions per user clarification.

Test plan:
  PHASE A: TYPEBAR-effect selection (enables INSERT, OVERWRITE)
    1. Launch TS, load a preset that has chain effects
    2. Click on a TYPEBAR hex (e.g. COMP at top of editor) — selects an
       effect in the typebar
    3. Click INSERT, OVERWRITE — should now emit DT1
    4. Click DELETE — should NOT emit (no chain selection yet)

  PHASE B: CHAIN-slot selection (enables DELETE)
    5. Click on a CHAIN hex that has an effect (not a `+` placeholder)
    6. Click DELETE — should now emit DT1

For the typebar click, COMP is at approximately (255, 155).
For the chain hex click, slot 0 (with effect) is at approximately
(290, 312) — but the patch must have an effect in slot 0.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
from map_all_effects import (usbpcap_start, usbpcap_stop, take_screenshot)
from explore_all_effects import click

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "chain_buttons"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    print("Killing existing TS and re-launching...")
    subprocess.run(["powershell", "-Command",
                    "Get-Process -Name 'BOSS TONE STUDIO for GX-10','msedgewebview2' "
                    "-ErrorAction SilentlyContinue | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(2.5)
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])
    time.sleep(11.0)
    focus_ts.maximize_tone_studio()
    time.sleep(1.5)

    pcap = OUT / "diag_v3.pcap"
    if pcap.exists():
        pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists():
        jsonl.unlink()

    cap = usbpcap_start(pcap)
    time.sleep(1.5)
    markers = []
    try:
        # Switch to PRESET tab
        click(56, 108); time.sleep(0.8)

        # Load P01-1 NATURAL AMP HB (a populated factory patch)
        print("Loading P01-1 NATURAL AMP HB...")
        click(80, 145); time.sleep(2.5)
        take_screenshot(OUT / "v3_after_preset_load.png")

        # ===== PHASE A: TYPEBAR selection → INSERT / OVERWRITE =====
        # Click on COMP in the typebar at approximately (255, 155)
        print("\n=== PHASE A: typebar selection (for INSERT/OVERWRITE) ===")
        print("Clicking COMP in typebar at (255, 155)...")
        click(255, 155); time.sleep(1.0)
        take_screenshot(OUT / "v3_after_typebar_select.png")

        for name, x, y in [("INSERT_typebar", 685, 109),
                            ("OVERWRITE_typebar", 786, 109)]:
            t = time.time()
            print(f"[{name}] click ({x},{y})")
            click(x, y); time.sleep(2.5)
            take_screenshot(OUT / f"v3_after_{name}.png")
            markers.append((name, t))
            time.sleep(0.5)

        # ===== PHASE B: CHAIN-slot selection → DELETE =====
        print("\n=== PHASE B: chain slot selection (for DELETE) ===")
        # Reload patch to undo any inserts that happened
        print("Reload preset P01-1 to reset chain...")
        click(80, 145); time.sleep(2.5)
        # Click on slot 0 (chain hex with an effect)
        print("Clicking chain slot 0 at (290, 312)...")
        click(290, 312); time.sleep(1.0)
        take_screenshot(OUT / "v3_after_chain_select.png")

        for name, x, y in [("DELETE_chain", 582, 109)]:
            t = time.time()
            print(f"[{name}] click ({x},{y})")
            click(x, y); time.sleep(2.5)
            take_screenshot(OUT / f"v3_after_{name}.png")
            markers.append((name, t))
            time.sleep(0.5)

        time.sleep(1.0)
    finally:
        usbpcap_stop(cap)

    # Convert + analyze
    subprocess.run([sys.executable,
                    str(Path(__file__).parent / "pcap_to_jsonl.py"),
                    str(pcap), "--out", str(jsonl)], check=True)

    events = []
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex":
                continue
            raw = bytes.fromhex(ev["hex"])
            if len(raw) < 14:
                continue
            cmd = raw[8] if len(raw) > 8 else 0
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            events.append({
                "ts": ev.get("ts", 0),
                "dir": ev.get("dir"),
                "cmd": cmd,
                "addr": addr,
                "payload": payload.hex().upper(),
            })

    print(f"\nTotal sysex events: {len(events)}")
    for name, t_click in markers:
        in_win = [e for e in events if t_click <= e["ts"] <= t_click + 4.0]
        host_w = sum(1 for e in in_win if e["dir"] == "host->dev" and e["cmd"] == 0x12)
        host_r = sum(1 for e in in_win if e["dir"] == "host->dev" and e["cmd"] == 0x11)
        dev_w = sum(1 for e in in_win if e["dir"] == "dev->host" and e["cmd"] == 0x12)
        bucket = (
            "A: TS-silent" if host_w == 0 and host_r == 0
            else "B: TS-sends, dev-silent" if dev_w == 0
            else "C: TS-sends, dev-replies"
        )
        print(f"  [{name:20s}]  host_w={host_w:3d}  host_r={host_r:3d}  "
              f"dev_w={dev_w:3d}  -> {bucket}")
        for e in in_win[:8]:
            cn = {0x11: "RQ1", 0x12: "DT1"}.get(e["cmd"], hex(e["cmd"]))
            pl = e["payload"][:40]
            print(f"    {e['dir']:9s} {cn} 0x{e['addr']:08X} {pl}")


if __name__ == "__main__":
    main()
