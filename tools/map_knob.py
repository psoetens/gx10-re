"""
Map a single knob to its byte address and discover its range.

Methodology:
  1. Restore U10-1 INIT (clean baseline).
  2. Drag the chosen effect onto slot 0 (use a recorded pcap from
     drag_each_typebar.py to make this deterministic — replay it).
  3. Snapshot the slot's parameter region (0x10000200..0x10000B40 and
     0x10001100..0x100011FF).
  4. Click the target knob in Tone Studio + drag it / use keyboard to
     change its value. Take a USBPcap during this so we have the DT1.
  5. Snapshot again.
  6. Diff -> the changed byte is the knob's address.
  7. Write 0x00 / 0x7F to that byte to find min/max.

This script does steps 1-3 and 5-7 automatically; step 4 still requires
either Tone Studio knob interaction or an alternate "set knob" mechanism
(double-click + type, scroll wheel, etc.).
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
from rapid_probe import step_7bit


def restore_empty():
    subprocess.run([
        "python", str(Path(__file__).parent / "restore_snapshot.py"),
        str(Path(__file__).parent.parent / "snapshots/u10-1_init.json"),
        "--gap", "0.020",
    ], capture_output=True, check=True)


def drag_replay(pcap_path: Path, out: midi_send.MidiOut):
    """Replay the host->dev DT1 sequence from a captured drag pcap."""
    jsonl = pcap_path.with_suffix(".jsonl")
    if not jsonl.exists():
        subprocess.run([
            "python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
            str(pcap_path), "--out", str(jsonl),
        ], capture_output=True, check=True)
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("dir") != "host->dev" or ev.get("kind") != "sysex":
                continue
            raw = bytes.fromhex(ev["hex"])
            if (len(raw) < 16 or raw[8] != 0x12):
                continue
            out.send_sysex(raw)
            time.sleep(0.02)


def snapshot_region(out: midi_send.MidiOut, start: int, end: int) -> dict:
    import midi_sniff
    idx_in, _ = midi_sniff.find_port("GX-10")
    log = Path("captures") / f"_knob_{int(time.time()*1000)%100000:05d}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    sniffer = midi_sniff.Sniffer(idx_in, log, "GX-10")
    sniffer.open()
    try:
        for addr in step_7bit(start, end, 0x40):
            out.send_sysex(midi_send.build_rq1(addr, 0x40))
            time.sleep(0.015)
        time.sleep(0.4)
    finally:
        sniffer.close()
    addr_map = {}
    with log.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex":
                continue
            raw = bytes.fromhex(ev["hex"])
            if (len(raw) < 16 or raw[0] != 0xF0 or raw[-1] != 0xF7
                    or raw[8] != 0x12):
                continue
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            for i, b in enumerate(payload):
                addr_map[addr + i] = b
    log.unlink(missing_ok=True)
    return addr_map


def diff(a: dict, b: dict):
    keys = set(a) | set(b)
    out = []
    for k in sorted(keys):
        va = a.get(k)
        vb = b.get(k)
        if va != vb:
            out.append((k, va, vb))
    return out


def find_knob_range(out, addr: int) -> dict:
    """Probe a parameter byte by writing 0x00 and 0x7F and reading back."""
    # Read current value
    snap_before = snapshot_region(out, addr & ~0x3F, (addr & ~0x3F) + 0x40)
    cur = snap_before.get(addr)

    # Write 0x00
    out.send_sysex(midi_send.build_dt1(0x00200003, b"\x01"))
    time.sleep(0.05)
    out.send_sysex(midi_send.build_dt1(addr, b"\x00"))
    time.sleep(0.10)
    snap_zero = snapshot_region(out, addr & ~0x3F, (addr & ~0x3F) + 0x40)
    val_at_zero = snap_zero.get(addr)

    # Write 0x7F
    out.send_sysex(midi_send.build_dt1(addr, b"\x7F"))
    time.sleep(0.10)
    snap_max = snapshot_region(out, addr & ~0x3F, (addr & ~0x3F) + 0x40)
    val_at_max = snap_max.get(addr)

    # Restore original
    if cur is not None:
        out.send_sysex(midi_send.build_dt1(addr, bytes([cur])))
        time.sleep(0.05)
    out.send_sysex(midi_send.build_dt1(0x00200003, b"\x00"))
    time.sleep(0.05)

    return {
        "addr": f"{addr:08X}",
        "before_default": cur,
        "wrote_0x00_read": val_at_zero,
        "wrote_0x7F_read": val_at_max,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", required=True, help="hex byte address to probe")
    ap.add_argument("--restore-first", action="store_true")
    ap.add_argument("--drag-pcap", help="optional drag pcap to replay before probing")
    args = ap.parse_args()

    if args.restore_first:
        restore_empty()
        time.sleep(0.5)

    idx, _ = midi_send.find_output_port("GX-10")
    out = midi_send.MidiOut(idx)
    out.send_sysex(midi_send.build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.2)

    if args.drag_pcap:
        drag_replay(Path(args.drag_pcap), out)
        time.sleep(0.5)

    info = find_knob_range(out, int(args.addr, 16))
    print(json.dumps(info, indent=2))
    out.close()


if __name__ == "__main__":
    main()
