"""Static dup + gap scan over captures/bts_effect_catalog.json.

Two checks:
1. Per-effect, group knobs by address. Any address with >1 knob entry
   is a phantom-duplicate candidate. The Linux side already removed
   the DELAY+ phantoms manually; this scan finds remaining cases for
   automated correction.
2. Per-effect, walk the knob offsets and look for gaps in the
   stride-4 layout. A gap is suspicious — either the catalog is
   missing an entry the device exposes, or the gap is real (e.g.
   conditional/hidden cells like FxItem header bytes).

Outputs:
  reports/duplicate_addresses.md
  reports/address_gaps.md

No BTS or device interaction — pure static analysis.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path


REPO = Path(__file__).parent.parent
CATALOG = REPO / "captures/bts_effect_catalog.json"
DUP_REPORT = REPO / "reports/duplicate_addresses.md"
GAP_REPORT = REPO / "reports/address_gaps.md"


def parse_addr(s: str) -> int:
    return int(s.replace("0x", "").replace("0X", ""), 16)


def find_dups(catalog: dict) -> dict:
    """Return {tkey: {address: [knob_labels]}} for every TYPE that has
    at least one address claimed by >1 knob."""
    dups = {}
    for tkey, eff in catalog.items():
        if tkey.startswith("_"):
            continue
        per_addr = defaultdict(list)
        for k in eff.get("knobs", []):
            addr = k.get("address")
            if not addr:
                continue
            per_addr[addr].append(k.get("label", "?"))
        bad = {a: labels for a, labels in per_addr.items() if len(labels) > 1}
        if bad:
            dups[tkey] = {"title": eff.get("title", "?"), "addr_to_labels": bad}
    return dups


def find_gaps(catalog: dict) -> dict:
    """Return {tkey: gap_list} where each gap_list is offsets that are
    missing from the catalog's stride-4 layout, between the first
    and last claimed offset for that effect. Counts knob addresses
    AND dropdown addresses (since dropdowns also occupy FxItem cells)."""
    gaps = {}
    for tkey, eff in catalog.items():
        if tkey.startswith("_"):
            continue
        knob_offs = {
            parse_addr(k["address"]) - 0x10001100
            for k in eff.get("knobs", [])
            if k.get("address")
        }
        dd_offs = {
            parse_addr(d["address"]) - 0x10001100
            for d in eff.get("dropdowns", [])
            if d.get("address")
        }
        offsets = sorted(knob_offs | dd_offs)
        if not offsets:
            continue
        # Walk stride-4 from first to last claimed offset; report missing.
        first, last = offsets[0], offsets[-1]
        # Stride alignment: param offsets are 0x03, 0x07, 0x0B, ... so
        # they're (4n + 3). Generate that grid from first to last.
        # Round first DOWN to the nearest 4n+3.
        if first % 4 != 3:
            first = first - ((first - 3) % 4)
        expected = list(range(first, last + 1, 4))
        missing = [o for o in expected if o not in offsets]
        if missing:
            gaps[tkey] = {
                "title": eff.get("title", "?"),
                "first_offset": f"0x{first:02X}",
                "last_offset": f"0x{last:02X}",
                "claimed_count": len(offsets),
                "missing_offsets": [f"0x{o:02X}" for o in missing],
            }
    return gaps


def write_dup_report(dups: dict) -> None:
    DUP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Duplicate-address scan",
        "",
        "Per-effect, addresses claimed by more than one knob entry. "
        "Each row is a phantom-candidate from the BTS bulk-enum probe "
        "where two BTS-UI labels resolved to the same FxItem cell.",
        "",
        f"Source: `captures/bts_effect_catalog.json`",
        f"Effects with duplicates: **{len(dups)}**",
        "",
    ]
    if not dups:
        lines.append("_No duplicates._")
    else:
        for tkey in sorted(dups.keys()):
            d = dups[tkey]
            lines.append(f"## {tkey} {d['title']}")
            lines.append("")
            lines.append("| Address | Labels |")
            lines.append("|---|---|")
            for addr in sorted(d["addr_to_labels"].keys()):
                labels = d["addr_to_labels"][addr]
                lines.append(f"| `{addr}` | {' / '.join(labels)} |")
            lines.append("")
    DUP_REPORT.write_text("\n".join(lines), encoding="utf-8")


def write_gap_report(gaps: dict) -> None:
    GAP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Address-gap scan",
        "",
        "Per-effect, FxItem param offsets missing from the catalog "
        "between the first and last claimed offset. A gap is "
        "suspicious — either the catalog is missing an entry the "
        "device exposes, or the gap is real (FxItem header bytes, "
        "fixed-zero filler bytes from the chart, or addresses with "
        "no UI exposure).",
        "",
        f"Source: `captures/bts_effect_catalog.json`",
        f"Effects with gaps: **{len(gaps)}**",
        "",
    ]
    if not gaps:
        lines.append("_No gaps._")
    else:
        for tkey in sorted(gaps.keys()):
            g = gaps[tkey]
            lines.append(f"## {tkey} {g['title']}")
            lines.append("")
            lines.append(f"- Span: {g['first_offset']} … {g['last_offset']}")
            lines.append(f"- Claimed: {g['claimed_count']} knobs")
            lines.append(f"- Missing: {', '.join(g['missing_offsets'])}")
            lines.append("")
    GAP_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    dups = find_dups(catalog)
    gaps = find_gaps(catalog)
    write_dup_report(dups)
    write_gap_report(gaps)
    n_knobs = sum(len(eff.get("knobs", []))
                  for eff in catalog.values()
                  if isinstance(eff, dict) and not eff.get("knobs") is None)
    print(f"  catalog effects: {sum(1 for k in catalog if not k.startswith('_'))}")
    print(f"  catalog knobs:   {n_knobs}")
    print(f"  dup effects:     {len(dups)}")
    print(f"  gap effects:     {len(gaps)}")
    if dups:
        print(f"  -> {DUP_REPORT}")
    if gaps:
        print(f"  -> {GAP_REPORT}")


if __name__ == "__main__":
    main()
