"""Apply Phase B bipolar verifications to the catalog.

For each verified bipolar knob (per
captures/effect_catalog_corrections_phase_b.json):
  - raw_min, raw_max := doc_min, doc_max
  - value_min, value_max := doc_min, doc_max
  - clear `_range_inconsistent`
  - add `_range_extended_2026_05_11: true` for audit trail

Failed-verification knobs are left with their existing flags.
"""
from __future__ import annotations
import json
from pathlib import Path


REPO = Path(__file__).parent.parent
CATALOG = REPO / "captures/bts_effect_catalog.json"
OVERLAY = REPO / "captures/effect_catalog_corrections_phase_b.json"


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    findings = overlay.get("findings", {})

    extended = 0
    failed = 0
    for tkey, eff_findings in findings.items():
        if "knobs" not in eff_findings:
            continue
        eff = catalog.get(tkey)
        if not eff:
            continue
        for label, v in eff_findings["knobs"].items():
            if not v.get("verified"):
                failed += 1
                continue
            # Find the knob in the catalog
            target = None
            for k in eff["knobs"]:
                if k.get("label") == label:
                    target = k
                    break
            if target is None:
                continue
            doc_min = v["doc_min"]
            doc_max = v["doc_max"]
            target["raw_min"] = doc_min
            target["raw_max"] = doc_max
            target["value_min"] = doc_min
            target["value_max"] = doc_max
            target.pop("_range_inconsistent", None)
            target["_range_extended_2026_05_11"] = True
            extended += 1

    CATALOG.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"  extended ranges: {extended}")
    print(f"  failed-verification knobs (left alone): {failed}")
    print(f"  wrote {CATALOG}")


if __name__ == "__main__":
    main()
