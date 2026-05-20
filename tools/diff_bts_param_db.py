"""Diff our captured `captures/bts_effect_catalog.json` against BTS's
own authoritative parameter database (`config/effect_parameter.js` in
the BTS macOS bundle).

Pipeline:
    osascript -l JavaScript tools/parse_bts_effect_parameter.js \
        > captures/bts_effect_parameter.json
    python tools/diff_bts_param_db.py \
        --bts captures/bts_effect_parameter.json \
        --ours captures/bts_effect_catalog.json \
        --out reports/bts_param_db_diff.md

The BTS file is keyed by effect name (e.g. "CHORUS", "AIRD PREAMP"),
our file is keyed by TYPE byte (0x00..0x52). Mapping is fuzzy: both
sides agree on title strings most of the time; manual overrides handle
the handful of titles where we disagree (e.g. BTS "WAH" vs ours
"WAH (CRY WAH)").

Per-knob comparison key: (relative-address, label-normalised).
Relative address = absolute address - 0x10001100.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# Manual overrides where our title and BTS's section name disagree.
# Right side = BTS section name. Keys are our `title` strings.
TITLE_OVERRIDES = {
    "BASS AIRD PREAMP": "AIRD BASS PREAMP",
    "X-COMPRESSOR": "X COMPRESSOR",
    "X_COMP_BASS": "X BASS COMPRESSOR",
    "DELAY+": "DELAY PLUS",
    "TWIST DELAY": "TWIST",
    "WARP DELAY": "WARP",
    "BASS FLANGER": "BASS FLANGER",
    "PRIME FLANGER": "PRIME FLANGER",
    "PRIME BASS FLANGER": "PRIME BASS FLANGER",
    "DIVIDER (DIV_MIX entry)": "DIVIDER",
    "SPLITTER (internal — hidden in BTS UI)": "SPLITTER",
    "MIXER (DIV_MIX exit)": "MIXER",
    "FUZZ": "FUZZ",
    "BASS FUZZ": "BASS FUZZ",
    "WAH (CRY WAH)": "WAH",
    "REVERB+": "REVERB PLUS",
    "SLOW BEND": "S-BEND",
    "BASS SLOW BEND": "BASS S-BEND",
    "CLASSIC VIBE": "CLASSIC-VIBE",
    "SITAR SIMULATOR": "SITAR SIMULATOR",
}


def normalise_label(s: str) -> str:
    """Strip whitespace/punctuation so 'EFFECT LEVEL' and 'EffectLevel'
    match. BTS uses spaces; we sometimes do too — preserve case-insensitive
    comparison.
    """
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def parse_addr(s) -> int:
    """Accepts integers (BTS) or hex strings (our '0x10001107' / int relative)."""
    if isinstance(s, int):
        return s
    if isinstance(s, str):
        s = s.strip()
        if s.startswith("0x") or s.startswith("0X"):
            return int(s, 16)
        return int(s)
    raise ValueError(f"unparseable address: {s!r}")


def to_rel(abs_or_rel: int) -> int:
    """Convert our absolute (0x10001100+offset) to relative byte offset
    matching BTS. BTS uses offsets within the slot.
    """
    SLOT0 = 0x10001100
    if abs_or_rel >= SLOT0:
        return abs_or_rel - SLOT0
    return abs_or_rel


def build_bts_by_name(bts: dict) -> dict:
    return {name: section for name, section in bts.items()}


def match_section(our_title: str, our_category: str, bts_by_name: dict):
    """Return the BTS section dict matching our entry, or None."""
    for cand in (
        TITLE_OVERRIDES.get(our_title),
        TITLE_OVERRIDES.get(our_category),
        our_title,
        our_category,
    ):
        if cand is not None and cand in bts_by_name:
            return cand, bts_by_name[cand]
    # Last-chance: case-insensitive name lookup
    low = (our_title or "").lower()
    for name in bts_by_name:
        if name.lower() == low:
            return name, bts_by_name[name]
    return None, None


def flatten_bts_params(section: dict) -> list[dict]:
    """One BTS row per (address, label) — deduplicated across
    showConditions variants that point at the same address+name.
    """
    seen: dict[tuple[int, str], dict] = {}
    for p in section.get("parameters", []):
        try:
            addr = parse_addr(p.get("address"))
        except Exception:
            continue
        label_norm = normalise_label(p.get("name", ""))
        key = (addr, label_norm)
        if key in seen:
            continue
        seen[key] = {
            "address": addr,
            "name": p.get("name", ""),
            "min": p.get("min"),
            "max": p.get("max"),
            "init": p.get("init"),
            "ofs": p.get("ofs"),
            "templateValue": p.get("templateValue"),
            "showConditions": p.get("showConditions"),
            "uniqueName": p.get("uniqueName"),
        }
    return list(seen.values())


def flatten_ours(entry: dict) -> list[dict]:
    """One row per knob/dropdown."""
    rows = []
    for k in entry.get("knobs", []) + entry.get("dropdowns", []):
        try:
            addr = to_rel(parse_addr(k.get("address")))
        except Exception:
            continue
        rows.append({
            "address": addr,
            "name": k.get("label", ""),
            "raw_min": k.get("raw_min"),
            "raw_max": k.get("raw_max"),
            "value_min": k.get("value_min"),
            "value_max": k.get("value_max"),
            "kind": k.get("kind"),
        })
    return rows


def diff_entry(type_byte: str, our: dict, bts_name: str, bts_section: dict):
    """Yield human-readable diff lines for one effect."""
    bts_rows = flatten_bts_params(bts_section)
    our_rows = flatten_ours(our)
    bts_by_addr = {r["address"]: r for r in bts_rows}
    our_by_addr = {r["address"]: r for r in our_rows}

    out = []
    only_bts = sorted(set(bts_by_addr) - set(our_by_addr))
    only_ours = sorted(set(our_by_addr) - set(bts_by_addr))
    common = sorted(set(bts_by_addr) & set(our_by_addr))

    label_mismatches = []
    range_mismatches = []
    for addr in common:
        b = bts_by_addr[addr]
        o = our_by_addr[addr]
        if normalise_label(b["name"]) != normalise_label(o["name"]):
            label_mismatches.append((addr, o["name"], b["name"]))
        # Compare raw ranges (BTS min/max are the raw codomain).
        if (b["min"], b["max"]) != (o["raw_min"], o["raw_max"]):
            range_mismatches.append((addr, o["name"], (o["raw_min"], o["raw_max"]), (b["min"], b["max"])))

    if not (only_bts or only_ours or label_mismatches or range_mismatches):
        return None  # clean — skip

    out.append(f"## {type_byte}  {our.get('title','?')}  (BTS: {bts_name})")
    out.append("")
    out.append(f"- ours: {len(our_rows)} entries, bts: {len(bts_rows)} entries")
    if only_bts:
        out.append("")
        out.append(f"### Addresses present in BTS but missing in ours  ({len(only_bts)})")
        for a in only_bts:
            b = bts_by_addr[a]
            cond = b.get("showConditions") or []
            ctxt = f"  cond={cond}" if cond else ""
            out.append(f"  - +0x{a:02X} ({a:>3}) `{b['name']}`  min={b['min']} max={b['max']} tmpl={b.get('templateValue')!r}{ctxt}")
    if only_ours:
        out.append("")
        out.append(f"### Addresses present in ours but missing in BTS  ({len(only_ours)})")
        for a in only_ours:
            o = our_by_addr[a]
            out.append(f"  - +0x{a:02X} ({a:>3}) `{o['name']}`  raw={o['raw_min']}..{o['raw_max']} val={o['value_min']}..{o['value_max']}")
    if label_mismatches:
        out.append("")
        out.append(f"### Label mismatches at same address  ({len(label_mismatches)})")
        for a, ours_l, bts_l in label_mismatches:
            out.append(f"  - +0x{a:02X} ({a:>3})  ours=`{ours_l}`  bts=`{bts_l}`")
    if range_mismatches:
        out.append("")
        out.append(f"### Raw-range mismatches at same address  ({len(range_mismatches)})")
        for a, name, ours_rng, bts_rng in range_mismatches:
            out.append(f"  - +0x{a:02X} ({a:>3}) `{name}`  ours={ours_rng[0]}..{ours_rng[1]}  bts={bts_rng[0]}..{bts_rng[1]}")
    out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bts", default="captures/bts_effect_parameter.json",
                    help="parsed BTS EFFECT_PARAMETERS JSON (from parse_bts_effect_parameter.js)")
    ap.add_argument("--ours", default="captures/bts_effect_catalog.json")
    ap.add_argument("--out", default="reports/bts_param_db_diff.md")
    args = ap.parse_args()

    bts = json.loads(Path(args.bts).read_text())
    ours = json.loads(Path(args.ours).read_text())
    bts_by_name = build_bts_by_name(bts)

    body = []
    body.append("# `captures/bts_effect_catalog.json` vs BTS `effect_parameter.js`")
    body.append("")
    body.append(f"Comparison generated by `tools/diff_bts_param_db.py`.")
    body.append("")
    body.append(f"- ours: `{args.ours}` ({len(ours)} effect types)")
    body.append(f"- bts:  `{args.bts}` ({len(bts)} sections)")
    body.append("")
    body.append("Per-knob comparison key: relative byte address (our absolute "
                "minus `0x10001100`) + case/punctuation-normalised label. "
                "BTS `min`/`max` are the raw codomain (offset-binary `ofs` "
                "subtracted) and should match our `raw_min`/`raw_max`.")
    body.append("")
    body.append("---")
    body.append("")

    unmatched = []
    matched = 0
    diffs = 0
    sections = []
    for type_byte, entry in ours.items():
        bts_name, bts_section = match_section(
            entry.get("title", ""), entry.get("category", ""), bts_by_name)
        if bts_section is None:
            unmatched.append((type_byte, entry.get("title")))
            continue
        matched += 1
        block = diff_entry(type_byte, entry, bts_name, bts_section)
        if block is not None:
            diffs += 1
            sections.append(block)

    body.insert(8, f"- matched {matched}/{len(ours)} effects; {diffs} have differences; {len(unmatched)} unmatched titles")
    if unmatched:
        body.append("## Unmatched titles")
        body.append("")
        body.append("These effect-type bytes in our catalog could not be paired "
                    "with a BTS section — title strings disagree. Add an entry "
                    "to `TITLE_OVERRIDES` to fix.")
        body.append("")
        for tb, title in unmatched:
            body.append(f"  - {tb}  {title!r}")
        body.append("")

    body.append("---")
    body.append("")
    body.extend(sections)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"  matched={matched}/{len(ours)}  with_diffs={diffs}  unmatched={len(unmatched)}")


if __name__ == "__main__":
    sys.exit(main())
