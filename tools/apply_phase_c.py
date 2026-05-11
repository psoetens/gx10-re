"""Apply Phase C variant-conditional findings to the catalog.

For each conditional label found:
  - Locate the knob in catalog[effect]['knobs'] or ['dropdowns']
  - Set visible_on_variants = [list of variant indices]
  - Add _visible_on_variant_names = [list of variant name strings]
  - Set _variant_conditional_2026_05_11 = True for audit
"""
from __future__ import annotations
import json
from pathlib import Path


REPO = Path(__file__).parent.parent
CATALOG = REPO / "captures/bts_effect_catalog.json"
OVERLAY = REPO / "captures/effect_catalog_corrections_phase_c.json"


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    findings = overlay.get("findings", {})

    added = 0
    not_found = []
    for tkey, ef in findings.items():
        if "conditional_labels" not in ef:
            continue
        eff = catalog.get(tkey)
        if not eff:
            continue
        names = ef.get("variant_names", [])
        for label, visible_on in ef["conditional_labels"].items():
            # Find by label match (try exact, then with "1: " / "2: " stripped)
            target = None
            for k in eff["knobs"]:
                if k.get("label") == label:
                    target = k
                    break
            if target is None:
                for d in eff.get("dropdowns", []):
                    if d.get("label") == label:
                        target = d
                        break
            if target is None:
                not_found.append((tkey, label))
                continue
            target["visible_on_variants"] = list(visible_on)
            target["_visible_on_variant_names"] = [names[i] for i in visible_on
                                                   if i < len(names)]
            target["_variant_conditional_2026_05_11"] = True
            added += 1

    CATALOG.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"  added visible_on_variants to {added} knobs")
    if not_found:
        print(f"  labels not found in catalog (likely new knobs): "
              f"{len(not_found)}")
        for tkey, lab in not_found[:10]:
            print(f"    {tkey}: {lab!r}")


if __name__ == "__main__":
    main()
