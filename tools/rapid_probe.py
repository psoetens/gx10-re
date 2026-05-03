"""
Rapid-fire RQ1 sender. No in-process sniffing — relies on an external
USBPcap capture being already running. Sends a list of RQ1s as fast as
the device tolerates. Far faster than address_scan.py for bulk dumps.

Plans match address_scan.py:
    --plan live-patch-deep
    --plan live-low (0x10000000-0x10001000 in 0x40 chunks)
    --plan live-chain (0x10001000-0x10004000 in 0x40 chunks)
    --plan custom --addr ... --size ...
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send


def addr_bytes_ok(addr: int) -> bool:
    """Roland addresses are 7-bit per byte — every byte must be <= 0x7F."""
    return all(b <= 0x7F for b in addr.to_bytes(4, "big"))


def step_7bit(start: int, end: int, step: int):
    """Yield addresses from start (inclusive) to end (exclusive) in `step` increments,
    skipping addresses whose byte-encoding has any byte > 0x7F. Note that
    `step` here is in conventional integer units, not 7-bit-clean units, so
    e.g. step=0x40 will produce 0x00, 0x40 within a byte then skip 0x80/0xC0."""
    a = start
    while a < end:
        if addr_bytes_ok(a):
            yield a
        a += step


def plan_live_low():
    return [(a, 0x40) for a in step_7bit(0x10000000, 0x10001000, 0x40)]

def plan_live_chain():
    return [(a, 0x40) for a in step_7bit(0x10001000, 0x10004000, 0x40)]

def plan_live_patch_deep():
    return plan_live_low() + plan_live_chain()

def plan_user_slot(slot: int):
    """Read full user-slot range (0x60400000 + slot*0x10000), 0x4000 bytes in 0x40 chunks."""
    base = 0x60400000 + slot * 0x10000
    return [(a, 0x40) for a in step_7bit(base, base + 0x4000, 0x40)]

def plan_user_low(slot: int):
    """Read first 0x1000 bytes of slot in 0x40 chunks."""
    base = 0x60400000 + slot * 0x10000
    return [(a, 0x40) for a in step_7bit(base, base + 0x1000, 0x40)]


PLANS = {
    "live-low": plan_live_low,
    "live-chain": plan_live_chain,
    "live-patch-deep": plan_live_patch_deep,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--gap", type=float, default=0.015,
                    help="seconds between sends (default 0.015)")
    ap.add_argument("--user-slot", type=int, default=None,
                    help="for --plan user-slot: which slot index (0-15)")
    args = ap.parse_args()

    if args.plan == "user-slot":
        if args.user_slot is None:
            print("--user-slot required", file=sys.stderr); sys.exit(2)
        plan = plan_user_slot(args.user_slot)
    elif args.plan == "user-low":
        if args.user_slot is None:
            print("--user-slot required", file=sys.stderr); sys.exit(2)
        plan = plan_user_low(args.user_slot)
    elif args.plan in PLANS:
        plan = PLANS[args.plan]()
    else:
        print(f"unknown plan: {args.plan}", file=sys.stderr); sys.exit(2)

    idx, name = midi_send.find_output_port("GX-10")
    if idx is None:
        print("GX-10 output port not found", file=sys.stderr); sys.exit(2)
    out = midi_send.MidiOut(idx)
    print(f"sending {len(plan)} RQ1s with gap={args.gap}s ...", file=sys.stderr)
    t0 = time.perf_counter()
    try:
        for addr, size in plan:
            out.send_sysex(midi_send.build_rq1(addr, size))
            time.sleep(args.gap)
    finally:
        out.close()
    elapsed = time.perf_counter() - t0
    print(f"done in {elapsed:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
