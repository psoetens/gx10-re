"""Diff GX-100 v1 vs v2 Parameter Guide chunks, per-effect.

Parses each effect section in the markdown chunks and extracts:
- the effect name (heading line before the parameters table)
- the TYPE / SP_TYPE / HARMONY enum value list

Compares v1 vs v2 lists and reports v2-only entries (= firmware-2.0
additions) and v1-only entries (= effects removed in v2, expected: 0).

Output is markdown — pipe to a file under reports/.

Usage:  python tools/diff_v1_v2_param_guide.py > reports/v2_subtype_additions.md
"""
import re
import sys
from pathlib import Path
from collections import OrderedDict


ROOT = Path(__file__).parent.parent
MANUALS = ROOT / "docs" / "manuals"

V1_CHUNKS = sorted(MANUALS.glob("GX-100_v1_Parameter_Guide_*.md"))
V2_CHUNKS = sorted(MANUALS.glob("GX-100_Parameter_Guide_*.md"))


# Section headings are uppercase lines (UPPER, optional spaces, no
# leading "|", no markdown chrome). They precede a "Chain | Palette"
# header and a "Parameter | Value | Explanation" table. We pick them
# up by treating any non-table, non-blank uppercase line as a candidate
# heading and trim "**" / image refs.
HEADING_RE = re.compile(r"^([A-Z][A-Z0-9 +\-/&]+?)\s*$")

# Page-break / chapter-title noise that the parser sees as headings but
# that aren't real effects.
HEADING_BLACKLIST = {
    "EFFECTS", "EFFECT", "MENU", "WRITE", "SOUND LIST",
    "SECTION", "INDEX", "NOTE", "ON/OFF", "TYPE", "CHAIN",
    "PALETTE", "ALL", "GLOBAL",
}


def normalise_enum_value(s: str) -> str:
    """Strip image placeholders, bold markers, and trailing whitespace
    so the same enum value across v1 vs v2 compares equal."""
    s = re.sub(r"!\[\]\[image\d+\]", "", s)
    s = re.sub(r"\[img\]", "", s)
    s = s.replace("**", "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def parse_chunk(path: Path):
    """Return OrderedDict[effect_name] = [list of TYPE/SP_TYPE/HARMONY enum values].

    For each effect section we capture only the **first** parameter
    whose enum values span multiple rows (the TYPE column). For
    effects with no TYPE selector (ON/OFF only, e.g. some MASTER
    blocks), the list is empty.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections = OrderedDict()

    i = 0
    cur_effect = None
    cur_params = []
    cur_param_name = None
    in_param_table = False

    def commit():
        nonlocal cur_effect
        if cur_effect:
            if cur_effect in sections:
                # Merge: page breaks split a single effect into two
                # heading occurrences; append the new params to the
                # existing list rather than overwriting.
                existing = sections[cur_effect]
                for p in cur_params:
                    if p not in existing:
                        existing.append(p)
            else:
                sections[cur_effect] = list(cur_params)

    while i < len(lines):
        line = lines[i].rstrip()
        # cleanup of v2 noise
        clean = line.replace("**", "").strip()
        clean = re.sub(r"!\[\]\[image\d+\]", "", clean).strip()

        # Effect heading: uppercase, no pipe, not blank, no header marker
        if clean and not clean.startswith("|") and HEADING_RE.match(clean) \
                and clean.upper() not in HEADING_BLACKLIST \
                and not clean.isdigit() \
                and "VALUE" not in clean and "EXPLANATION" not in clean \
                and "PARAMETER" not in clean and "CHAIN" not in clean:
            # Heuristic: heading is followed (within ~12 lines) by either
            # "| Chain" or "| Parameter" header
            lookahead = "\n".join(lines[i+1:i+13])
            if "| Chain" in lookahead or "| Parameter" in lookahead:
                commit()
                cur_effect = clean
                cur_params = []
                cur_param_name = None
                in_param_table = False
                i += 1
                continue

        # Detect start of parameter table
        if line.startswith("| Parameter") or line.startswith("|Parameter"):
            in_param_table = True
            cur_param_name = None
            i += 1
            # skip the separator row
            if i < len(lines) and re.match(r"^\|\s*:?-+", lines[i]):
                i += 1
            continue

        if in_param_table:
            if not line.startswith("|"):
                in_param_table = False
                i += 1
                continue
            # Split table row
            cells = [c.strip().replace("**", "") for c in line.strip("|").split("|")]
            cells = [re.sub(r"!\[\]\[image\d+\]", "", c).strip() for c in cells]
            if len(cells) < 3:
                i += 1
                continue
            param, value, _explain = cells[0], cells[1], cells[2]

            if param:
                # New parameter row. We capture TYPE / SP_TYPE / HARMONY.
                cur_param_name = param
                if param.upper() in ("TYPE", "SP TYPE", "SP_TYPE",
                                     "HARMONY", "AMP TYPE"):
                    v = normalise_enum_value(value)
                    if v and v not in cur_params:
                        cur_params.append(v)
                # other params (DRIVE, etc.) are scalar — ignore for diff
            else:
                # Continuation row of the previous parameter
                if cur_param_name and cur_param_name.upper() in (
                        "TYPE", "SP TYPE", "SP_TYPE", "HARMONY", "AMP TYPE"):
                    v = normalise_enum_value(value)
                    if v and v not in cur_params:
                        cur_params.append(v)
        i += 1

    commit()
    return sections


def parse_all(chunks):
    merged = OrderedDict()
    for c in chunks:
        for k, v in parse_chunk(c).items():
            # keep first occurrence (chunks have stable order)
            if k not in merged:
                merged[k] = v
    return merged


def diff(v1, v2):
    """Return per-effect (v2_only, v1_only) lists."""
    rows = []
    for effect in v2:
        if effect not in v1:
            rows.append((effect, list(v2[effect]), [], "ADDED"))
            continue
        v1_set = set(v1[effect])
        v2_set = set(v2[effect])
        added = [t for t in v2[effect] if t not in v1_set]
        removed = [t for t in v1[effect] if t not in v2_set]
        if added or removed:
            rows.append((effect, added, removed, "DIFF"))
        else:
            rows.append((effect, [], [], "SAME"))
    for effect in v1:
        if effect not in v2:
            rows.append((effect, [], list(v1[effect]), "REMOVED"))
    return rows


def main():
    print("# GX-100 v1 vs v2 Parameter Guide diff — per-effect TYPE additions")
    print()
    print(f"Sources:")
    print(f"- v1 chunks: {len(V1_CHUNKS)} files")
    print(f"- v2 chunks: {len(V2_CHUNKS)} files")
    print()

    v1 = parse_all(V1_CHUNKS)
    v2 = parse_all(V2_CHUNKS)

    print(f"Effect sections found: v1 = {len(v1)}, v2 = {len(v2)}")
    print()

    rows = diff(v1, v2)
    n_added_effects = sum(1 for _, _, _, k in rows if k == "ADDED")
    n_diff_effects  = sum(1 for _, a, r, k in rows if k == "DIFF")
    n_same_effects  = sum(1 for _, _, _, k in rows if k == "SAME")
    n_removed       = sum(1 for _, _, _, k in rows if k == "REMOVED")
    print(f"Effect-section status: ADDED={n_added_effects}, "
          f"DIFF={n_diff_effects}, SAME={n_same_effects}, "
          f"REMOVED={n_removed}")
    print()

    print("## Effects entirely added in v2.0")
    any_added = False
    for effect, added, _, kind in rows:
        if kind == "ADDED":
            any_added = True
            print(f"- **{effect}** — {len(added)} TYPE/SP_TYPE entr"
                  f"{'y' if len(added)==1 else 'ies'}: "
                  + (", ".join(f"`{t}`" for t in added) if added
                     else "(no TYPE selector / single-mode effect)"))
    if not any_added:
        print("(none)")
    print()

    print("## Sub-types added inside existing effects")
    for effect, added, removed, kind in rows:
        if kind == "DIFF":
            print(f"### {effect}")
            if added:
                print("**Added in v2.0:**")
                for t in added:
                    print(f"- `{t}`")
            if removed:
                print("**Removed/renamed (in v1, not in v2):**")
                for t in removed:
                    print(f"- `{t}`")
            print()

    print("## Effects unchanged between v1 and v2 (TYPE list identical)")
    same = [e for e, _, _, k in rows if k == "SAME"]
    print(f"({len(same)} effects)")
    print()
    for e in same:
        print(f"- {e}")
    print()

    print("## Effects in v1 but not v2 (expected: empty)")
    any_removed = False
    for effect, _, removed, kind in rows:
        if kind == "REMOVED":
            any_removed = True
            print(f"- **{effect}** ({len(removed)} entries)")
    if not any_removed:
        print("(none)")


if __name__ == "__main__":
    main()
