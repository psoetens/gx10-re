"""
Sweep the GX-10 address space by sending RQ1 (data request) probes ourselves
and capturing the device's DT1 replies.

Strategy: open both the GX-10 input (sniffer) and output (probe sender) ports
from the same process, send RQ1 at a list of addresses, and log every reply.
The replies tell us:
  - Which addresses are valid (we get a DT1 back)
  - The size of the resource at each address (the device may chunk)
  - The actual contents (we can interpret ASCII names, parameter ranges, etc.)

We use one process so that send and receive are correlated by `t_seconds`
without needing a label fifo.

CLI:
    python address_scan.py --plan top-regions  --log captures/scan_top.jsonl
    python address_scan.py --plan user-bank    --log captures/scan_user.jsonl
    python address_scan.py --plan custom --addr 10000000 --size 100 --log out.jsonl
"""
import argparse
import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import midi_send
import midi_sniff


def collect_replies(log_path: Path, port_substr: str, run_seconds: float, send_plan):
    """Run the sniffer and call send_plan() once it's started.

    The sniffer is the established midi_sniff.Sniffer; we drive it on the main
    thread by polling for the configured time, then close it.
    """
    idx_in, name_in = midi_sniff.find_port(port_substr)
    if idx_in is None:
        raise RuntimeError(f"no MIDI input port matching {port_substr!r}")

    idx_out, name_out = midi_send.find_output_port(port_substr)
    if idx_out is None:
        raise RuntimeError(f"no MIDI output port matching {port_substr!r}")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    sniffer = midi_sniff.Sniffer(idx_in, log_path, name_in)
    sniffer.open()
    sniffer.set_label(f"opened in={name_in!r} out={name_out!r}")

    out = midi_send.MidiOut(idx_out)
    sender_done = threading.Event()

    def sender_thread():
        try:
            time.sleep(0.5)  # let sniffer fully arm
            for label, sysex in send_plan:
                sniffer.set_label(f"SEND {label}: {sysex.hex().upper()}")
                out.send_sysex(sysex)
                # small inter-request gap so device can answer in peace
                time.sleep(0.3)
        finally:
            sender_done.set()

    t = threading.Thread(target=sender_thread, daemon=True)
    t.start()

    deadline = time.time() + run_seconds
    while time.time() < deadline:
        if sender_done.is_set() and time.time() > deadline - 1.0:
            # All probes sent and we've drained for at least 1 sec; can stop
            break
        time.sleep(0.05)

    out.close()
    sniffer.close()


# ---- prebuilt scan plans ---------------------------------------------------

def plan_top_regions():
    """Probe the start of each known top-level region with a small read."""
    plan = []
    plan.append(("identity", midi_send.build_identity_request()))
    for addr_hex in [
        "00000000",
        "01000000",
        "02000000",
        "10000000",
        "10001000",
        "10002000",
        "20000000",
        "30000000",
        "40000000",
        "50000000",
        "60000000",
        "60400000",
        "70000000",
        "7F000000",
    ]:
        addr = int(addr_hex, 16)
        plan.append((f"RQ1 {addr_hex} size=40", midi_send.build_rq1(addr, 0x40)))
    return plan


def plan_live_patch():
    """Sweep the entire live patch buffer in 0x40-byte chunks."""
    plan = [("identity", midi_send.build_identity_request())]
    for offset in range(0, 0x4000, 0x40):
        addr = 0x10000000 + offset
        addr_hex = f"{addr:08X}"
        plan.append((f"RQ1 {addr_hex}", midi_send.build_rq1(addr, 0x40)))
    return plan


def plan_live_patch_deep():
    """Deep-sweep the live patch buffer including the strict 0x10001000+ region.

    Observations: 0x10000000-0x10000F40 accepts large reads (size up to 0x10000)
    and replies with all populated records. 0x10001000+ is stricter: it only
    replies if the requested size is <= 0x40, and only at addresses that are
    actual record starts. So we sweep 0x10001000 .. 0x10010000 in 0x40-byte
    chunks with size=0x40 each.
    """
    plan = [("identity", midi_send.build_identity_request())]
    # First region: one big read covers all populated records
    plan.append(("RQ1 10000000 size=10000", midi_send.build_rq1(0x10000000, 0x10000)))
    # Second region: dense 0x40-byte sweep
    for offset in range(0x1000, 0x10000, 0x40):
        addr = 0x10000000 + offset
        plan.append((f"RQ1 {addr:08X} size=40", midi_send.build_rq1(addr, 0x40)))
    return plan


def plan_announce_editor():
    """Mimic Tone Studio's startup handshake (DT1 0x7F000001=0x01)."""
    return [("DT1 7F000001=01 editor-attached", midi_send.build_dt1(0x7F000001, b"\x01"))]


def plan_release_editor():
    """Reverse the editor-attached bit (DT1 0x7F000001=0x00)."""
    return [("DT1 7F000001=00 editor-detached", midi_send.build_dt1(0x7F000001, b"\x00"))]


def plan_user_bank(slot_count: int = 16):
    """Read each user-bank slot (name + a chunk of params)."""
    plan = [("identity", midi_send.build_identity_request())]
    for slot in range(slot_count):
        addr = 0x60400000 + slot * 0x10000
        addr_hex = f"{addr:08X}"
        plan.append((f"RQ1 USER{slot+1} name {addr_hex}", midi_send.build_rq1(addr, 0x40)))
    return plan


def plan_system():
    plan = [("identity", midi_send.build_identity_request())]
    for offset in range(0, 0x800, 0x40):
        addr = 0x7F000000 + offset
        plan.append((f"RQ1 SYS {addr:08X}", midi_send.build_rq1(addr, 0x40)))
    return plan


PLANS = {
    "top-regions": plan_top_regions,
    "live-patch": plan_live_patch,
    "live-patch-deep": plan_live_patch_deep,
    "user-bank": plan_user_bank,
    "system": plan_system,
    "announce-editor": plan_announce_editor,
    "release-editor": plan_release_editor,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="GX-10")
    ap.add_argument("--log", required=True)
    ap.add_argument("--plan", choices=list(PLANS) + ["custom"], required=True)
    ap.add_argument("--addr", help="hex addr (only for --plan custom)")
    ap.add_argument("--size", help="hex size (only for --plan custom)")
    ap.add_argument("--seconds", type=float, default=None,
                    help="how long to keep the sniffer running. Auto-derived from plan size if omitted.")
    args = ap.parse_args()

    if args.plan == "custom":
        if not args.addr or not args.size:
            print("--plan custom requires --addr and --size", file=sys.stderr)
            sys.exit(2)
        plan = [(f"RQ1 {args.addr.upper()} size={args.size}",
                 midi_send.build_rq1(int(args.addr, 16), int(args.size, 16)))]
    else:
        plan = PLANS[args.plan]()

    seconds = args.seconds if args.seconds is not None else max(5.0, len(plan) * 0.5 + 2.0)
    print(f"plan: {len(plan)} sysex sends, run for ~{seconds:.1f}s", file=sys.stderr)
    collect_replies(Path(args.log), args.port, seconds, plan)
    print("done", file=sys.stderr)


if __name__ == "__main__":
    main()
