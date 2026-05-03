"""Label each captured effect's TYPE byte with the official enum name.

Reads `triplet_at_10001100` from every summary.json, decodes the first
byte through FX_TYPE_NAME, and writes back `fx_type_official` and
`fx_type_byte` fields. Also generates a master cross-reference table.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fx_type_enum import FX_TYPE_NAME

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"


def main():
    rows = []
    labelled = 0
    for sp in sorted(TYPEBAR.glob("page*/*/summary.json")):
        s = json.loads(sp.read_text())
        triplet = s.get("triplet_at_10001100", "")
        if not triplet or len(triplet) < 2:
            continue
        type_byte = int(triplet[:2], 16)
        official = FX_TYPE_NAME.get(type_byte, "<UNKNOWN>")
        s["fx_type_byte"] = type_byte
        s["fx_type_official"] = official
        sp.write_text(json.dumps(s, indent=2, default=list))
        rows.append((s["page"], s["idx"], s["name"], type_byte, official))
        labelled += 1

    rows.sort(key=lambda r: (r[3]))  # sort by type byte
    print(f"Labelled {labelled} effects.\n")
    print(f"{'byte':>5}  {'official':28s}  {'our_name':18s}  page,idx")
    print("-" * 70)
    for page, idx, name, byte, official in rows:
        match = "OK" if (
            name.upper().replace("_", " ").replace("-", " ").replace(" ", "")
            in official.replace("_", " ").replace("-", " ").replace(" ", "")
            or official.replace("_", " ").replace("-", " ").replace(" ", "")
            in name.upper().replace("_", " ").replace("-", " ").replace(" ", "")
        ) else "?"
        print(f"  0x{byte:02X}  {official:28s}  {name:18s}  p{page},i{idx:02d}  {match}")


if __name__ == "__main__":
    main()
