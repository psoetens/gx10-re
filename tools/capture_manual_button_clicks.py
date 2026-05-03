"""Run a USBPcap capture with countdown prompts so the user can manually
click each button (DELETE/INSERT/OVERWRITE) — bypassing the question of
whether synthesized win32 clicks are reaching BTS.

Run as:
    python tools/capture_manual_button_clicks.py

The script does NOT click anything itself. It only:
  1. Starts a USBPcap capture
  2. Prompts the user with timed instructions
  3. Records timestamps of when each prompt was issued (= click marker)
  4. Stops capture and analyzes per-marker windows

This isolates "does BTS emit MIDI when buttons are clicked" from "do my
synthesized clicks reach the buttons".
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))

sys.path.insert(0, str(Path(__file__).parent))
from map_all_effects import (usbpcap_start, usbpcap_stop)

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "chain_buttons"
OUT.mkdir(parents=True, exist_ok=True)


def prompt(seconds: int, msg: str):
    print(f"\n>>> {msg}")
    for s in range(seconds, 0, -1):
        print(f"    ... {s}s", end="\r", flush=True)
        time.sleep(1)
    print(" " * 40, end="\r")


def main():
    pcap = OUT / "manual.pcap"
    if pcap.exists(): pcap.unlink()
    jsonl = pcap.with_suffix(".jsonl")
    if jsonl.exists(): jsonl.unlink()

    print("Make sure BTS is open with a populated preset loaded.")
    print("This script will prompt you to click each button.")
    print("Each prompt window is 8 seconds.\n")
    time.sleep(2)

    cap = usbpcap_start(pcap)
    time.sleep(1.5)
    markers = []
    try:
        # Phase A: typebar selection enables INSERT/OVERWRITE
        prompt(6, "Click an effect on the TYPEBAR (top row of small hexes), e.g. COMP")
        markers.append(("typebar_select", time.time()))

        prompt(8, "Now click the INSERT button (top row, second from left)")
        markers.append(("INSERT_click", time.time()))

        prompt(8, "Now click an effect on the TYPEBAR again to re-arm")
        markers.append(("typebar_reselect", time.time()))

        prompt(8, "Now click the OVERWRITE button")
        markers.append(("OVERWRITE_click", time.time()))

        # Phase B: chain selection enables DELETE
        prompt(6, "Now click an effect in the CHAIN (the row of larger named hexes)")
        markers.append(("chain_select", time.time()))

        prompt(8, "Now click the DELETE button")
        markers.append(("DELETE_click", time.time()))

        prompt(2, "Done — stopping capture")
    finally:
        usbpcap_stop(cap)

    # Convert pcap
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
        in_win = [e for e in events if t_click - 0.5 <= e["ts"] <= t_click + 6.0]
        host_w = sum(1 for e in in_win if e["dir"] == "host->dev" and e["cmd"] == 0x12)
        host_r = sum(1 for e in in_win if e["dir"] == "host->dev" and e["cmd"] == 0x11)
        dev_w = sum(1 for e in in_win if e["dir"] == "dev->host" and e["cmd"] == 0x12)
        bucket = ("A: TS-silent" if host_w == 0 and host_r == 0
                  else "B: TS-sends, dev-silent" if dev_w == 0
                  else "C: TS-sends, dev-replies")
        print(f"  [{name:20s}]  host_w={host_w:3d}  host_r={host_r:3d}  "
              f"dev_w={dev_w:3d}  -> {bucket}")
        for e in in_win[:8]:
            cn = {0x11: "RQ1", 0x12: "DT1"}.get(e["cmd"], hex(e["cmd"]))
            pl = e["payload"][:40]
            print(f"    {e['dir']:9s} {cn} 0x{e['addr']:08X} {pl}")


if __name__ == "__main__":
    main()
