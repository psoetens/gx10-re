"""
Sweep one knob via click + Arrow Up / Arrow Down, capturing every DT1.

For a knob at window-local (x, y):
  1. Bring Tone Studio to foreground.
  2. Click the knob.
  3. Press Arrow Down N times to find min (DT1 stops repeating last value).
  4. Press Arrow Up 2N times to find max.
  5. Capture USBPcap throughout.

Output: a per-knob report:
  - DT1 address used by Tone Studio when this knob is changed
  - Cell layout (4-byte cell, value byte position)
  - Min observed
  - Max observed
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0


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
    time.sleep(0.3)


def pcap_to_jsonl(pcap: Path, jsonl: Path):
    subprocess.run([
        "python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
        str(pcap), "--out", str(jsonl),
    ], capture_output=True, check=True)


def parse_knob_dt1s(jsonl: Path):
    """Return list of (t, addr, payload_bytes) for host->dev DT1s."""
    out = []
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
            out.append((ev.get("t", 0.0), addr, payload))
    return out


def sweep(knob_x: int, knob_y: int, presses: int = 130, gap: float = 0.025,
          pcap_path: Path = None):
    pcap_path = pcap_path or Path("captures") / f"_knob_{int(time.time()):d}.pcap"
    pcap_path.parent.mkdir(parents=True, exist_ok=True)
    if pcap_path.exists():
        pcap_path.unlink()

    cap = usbpcap_start(pcap_path)
    time.sleep(0.8)

    try:
        hwnd = focus_ts.focus_tone_studio()
        time.sleep(0.2)
        sx, sy = focus_ts.screen_xy(hwnd, knob_x, knob_y)
        # Click the knob to focus it. Then ensure focus stays — re-click after the
        # click in case any modal popped up.
        pyautogui.click(sx, sy)
        time.sleep(0.4)

        # Arrow Down to walk to min
        for _ in range(presses):
            pyautogui.press("down")
            time.sleep(gap)
        time.sleep(0.4)

        # Arrow Up to walk to max (and overshoot slightly to confirm clamp)
        for _ in range(presses * 2):
            pyautogui.press("up")
            time.sleep(gap)
        time.sleep(1.0)
    finally:
        usbpcap_stop(cap)

    return pcap_path


def analyze(pcap_path: Path):
    jsonl = pcap_path.with_suffix(".jsonl")
    pcap_to_jsonl(pcap_path, jsonl)
    dt1s = parse_knob_dt1s(jsonl)
    if not dt1s:
        return {"address": None, "min": None, "max": None, "n_dt1": 0}

    # Group by address (each knob writes to one address)
    by_addr = {}
    for t, addr, payload in dt1s:
        by_addr.setdefault(addr, []).append((t, payload))
    # Pick the dominant address
    dom_addr = max(by_addr.keys(), key=lambda a: len(by_addr[a]))
    seq = by_addr[dom_addr]
    # The value byte is the LAST byte of each payload (pattern `08 00 ?? VV`).
    values = [p[-1] for _, p in seq]
    payload_lens = sorted({len(p) for _, p in seq})
    return {
        "address": f"{dom_addr:08X}",
        "value_byte_offset": "last",
        "payload_lens": payload_lens,
        "min": min(values),
        "max": max(values),
        "n_dt1": len(seq),
        "first_payload": seq[0][1].hex().upper(),
        "all_addresses_seen": [f"{a:08X}({len(by_addr[a])})" for a in by_addr],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--x", type=int, required=True, help="knob x in window-local px")
    ap.add_argument("--y", type=int, required=True, help="knob y in window-local px")
    ap.add_argument("--presses", type=int, default=130)
    ap.add_argument("--gap", type=float, default=0.025)
    ap.add_argument("--pcap", help="output pcap path")
    args = ap.parse_args()

    pcap_path = Path(args.pcap) if args.pcap else None
    pcap_path = sweep(args.x, args.y, args.presses, args.gap, pcap_path)
    info = analyze(pcap_path)
    info["pcap"] = str(pcap_path)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
