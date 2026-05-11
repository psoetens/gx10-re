"""Apply Phase B-2 truncated lookup table extensions to the catalog."""
from __future__ import annotations
import json
from pathlib import Path


REPO = Path(__file__).parent.parent
CATALOG = REPO / "captures/bts_effect_catalog.json"
OVERLAY = REPO / "captures/effect_catalog_corrections_phase_b2.json"


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    findings = overlay.get("findings", {})

    knobs_extended = 0
    entries_added = 0
    for tkey, eff_findings in findings.items():
        ek = eff_findings.get("extended_knobs")
        if not ek:
            continue
        eff = catalog.get(tkey)
        if not eff:
            continue
        for label, info in ek.items():
            new = info.get("new_entries", {})
            if not new:
                continue
            target = None
            for k in eff["knobs"]:
                if k.get("label") == label:
                    target = k
                    break
            if target is None:
                continue
            rd = target.get("raw_to_display", {})
            for r, v in new.items():
                rd[r] = v
                entries_added += 1
            target["raw_to_display"] = rd
            # Update raw_max / value_max from the extended table
            keys = [int(r) for r in rd.keys()]
            target["raw_max"] = max(keys)
            # value_max best effort: try to parse the value at max raw
            max_display = rd[str(max(keys))]
            target.pop("_probe_likely_truncated", None)
            target["_lookup_extended_2026_05_11"] = True
            target["_lookup_max_display"] = max_display
            knobs_extended += 1

    CATALOG.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"  knobs extended: {knobs_extended}")
    print(f"  new lookup entries: {entries_added}")
    print(f"  wrote {CATALOG}")


if __name__ == "__main__":
    main()
