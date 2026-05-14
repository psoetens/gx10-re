"""
For each effect already drag-captured under captures/typebar_full/<page>/<idx>_<name>,
load that effect into slot 0 (by replaying its drag.pcap), then for each
detected knob, click + arrow-sweep + capture USBPcap. Save per-knob analysis.

This is the second pass after map_all_effects.py --no-knobs.

Resumable: skips effects whose summary has knob data already.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image, ImageGrab
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
import midi_send

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

ROOT = Path(__file__).parent.parent
TYPEBAR_DIR = ROOT / "captures" / "typebar_full"
INIT_SNAPSHOT = ROOT / "snapshots" / "u10-1_init.json"


def usbpcap_start(out_pcap: Path):
    out_pcap.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [r"C:\Program Files\USBPcap\USBPcapCMD.exe",
         "-d", r"\\.\USBPcap1",
         "-o", str(out_pcap),
         "-A", "--inject-descriptors"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def usbpcap_stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(0.3)


def detect_knobs_from_screenshot(img: Image.Image):
    """White-label cluster detection (same as in map_all_effects.py)."""
    knobs = []
    for knob_y, label_y in ((590, 634), (710, 755)):
        in_text = False
        starts = []
        ends = []
        for x in range(240, 1900):
            r, g, b = img.getpixel((x, label_y))[:3]
            white = (r > 180 and g > 180 and b > 180)
            if white and not in_text:
                starts.append(x)
                in_text = True
            elif not white and in_text:
                ends.append(x - 1)
                in_text = False
        if in_text:
            ends.append(1900)
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
            cx = (grp[0][0] + grp[-1][1]) // 2
            knobs.append((cx, knob_y))
    return knobs


def replay_drag_pcap(pcap: Path):
    """Replay the host->dev DT1s from a saved drag pcap."""
    jsonl = pcap.with_suffix(".jsonl")
    if not jsonl.exists():
        subprocess.run(
            ["python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
             str(pcap), "--out", str(jsonl)],
            capture_output=True, check=True)
    idx, _ = midi_send.find_output_port("GX-10")
    out = midi_send.MidiOut(idx)
    try:
        out.send_sysex(midi_send.build_dt1(0x7F000001, b"\x01"))
        time.sleep(0.2)
        with jsonl.open() as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("dir") != "host->dev" or ev.get("kind") != "sysex":
                    continue
                raw = bytes.fromhex(ev["hex"])
                if len(raw) < 16 or raw[8] != 0x12:
                    continue
                out.send_sysex(raw)
                time.sleep(0.02)
    finally:
        out.close()


def kill_ts():
    subprocess.run(["powershell", "-Command",
                    "Get-Process -Name 'BOSS TONE STUDIO for GX-10','msedgewebview2' -ErrorAction SilentlyContinue | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(2.0)


def restore_init():
    subprocess.run(["python", str(Path(__file__).parent / "restore_snapshot.py"),
                    str(INIT_SNAPSHOT), "--gap", "0.020"],
                   capture_output=True, check=True)


def launch_ts():
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])
    time.sleep(11.0)
    focus_ts.maximize_tone_studio()
    time.sleep(0.5)


def sweep_knob(knob_x, knob_y, out_pcap: Path, presses=200, gap=0.020):
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


def analyze_knob_pcap(pcap: Path) -> dict:
    jsonl = pcap.with_suffix(".jsonl")
    subprocess.run(
        ["python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
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
            if len(raw) < 16 or raw[8] != 0x12:
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
        "min": min(values),
        "max": max(values),
        "n_dt1": len(payloads),
    }


def process_effect(eff_dir: Path):
    summary_path = eff_dir / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    drag_pcap = eff_dir / "drag.pcap"
    drag_png = eff_dir / "drag.png"
    if not drag_pcap.exists() or not drag_png.exists():
        return None

    img = Image.open(drag_png)
    knobs = detect_knobs_from_screenshot(img)
    if not knobs:
        summary["knobs"] = []
        summary_path.write_text(json.dumps(summary, indent=2))
        return summary

    # Reset state and replay this effect's drag
    kill_ts()
    restore_init()
    time.sleep(1.0)
    replay_drag_pcap(drag_pcap)
    time.sleep(0.5)
    launch_ts()

    knobs_data = []
    for ki, (kx, ky) in enumerate(knobs):
        knob_pcap = eff_dir / f"knob_{ki:02d}_{kx}_{ky}.pcap"
        if not knob_pcap.exists() or knob_pcap.stat().st_size < 2000:
            sweep_knob(kx, ky, knob_pcap, presses=130, gap=0.020)
        info = analyze_knob_pcap(knob_pcap)
        info["knob_idx"] = ki
        info["knob_x"] = kx
        info["knob_y"] = ky
        knobs_data.append(info)

    summary["knobs"] = knobs_data
    summary["n_knobs_detected"] = len(knobs)
    summary_path.write_text(json.dumps(summary, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--effect", help="single effect dir name (relative to captures/typebar_full)")
    ap.add_argument("--page", type=int, help="restrict to page")
    args = ap.parse_args()

    if args.effect:
        process_effect(TYPEBAR_DIR / args.effect)
        return

    pages = [0, 1, 2] if args.page is None else [args.page]
    for p in pages:
        page_dir = TYPEBAR_DIR / f"page{p}"
        if not page_dir.exists():
            continue
        for eff_dir in sorted(page_dir.iterdir()):
            if not eff_dir.is_dir():
                continue
            summary_path = eff_dir / "summary.json"
            if summary_path.exists():
                s = json.loads(summary_path.read_text())
                if s.get("knobs") and all(k.get("address") for k in s["knobs"]):
                    print(f"skip {eff_dir.name} (already swept)")
                    continue
            print(f"\n=== {eff_dir.relative_to(TYPEBAR_DIR)} ===")
            try:
                rec = process_effect(eff_dir)
                if rec and rec.get("knobs"):
                    for k in rec["knobs"]:
                        print(f"  knob {k['knob_idx']:2d} @ ({k['knob_x']},{k['knob_y']}): "
                              f"addr={k.get('address')} range={k.get('min')}-{k.get('max')}")
            except Exception as e:
                print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
