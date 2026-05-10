"""Apply verified corrections from captures/effect_catalog_corrections.json
on top of captures/bts_effect_catalog.json:

1. Remove phantom labels (per-TYPE knob entries that don't exist on
   the device — discovered when their catalog address collides with
   another, real knob).
2. De-duplicate within-effect duplicate addresses (catalog generator
   bug from sub-section chart text — keeps one entry, marks the
   removal in `_dedup_removed`).
3. Apply knob_overrides (per-TYPE address corrections / new entries
   for verified addresses).
4. Apply dropdown_overrides (SP TYPE etc. placed at wrong addresses).
5. Mark entries that are catalog-correct based on `verified_correct`.

Reads:  captures/bts_effect_catalog.json  +  captures/effect_catalog_corrections.json
Writes: captures/bts_effect_catalog.json  (in place; backed up to .bak)
"""
from __future__ import annotations
import json
import shutil
from collections import OrderedDict
from pathlib import Path


REPO = Path(__file__).parent.parent
CATALOG_PATH = REPO / "captures/bts_effect_catalog.json"
CORRECTIONS_PATH = REPO / "captures/effect_catalog_corrections.json"
BACKUP_PATH = REPO / "captures/bts_effect_catalog.json.bak"


def find_knob(knobs: list, label: str) -> int | None:
    for i, k in enumerate(knobs):
        if k.get("label") == label:
            return i
    return None


def find_dropdown(dropdowns: list, label: str) -> int | None:
    for i, d in enumerate(dropdowns):
        if d.get("label") == label:
            return i
    return None


def main():
    if not CATALOG_PATH.exists():
        raise SystemExit(f"missing {CATALOG_PATH}")
    if not CORRECTIONS_PATH.exists():
        raise SystemExit(f"missing {CORRECTIONS_PATH}")

    catalog = json.loads(CATALOG_PATH.read_text())
    corrections = json.loads(CORRECTIONS_PATH.read_text())

    # Backup
    shutil.copy(CATALOG_PATH, BACKUP_PATH)
    print(f"  backed up to {BACKUP_PATH}")

    # Build a per-effect change log
    changes: dict[str, list[str]] = {}

    # --- 1. Remove phantom labels ----------------------------------
    for type_hex, labels in corrections.get("remove_phantom_labels", {}).items():
        if type_hex.startswith("_"):
            continue
        entry = catalog.get(type_hex)
        if not entry:
            continue
        knobs = entry.get("knobs", [])
        before = len(knobs)
        kept = []
        for k in knobs:
            if k.get("label") in labels:
                changes.setdefault(type_hex, []).append(
                    f"removed phantom knob '{k['label']}' "
                    f"(was at {k.get('address','?')})"
                )
                continue
            kept.append(k)
        entry["knobs"] = kept
        if len(kept) != before:
            print(f"  {type_hex}: removed {before-len(kept)} phantom knobs")

    # --- 2. De-duplicate same-address-same-label entries ----------
    # Within each effect, keep first-seen for any (address, label) pair
    # that repeats. Same-address with different labels is left alone
    # because some catalog mishaps had real knobs colliding wrongly.
    for type_hex, entry in catalog.items():
        if type_hex.startswith("_"):
            continue
        knobs = entry.get("knobs", [])
        seen = set()
        deduped = []
        removed = []
        for k in knobs:
            key = (k.get("address"), k.get("label"))
            if key in seen and key[0] is not None:
                removed.append(k)
                continue
            seen.add(key)
            deduped.append(k)
        if removed:
            entry["knobs"] = deduped
            for k in removed:
                changes.setdefault(type_hex, []).append(
                    f"deduped duplicate knob '{k['label']}' at {k['address']}"
                )

    # --- 3. Apply knob_overrides ----------------------------------
    for type_hex, overrides in corrections.get("knob_overrides", {}).items():
        if type_hex.startswith("_"):
            continue
        entry = catalog.get(type_hex)
        if not entry:
            continue
        knobs = entry.get("knobs", [])
        for label, override in overrides.items():
            if label.startswith("_"):
                continue
            idx = find_knob(knobs, label)
            new_addr = override.get("address")
            # Schema: any non-underscored key in override is copied
            # to the catalog knob (except 'address' which is handled
            # explicitly). Underscored keys (_note, _visible_on_...)
            # are copied as-is for human-readable annotation.
            # _fix_enum_min / _fix_enum_values: corrections for enum knobs
            # where the probe sampled an incomplete raw range (e.g.
            # MIC DISTANCE probed raw 1..2 missed raw 0 = SHORT).
            # Rebuild raw_min, raw_max, values, raw_to_display from the
            # documented enum.
            enum_min = override.pop("_fix_enum_min", None)
            enum_values = override.pop("_fix_enum_values", None)
            extra_fields = {k: v for k, v in override.items()
                            if k != "address"}
            if idx is not None:
                old_addr = knobs[idx].get("address")
                if old_addr != new_addr:
                    changes.setdefault(type_hex, []).append(
                        f"corrected knob '{label}': {old_addr} -> {new_addr}"
                    )
                knobs[idx]["address"] = new_addr
                # remove inferred-flag if previously set
                knobs[idx].pop("_address_inferred", None)
                knobs[idx].pop("_address_verified_2026_05_10", None)
                knobs[idx]["_address_verified_2026_05_10"] = True
                if enum_values is not None:
                    # Rebuild enum fields from the documented value list.
                    rmin = enum_min if enum_min is not None else 0
                    rmax = rmin + len(enum_values) - 1
                    rtd = {str(rmin + i): v for i, v in enumerate(enum_values)}
                    old_values = knobs[idx].get("values")
                    knobs[idx]["raw_min"] = rmin
                    knobs[idx]["raw_max"] = rmax
                    knobs[idx]["values"] = list(enum_values)
                    knobs[idx]["raw_to_display"] = rtd
                    changes.setdefault(type_hex, []).append(
                        f"  '{label}' enum extended: {old_values} -> "
                        f"{list(enum_values)} (raw {rmin}..{rmax})"
                    )
                for fk, fv in extra_fields.items():
                    knobs[idx][fk] = fv
                    if fk == "visible_on_variants":
                        changes.setdefault(type_hex, []).append(
                            f"  '{label}' visible_on_variants = {fv}"
                        )
            else:
                # Add as a new entry
                new_entry = {
                    "address": new_addr,
                    "label": label,
                    "_address_verified_2026_05_10": True,
                    **extra_fields,
                }
                knobs.append(new_entry)
                changes.setdefault(type_hex, []).append(
                    f"added knob '{label}' at {new_addr}"
                )
                if "visible_on_variants" in extra_fields:
                    changes.setdefault(type_hex, []).append(
                        f"  '{label}' visible_on_variants = {extra_fields['visible_on_variants']}"
                    )

    # --- 4. Apply dropdown_overrides ------------------------------
    for type_hex, overrides in corrections.get("dropdown_overrides", {}).items():
        if type_hex.startswith("_"):
            continue
        entry = catalog.get(type_hex)
        if not entry:
            continue
        dropdowns = entry.setdefault("dropdowns", [])
        for label, override in overrides.items():
            if label.startswith("_"):
                continue
            idx = find_dropdown(dropdowns, label)
            new_addr = override.get("address")
            if idx is not None:
                old_addr = dropdowns[idx].get("address")
                if old_addr != new_addr:
                    changes.setdefault(type_hex, []).append(
                        f"corrected dropdown '{label}': {old_addr} -> {new_addr}"
                    )
                dropdowns[idx]["address"] = new_addr
                dropdowns[idx]["_address_verified_2026_05_10"] = True

    # --- 5. Mark verified-correct entries -------------------------
    for type_hex, labels in corrections.get("verified_correct", {}).items():
        if type_hex.startswith("_"):
            continue
        entry = catalog.get(type_hex)
        if not entry:
            continue
        for label in labels:
            idx = find_knob(entry.get("knobs", []), label)
            if idx is not None:
                entry["knobs"][idx]["_address_verified_2026_05_10"] = True

    # --- write ----------------------------------------------------
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2))
    print(f"\n  wrote {CATALOG_PATH}")

    # change summary
    print(f"\n=== changes per effect ({sum(len(v) for v in changes.values())} total) ===")
    for type_hex in sorted(changes):
        print(f"\n{type_hex}:")
        for line in changes[type_hex]:
            print(f"  {line}")


if __name__ == "__main__":
    main()
