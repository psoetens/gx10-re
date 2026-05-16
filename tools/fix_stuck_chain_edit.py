"""Clear a stuck ChainEditTrigger flag on the GX-10.

Symptom: BTS's INSERT / DELETE / OVERWRITE buttons go "stone dead" —
they depress visually when clicked, but no MIDI is emitted and the
chain never updates. Drag-drop still works.

Root cause: BTS (chain_controller.js:4208) guards every chain-edit
trigger with `if (globalIsChainEditing === isEditing) return;` and
syncs that flag with the device's address 0x00200003 (Setup_temp
ChainEditTrigger). If a prior reverse-engineering / capture / crash
left the device with ChainEditTrigger=1, BTS reads that on launch,
sets globalIsChainEditing=true, and from then on every action button
no-ops because the guard says "already editing".

The fix: write 0 to address 0x00200003. Then relaunch BTS so it
re-reads the device state.

Usage:
  python tools/fix_stuck_chain_edit.py
  python tools/fix_stuck_chain_edit.py --no-relaunch   # just clear
"""
import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
from example_lib import GX10Session
from device_id import require_alive


def kill_bts():
    subprocess.run(["powershell", "-Command",
                    "Get-Process -Name 'BOSS TONE STUDIO for GX-10','msedgewebview2' "
                    "-ErrorAction SilentlyContinue | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(2.5)


def launch_bts():
    subprocess.Popen([r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"])


def read_back():
    """Sniff while sending RQ1 to verify the address now reads 0.
    Returns the byte value, or None on timeout/error."""
    try:
        events = []
        lock = threading.Lock()
        idx, name = midi_sniff.find_port("GX-10")
        if idx is None:
            return None
        s = midi_sniff.Sniffer(idx, Path("__nul__.jsonl"), name)

        def emit(o):
            if o.get("kind") == "sysex":
                with lock:
                    events.append(bytes.fromhex(o["hex"]))
        s._emit = emit
        s.open()
        out_idx, _ = find_output_port("GX-10")
        out = MidiOut(out_idx)
        time.sleep(0.3)
        out.send_sysex(build_rq1(0x00200003, 1))
        time.sleep(0.5)
        try:
            s.close()
        except Exception:
            pass
        try:
            out.close()
        except Exception:
            pass
        for e in events:
            if (len(e) >= 14 and e[8] == 0x12
                    and int.from_bytes(e[9:13], "big") == 0x00200003):
                return e[13]
        return None
    except Exception as exc:
        print(f"  (read_back error: {exc})")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-relaunch", action="store_true",
                    help="Just clear the flag; don't restart BTS")
    ap.add_argument("--no-verify", action="store_true",
                    help="Skip the read-back verification (avoids occasional WinMM hang)")
    args = ap.parse_args()

    print("Killing BTS to free MIDI port...")
    kill_bts()

    # Use GX10Session (with built-in sniffer) so we can do the strict
    # identity check before writing anything to the device.
    sess = GX10Session()
    require_alive(sess)
    msg = build_dt1(0x00200003, b"\x00")
    print(f"Sending DT1 ChainEditTrigger=0:  {msg.hex().upper()}")
    sess.send(msg)
    try: sess.out.close()
    except Exception: pass
    try: sess.sniffer.close()
    except Exception: pass
    time.sleep(0.4)

    if not args.no_verify:
        val = read_back()
        if val is None:
            print("WARN: could not read back ChainEditTrigger (device silent)")
        elif val == 0:
            print("Verified: ChainEditTrigger now reads 0 on the device.")
        else:
            print(f"WARN: ChainEditTrigger still reads {val} after the write.")

    if args.no_relaunch:
        print("Skipping BTS relaunch (--no-relaunch).")
        return
    print("Relaunching BTS...")
    launch_bts()
    print("Done. Try the INSERT / DELETE / OVERWRITE buttons.")


if __name__ == "__main__":
    main()
