"""Quick sanity report across all per_type_done effects."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"


def main():
    total_extra = 0
    total_layouts = 0
    rows = []
    for page_dir in sorted(TYPEBAR.glob("page*")):
        for eff_dir in sorted(page_dir.iterdir()):
            done = eff_dir / "per_type_done.flag"
            if not done.exists():
                continue
            sp = eff_dir / "summary.json"
            if not sp.exists():
                continue
            try:
                summary = json.loads(sp.read_text())
            except:
                continue
            n_layouts = len(summary.get("per_type_layouts", []))
            n_master = len(summary.get("master_knob_positions", []))
            n_base = len(summary.get("knobs", []))
            n_extra = len(summary.get("knobs_extra", []))
            total_layouts += n_layouts
            total_extra += n_extra
            rows.append({
                "page": summary.get("page"),
                "idx": summary.get("idx"),
                "name": summary.get("name"),
                "type_max": summary.get("type_max"),
                "n_layouts": n_layouts,
                "n_master": n_master,
                "n_base": n_base,
                "n_extra": n_extra,
            })
    rows.sort(key=lambda r: (r["page"], r["idx"]))
    print(f"{'NAME':18s} {'TYPES':>6s} {'LAY':>4s} {'MASTER':>7s} {'BASE':>5s} {'EXTRA':>6s}")
    for r in rows:
        flag = "  *" if r["n_extra"] > 0 else "   "
        print(f"{r['name']:18s} {r['type_max']+1:6d} {r['n_layouts']:4d} "
              f"{r['n_master']:7d} {r['n_base']:5d} {r['n_extra']:6d}{flag}")
    print(f"\nTotal effects: {len(rows)}, total layouts: {total_layouts}, "
          f"total new-knob records: {total_extra}")


if __name__ == "__main__":
    main()
