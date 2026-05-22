"""Merge BTS's authoritative parameter database into our existing catalog.

Sources:
  captures/bts_effect_parameter_with_resources.json  (BTS data, gitignored;
      produced by `osascript -l JavaScript tools/parse_bts_effect_parameter.js
      --with-resources`)
  captures/bts_effect_catalog.json                   (our probe-sourced catalog
      with Parameter Guide cross-references and live-device probe samples)

Output:
  catalogs/bts_effect_catalog_complete.json          (the merged catalog)

Rules:
- BTS is the source of truth for: raw_min / raw_max, init, ofs, size,
  templateValue, format_js, factor, showConditions, uniqueName, the set
  of parameters (every BTS param becomes a knob/dropdown entry).
- Our catalog supplies the supplementary fields BTS doesn't have:
  value_min/value_max (display range), unit, step, raw_to_display
  lookup tables, *_documented (Parameter Guide cross-references), and
  *_probe_sample (live device).
- Knob vs dropdown: BTS doesn't tag this directly. We treat a parameter
  as a dropdown when its resourceId points at an enum list whose length
  equals (max - min + 1). Otherwise numeric.
- Same-address rows differing only by showConditions are kept as separate
  entries (preserves variants like MASTER's BPM vs BPM(MIDI)).

The schema mirrors the existing catalog but adds a `bts` sub-object per
section and per knob/dropdown holding the BTS-only fields. Existing
field names are preserved so downstream tools keep working until they
opt into the new fields.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from diff_bts_param_db import TITLE_OVERRIDES, normalise_label, parse_addr, to_rel  # noqa: E402


# Inverse of constant.js's INTEGER_* constants — for serialising back the
# `size` field as a readable label rather than a raw integer.
SIZE_NAMES = {
    0x10000: "INTEGER1x1",
    0x10001: "INTEGER1x2",
    0x10002: "INTEGER1x3",
    0x10003: "INTEGER1x4",
    0x10004: "INTEGER1x5",
    0x10005: "INTEGER1x6",
    0x10006: "INTEGER1x7",
    0x10007: "INTEGER2x4",
    0x10008: "INTEGER4x4",
    0x1000B: "INTEGER2x7",
}


def size_name(raw):
    if isinstance(raw, str):
        return raw
    return SIZE_NAMES.get(raw, f"0x{raw:X}" if isinstance(raw, int) else None)


def match_section(our_title, our_category, bts_by_name):
    for cand in (
        TITLE_OVERRIDES.get(our_title),
        TITLE_OVERRIDES.get(our_category),
        our_title,
        our_category,
    ):
        if cand is not None and cand in bts_by_name:
            return cand, bts_by_name[cand]
    low = (our_title or "").lower()
    for name in bts_by_name:
        if name.lower() == low:
            return name, bts_by_name[name]
    return None, None


def index_ours(entry):
    """Index our knobs/dropdowns by (relative_address, normalised_label)."""
    idx = {}
    for k in entry.get("knobs", []):
        addr = to_rel(parse_addr(k["address"]))
        idx[(addr, normalise_label(k.get("label", "")))] = ("knob", k)
    for k in entry.get("dropdowns", []):
        addr = to_rel(parse_addr(k["address"]))
        idx[(addr, normalise_label(k.get("label", "")))] = ("dropdown", k)
    # Secondary index on address alone (for when labels disagree —
    # BTS wins for the label, but we still want to recover our
    # supplementary numeric fields).
    by_addr = {}
    for k in entry.get("knobs", []) + entry.get("dropdowns", []):
        by_addr.setdefault(to_rel(parse_addr(k["address"])), []).append(k)
    return idx, by_addr


def is_dropdown(p, section):
    """In BTS every parameter renders as a knob/dial. The "dropdown"
    distinction in our existing catalog corresponds to the cascading
    sub-type discriminators — exactly the entries BTS lists in the
    section-level `selectBoxes` array (`type`, `mode`, `sp-type`, etc.).
    """
    select_boxes = section.get("selectBoxes") or []
    return p.get("uniqueName") in select_boxes


def enum_values(p, resources):
    rid = p.get("resourceId")
    if rid is None:
        return None
    try:
        entry = resources[rid]
    except (IndexError, TypeError):
        return None
    text = entry.get("text") if isinstance(entry, dict) else None
    if isinstance(text, list):
        return list(text)
    return None


def _ui_coord(v):
    """Normalise a row/col/page coordinate. BTS uses the string `'-'`
    as a sentinel for `not displayed in this UI variant`. We return
    `int` for real coordinates, `None` for the sentinel, and `None`
    for absent values.
    """
    if v in (None, "-"):
        return None
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return v


def _ui_block(p):
    """Build the optional `ui` sub-block:

        ui.pc = {row, col}      # BTS desktop editor placement (single canvas)
        ui.sp = {page, row, col}  # device on-screen edit placement (paged)

    Each side is included only when at least one coordinate is present.
    """
    pc_row = _ui_coord(p.get("rowPC"))
    pc_col = _ui_coord(p.get("colPC"))
    sp_page = _ui_coord(p.get("pageSP"))
    sp_row = _ui_coord(p.get("rowSP"))
    sp_col = _ui_coord(p.get("colSP"))
    ui = {}
    if pc_row is not None or pc_col is not None:
        ui["pc"] = {"row": pc_row, "col": pc_col}
    if sp_page is not None or sp_row is not None or sp_col is not None:
        ui["sp"] = {"page": sp_page, "row": sp_row, "col": sp_col}
    return ui


def merge_param(p, ours_index, ours_by_addr, resources, section):
    rel_addr = parse_addr(p["address"])
    key = (rel_addr, normalise_label(p["name"]))
    abs_addr = 0x10001100 + rel_addr
    bts_block = {
        "address": rel_addr,
        "unique_name": p.get("uniqueName"),
        "init": p.get("init"),
        "ofs": p.get("ofs"),
        "size": size_name(p.get("size")),
        "template": p.get("templateValue"),
        "format_js": p.get("format"),
        "factor": p.get("factor"),
        "show_when": p.get("showConditions") or [],
        "resource_id": p.get("resourceId"),
        "ui": _ui_block(p),
        "center": p.get("center"),
        "pid": p.get("pid"),
        "dial_class": p.get("dialClass"),
        "is_not_editable": p.get("isNotEditable"),
        "related_params": p.get("relatedParams"),
        "sort_index": p.get("sortIndex"),
    }
    # Strip unused fields.
    bts_block = {k: v for k, v in bts_block.items()
                 if v not in (None, [], "", {})}

    is_dd = is_dropdown(p, section)
    out = {
        "address": f"0x{abs_addr:08X}",
        "label": p["name"],
        "kind": "enum" if is_dd else "numeric",
        "raw_min": p.get("min"),
        "raw_max": p.get("max"),
        "bts": bts_block,
    }
    # Attach BTS's enum-string list whenever resourceId points at one,
    # even on parameters we don't classify as dropdowns — the strings
    # are still useful for downstream display (e.g. WAVEFORM TRI/SINE
    # is a knob in BTS but its raw 0/1 maps to those labels).
    vals = enum_values(p, resources)
    if vals is not None:
        out["values"] = vals
    # Pull supplementary fields from our existing catalog.
    matched = None
    if key in ours_index:
        _kind, matched = ours_index[key]
    elif rel_addr in ours_by_addr:
        # Single occupant at this address — labels disagreed but it's
        # almost certainly the same knob. Take whichever's there.
        candidates = ours_by_addr[rel_addr]
        if len(candidates) == 1:
            matched = candidates[0]
    if matched:
        for f in ("value_min", "value_max", "unit", "step", "offset",
                  "value_min_documented", "value_max_documented",
                  "raw_min_documented", "raw_max_documented",
                  "raw_min_probe_sample", "raw_max_probe_sample",
                  "value_min_probe_sample", "value_max_probe_sample",
                  "raw_to_display"):
            if f in matched:
                out[f] = matched[f]
    return out, is_dd


def merge_section(type_byte, ours_entry, bts_name, bts_section, resources):
    ours_index, ours_by_addr = index_ours(ours_entry)
    knobs = []
    dropdowns = []
    seen = set()
    for p in bts_section.get("parameters", []):
        if "address" not in p:
            continue
        rel = parse_addr(p["address"])
        ukey = (rel, p.get("uniqueName") or p["name"])
        if ukey in seen:
            continue
        seen.add(ukey)
        out, is_dd = merge_param(p, ours_index, ours_by_addr, resources, bts_section)
        (dropdowns if is_dd else knobs).append(out)

    # Surface any of our entries that BTS doesn't list — kept so we don't
    # silently drop them. These usually reflect bugs in our older catalog
    # (e.g. label mis-attributed to wrong address) and should be reviewed.
    bts_addrs = {parse_addr(p["address"]) for p in bts_section.get("parameters", [])
                 if "address" in p}
    orphans = []
    for kind, k in [("knob", k) for k in ours_entry.get("knobs", [])] + \
                   [("dropdown", k) for k in ours_entry.get("dropdowns", [])]:
        rel = to_rel(parse_addr(k["address"]))
        if rel not in bts_addrs:
            orphans.append({**k, "_orphan": "no BTS parameter at this address"})

    merged = {
        "title": ours_entry.get("title"),
        "category": ours_entry.get("category"),
        "bts_section": bts_name,
        "bts": {
            "color": bts_section.get("color"),
            "dial_color": bts_section.get("dialColor"),
            "label_main": bts_section.get("labelMain"),
            "label_sub": bts_section.get("labelSub"),
            "label_palette_main": bts_section.get("labelPaletteMain"),
            "label_palette_sub": bts_section.get("labelPaletteSub"),
            "small_label_sub": bts_section.get("smallLabelSub"),
            "select_boxes": bts_section.get("selectBoxes") or [],
            "has_switch": bts_section.get("hasSwitch"),
            "is_bass_type": bts_section.get("isBassType"),
            "do_not_show_sub_type": bts_section.get("doNotShowSubType"),
        },
        "knobs": knobs,
        "dropdowns": dropdowns,
    }
    merged["bts"] = {k: v for k, v in merged["bts"].items()
                     if v not in (None, [], "")}
    if orphans:
        merged["orphans_from_old_catalog"] = orphans
    return merged


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bts", default="captures/bts_effect_parameter_with_resources.json")
    ap.add_argument("--ours", default="captures/bts_effect_catalog.json")
    ap.add_argument("--out", default="catalogs/bts_effect_catalog_complete.json")
    args = ap.parse_args()

    bts_doc = json.loads(Path(args.bts).read_text())
    bts_params = bts_doc["effect_parameters"]
    resources = bts_doc["resources"]
    ours = json.loads(Path(args.ours).read_text())

    merged = {}
    matched = unmatched = 0
    for type_byte, entry in ours.items():
        bts_name, bts_section = match_section(
            entry.get("title", ""), entry.get("category", ""), bts_params)
        if bts_section is None:
            unmatched += 1
            merged[type_byte] = {
                **entry,
                "_warning": "no matching BTS section — entry passed through unchanged",
            }
            continue
        matched += 1
        merged[type_byte] = merge_section(
            type_byte, entry, bts_name, bts_section, resources)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"  matched={matched}/{len(ours)}  unmatched={unmatched}")


if __name__ == "__main__":
    sys.exit(main())
