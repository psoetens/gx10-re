"""
Systematic effect-type mapper.

For each candidate type ID T at byte 0x10001100 (the slot-0 effect-type
register, observed to be the byte Tone Studio writes during drag-and-drop):

  1. Restore the U10-1 EMPTY edit buffer.
  2. Reproduce Tone Studio's "add a COMP effect to slot 0" command sequence
     — three DT1 writes at 0x10001100/0x10001102/0x10001101 (category, modifier,
     type) bracketed by the editor-attach flag at 0x00200003. This puts the
     slot into a known valid state.
  3. Write T to 0x10001100. The device cascades parameter defaults.
  4. Read the patch buffer at 0x10001100..0x100011FF. Save as a snapshot.
  5. Optionally: kill+launch Tone Studio and screenshot to capture the
     human-readable effect NAME. This is slow; pass --names to enable.

Saves per-type data into snapshots/effects/slot0-tXX.json plus a summary.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
from rapid_probe import step_7bit, plan_live_low

ZERO_PAYLOAD = bytes([0])
ONE_PAYLOAD = bytes([1])


def open_out():
    idx, _ = midi_send.find_output_port("GX-10")
    return midi_send.MidiOut(idx)


def announce_editor(out):
    out.send_sysex(midi_send.build_dt1(0x7F000001, ONE_PAYLOAD))
    time.sleep(0.15)


def reset_to_empty(out, snap_path: Path):
    """Quick & dirty: send a DT1 with known-good 'empty' content to slot 0
    chain bytes. Avoids the full 4475-byte restore for speed."""
    # The U10-1 INIT pattern at 0x10001100 starts with `02 01 01 ...`.
    # Restoring just the slot-0 effect-control bytes is enough for our
    # iteration purposes; we don't need a full patch reset every loop.
    out.send_sysex(midi_send.build_dt1(0x00200003, ONE_PAYLOAD))
    time.sleep(0.05)
    out.send_sysex(midi_send.build_dt1(0x10001100, b"\x02\x01\x01"))
    time.sleep(0.10)
    out.send_sysex(midi_send.build_dt1(0x00200003, ZERO_PAYLOAD))
    time.sleep(0.10)


def add_comp_then_set_type(out, type_id: int):
    """Replicate Tone Studio's full drag-COMP sequence with our type id.

    Observed during a COMP drag: Tone Studio writes 0x10001100=0x08,
    0x10001102=0x00, 0x10001101=0x01 (in that order). The per-effect
    triplet (cat, modifier, sub) is therefore (type_id, 0x01, 0x00) for
    "main" effect types. We write all three atomically as a single 3-byte
    DT1.
    """
    out.send_sysex(midi_send.build_dt1(0x00200003, ONE_PAYLOAD))
    time.sleep(0.03)
    # Write the full 3-byte slot descriptor at once so the device sees a
    # coherent (cat, modifier, sub) triplet rather than partial state.
    out.send_sysex(midi_send.build_dt1(0x10001100, bytes([type_id, 0x01, 0x00])))
    time.sleep(0.05)
    # Emit the chain order Tone Studio uses (so the device routes the slot
    # into the audible chain). Same ordering Tone Studio sent on COMP-drag:
    chain = bytes([0x0C, 0x01, 0x00] + list(range(0x02, 0x32)))
    out.send_sysex(midi_send.build_dt1(0x10000F00, chain))
    time.sleep(0.05)
    out.send_sysex(midi_send.build_dt1(0x00200003, ZERO_PAYLOAD))
    time.sleep(0.10)


_GLOBAL_SNIFFER = None
_GLOBAL_SNIFFER_LOG = None


def _ensure_sniffer():
    global _GLOBAL_SNIFFER, _GLOBAL_SNIFFER_LOG
    if _GLOBAL_SNIFFER is not None:
        return _GLOBAL_SNIFFER, _GLOBAL_SNIFFER_LOG
    import midi_sniff
    idx_in, _ = midi_sniff.find_port("GX-10")
    log = Path("captures") / f"_eff_{int(time.time()):d}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    _GLOBAL_SNIFFER_LOG = log
    _GLOBAL_SNIFFER = midi_sniff.Sniffer(idx_in, log, "GX-10")
    _GLOBAL_SNIFFER.open()
    return _GLOBAL_SNIFFER, _GLOBAL_SNIFFER_LOG


def _stop_sniffer():
    global _GLOBAL_SNIFFER
    if _GLOBAL_SNIFFER is not None:
        try:
            _GLOBAL_SNIFFER.close()
        except Exception:
            pass
        _GLOBAL_SNIFFER = None


def read_slot0(out, span: int = 0x80):
    """Read 0x10001100..0x10001100+span via small RQ1s. Reuse a single
    long-lived sniffer process-wide; mark a label so we can scope which
    bytes belong to this read.

    Returns a {addr: byte} dict for the bytes received during this call only.
    """
    sniffer, log = _ensure_sniffer()
    marker = f"READ_SLOT0_{time.time_ns()}"
    sniffer.set_label(marker)
    cutoff = time.perf_counter()
    for addr in step_7bit(0x10001100, 0x10001100 + span, 0x40):
        out.send_sysex(midi_send.build_rq1(addr, 0x40))
        time.sleep(0.02)
    time.sleep(0.4)

    # Re-read the log file from the start; collect only events that arrived
    # AFTER our marker. Sniffer's t is `time.perf_counter() - t0`, so we use
    # the stored sniffer.t0 to compute absolute perf_counter.
    addr_map = {}
    with log.open("r", encoding="utf-8") as f:
        in_window = False
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "label" and ev.get("label") == marker:
                in_window = True
                continue
            if not in_window:
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
    return addr_map


def kill_tone_studio():
    subprocess.run(
        ["powershell", "-Command",
         "Get-Process -Name 'BOSS TONE STUDIO for GX-10' -ErrorAction SilentlyContinue | Stop-Process -Force"],
        capture_output=True,
    )
    time.sleep(2.0)


def launch_tone_studio():
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])
    time.sleep(11.0)


def screenshot(path: Path):
    subprocess.run(
        ["python", str(Path(__file__).parent / "screenshot.py"), "--out", str(path)],
        capture_output=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0x01)
    ap.add_argument("--end", type=int, default=0x20, help="exclusive")
    ap.add_argument("--out", required=True, help="snapshots/effects directory")
    ap.add_argument("--names", action="store_true", help="kill+launch Tone Studio per type to capture names")
    args = ap.parse_args()

    out_dir = Path(args.out)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)

    out = open_out()
    announce_editor(out)

    summary = []

    try:
        for t in range(args.start, args.end):
            # Prep state: restore slot-0 to its pre-add condition each time
            reset_to_empty(out, Path("snapshots/u10-1_init.json"))
            time.sleep(0.2)

            add_comp_then_set_type(out, t)
            time.sleep(0.4)

            addr_map = read_slot0(out)
            snap_path = out_dir / f"slot0-t{t:02X}.json"
            ser = {f"{a:08X}": b for a, b in sorted(addr_map.items())}
            snap_path.write_text(json.dumps(ser, indent=2))

            row = {
                "type_id": t,
                "type_id_hex": f"{t:02X}",
                "first16_at_10001100": [
                    f"{addr_map.get(0x10001100 + i, -1):02X}"
                    if (0x10001100 + i) in addr_map else "--"
                    for i in range(16)
                ],
            }

            if args.names:
                kill_tone_studio()
                launch_tone_studio()
                shot = out_dir / "screenshots" / f"slot0-t{t:02X}.png"
                screenshot(shot)
                row["screenshot"] = str(shot)

            summary.append(row)
            print(f"t={t:02X}  bytes[0..15]={' '.join(row['first16_at_10001100'])}",
                  flush=True)

        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    finally:
        _stop_sniffer()
        out.close()


if __name__ == "__main__":
    main()
