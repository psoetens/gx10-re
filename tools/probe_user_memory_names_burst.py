"""Burst-mode user-memory name probe — fires all RQ1s back-to-back
through a single MIDI session, then collects DT1 replies. Avoids the
WinMM hang we saw with the per-memory open/close pattern.

Works on both GX-10 (198 user memories) and GX-100 (200 user memories).
The default --end value adapts to whichever device is connected.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff
from device_profile import detect_and_profile


MEMORY_BASE = 0x20000000     # chart hex: (0x20, 0x00, 0x00, 0x00)
# Stride in chart hex is "00 06 00 00" — the high byte ('b') is 0x06.
# In linear (7-bit-packed) space the spacing between memories is 6*128^2.
MEMORY_STRIDE_LINEAR = 6 * 128 * 128  # = 0x18000
NAME_LEN = 16


def memory_addr(n: int) -> int:
    """Compute the chart-hex address of memory N (0..199).

    Roland addresses are 4 bytes each 0..127. Adding stride between
    memories happens in 7-bit-per-byte arithmetic, NOT raw int math:
    after byte-b reaches 0x7E (memory 21) the next memory carries into
    byte-a, so memory 22 is at 0x21 04 00 00 (not 0x20 84 00 00).
    """
    base_a = (MEMORY_BASE >> 24) & 0xFF
    base_b = (MEMORY_BASE >> 16) & 0xFF
    base_c = (MEMORY_BASE >> 8) & 0xFF
    base_d = MEMORY_BASE & 0xFF
    base_lin = ((base_a & 0x7F) << 21) | ((base_b & 0x7F) << 14) | \
               ((base_c & 0x7F) << 7) | (base_d & 0x7F)
    addr_lin = base_lin + n * MEMORY_STRIDE_LINEAR
    a = (addr_lin >> 21) & 0x7F
    b = (addr_lin >> 14) & 0x7F
    c = (addr_lin >> 7) & 0x7F
    d = addr_lin & 0x7F
    return (a << 24) | (b << 16) | (c << 8) | d


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    addr = int.from_bytes(raw[9:13], "big")
    payload = bytes(raw[13:-2])
    return addr, payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="GX-10")
    ap.add_argument("--out", default="captures/user_memory_names.json")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None,
                    help="last memory # inclusive (default: device's user-memory count - 1)")
    ap.add_argument("--inter-rq1-ms", type=int, default=20,
                    help="ms between RQ1 sends (slow if device drops)")
    ap.add_argument("--collect-secs", type=float, default=8.0,
                    help="seconds to wait after last RQ1 for DT1s")
    args = ap.parse_args()

    # Detect device to set the default --end
    model, profile = detect_and_profile(port_substr=args.port)
    if args.end is None:
        args.end = profile["memory_count"] - 1
    print(f"Device: {model}  (memory_count={profile['memory_count']})", flush=True)
    print(f"opening MIDI input '{args.port}'...", flush=True)
    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port(args.port)
    if in_idx is None:
        print("ERROR: no input port"); sys.exit(2)
    s = midi_sniff.Sniffer(in_idx, Path("__nul__.jsonl"), in_name)

    def emit(o):
        if o.get("kind") == "sysex":
            try:
                with lock:
                    events.append(bytes.fromhex(o["hex"]))
            except Exception:
                pass
    s._emit = emit
    s.open()
    print(f"  input opened: {in_name}", flush=True)

    out_idx, out_name = find_output_port(args.port)
    if out_idx is None:
        print("ERROR: no output port"); sys.exit(2)
    out = MidiOut(out_idx)
    print(f"opened output: {out_name}", flush=True)
    time.sleep(0.4)

    # Send burst of RQ1s
    n = args.end - args.start + 1
    print(f"sending {n} RQ1s...", flush=True)
    t_burst = time.time()
    for mem_n in range(args.start, args.end + 1):
        addr = memory_addr(mem_n)
        out.send_sysex(build_rq1(addr, NAME_LEN))
        time.sleep(args.inter_rq1_ms / 1000.0)
    print(f"  burst sent in {time.time()-t_burst:.1f}s", flush=True)
    print(f"collecting DT1 replies for {args.collect_secs}s...", flush=True)
    time.sleep(args.collect_secs)

    # Snapshot events before any cleanup (cleanup can hang in WinMM)
    with lock:
        snap = list(events)
    print(f"got {len(snap)} sysex events; matching to addresses...", flush=True)
    events = snap

    # Parse and match — skip close() as WinMM unprepare hangs sometimes;
    # we'll os._exit at the end and let the OS clean up handles.
    by_addr = {}
    for e in events:
        p = parse_dt1(e)
        if not p:
            continue
        addr, payload = p
        by_addr[addr] = payload

    names = {}
    missing = []
    for mem_n in range(args.start, args.end + 1):
        addr = memory_addr(mem_n)
        payload = by_addr.get(addr)
        if payload is None or len(payload) < NAME_LEN:
            missing.append(mem_n)
            names[str(mem_n)] = {"addr": f"{addr:08X}", "name": None,
                                  "error": "no_reply"}
            continue
        ascii_name = "".join(chr(b) if 32 <= b <= 126 else "?"
                              for b in payload[:NAME_LEN])
        names[str(mem_n)] = {"addr": f"{addr:08X}", "name": ascii_name}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(names, indent=2))
    print(f"\nwrote {out_path} ({len(names)} entries; {len(missing)} missing)", flush=True)
    if missing:
        print(f"missing: {missing[:30]}{'...' if len(missing) > 30 else ''}", flush=True)

    # Print first 30 names
    print("\nFirst 30 entries:")
    for mem_n in range(args.start, min(args.start + 30, args.end + 1)):
        e = names[str(mem_n)]
        print(f"  mem {mem_n:3d}  0x{e['addr']}  '{e.get('name')}'")

    # Force exit — skipping the WinMM cleanup that tends to hang
    import os
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
