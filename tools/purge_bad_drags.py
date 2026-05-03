"""Delete drag pcaps that didn't capture a valid effect-set DT1, so a re-run
of map_all_effects.py picks them up again."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TYPEBAR_DIR = ROOT / "captures" / "typebar_full"


def is_valid(jsonl: Path) -> bool:
    if not jsonl.exists():
        return False
    has_10001100 = False
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
            addr = int.from_bytes(raw[9:13], "big")
            if addr == 0x10001100:
                has_10001100 = True
                break
    return has_10001100


def main():
    purged = []
    for page_dir in sorted(TYPEBAR_DIR.glob("page*")):
        for eff_dir in sorted(page_dir.iterdir()):
            if not eff_dir.is_dir():
                continue
            pcap = eff_dir / "drag.pcap"
            jsonl = eff_dir / "drag.jsonl"
            if pcap.exists() and is_valid(jsonl):
                continue
            # Purge: delete the directory entirely so the pipeline redoes it.
            shutil.rmtree(eff_dir)
            purged.append(str(eff_dir.relative_to(TYPEBAR_DIR)))
    print(f"purged {len(purged)} bad drag dirs")
    for p in purged:
        print(f"  {p}")


if __name__ == "__main__":
    main()
