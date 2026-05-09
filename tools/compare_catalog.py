"""Compare v2 ground-truth catalog vs typebar_full's claimed mapping.

Reports per-effect:
- correct: address-label pairs that match
- permuted: address has a different label in typebar_full
- missing_in_typebar: v2 found a label at addr that typebar didn't list
- only_typebar: typebar listed addr that v2 didn't see (could be hidden
  or the effect doesn't have it visible)

Outputs:
- captures/bts_typebar_resweep_v2/catalog_diff.md   — per-effect verdict
- captures/bts_typebar_resweep_v2/catalog_corrected.json — the v2
  ground-truth in a normalised format the catalog regenerator can ingest
"""
from __future__ import annotations
import argparse
import glob
import json
from pathlib import Path


def load_typebar() -> dict[int, dict]:
    by_type = {}
    for f in sorted(glob.glob("captures/typebar_full/page*/*/summary.json")):
        try: d = json.load(open(f))
        except Exception: continue
        triplet = d.get("triplet_at_10001100", "")
        if len(triplet) >= 2:
            by_type[int(triplet[:2], 16)] = d
    return by_type


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="captures/bts_typebar_resweep_v2/catalog.json")
    ap.add_argument("--out-md", default="captures/bts_typebar_resweep_v2/catalog_diff.md")
    ap.add_argument("--out-json", default="captures/bts_typebar_resweep_v2/catalog_corrected.json")
    args = ap.parse_args()

    v2 = json.loads(Path(args.catalog).read_text())
    typebar = load_typebar()
    print(f"v2 entries: {len(v2)}; typebar entries: {len(typebar)}")

    md = ["# Catalog diff — typebar_full claims vs v2 ground truth", ""]
    md.append("| TYPE | Effect | typebar count | v2 count | mapped | status |")
    md.append("|------|--------|--------------:|---------:|-------:|--------|")

    corrected = {}

    for type_byte_hex, v2_entry in sorted(v2.items()):
        type_byte = int(type_byte_hex, 16)
        name = v2_entry["effect_name_typebar"]
        v2_addrs = v2_entry["labels_by_addr"]
        tbf = typebar.get(type_byte, {})
        tbf_knobs = tbf.get("knobs", [])
        tbf_addrs = {}
        for k in tbf_knobs:
            addr = k.get("address")
            label = k.get("name_manual_v2") or k.get("name_manual") or "?"
            if addr:
                tbf_addrs[f"0x{addr.upper()}" if addr.startswith("0x") else f"0x{addr.upper()}"] = label

        # Normalize addresses to upper-case 0x prefix
        v2_normed = {a.upper(): l for a, l in v2_addrs.items()}
        tbf_normed = {a.upper(): l for a, l in tbf_addrs.items()}

        all_addrs = sorted(set(v2_normed) | set(tbf_normed))

        correct = []
        permuted = []
        missing_in_typebar = []
        only_typebar = []
        for a in all_addrs:
            v2_lab = v2_normed.get(a)
            tb_lab = tbf_normed.get(a)
            if v2_lab and tb_lab:
                if v2_lab == tb_lab:
                    correct.append((a, v2_lab))
                else:
                    permuted.append((a, v2_lab, tb_lab))
            elif v2_lab and not tb_lab:
                missing_in_typebar.append((a, v2_lab))
            elif tb_lab and not v2_lab:
                only_typebar.append((a, tb_lab))

        # Status summary
        if v2_entry["n_filled_knobs"] == 0:
            status = "❓ v2 found 0 knobs (BTS UI race)"
        elif not permuted and not only_typebar and not missing_in_typebar:
            status = "✅ exact match"
        elif permuted:
            status = f"❌ {len(permuted)} permuted"
        elif missing_in_typebar:
            status = f"⚠️ {len(missing_in_typebar)} new (typebar incomplete)"
        elif only_typebar:
            status = f"⚠️ {len(only_typebar)} typebar-only"
        else:
            status = "?"

        md.append(f"| `{type_byte_hex}` | {name} | {len(tbf_addrs)} | "
                  f"{v2_entry['n_filled_knobs']} | {len(v2_normed)} | {status} |")

        corrected[type_byte_hex] = {
            "effect_name_typebar": name,
            "ground_truth_labels": v2_normed,
            "typebar_claimed_labels": tbf_normed,
            "correct": [{"addr": a, "label": l} for (a, l) in correct],
            "permuted": [{"addr": a, "real": r, "typebar": t} for (a, r, t) in permuted],
            "missing_in_typebar": [{"addr": a, "label": l} for (a, l) in missing_in_typebar],
            "only_typebar": [{"addr": a, "label": l} for (a, l) in only_typebar],
        }

    md.append("")
    md.append("## Detail per effect")
    md.append("")
    for type_byte_hex, c in sorted(corrected.items()):
        md.append(f"### `{type_byte_hex}` {c['effect_name_typebar']}")
        md.append("")
        if c["correct"]:
            md.append("Correct:")
            for x in c["correct"]:
                md.append(f"- `{x['addr']}` → **{x['label']}**")
            md.append("")
        if c["permuted"]:
            md.append("**Permuted (typebar wrong):**")
            for x in c["permuted"]:
                md.append(f"- `{x['addr']}` → real **{x['real']}** (typebar said: {x['typebar']})")
            md.append("")
        if c["missing_in_typebar"]:
            md.append("Missing in typebar:")
            for x in c["missing_in_typebar"]:
                md.append(f"- `{x['addr']}` → **{x['label']}** (typebar didn't have it)")
            md.append("")
        if c["only_typebar"]:
            md.append("Typebar-only (not visible in v2 — possibly enum/hidden):")
            for x in c["only_typebar"]:
                md.append(f"- `{x['addr']}` → typebar said **{x['label']}**")
            md.append("")

    Path(args.out_md).write_text("\n".join(md), encoding="utf-8")
    Path(args.out_json).write_text(json.dumps(corrected, indent=2))
    print(f"wrote {args.out_md}")
    print(f"wrote {args.out_json}")

    # Summary count
    perm = sum(1 for c in corrected.values() if c["permuted"])
    miss = sum(1 for c in corrected.values() if c["missing_in_typebar"])
    extra = sum(1 for c in corrected.values() if c["only_typebar"])
    exact = sum(1 for c in corrected.values()
                if not c["permuted"] and not c["missing_in_typebar"] and not c["only_typebar"])
    print(f"\nSummary across {len(corrected)} effects:")
    print(f"  exact match:           {exact}")
    print(f"  permuted (typebar wrong): {perm}")
    print(f"  typebar incomplete (new): {miss}")
    print(f"  typebar extra:         {extra}")


if __name__ == "__main__":
    main()
