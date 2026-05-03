"""
Convert a USBPcap capture into the same JSONL format produced by midi_sniff.py,
so the existing sysex_decode.py tool works on bidirectional USB captures.

Calls tshark to extract:
  - frame timestamp (relative to first frame)
  - USB direction (host->dev or dev->host) from usb.endpoint_address.direction
  - reassembled SysEx hex from the usbaudio dissector

Output is JSONL on stdout (or --out file). One event per line.

Usage:
    python pcap_to_jsonl.py captures/usbpcap/handshake_full.pcap > captures/handshake_usb.jsonl
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_TSHARK = r"C:\Program Files\Wireshark\tshark.exe"


def find_tshark():
    p = shutil.which("tshark") or DEFAULT_TSHARK
    if not Path(p).exists():
        raise FileNotFoundError(f"tshark not found at {p}; pass --tshark to override")
    return p


def extract(pcap_path: Path, tshark_path: str):
    """Run tshark -V on the SysEx-bearing frames and parse direction + reassembled hex.

    The usbaudio dissector emits a "[Reassembled data: ...]" line containing
    the full SysEx (F0 ... F7) on the frame that carries the SysEx-end event
    packet. We pair that with the USB direction (URB IN vs OUT) and the
    relative timestamp from the same frame.
    """
    cmd = [tshark_path, "-r", str(pcap_path), "-V", "-Y", "sysex"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"tshark -V failed: {proc.stderr.strip()}")
    return parse_v_output(proc.stdout)


def parse_v_output(text: str):
    """Parse tshark -V output into (frame, t, direction, sysex_hex) tuples.

    Only the *first* line of each frame block ("Frame 25: 35 bytes ...")
    starts a new event — there are also nested "Frame Number:" and "Frame
    Length:" lines inside the per-frame body that must NOT reset state.
    """
    import re
    frame_start = re.compile(r"^Frame (\d+):\s")
    events = []
    cur = {}
    for line in text.splitlines():
        m = frame_start.match(line)  # don't strip — top-level frame lines have no leading whitespace
        if m:
            if cur.get("hex"):
                events.append(cur)
            cur = {"frame": int(m.group(1))}
            continue
        s = line.strip()
        if s.startswith("[Time since reference or first frame:"):
            try:
                tail = s.split(":", 1)[1].rstrip("]").strip()
                cur["t"] = float(tail.split()[0])
            except Exception:
                pass
            continue
        if "Direction: IN" in s and "dir" not in cur:
            cur["dir"] = "dev->host"
        elif "Direction: OUT" in s and "dir" not in cur:
            cur["dir"] = "host->dev"
        if "[Reassembled data:" in s:
            hex_part = s.split("[Reassembled data:", 1)[1].rstrip("]").strip()
            cur["hex"] = hex_part.replace(" ", "").upper()
    if cur.get("hex"):
        events.append(cur)
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap")
    ap.add_argument("--out", default="-")
    ap.add_argument("--tshark", default=None)
    args = ap.parse_args()

    tshark_path = args.tshark or find_tshark()
    events = extract(Path(args.pcap), tshark_path)

    out_fp = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8")
    try:
        # First emit a synthetic "open" so the file shape mirrors midi_sniff.py.
        out_fp.write(json.dumps({"event": "opened", "source": "pcap", "pcap": args.pcap, "t": 0.0, "label": "(no label)"}) + "\n")
        for ev in events:
            length = len(ev["hex"]) // 2
            out_fp.write(json.dumps({
                "dir": ev.get("dir", "?"),
                "kind": "sysex",
                "len": length,
                "hex": ev["hex"],
                "t": ev.get("t", 0.0),
                "frame": ev.get("frame", ""),
                "label": "(usbpcap)",
            }) + "\n")
    finally:
        if out_fp is not sys.stdout:
            out_fp.close()


if __name__ == "__main__":
    main()
