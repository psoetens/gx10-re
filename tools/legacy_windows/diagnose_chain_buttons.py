"""Diagnose why INSERT / DELETE / OVERWRITE buttons stopped working in BTS.

Strategy:
  1. Start USBPcap capture.
  2. Pause 1 s for baseline.
  3. Click DELETE button at (582, 109). Wait 2 s.
  4. Click INSERT button at (685, 109). Wait 2 s.
  5. Click OVERWRITE button at (786, 109). Wait 2 s.
  6. Stop capture.
  7. Decode and classify each click:
     - host emits DT1/RQ1 / silence?
     - device replies / silence / NACK?

Outcome buckets:
  A) TS sends nothing → client-side state issue (TS thinks the button
     is disabled, or input handler is broken). Common causes: focus,
     disabled state due to no chain selection, BTS internal bug.
  B) TS sends, device doesn't reply → device firmware glitch or
     the device is in a weird state.
  C) TS sends, device replies normally → buttons ARE working at the
     wire level; user perception bug, or display didn't update.

Notes for the run:
  - It's important the EDITOR view is active before running.
  - We don't drop or restore the patch — keep current state.
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


def capture_with_markers():
    pcap = OUT / "diag.pcap"
    if pcap.exists():
        pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists():
        jsonl.unlink()

    cap = usbpcap_start(pcap)
    time.sleep(1.5)
    markers = []
    try:
        # Baseline screenshot before any clicks
        take_screenshot(OUT / "before.png")
        time.sleep(0.5)

        for name, x, y in BUTTONS:
            t_start = time.time()
            print(f"[{name}] clicking ({x}, {y})")
            click(x, y)
            time.sleep(2.0)
            take_screenshot(OUT / f"after_{name}.png")
            markers.append((name, t_start))
            time.sleep(0.5)
        time.sleep(1.0)
    finally:
        usbpcap_stop(cap)

    # Convert pcap to jsonl
    subprocess.run([
        sys.executable,
        str(Path(__file__).parent / "pcap_to_jsonl.py"),
        str(pcap),
        "--out", str(jsonl)
    ], check=True)

    return pcap, jsonl, markers


def analyze(jsonl: Path, markers):
    # Read events with timestamps
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

    print(f"\nTotal sysex events captured: {len(events)}")
    # Bucket events into per-button windows. The pcap timestamps are
    # epoch-relative; markers are also epoch (time.time()). Use a 4 s
    # window starting at each click.
    print("\nPer-button activity:")
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
        print(f"  [{name}]  host_writes={host_writes}  host_reads={host_reads}  "
              f"dev_writes={dev_writes}  -> {bucket}")
        # Show first few events
        for e in in_win[:8]:
            cn = {0x11: "RQ1", 0x12: "DT1"}.get(e["cmd"], hex(e["cmd"]))
            pl = e["payload"][:40]
            print(f"    {e['dir']:9s} {cn} 0x{e['addr']:08X} {pl}")


def main():
    # Launch TS without snapshot restore — we want to test the BTS bug
    # in its current state, not after restoring a patch.
    import subprocess
    print("Killing existing TS and re-launching...")
    subprocess.run(["powershell", "-Command",
                    "Get-Process -Name 'BOSS TONE STUDIO for GX-10','msedgewebview2' "
                    "-ErrorAction SilentlyContinue | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(2.5)
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])
    time.sleep(11.0)
    focus_ts.maximize_tone_studio()
    time.sleep(1.0)

    print("Diagnostic running...")
    pcap, jsonl, markers = capture_with_markers()
    analyze(jsonl, markers)
    print(f"\npcap: {pcap}")
    print(f"jsonl: {jsonl}")
    print(f"\nReview screenshots: before.png, after_DELETE.png, after_INSERT.png, after_OVERWRITE.png")


if __name__ == "__main__":
    main()
