"""Orchestrate a BTS startup-handshake capture without manual UI clicks.

Sequence:
  t=0    : start a midi_sniff thread that logs JSONL to <log>
  t=2    : launch BOSS TONE STUDIO
  t=2..30: BTS loads, connects, performs its handshake
  t=30   : send a Program Change to advance the device patch (BTS reacts)
  t=40   : close BTS  (its disconnect handshake fires)
  t=50   : sniffer stops

Captures ALL device->host traffic during the entire timeline.
Filters out MIDI clock (F8) and active-sensing (FE) noise from the JSONL
on output to keep the decoded transcript readable.

Cross-platform: macOS uses Apple Events (osascript) for graceful BTS
close; Windows uses taskkill /F. Both paths live in tools/bts_launcher.py.
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_sniff
import bts_launcher
from midi_send import find_output_port, MidiOut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--bts-load-secs", type=float, default=30.0)
    ap.add_argument("--post-pc-secs", type=float, default=10.0)
    ap.add_argument("--post-close-secs", type=float, default=10.0)
    ap.add_argument("--bts-exe", default=None,
                    help="override the detected BTS executable path")
    args = ap.parse_args()

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    print("=== orchestrated BTS capture ===", flush=True)

    # 1) Start sniffer thread
    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        print("ERROR: no GX-10 input port"); sys.exit(2)
    sniffer = midi_sniff.Sniffer(in_idx, log_path, in_name)
    sniffer.open()
    print(f"  [t=0.0]  sniffer running -> {log_path}", flush=True)
    t0 = time.time()

    # 2) Launch BTS
    if bts_launcher.is_bts_running():
        print("WARNING: BTS already running — orchestration may misbehave "
              "if you have an interactive session open", flush=True)
    time.sleep(2.0)
    print(f"  [t={time.time()-t0:.1f}] launching BTS...", flush=True)
    bts_proc = bts_launcher.launch(args.bts_exe)
    print(f"  [t={time.time()-t0:.1f}] BTS PID={bts_proc.pid}; waiting "
          f"{args.bts_load_secs}s for connect handshake to complete", flush=True)
    time.sleep(args.bts_load_secs)

    # 3) Send a Program Change to advance the patch
    print(f"  [t={time.time()-t0:.1f}] sending Program Change to advance patch", flush=True)
    out_idx, _ = find_output_port("GX-10")
    out = MidiOut(out_idx)
    time.sleep(0.3)
    # Bank Select MSB=0 LSB=0, then PC#=1
    out.send_short_msg(bytes([0xB0, 0x00, 0x00]))   # Bank MSB
    out.send_short_msg(bytes([0xB0, 0x20, 0x00]))   # Bank LSB
    out.send_short_msg(bytes([0xC0, 0x00]))         # Program Change to PC#1
    print(f"  [t={time.time()-t0:.1f}] sent BankSelect + PC#1; "
          f"waiting {args.post_pc_secs}s for BTS to react", flush=True)
    time.sleep(args.post_pc_secs)

    # 4) Close BTS
    print(f"  [t={time.time()-t0:.1f}] closing BTS (graceful)", flush=True)
    rc = bts_launcher.kill(bts_proc, graceful=True, timeout=6.0)
    print(f"  [t={time.time()-t0:.1f}] BTS exited rc={rc}; waiting "
          f"{args.post_close_secs}s for disconnect handshake to settle", flush=True)
    time.sleep(args.post_close_secs)

    # 5) Stop sniffer
    print(f"  [t={time.time()-t0:.1f}] stopping sniffer", flush=True)
    sniffer.close()

    print("=== done ===", flush=True)
    print(f"  log: {log_path}", flush=True)
    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
