"""Probe all 96 GX-10 preset names (memories #200..295) via the
load-into-buffer flow.

Presets aren't mapped at a static address (verified — 0x29300000
returns RQ1-NAK). The standard Roland approach is:

  1. Save the user's current memory # (read 4 bytes at 0x00000000).
  2. For each preset N:
       a. Write 4 nibbles of N to 0x00000000 (PatchSelect)
       b. Wait ~150 ms for the device to load
       c. RQ1 0x10000000 size=16 (memory_temp NAME field)
       d. Receive DT1 with the name
  3. Restore the original memory #.

WARNING: this changes the currently-loaded patch on the device. If the
user has unsaved edits in their working memory, they will be LOST.
Press Ctrl+C to abort — the restore-original-patch step still runs.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
from device_profile import detect_and_profile


PATCH_SELECT_ADDR = 0x00000000
MEMORY_TEMP_NAME_ADDR = 0x10000000
NAME_LEN = 16


def encode_memory_n(n: int) -> bytes:
    """4 bytes, low-nibble of each = nibble of n.
    e.g. n=206 -> 0x00CE -> bytes(0x00, 0x00, 0x0C, 0x0E)."""
    return bytes([(n >> 12) & 0xF, (n >> 8) & 0xF,
                  (n >> 4) & 0xF, n & 0xF])


def decode_memory_n(b: bytes) -> int:
    if len(b) < 4:
        return -1
    return ((b[0] & 0xF) << 12) | ((b[1] & 0xF) << 8) | \
           ((b[2] & 0xF) << 4) | (b[3] & 0xF)


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


def wait_for_dt1(events, lock, addr, deadline_ts, seen_idx):
    """Block until a DT1 at `addr` arrives or `deadline_ts` passes.
    Returns (payload_or_None, new_seen_idx)."""
    while time.time() < deadline_ts:
        with lock:
            new = list(events[seen_idx:])
            seen_idx = len(events)
        for e in new:
            p = parse_dt1(e)
            if p and p[0] == addr:
                return p[1], seen_idx
        time.sleep(0.01)
    return None, seen_idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="GX-10")
    ap.add_argument("--out", default="captures/preset_memory_names.json")
    ap.add_argument("--start", type=int, default=200)
    ap.add_argument("--end",   type=int, default=None,
                    help="last preset # inclusive (default: profile.memory_count + presets - 1)")
    ap.add_argument("--load-wait-ms", type=int, default=1500,
                    help="ms to wait after PatchSelect write before reading name "
                         "(test_patch_load.py shows bulk emit completes around "
                         "+1126ms, so 1500 is comfortably past that)")
    args = ap.parse_args()

    model, profile = detect_and_profile(port_substr=args.port)
    # GX-10: 200 user + 96 preset = 296 total -> last index 295
    # GX-100: 200 user + 100 preset = 300 total -> last index 299
    if args.end is None:
        # If memory_count is the user count, preset count is 96 (GX-10) or 100 (GX-100)
        preset_count = profile.get("preset_count", 96)
        args.end = args.start + preset_count - 1
    print(f"Device: {model}", flush=True)
    print(f"Probing presets {args.start}..{args.end} "
          f"({args.end - args.start + 1} memories) "
          f"with {args.load_wait_ms}ms load-wait per probe.", flush=True)

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

    out_idx, _ = find_output_port(args.port)
    out = MidiOut(out_idx)
    time.sleep(0.3)

    seen = 0
    # 1. Save current memory #
    out.send_sysex(build_rq1(PATCH_SELECT_ADDR, 4))
    payload, seen = wait_for_dt1(events, lock, PATCH_SELECT_ADDR,
                                  time.time() + 1.0, seen)
    if payload is None:
        print("ERROR: device did not reply to PatchSelect read")
        sys.exit(2)
    original_n = decode_memory_n(payload)
    print(f"Original memory # = {original_n} ({payload.hex().upper()}). "
          f"Will restore on exit.", flush=True)

    # 2. Loop presets
    names = {}
    missing = []
    try:
        for n in range(args.start, args.end + 1):
            out.send_sysex(build_dt1(PATCH_SELECT_ADDR, encode_memory_n(n)))
            time.sleep(args.load_wait_ms / 1000.0)
            out.send_sysex(build_rq1(MEMORY_TEMP_NAME_ADDR, NAME_LEN))
            payload, seen = wait_for_dt1(events, lock,
                                          MEMORY_TEMP_NAME_ADDR,
                                          time.time() + 0.6, seen)
            if payload and len(payload) >= NAME_LEN:
                ascii_name = "".join(chr(b) if 32 <= b <= 126 else "?"
                                      for b in payload[:NAME_LEN])
                names[str(n)] = {"name": ascii_name,
                                  "raw": payload[:NAME_LEN].hex().upper()}
                if (n - args.start) % 8 == 0 or n == args.end:
                    print(f"  {n:3d}  '{ascii_name}'", flush=True)
            else:
                names[str(n)] = {"name": None, "error": "no_reply"}
                missing.append(n)
                print(f"  {n:3d}  (no reply)", flush=True)
    except KeyboardInterrupt:
        print("\n[Ctrl+C] aborted — will still restore original patch", flush=True)
    finally:
        # 3. Restore original memory #
        if original_n >= 0:
            print(f"\nRestoring memory # {original_n}...", flush=True)
            out.send_sysex(build_dt1(PATCH_SELECT_ADDR, encode_memory_n(original_n)))
            time.sleep(0.3)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(names, indent=2))
    print(f"\nWrote {out_path} ({len(names)} entries; {len(missing)} missing)", flush=True)
    if missing:
        print(f"Missing: {missing[:30]}{'...' if len(missing) > 30 else ''}")

    print("\nFirst 10 preset names:")
    for n in range(args.start, min(args.start + 10, args.end + 1)):
        e = names.get(str(n), {})
        print(f"  P{n - args.start:02d}  preset_n={n}  '{e.get('name')}'")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
