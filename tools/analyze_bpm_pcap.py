"""Decode the BPM byte→display mapping from the captured BPM sweep pcap.

After investigate_bpm.py drives the BPM knob from 250→40 (with screenshots
at saturation points), this script extracts every DT1 at the BPM address
(0x10000F02) and prints the byte sequence so we can deduce the mapping
(likely 14-bit nibble pair: byte_hi*16 + byte_lo).
"""
import json
import subprocess
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent


def main():
    pcap = ROOT / "captures" / "bpm_test" / "bpm_sweep.pcap"
    jsonl = pcap.with_suffix(".jsonl")
    if not jsonl.exists() and pcap.exists():
        subprocess.run([sys.executable,
                        str(Path(__file__).parent / "pcap_to_jsonl.py"),
                        str(pcap), "--out", str(jsonl)],
                       check=True)
    if not jsonl.exists():
        print(f"no jsonl found at {jsonl}")
        return

    BPM_ADDR = 0x10000F02
    events = []
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except:
                continue
            if ev.get("kind") != "sysex" or ev.get("dir") != "host->dev":
                continue
            raw = bytes.fromhex(ev["hex"])
            if len(raw) < 16 or raw[8] != 0x12:
                continue
            addr = int.from_bytes(raw[9:13], "big")
            if addr != BPM_ADDR:
                continue
            payload = raw[13:-2]
            events.append(payload)

    print(f"Total BPM DT1 events: {len(events)}")
    if not events:
        return

    # Look at distinct payloads in order of appearance
    seen_first = []
    seen = set()
    for p in events:
        h = p.hex().upper()
        if h not in seen:
            seen.add(h); seen_first.append(p)
    print(f"Distinct payload values: {len(seen_first)}")

    print("\nFirst 30 distinct payloads (sweep direction = first ones seen):")
    for p in seen_first[:30]:
        print(f"  bytes={list(p)}  hex={p.hex().upper()}")
    print("\nLast 30 distinct payloads:")
    for p in seen_first[-30:]:
        print(f"  bytes={list(p)}  hex={p.hex().upper()}")

    # Try to decode: assume payload is 4 bytes, split into 4 nibbles.
    # Likely encoding: value = byte0*4096 + byte1*256 + byte2*16 + byte3
    # OR value = byte2*16 + byte3 (low 8 bits in two nibbles).
    print("\nDecoded values (assuming low-2-bytes nibble pair, byte[2]*16 + byte[3]):")
    distinct_vals = []
    seen_v = set()
    for p in events:
        if len(p) >= 4:
            v = p[2] * 16 + p[3]
            if v not in seen_v:
                seen_v.add(v); distinct_vals.append(v)
    print(f"  unique values: {len(distinct_vals)}, range {min(distinct_vals)}..{max(distinct_vals)}")
    print(f"  values: {sorted(distinct_vals)[:20]} ... {sorted(distinct_vals)[-10:]}")

    # Also try: 14-bit two-byte encoding from bytes [1] and [2]
    print("\nDecoded values (byte[1]*16 + byte[2]):")
    distinct_vals = []
    seen_v = set()
    for p in events:
        if len(p) >= 3:
            v = p[1] * 16 + p[2]
            if v not in seen_v:
                seen_v.add(v); distinct_vals.append(v)
    print(f"  unique values: {len(distinct_vals)}, range {min(distinct_vals)}..{max(distinct_vals)}")
    print(f"  values: {sorted(distinct_vals)[:20]} ... {sorted(distinct_vals)[-10:]}")


if __name__ == "__main__":
    main()
