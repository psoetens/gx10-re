"""
For each item in Tone Studio's top effect-type bar (COMP, X-COMP, BOOST, ...),
drag-and-drop it onto chain slot 0, with USBPcap capturing the resulting
DT1 sequence. After each drag, screenshot Tone Studio so we can label the
captured DT1 sequence with the effect's display name.

Each item produces:
  - captures/typebar/dragN_<NAME>.pcap   - USBPcap of the drag
  - captures/typebar/dragN_<NAME>.png    - Tone Studio screenshot
  - captures/typebar/index.json          - {idx, name, pcap, screenshot, type_byte_at_10001100}

This is the *reliable* path to a complete per-effect-type protocol map. Each
drag's DT1 sequence is the atomic command for "set slot 0 to this effect",
which can be replayed without Tone Studio.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import uiautomation as auto
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

TARGET = "BOSS TONE STUDIO for GX-10"

# Type-bar item label + pixel coordinates within the Tone Studio window
# (derived from screenshot ui_002.png; window at -9,-9, both rows visible).
TYPEBAR = [
    ("COMP",     254, 156),
    ("X-COMP",   308, 156),
    ("BOOST",    363, 156),
    ("OD",       418, 156),
    ("X-OD",     472, 156),
    ("DIST",     533, 156),
    ("X-DIST",   590, 156),
    ("METAL",    645, 156),
    ("FUZZ",     703, 156),
    ("AMP",      759, 156),
    ("PEQ",      816, 156),
    ("GEQ",      872, 156),
    ("CHO",      928, 156),
    ("CHO_PRIME", 982, 156),
    ("FL",      1041, 156),
    ("FL_PRIME", 1097, 156),
    ("PH",      1156, 156),
    ("PH_SCRIPT", 1208, 156),
    ("PH_PRIME", 1265, 156),
    ("CLASS_VIBE", 1322, 156),
    ("ROTARY",  1378, 156),
    ("VIB",     1432, 156),
    ("VIB_PRIME", 1490, 156),
    ("TREM",    1546, 156),
    ("PAN",     1602, 156),
    ("RING_MOD", 1658, 156),
    ("SLICER",  1716, 156),
    ("HMN",     1772, 156),
    ("PS",      1828, 156),
    ("HARM",    1884, 156),
]

SLOT0 = (285, 312)  # first chain hex


def kill_ts():
    subprocess.run(
        ["powershell", "-Command",
         "Get-Process -Name 'BOSS TONE STUDIO for GX-10' -ErrorAction SilentlyContinue | Stop-Process -Force"],
        capture_output=True,
    )
    time.sleep(2.0)


def launch_ts():
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])
    time.sleep(11.0)


def restore_empty():
    """Run restore_snapshot.py with U10-1 init."""
    subprocess.run([
        "python",
        str(Path(__file__).parent / "restore_snapshot.py"),
        str(Path(__file__).parent.parent / "snapshots" / "u10-1_init.json"),
        "--gap", "0.020",
    ], capture_output=True)


def usbpcap_start(out_pcap: Path):
    return subprocess.Popen([
        r"C:\Program Files\USBPcap\USBPcapCMD.exe",
        "-d", r"\\.\USBPcap1",
        "-o", str(out_pcap),
        "-A", "--inject-descriptors",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def usbpcap_stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(0.5)


def screenshot(path: Path):
    subprocess.run([
        "python",
        str(Path(__file__).parent / "screenshot.py"),
        "--out", str(path),
    ], capture_output=True)


def acquire_window():
    win = auto.WindowControl(searchDepth=1, Name=TARGET)
    if not win.Exists(maxSearchSeconds=10):
        raise RuntimeError("Tone Studio window not found")
    r = win.BoundingRectangle
    return (r.left, r.top)


def drag_to_slot0(origin, src_xy):
    sx = origin[0] + src_xy[0]
    sy = origin[1] + src_xy[1]
    dx = origin[0] + SLOT0[0]
    dy = origin[1] + SLOT0[1]
    pyautogui.moveTo(sx, sy, duration=0.2)
    pyautogui.mouseDown()
    pyautogui.moveTo(dx, dy, duration=1.0)
    time.sleep(0.3)
    pyautogui.mouseUp()
    time.sleep(2.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="captures/typebar dir")
    ap.add_argument("--start", type=int, default=0, help="index in TYPEBAR list")
    ap.add_argument("--count", type=int, default=len(TYPEBAR))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    index = []
    end = min(args.start + args.count, len(TYPEBAR))

    for i in range(args.start, end):
        name, x, y = TYPEBAR[i]
        print(f"\n=== [{i}] {name} ===", flush=True)

        # Reset to a known empty state
        kill_ts()
        restore_empty()
        launch_ts()
        origin = acquire_window()

        # Capture the drag
        pcap_path = out_dir / f"drag{i:02d}_{name}.pcap"
        usb = usbpcap_start(pcap_path)
        time.sleep(1.0)
        try:
            drag_to_slot0(origin, (x, y))
            time.sleep(1.0)
        finally:
            usbpcap_stop(usb)

        # Screenshot the result
        shot_path = out_dir / f"drag{i:02d}_{name}.png"
        screenshot(shot_path)

        # Read the type byte
        # We invoke midi_send via subprocess to avoid threading conflicts
        result = subprocess.run([
            "python",
            str(Path(__file__).parent / "midi_send.py"),
            "--rq1", "10001100", "00000010",
        ], capture_output=True, text=True)

        index.append({
            "idx": i,
            "name": name,
            "pcap": str(pcap_path),
            "screenshot": str(shot_path),
            "drag_src": [x, y],
        })
        (out_dir / "index.json").write_text(json.dumps(index, indent=2))


if __name__ == "__main__":
    main()
