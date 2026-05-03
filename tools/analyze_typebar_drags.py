"""
Analyze the per-effect drag captures produced by drag_each_typebar.py.

For each `dragNN_NAME.pcap`:
  1. Convert to JSONL via pcap_to_jsonl.
  2. Extract the host->dev DT1 writes — these are the atomic "set slot 0
     to this effect" command sequence.
  3. Extract the device->host DT1 replies that arrived during the drag —
     these reveal the parameter defaults for the new effect.
  4. Identify the type-byte triplet at 0x10001100 (3 bytes).
  5. Save a per-effect record.

Output: docs/effects/typebar.md plus per-effect snapshots.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def parse_pcap_to_jsonl(pcap: Path, jsonl: Path):
    if jsonl.exists() and jsonl.stat().st_mtime >= pcap.stat().st_mtime:
        return
    subprocess.run([
        "python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
        str(pcap), "--out", str(jsonl),
    ], capture_output=True)


def is_gx10_dt1(hex_str: str) -> bool:
    raw = bytes.fromhex(hex_str)
    return (len(raw) >= 16 and raw[0] == 0xF0 and raw[-1] == 0xF7
            and raw[1] == 0x41 and raw[3:8] == b"\x00\x00\x00\x00\x0B"
            and raw[8] == 0x12)


def parse_dt1(hex_str: str):
    """Return (addr, payload_bytes) for a Roland DT1 SysEx."""
    raw = bytes.fromhex(hex_str)
    addr = int.from_bytes(raw[9:13], "big")
    payload = raw[13:-2]
    return addr, payload


def extract_drag_record(jsonl: Path):
    host_writes = []
    dev_replies = []
    triplet_at_10001100 = None
    chain_order = None
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex":
                continue
            if not is_gx10_dt1(ev["hex"]):
                continue
            addr, payload = parse_dt1(ev["hex"])
            if ev.get("dir") == "host->dev":
                host_writes.append({
                    "t": ev.get("t", 0.0),
                    "addr": f"{addr:08X}",
                    "data_hex": payload.hex().upper(),
                    "len": len(payload),
                })
                if 0x10001100 <= addr <= 0x10001102 and len(payload) == 1:
                    if triplet_at_10001100 is None:
                        triplet_at_10001100 = {0: None, 1: None, 2: None}
                    triplet_at_10001100[addr - 0x10001100] = payload[0]
                if addr == 0x10001100 and len(payload) == 3:
                    triplet_at_10001100 = {0: payload[0], 1: payload[1], 2: payload[2]}
                if addr == 0x10000F00 and len(payload) >= 3:
                    chain_order = payload.hex().upper()
            else:
                dev_replies.append({
                    "t": ev.get("t", 0.0),
                    "addr": f"{addr:08X}",
                    "data_hex": payload.hex().upper(),
                    "len": len(payload),
                })

    triplet = None
    if triplet_at_10001100:
        triplet = "{:02X} {:02X} {:02X}".format(
            triplet_at_10001100.get(0, 0),
            triplet_at_10001100.get(1, 0),
            triplet_at_10001100.get(2, 0),
        )
    return {
        "host_dt1_count": len(host_writes),
        "dev_reply_count": len(dev_replies),
        "triplet_0x10001100": triplet,
        "chain_order_hex": chain_order,
        "host_writes": host_writes[:30],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", required=True)
    ap.add_argument("--out", required=True, help="output Markdown file")
    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    pcaps = sorted(in_dir.glob("drag*.pcap"))

    rows = []
    for pcap in pcaps:
        m = re.match(r"drag(\d+)_(.+)\.pcap", pcap.name)
        if not m:
            continue
        idx = int(m.group(1))
        name = m.group(2)
        jsonl = pcap.with_suffix(".jsonl")
        parse_pcap_to_jsonl(pcap, jsonl)
        rec = extract_drag_record(jsonl)
        rec.update({"idx": idx, "name": name, "pcap": pcap.name})
        rows.append(rec)

    rows.sort(key=lambda r: r["idx"])

    md = ["# Type-bar effect map", "",
          "Captured by `drag_each_typebar.py`. Each row is one drag of a type-bar",
          "item onto chain slot 0 (after restoring U10-1 INIT). The triplet at",
          "`0x10001100` is the per-effect identity (category, modifier, sub).",
          "",
          "| # | Type bar | Triplet @ 0x10001100 | host DT1 count | reply count |",
          "|---|----------|---------------------|----------------|-------------|"]
    for r in rows:
        md.append(f"| {r['idx']:2d} | {r['name']} | `{r['triplet_0x10001100']}` | {r['host_dt1_count']} | {r['dev_reply_count']} |")

    md.append("\n## Full DT1 sequence per effect\n")
    for r in rows:
        md.append(f"### {r['idx']:2d} {r['name']}")
        md.append("")
        md.append("```")
        for w in r["host_writes"]:
            md.append(f"  t={w['t']:7.3f} DT1 0x{w['addr']} = {w['data_hex']} ({w['len']}B)")
        md.append("```")
        md.append("")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {args.out}: {len(rows)} effects mapped")


if __name__ == "__main__":
    main()
