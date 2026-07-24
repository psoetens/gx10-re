"""How early after a patch-select can we RQ1 user memory safely?

Motivation (gxnarly patch-load flow, 2026-07-24)
------------------------------------------------
gxnarly currently waits a hardcoded 1.2 s after a patch-select before
reading the body, because the device's own bulk-emit lands ~1126 ms
later (see docs/gaps.md §8) and reading into that burst was assumed
unsafe. But the body it wants is also available in USER MEMORY at
`0x20000000 + n*0x60000`, which is STATIC — it does not depend on the
device finishing its load. Memory reads are also address-disjoint from
the two things the device emits unsolicited:

    device staging emit     0x00200xxx
    device partial body     0x10xxxxxx
    this probe's read       0x2xxxxxxx   <- disjoint

So reassembly *should* be unambiguous. Device *stability* under a read
issued while it is mid-load is the open question. This probe measures
both, at a range of offsets after the patch-select.

Method
------
For each delay d, repeat R times:
    1. select the OTHER slot, settle 2 s          (force a real load)
    2. select the TARGET slot            -> t0
    3. wait d ms
    4. RQ1 memory(TARGET), size 0x4000   (single-shot)
    5. collect replies until quiet, classify:
         - in-range DT1s  -> reassembled body (dict addr->payload)
         - other DT1s     -> unsolicited traffic seen during the read
    6. compare the body against a fully-settled REFERENCE read
    7. health check (identity request). No reply => device wedged, ABORT.

Safety: read-only. The only writes are patch-select DT1s to
`0x00000000`, i.e. exactly what pressing a memory footswitch does. The
original memory number is restored at the end. Worst realistic failure
is a device wedge needing a power cycle.

Usage:
    python3 tools/probe_load_read_window.py
    python3 tools/probe_load_read_window.py --target 18 --other 19 --repeats 3
    python3 tools/probe_load_read_window.py --delays 0,300,900,1200
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1, \
    build_identity_request
import midi_sniff
from device_id import require_alive_raw

BODY_SIZE = 0x4000


# --- address helpers -------------------------------------------------

def unpack7(addr: int) -> int:
    """Wire address (4x 7-bit bytes) -> linear offset."""
    return (((addr >> 24) & 0x7F) << 21 | ((addr >> 16) & 0x7F) << 14
            | ((addr >> 8) & 0x7F) << 7 | (addr & 0x7F))


def pack7(lin: int) -> int:
    return (((lin >> 21) & 0x7F) << 24 | ((lin >> 14) & 0x7F) << 16
            | ((lin >> 7) & 0x7F) << 8 | (lin & 0x7F))


def user_memory_address(n: int) -> int:
    """Mirror of gxnarly LiveDeviceLink.userMemoryAddress(_:)."""
    base_lin = 0x4000000          # pack7bit(0x20000000)
    stride_lin = 0x18000          # 6 << 14  (= +0x60000 in wire form)
    return pack7(base_lin + n * stride_lin)


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def is_identity_reply(raw) -> bool:
    return bool(raw) and len(raw) > 6 and raw[0] == 0xF0 and raw[3] == 0x06 \
        and raw[4] == 0x02


def encode_n(n: int) -> bytes:
    return bytes([(n >> 12) & 0xF, (n >> 8) & 0xF, (n >> 4) & 0xF, n & 0xF])


def decode_n(b: bytes) -> int:
    return ((b[0] & 0xF) << 12) | ((b[1] & 0xF) << 8) | \
           ((b[2] & 0xF) << 4) | (b[3] & 0xF)


# --- probe core ------------------------------------------------------

class Probe:
    def __init__(self, out, events, lock):
        self.out, self.events, self.lock = out, events, lock

    def drain(self):
        with self.lock:
            self.events.clear()

    def snapshot(self):
        with self.lock:
            return list(self.events)

    def select(self, n: int):
        self.out.send_sysex(build_dt1(0x00000000, encode_n(n)))

    def read_memory(self, slot: int, quiet_ms=400, timeout_s=3.0):
        """RQ1 the whole body; return (in_range, unsolicited, duration)."""
        base = user_memory_address(slot)
        base_lin = unpack7(base)
        self.out.send_sysex(build_rq1(base, BODY_SIZE))
        t0 = time.time()
        last_event = t0
        seen = 0
        while True:
            time.sleep(0.02)
            n = len(self.snapshot())
            if n > seen:
                seen, last_event = n, time.time()
            if (time.time() - last_event) * 1000 > quiet_ms:
                break
            if time.time() - t0 > timeout_s:
                break
        duration = time.time() - t0
        in_range, unsolicited = {}, []
        for ts, raw in self.snapshot():
            p = parse_dt1(raw)
            if not p:
                continue
            addr, payload = p
            off = unpack7(addr) - base_lin
            if 0 <= off < BODY_SIZE:
                in_range[addr] = payload
            else:
                unsolicited.append(addr)
        return in_range, unsolicited, duration

    def alive(self, timeout_s=0.8) -> bool:
        self.drain()
        self.out.send_sysex(build_identity_request())
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(0.03)
            for ts, raw in self.snapshot():
                if is_identity_reply(raw):
                    return True
        return False


def compare(ref: dict, got: dict) -> str:
    if not got:
        return "EMPTY"
    missing = set(ref) - set(got)
    extra = set(got) - set(ref)
    differing = [a for a in (set(ref) & set(got)) if ref[a] != got[a]]
    if not missing and not extra and not differing:
        return "IDENTICAL"
    bits = []
    if missing:
        bits.append(f"missing={len(missing)}")
    if extra:
        bits.append(f"extra={len(extra)}")
    if differing:
        bits.append(f"differing={len(differing)}")
    return "MISMATCH(" + ",".join(bits) + ")"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=18, help="V of slot to read")
    ap.add_argument("--other", type=int, default=19, help="V to bounce off")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--delays", default="0,150,300,600,900,1200",
                    help="ms offsets after patch-select to try")
    ap.add_argument("--settle", type=float, default=2.0)
    args = ap.parse_args()
    delays = [int(x) for x in args.delays.split(",")]

    events, lock = [], threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        sys.exit("no GX-10 MIDI input found (USB cable to THIS machine? "
                 "another app holding the port?)")
    s = midi_sniff.Sniffer(in_idx, Path("__nul__.jsonl"), in_name)

    def emit(o):
        if o.get("kind") == "sysex":
            try:
                with lock:
                    events.append((time.time(), bytes.fromhex(o["hex"])))
            except Exception:
                pass
    s._emit = emit
    s.open()
    out_idx, out_name = find_output_port("GX-10")
    if out_idx is None:
        sys.exit("no GX-10 MIDI output found")
    out = MidiOut(out_idx)
    time.sleep(0.3)
    print(f"in='{in_name}' out='{out_name}'")

    require_alive_raw(out, events, lock=lock)
    p = Probe(out, events, lock)

    # Subscribe so the device emits its usual notifications.
    out.send_sysex(build_dt1(0x7F000001, b"\x01"))
    time.sleep(0.3)

    # Remember where the user was, so we can put it back.
    p.drain()
    out.send_sysex(build_rq1(0x00000000, 4))
    time.sleep(0.4)
    original = None
    for ts, raw in p.snapshot():
        q = parse_dt1(raw)
        if q and q[0] == 0x00000000 and len(q[1]) >= 4:
            original = decode_n(q[1])
    print(f"original memory # = {original}")

    # --- REFERENCE: fully settled read -----------------------------
    print(f"\n== reference read (settled {args.settle}s) slot={args.target} ==")
    p.select(args.other)
    time.sleep(args.settle)
    p.select(args.target)
    time.sleep(args.settle)
    p.drain()
    ref, ref_unsol, ref_dt = p.read_memory(args.target)
    print(f"  {len(ref)} DT1 records, {sum(len(v) for v in ref.values())} bytes,"
          f" {ref_dt:.2f}s, unsolicited={len(ref_unsol)}")
    if not ref:
        sys.exit("reference read returned nothing — aborting")

    # Second settled read to prove the comparison is stable at all.
    p.drain()
    ref2, _, _ = p.read_memory(args.target)
    print(f"  settled-vs-settled self-check: {compare(ref, ref2)}")

    # --- R3: edit buffer vs memory right after a clean load --------
    print("\n== R3: edit buffer vs memory (settled) ==")
    p.select(args.other)
    time.sleep(args.settle)
    p.select(args.target)
    time.sleep(args.settle)
    p.drain()
    out.send_sysex(build_rq1(0x10000000, BODY_SIZE))
    time.sleep(1.5)
    eb = {}
    for ts, raw in p.snapshot():
        q = parse_dt1(raw)
        if q and 0 <= unpack7(q[0]) - unpack7(0x10000000) < BODY_SIZE:
            eb[unpack7(q[0]) - unpack7(0x10000000)] = q[1]
    mem_by_off = {unpack7(a) - unpack7(user_memory_address(args.target)): v
                  for a, v in ref.items()}
    common = set(eb) & set(mem_by_off)
    same = sum(1 for o in common if eb[o] == mem_by_off[o])
    print(f"  edit-buffer records={len(eb)} memory records={len(mem_by_off)} "
          f"common={len(common)} identical={same} "
          f"differing={len(common) - same}")

    # --- the actual sweep ------------------------------------------
    print("\n== read-window sweep ==")
    results = []
    wedged = False
    for d in delays:
        for r in range(args.repeats):
            p.select(args.other)
            time.sleep(args.settle)
            p.drain()
            p.select(args.target)
            t0 = time.time()
            time.sleep(d / 1000.0)
            got, unsol, dt = p.read_memory(args.target)
            verdict = compare(ref, got)
            healthy = p.alive()
            row = {"delay_ms": d, "repeat": r, "verdict": verdict,
                   "records": len(got), "unsolicited": len(unsol),
                   "read_s": round(dt, 3),
                   "t_read_start_ms": int((t0 + d / 1000.0 - t0) * 1000),
                   "healthy_after": healthy}
            results.append(row)
            print(f"  d={d:>5}ms r{r}: {verdict:<28} records={len(got):>3} "
                  f"unsol={len(unsol):>3} read={dt:.2f}s "
                  f"alive={'yes' if healthy else 'NO'}")
            if not healthy:
                print("  !! device stopped answering identity — ABORTING")
                wedged = True
                break
        if wedged:
            break

    # Restore.
    if original is not None:
        time.sleep(0.5)
        p.select(original)
        print(f"\nrestored memory # {original}")

    out_path = Path(__file__).parent.parent / "captures" / \
        "load_read_window.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(
        {"target": args.target, "other": args.other,
         "reference_records": len(ref), "wedged": wedged,
         "results": results}, indent=2))
    print(f"wrote {out_path}")

    # --- summary ---------------------------------------------------
    print("\n== summary: earliest offset that is always IDENTICAL + alive ==")
    ok_by_delay = {}
    for row in results:
        ok = row["verdict"] == "IDENTICAL" and row["healthy_after"]
        ok_by_delay.setdefault(row["delay_ms"], []).append(ok)
    safe = [d for d in delays
            if ok_by_delay.get(d) and all(ok_by_delay[d])]
    print(f"  all-clean offsets: {safe if safe else 'NONE'}")
    if wedged:
        print("  NOTE: run aborted early on a wedge — power-cycle the pedal.")
    s.close()


if __name__ == "__main__":
    main()
