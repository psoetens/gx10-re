"""Diagnose chain buttons WITH a non-empty patch loaded and a slot selected.

Hypothesis (from v1): the INSERT/DELETE/OVERWRITE buttons are disabled
when the chain is empty or no slot is selected. v1 diagnostic showed
all three buttons send zero MIDI on an EMPTY chain.

Test plan:
  1. Launch TS (kill + relaunch).
  2. Click into PRESET tab, then click on P02-1 JC CLEAN (or first
     PRESET row) — this loads a patch with effects in the chain.
  3. Click on the first chain hex slot to SELECT it.
  4. Re-run the same DELETE / INSERT / OVERWRITE click sequence.
  5. Compare: are buttons now enabled and emitting DT1?
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

BUTTONS = [
    ("DELETE",    582, 109),
    ("INSERT",    685, 109),
    ("OVERWRITE", 786, 109),
]


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

    pcap = OUT / "diag_v2.pcap"
    if pcap.exists():
        pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists():
        jsonl.unlink()

    cap = usbpcap_start(pcap)
    time.sleep(1.5)
    markers = []
    try:
        # 1. Click PRESET tab in left rail (deselects USER, shows PRESET list)
        print("Clicking PRESET tab...")
        click(56, 108)
        time.sleep(1.0)

        # 2. Click on the first preset row (P01-1 NATURAL AMP HB at y~145)
        print("Clicking P01-1 (NATURAL AMP HB)...")
        click(80, 145)
        time.sleep(2.5)
        take_screenshot(OUT / "v2_after_preset_load.png")

        # 3. Click on the first chain hex to select it
        # Slot 0 hex is at approximately (290, 312)
        print("Clicking slot 0 hex to SELECT it...")
        click(290, 312)
        time.sleep(1.0)
        take_screenshot(OUT / "v2_after_slot_select.png")

        # Now click the three buttons
        for name, x, y in BUTTONS:
            t_start = time.time()
            print(f"[{name}] clicking ({x}, {y})")
            click(x, y)
            time.sleep(2.0)
            take_screenshot(OUT / f"v2_after_{name}.png")
            markers.append((name, t_start))
            time.sleep(0.5)
        time.sleep(1.0)
    finally:
        usbpcap_stop(cap)

    # Convert pcap
    subprocess.run([sys.executable,
                    str(Path(__file__).parent / "pcap_to_jsonl.py"),
                    str(pcap), "--out", str(jsonl)], check=True)

    # Analyze
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
        host_writes = sum(1 for e in in_win if e["dir"] == "host->dev" and e["cmd"] == 0x12)
        host_reads = sum(1 for e in in_win if e["dir"] == "host->dev" and e["cmd"] == 0x11)
        dev_writes = sum(1 for e in in_win if e["dir"] == "dev->host" and e["cmd"] == 0x12)
        bucket = (
            "A: TS-silent" if host_writes == 0 and host_reads == 0
            else "B: TS-sends, dev-silent" if dev_writes == 0
            else "C: TS-sends, dev-replies"
        )
        print(f"  [{name}]  host_w={host_writes}  host_r={host_reads}  "
              f"dev_w={dev_writes}  -> {bucket}")
        for e in in_win[:6]:
            cn = {0x11: "RQ1", 0x12: "DT1"}.get(e["cmd"], hex(e["cmd"]))
            pl = e["payload"][:40]
            print(f"    {e['dir']:9s} {cn} 0x{e['addr']:08X} {pl}")


if __name__ == "__main__":
    main()
