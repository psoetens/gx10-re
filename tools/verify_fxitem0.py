"""Read FxItem #0 and compare to a snapshot.bin.

Uses size=0x140 in the RQ1 (each byte ≤ 0x7F). Device replies with as
much as it has — empirically ~179 bytes.
"""
from __future__ import annotations
import argparse
import queue
import sys
import time
import ctypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--port", default="GX-10")
    args = ap.parse_args()
    snapshot = Path(args.snapshot).read_bytes()

    out_idx, _ = midi_send.find_output_port(args.port)
    in_idx, in_name = midi_sniff.find_port(args.port)
    if out_idx is None or in_idx is None:
        print("ERROR: missing port"); return 2

    q: "queue.Queue[bytes]" = queue.Queue()
    sniffer = midi_sniff.Sniffer(in_idx, Path("captures/_probe/verify.jsonl"), in_name)
    sniffer.open()
    # patch the sniffer to push messages to our queue too
    orig_emit = sniffer._emit
    def emit(obj):
        if obj.get("kind") == "sysex":
            try:
                q.put(bytes.fromhex(obj["hex"]))
            except Exception:
                pass
        return orig_emit(obj)
    sniffer._emit = emit

    out = midi_send.MidiOut(out_idx)
    try:
        out.send_sysex(midi_send.build_rq1(0x10001100, 0x140))
        time.sleep(0.4)
    finally:
        out.close()
    sniffer.close()

    # Find the DT1 reply for 0x10001100
    found = None
    while not q.empty():
        msg = q.get_nowait()
        if len(msg) > 14 and msg[8] == 0x12 and msg[9:13] == b"\x10\x00\x11\x00":
            found = bytes(msg[13:-2])  # payload only
            break
    if found is None:
        print("ERROR: no reply"); return 2
    print(f"current FxItem #0 ({len(found)} bytes): {found[:32].hex()}...")
    print(f"snapshot     ({len(snapshot)} bytes): {snapshot[:32].hex()}...")
    if found == snapshot:
        print("EXACT MATCH ✓")
    else:
        # Show byte-by-byte diff
        diffs = []
        for i in range(min(len(found), len(snapshot))):
            if found[i] != snapshot[i]:
                diffs.append((i, snapshot[i], found[i]))
        print(f"DIFFERS at {len(diffs)} of {min(len(found), len(snapshot))} bytes")
        for i, s, c in diffs[:20]:
            print(f"  off=0x{i:02X}: snapshot=0x{s:02X}  current=0x{c:02X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
