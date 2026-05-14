"""Like bts_orchestrate.py but with a manual "press Enter to continue"
pause between BTS-load and BTS-close, so the user can drive the actual
GUI scenario for tasks 2/3/4.
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_sniff


BTS_EXE = r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--bts-load-secs", type=float, default=12.0,
                    help="seconds to wait after launching BTS for it to settle")
    ap.add_argument("--post-close-secs", type=float, default=3.0)
    ap.add_argument("--bts-exe", default=BTS_EXE)
    args = ap.parse_args()

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"=== BTS pause-mode capture -> {log_path.name} ===", flush=True)

    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        print("ERROR: no GX-10 input port"); sys.exit(2)
    sniffer = midi_sniff.Sniffer(in_idx, log_path, in_name)
    sniffer.open()
    t0 = time.time()
    print(f"  [t=0]  sniffer running -> {log_path}", flush=True)

    time.sleep(2.0)
    print(f"  [t={time.time()-t0:.1f}] launching BTS...", flush=True)
    bts_proc = subprocess.Popen([args.bts_exe], close_fds=True)
    print(f"  [t={time.time()-t0:.1f}] BTS PID={bts_proc.pid}; "
          f"waiting {args.bts_load_secs}s for it to connect", flush=True)
    time.sleep(args.bts_load_secs)

    print()
    print(f"  [t={time.time()-t0:.1f}] >>> BTS is ready. Do the scenario "
          f"in BTS now, then press ENTER here to close BTS + stop the "
          f"sniffer.", flush=True)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass

    print(f"  [t={time.time()-t0:.1f}] closing BTS via taskkill", flush=True)
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(bts_proc.pid)],
                       check=False, capture_output=True)
    except Exception as e:
        print(f"    taskkill failed: {e}", flush=True)
    time.sleep(args.post_close_secs)

    print(f"  [t={time.time()-t0:.1f}] stopping sniffer", flush=True)
    sniffer.close()

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
