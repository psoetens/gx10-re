"""Extract per-effect TYPE / SP TYPE / MIC TYPE value enums from the
Parameter Guide chunks. Builds a dict suitable for decoding captured
TYPE bytes (e.g. COMPRESSOR TYPE byte 0 = "BOSS COMP").

For most effects, TYPE is documented inline in the parameter table:

    | TYPE  | BOSS COMP  | ... |
    |       | D-COMP     | ... |
    |       | ORANGE     | ... |

For AIRD PREAMP, TYPE/SP TYPE/MIC TYPE point to separate "lists" later
in the manual:

    AIRD PREAMP TYPE list
    SP TYPE list
    MIC TYPE list

Each list is one or more enumerated tables. We harvest those too.

Output:
  catalogs/per_effect_types.json — {EFFECT_NAME: {"TYPE": [...], "SP TYPE": [...], ...}}
  tools/per_effect_types.py — Python module with PER_EFFECT_TYPES dict
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from manual_xref_v2 import (parse_chunk, INTERNAL_TO_MANUAL, CHUNKS,
                             strip_md_formatting)

ROOT = Path(__file__).parent.parent
MANUALS = ROOT / "docs" / "manuals"
OUT_JSON = ROOT / "catalogs" / "per_effect_types.json"
OUT_PY = ROOT / "tools" / "per_effect_types.py"


# Sections in the Parameter Guide that define value lists referenced by
# "Refer to ..." in main parameter tables.
AUX_LIST_HEADINGS = {
    "AIRD PREAMP TYPE LIST",
    "SP TYPE LIST",
    "MIC TYPE LIST",
    "AIRD BASS PREAMP TYPE LIST",
}


def harvest_aux_lists(text: str):
    """Find aux-list sections and return {heading_uppercased: [values]}.

    These sections aren't full effect blocks — they're heading + a
    table whose first column holds the value names (often **bold**).
    """
    lines = text.splitlines()
    out = {}
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        upper = ln.upper().strip()
        if upper in AUX_LIST_HEADINGS:
            values = []
            for j in range(i + 1, min(i + 60, len(lines))):
                t = lines[j].strip()
                if not t.startswith("|"):
                    if values:
                        break
                    continue
                cells = [strip_md_formatting(c) for c in t.strip("|").split("|")]
                if not cells or not cells[0]:
                    continue
                if re.match(r"^[\s:\-]+$", cells[0]):
                    continue
                v = cells[0]
                # Skip generic table headers
                if v.lower() in ("type", "name", "value"):
                    continue
                # Expand "USER1-16" / "USER1-N" range notation into individual values
                rng = re.match(r"^([A-Z][A-Z0-9 ]*?)(\d+)\s*[-–—]\s*(\d+)$", v)
                if rng:
                    prefix = rng.group(1).strip()
                    a, b = int(rng.group(2)), int(rng.group(3))
                    for n_idx in range(a, b + 1):
                        values.append(f"{prefix}{n_idx}")
                else:
                    values.append(v)
            out[upper] = values
        i += 1
    return out


# Manual labels for the "TYPE-like" dropdown across effects.
# When summary.json has has_type=True the captured byte address is the
# value of one of these dropdowns. Order matters when multiple match.
TYPE_LIKE_LABELS = (
    "TYPE", "WAH TYPE", "VOICE", "STAGE", "MODE",
    "FILTER MODE", "MIXER MODE", "DIVIDER MODE", "MIX MODE",
    "PATTERN", "WAVEFORM", "INTELLIGENT", "POLARITY",
    "OUTPUT MODE", "SPEED SELECT", "CH SELECT", "TRIGGER",
)
# SP TYPE-like (only AMP family really has these)
SP_TYPE_LIKE = ("SP TYPE",)
MIC_TYPE_LIKE = ("MIC TYPE",)


def main():
    db = {}      # effect heading -> params
    aux = {}     # aux list heading -> values
    for chunk in CHUNKS:
        text = (MANUALS / chunk).read_text(encoding="utf-8")
        for heading, params in parse_chunk(text):
            db[heading] = params
        for k, v in harvest_aux_lists(text).items():
            aux[k] = v

    print(f"Parsed {len(db)} effect sections, {len(aux)} aux lists")
    for k, v in aux.items():
        print(f"  aux: {k} -> {len(v)} values: {v[:4]}...")

    # Build per-effect type dict
    all_dropdown_labels = (TYPE_LIKE_LABELS + SP_TYPE_LIKE + MIC_TYPE_LIKE)
    per_effect = {}
    for heading, params in db.items():
        result = {}
        for p in params:
            n = p["name"].upper().strip()
            if n not in all_dropdown_labels:
                continue
            value = p.get("value", "").strip()
            extras = p.get("enum_values", [])
            # Resolve "Refer to ..." references
            ref_match = re.search(r"Refer to.*?(AIRD PREAMP TYPE list|"
                                  r"AIRD BASS PREAMP TYPE list|"
                                  r"SP TYPE list|MIC TYPE list)",
                                  value, re.IGNORECASE)
            if ref_match:
                aux_key = ref_match.group(1).upper()
                vals = aux.get(aux_key, [])
                if vals:
                    result[n] = vals
                continue
            # Inline values:
            # - The "value" cell may hold a comma-separated enum
            #   (e.g. "4 STAGE, 8 STAGE, 12 STAGE") OR a single value with
            #   continuation rows OR a sentence-style description.
            all_vals = []
            if value:
                # Split on commas if it looks like a comma-separated list
                # (no sentences with periods/lowercase verbs)
                if "," in value and not re.search(r"\b(this|the|adjusts|selects|determines|set)\b",
                                                    value, re.IGNORECASE):
                    all_vals.extend([s.strip() for s in value.split(",")])
                else:
                    # Skip pure descriptive sentences. Heuristic: starts
                    # with capital + several lowercase letters in a word
                    first_word = value.split()[0] if value.split() else ""
                    if not re.match(r"^[A-Z][a-z]{4,}", first_word):
                        all_vals.append(value)
            all_vals.extend(extras)
            all_vals = [v.strip() for v in all_vals if v.strip()]
            # Deduplicate while preserving order
            seen = set(); uniq = []
            for v in all_vals:
                if v not in seen:
                    seen.add(v); uniq.append(v)
            if len(uniq) >= 2:  # only keep when there's a real enum
                result[n] = uniq
        if result:
            per_effect[heading] = result

    print(f"\nEffects with TYPE/SP TYPE/MIC TYPE: {len(per_effect)}")
    for k in sorted(per_effect):
        kinds = sorted(per_effect[k].keys())
        sizes = {kk: len(per_effect[k][kk]) for kk in kinds}
        print(f"  {k:30s}  {sizes}")

    # Save JSON
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(per_effect, indent=2, ensure_ascii=False))
    print(f"\nWrote {OUT_JSON}")

    # Save Python module
    lines = [
        '"""Per-effect TYPE/SP TYPE/MIC TYPE value enumerations,',
        'harvested from the GX-10 Parameter Guide. Maps effect name (as',
        'used in MemoryFxItem TYPE enum) to a dict of dropdown -> list',
        'of value labels in declaration order.',
        '',
        'Use to decode the byte value of e.g. COMPRESSOR\'s TYPE knob:',
        '    name = PER_EFFECT_TYPES["COMPRESSOR"]["TYPE"][type_byte]',
        '"""',
        "PER_EFFECT_TYPES = {",
    ]
    for k in sorted(per_effect):
        lines.append(f'    "{k}": {{')
        for sub in sorted(per_effect[k]):
            vals = per_effect[k][sub]
            esc = [v.replace('"', '\\"') for v in vals]
            lines.append(f'        "{sub}": [{", ".join(repr(v) for v in esc)}],')
        lines.append("    },")
    lines.append("}")
    lines.append("")
    OUT_PY.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PY}")


if __name__ == "__main__":
    main()
