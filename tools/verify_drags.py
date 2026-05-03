"""
Scan all drag pcaps and identify ones that didn't capture a valid effect-set
DT1 (i.e. nothing landed). Output the list so we can redo those.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TYPEBAR_DIR = ROOT / "captures" / "typebar_full"


def has_drag_dt1s(pcap: Path) -> dict:
    jsonl = pcap.with_suffix(".jsonl")
    if not jsonl.exists():
        subprocess.run(
            ["python", str(Path(__file__).parent / "pcap_to_jsonl.py"),
             str(pcap), "--out", str(jsonl)], capture_output=True)
    if not jsonl.exists():
        return {"valid": False, "reason": "no jsonl"}
    n_dt1 = 0
    has_10001100 = False
    has_chain_order = False
    triplet = None
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex" or ev.get("dir") != "host->dev":
                continue
            raw = bytes.fromhex(ev["hex"])
            if len(raw) < 16 or raw[8] != 0x12:
                continue
            n_dt1 += 1
            addr = int.from_bytes(raw[9:13], "big")
            if addr == 0x10001100:
                has_10001100 = True
                if len(raw) >= 18:
                    triplet = raw[13:13+min(3, len(raw)-15)].hex().upper()
            if addr == 0x10000F00:
                has_chain_order = True
    return {
        "valid": has_10001100,
        "n_dt1": n_dt1,
        "has_chain_order": has_chain_order,
        "triplet": triplet,
    }


def main():
    bad = []
    good = []
    for page_dir in sorted(TYPEBAR_DIR.glob("page*")):
        for eff_dir in sorted(page_dir.iterdir()):
            if not eff_dir.is_dir():
                continue
            pcap = eff_dir / "drag.pcap"
            if not pcap.exists():
                bad.append((str(eff_dir.relative_to(TYPEBAR_DIR)), "no pcap"))
                continue
            info = has_drag_dt1s(pcap)
            if info["valid"]:
                good.append((str(eff_dir.relative_to(TYPEBAR_DIR)), info))
            else:
                bad.append((str(eff_dir.relative_to(TYPEBAR_DIR)), info))
    print(f"GOOD: {len(good)}")
    for name, info in good:
        print(f"  {name}: triplet={info['triplet']}, dt1={info['n_dt1']}")
    print(f"\nBAD ({len(bad)}):")
    for name, info in bad:
        print(f"  {name}: {info}")


if __name__ == "__main__":
    main()
