"""Merge documented parameter ranges from the GX-10 Parameter Guide markdown
files into captures/bts_effect_catalog.json.

Reads:
  docs/manuals/GX-10_Parameter_Guide_01..04*.md (effect sections)
  captures/bts_effect_catalog.json (BTS-probed knob data, raw=0..15)

Writes:
  captures/bts_effect_catalog.json (in place, with extended raw_max/value_max
                                    derived from documented value ranges, and
                                    enum knobs filled in with full value lists)

Logic per knob:
  - parse param-guide table to get (effect_section -> {param_label -> spec})
    where spec is one of:
      {"kind": "numeric", "min": <int>, "max": <int>, "unit": <str>}
      {"kind": "enum", "values": [<str>, ...]}
      {"kind": "onoff"}                # OFF/ON
      {"kind": "ratio"}                # special: 1:1..INF:1 etc
  - for each effect in catalog, look up its title in the param guide map
  - for each knob, look up its label in that effect's param spec
    - numeric guide + numeric probed (with linear formula step+offset):
        raw_max_doc = round((max_value - offset) / step)
        raw_min_doc = round((min_value - offset) / step)
        update raw_max = max(raw_max_probed, raw_max_doc)
        update value_max = max(value_max_probed, max_value)
    - enum guide: replace `values` with documented list (longer, authoritative)
"""
from __future__ import annotations
import json
import re
from pathlib import Path


REPO = Path(__file__).parent.parent
MANUAL_GLOB = "docs/manuals/GX-10_Parameter_Guide_0[1-4]*.md"
CATALOG = REPO / "captures/bts_effect_catalog.json"


# Map param-guide effect section titles to catalog effect titles.
# Some titles differ (e.g. param guide "DELAY PLUS" vs probed "DELAY+";
# "WAH" vs probed "WAH (CRY WAH)"; etc).
TITLE_ALIASES = {
    "DELAY PLUS": "DELAY+",
    "WAH": "WAH (CRY WAH)",
    "AIRD BASS PREAMP": "BASS AIRD PREAMP",
    "TWIST": "TWIST DELAY",
    "WARP": "WARP DELAY",
    "REVERB PLUS": "REVERB+",
    "S-BEND": "SLOW BEND",
    "BASS S-BEND": "BASS SLOW BEND",
    "X-BASS COMPRESSOR": "X BASS COMPRESSOR",
    "CLASSIC-VIBE": "CLASSIC VIBE",
    "DIVIDER": "DIVIDER (DIV_MIX entry)",
    "MIXER": "MIXER (DIV_MIX exit)",
    # SPLITTER (0x1E) is internal — no param-guide section
}

# Per-knob label aliases for cases where BTS UI label differs from the
# parameter guide. Format: {(catalog_title, bts_label): guide_label}.
KNOB_LABEL_ALIASES = {
    # AUTO WAH "FILTER MODE" in BTS = "FILTER" in guide
    ("AUTO WAH", "FILTER MODE"): "FILTER",
    # DIVIDER/MIXER family expose "LOOP LEVEL" in BTS — same 0..100 as
    # PHRASE LOOP's LOOP LEVEL.
    ("DIVIDER (DIV_MIX entry)", "LOOP LEVEL"): "LOOP LEVEL",
    ("MIXER (DIV_MIX exit)", "LOOP LEVEL"): "LOOP LEVEL",
    # CHORUS OUTPUT MODE is shared with PRIME CHORUS in v2.
    ("CHORUS", "OUTPUT MODE"): "OUTPUT MODE",
}

# When a BTS label has no direct param-guide match in its own section,
# fall back to a different effect's guide section that does define it.
# Format: {(catalog_title, bts_label): (guide_section, guide_label)}.
KNOB_CROSS_SECTION_FALLBACKS = {
    ("CHORUS", "OUTPUT MODE"): ("PRIME CHORUS", "OUTPUT MODE"),
    ("DIVIDER (DIV_MIX entry)", "LOOP LEVEL"): ("PHRASE LOOP", "LOOP LEVEL"),
    ("MIXER (DIV_MIX exit)", "LOOP LEVEL"): ("PHRASE LOOP", "LOOP LEVEL"),
    ("SPLITTER (internal — hidden in BTS UI)", "LOOP LEVEL"):
        ("PHRASE LOOP", "LOOP LEVEL"),
    # TOUCH WAH RISE TIME and TREMOLO SENS aren't in their own guide
    # sections in the v1 manual but are documented as 0..100 in adjacent
    # ones (TREMOLO has RISE TIME; TOUCH WAH has SENS).
    ("TOUCH WAH", "RISE TIME"): ("TREMOLO", "RISE TIME"),
    ("BASS TOUCH WAH", "RISE TIME"): ("TREMOLO", "RISE TIME"),
    ("TREMOLO", "SENS"): ("TOUCH WAH", "SENS"),
}


def parse_value_cell(value: str) -> dict | None:
    """Parse a 'Value' cell from the param-guide tables. Returns spec dict or None."""
    s = value.strip()
    # Strip markdown bold and unescape backslash-escapes
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = s.replace("\\-", "-")
    if not s:
        return None

    # ON/OFF
    if re.fullmatch(r"OFF\s*,\s*ON|ON\s*,\s*OFF", s):
        return {"kind": "onoff", "values": ["OFF", "ON"]}

    # Numeric range like "0-100" or "-50-+50" or "0–120" (em-dash)
    # Normalize em-dash to hyphen for parsing
    s_norm = s.replace("–", "-").replace("—", "-")
    # Match "[+-]N - [+-]N" with optional unit suffix
    m = re.fullmatch(
        r"\s*([+-]?\d+(?:\.\d+)?)\s*-\s*([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%/]*)\s*",
        s_norm,
    )
    if m:
        lo, hi, unit = m.group(1), m.group(2), m.group(3)
        try:
            lo_n = float(lo) if "." in lo else int(lo)
            hi_n = float(hi) if "." in hi else int(hi)
            return {"kind": "numeric", "min": lo_n, "max": hi_n, "unit": unit}
        except ValueError:
            pass

    # Special "1:1-INF:1"
    if re.match(r"\d+:\d+\s*[-–]\s*INF:\d+", s_norm):
        return {"kind": "ratio", "raw": s}

    # Frequency ranges with kHz/Hz mixed: e.g. "20.0Hz-20.0kHz"
    m = re.fullmatch(
        r"([\d.]+)(Hz|kHz)\s*-\s*([\d.]+)(Hz|kHz)",
        s_norm,
    )
    if m:
        return {"kind": "freq_range", "raw": s}

    # FLAT / shaped curve token
    if re.fullmatch(r"[A-Z][A-Z0-9/]*", s_norm.replace(" ", "")):
        return {"kind": "enum_value", "value": s}

    # Multi-token like "DUAL/USER/..." – treat as enum value (single row contribution)
    return {"kind": "enum_value", "value": s}


def parse_param_table(lines: list[str], start: int) -> tuple[dict, int]:
    """Parse a parameter table starting at index `start`. Returns
    (params_dict, next_line_idx). params_dict is {param_name: spec}.

    `spec` for numeric/onoff/ratio is a single dict; for enum it's
    {"kind": "enum", "values": [...]} accumulated across continuation rows
    (rows where Parameter cell is empty).
    """
    params: dict = {}
    last_param: str | None = None
    i = start
    while i < len(lines):
        line = lines[i]
        if not line.lstrip().startswith("|"):
            break
        # Skip the header separator: | :--- | :--- | ...
        if re.match(r"^\s*\|\s*:?-+\s*\|", line):
            i += 1
            continue
        # Split row into cells
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            i += 1
            continue
        param_cell = re.sub(r"\*\*(.+?)\*\*", r"\1", cells[0]).strip()
        # Strip footnote markers like "\*1", "\*2", "*1", "*2"
        param_cell = re.sub(r"\s*\\?\*\d+\s*", " ", param_cell).strip()
        # Strip markdown backslash escapes (e.g. "\-2 OCT" -> "-2 OCT")
        param_cell = param_cell.replace("\\-", "-").replace("\\(", "(").replace("\\)", ")")
        # Normalize internal whitespace
        param_cell = re.sub(r"\s+", " ", param_cell)
        value_cell = cells[1]
        if not param_cell and last_param:
            # Continuation row -> treat as another enum value
            spec = params[last_param]
            if spec.get("kind") in ("enum", "enum_value"):
                pass  # will append
            else:
                params[last_param] = {"kind": "enum", "values": []}
                # carry over earlier "enum_value" if any
                if isinstance(spec, dict) and spec.get("kind") == "enum_value":
                    params[last_param]["values"].append(spec["value"])
            sp = parse_value_cell(value_cell)
            if sp and sp.get("kind") == "enum_value":
                params[last_param]["values"].append(sp["value"])
        elif param_cell in ("Parameter", ""):
            i += 1
            continue
        else:
            sp = parse_value_cell(value_cell)
            if sp is None:
                i += 1
                continue
            if sp["kind"] == "enum_value":
                # First row of a possible enum
                params[param_cell] = {"kind": "enum", "values": [sp["value"]]}
            else:
                params[param_cell] = sp
            last_param = param_cell
        i += 1
    return params, i


def parse_param_guide() -> dict[str, dict]:
    """Returns {effect_title_normalized: {param_label: spec}}."""
    sections: dict[str, dict] = {}
    md_files = sorted(REPO.glob(MANUAL_GLOB))
    for md in md_files:
        text = md.read_text(encoding="utf-8")
        # Normalize non-breaking spaces to regular spaces (some headings like
        # "TOUCH\xa0WAH" use NBSP which breaks ASCII regexes).
        text = text.replace(" ", " ")
        lines = text.split("\n")
        i = 0
        current_section: str | None = None
        while i < len(lines):
            line = lines[i].strip()
            # Section header: a line that is uppercase letters + spaces (and a few special chars),
            # not a table row, and immediately preceding a "Chain | Palette" or descriptive paragraph.
            if (line and re.fullmatch(r"[A-Z0-9 ()/+&\-.]{3,}", line)
                    and not line.startswith("|")
                    and not line.startswith("**")
                    and "EFFECTS" not in line.upper().split()
                    and "list" not in lines[i].lower()):
                # heuristic: must look like an effect title — single line, mostly ALL CAPS
                if re.fullmatch(r"[A-Z][A-Z0-9 +/&\-.()]{2,}", line):
                    current_section = line
            # Parameter table marker
            if line.startswith("| Parameter") and current_section:
                params, next_i = parse_param_table(lines, i + 1)
                sections.setdefault(current_section, {}).update(params)
                i = next_i
                continue
            i += 1
    return sections


def merge():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    sections = parse_param_guide()

    # Build mapping {catalog_title: section_dict}
    title_map: dict[str, dict] = {}
    for sec_title, params in sections.items():
        catalog_title = TITLE_ALIASES.get(sec_title, sec_title)
        if catalog_title is None:
            continue
        title_map.setdefault(catalog_title, {}).update(params)

    # Diagnostics
    catalog_titles = {e["title"] for e in catalog.values()}
    matched_titles = catalog_titles & set(title_map.keys())
    unmatched_catalog = catalog_titles - set(title_map.keys())
    unmatched_guide = set(title_map.keys()) - catalog_titles
    print(f"  param-guide sections: {len(sections)}")
    print(f"  catalog effects matched: {len(matched_titles)}/{len(catalog_titles)}")
    if unmatched_catalog:
        print(f"  catalog effects without guide section:")
        for t in sorted(unmatched_catalog):
            print(f"    - {t}")
    if unmatched_guide:
        print(f"  guide sections not used:")
        for t in sorted(unmatched_guide):
            print(f"    - {t}")

    # GEQ band knobs all share the same -20..+20 dB range. The guide only
    # documents "31.5 Hz" + "LEVEL" so propagate to the other 9 bands.
    geq_band_re = re.compile(r"^\d+(\.\d+)?\s*(Hz|kHz)$", re.I)

    # Reserved for any future effect whose probe captures the wrong panel
    # because BTS rendered an unrelated effect's UI. Empty after the
    # FEEDBACKER + SITAR SIMULATOR re-probe on a fresh BTS instance.
    MISRENDERED_PROBE: set[str] = set()

    knobs_extended = 0
    enums_filled = 0
    for tkey, eff in catalog.items():
        title = eff["title"]
        if title in MISRENDERED_PROBE:
            eff["_probe_misrendered"] = (
                "BTS displayed an unrelated effect's panel during the bulk "
                "probe; captured knob labels are not this effect's actual "
                "parameters. Re-probe on a freshly-restarted BTS to fix."
            )
        params = title_map.get(title, {})
        # Don't continue when params is empty — KNOB_CROSS_SECTION_FALLBACKS
        # may still let us source a range from another section (e.g. SPLITTER
        # has no guide section but its LOOP LEVEL maps to PHRASE LOOP's).
        for knob in eff["knobs"] + eff["dropdowns"]:
            raw_label = knob["label"].strip().upper()
            # Strip leading "1:" / "2:" tap prefixes
            label_norm = re.sub(r"^\d+:\s*", "", raw_label).strip()
            # Also normalize whitespace and remove spaces between number+unit
            # so "31.5Hz" matches "31.5 Hz" from the guide.
            def squish(s: str) -> str:
                return re.sub(r"\s+", "", s)
            label_squish = squish(label_norm)
            # Find matching guide param (case-insensitive). The guide
            # frequently merges multi-tap entries like "1: PITCH  2: PITCH"
            # into one row — split on whitespace and look for the bare label.
            guide_spec = None
            for p, spec in params.items():
                p_norm = p.strip().upper()
                if p_norm == label_norm or p_norm == raw_label:
                    guide_spec = spec
                    break
                if squish(p_norm) == label_squish:
                    guide_spec = spec
                    break
                # Try splitting "1: X  2: X" into pieces
                pieces = re.split(r"\s+\d+:\s*", " " + p_norm)
                pieces = [pc.strip() for pc in pieces if pc.strip()]
                if label_norm in pieces or raw_label in pieces:
                    guide_spec = spec
                    break
                # Multi-channel entries like "PITCH 1 PITCH 2" or
                # "A LEVEL B LEVEL" — split on word boundary chars and look
                # for the label as a contiguous subsequence.
                if (f" {label_norm} " in f" {p_norm} "
                        or f" {raw_label} " in f" {p_norm} "):
                    guide_spec = spec
                    break
            # Manual aliases: re-target the lookup label
            if not guide_spec:
                alias = KNOB_LABEL_ALIASES.get((title, label_norm))
                if alias:
                    for p, spec in params.items():
                        if p.strip().upper() == alias.upper():
                            guide_spec = spec
                            break
            # Cross-section fallback (label appears in a sibling effect)
            if not guide_spec:
                fb = KNOB_CROSS_SECTION_FALLBACKS.get((title, label_norm))
                if fb:
                    sec, lbl = fb
                    sec_params = title_map.get(sec) or sections.get(sec, {})
                    for p, spec in sec_params.items():
                        if p.strip().upper() == lbl.upper():
                            guide_spec = spec
                            break
            if not guide_spec and title == "GRAPHIC EQUALIZER" and geq_band_re.match(label_norm):
                # Apply the band-knob range (-20..+20 dB) from any documented band
                for p, spec in params.items():
                    if geq_band_re.match(p.strip().upper().replace(" ", "")) and spec.get("kind") == "numeric":
                        guide_spec = spec
                        break
            if not guide_spec:
                continue
            kind_doc = guide_spec["kind"]
            kind_probed = knob.get("kind")

            if kind_doc == "numeric" and kind_probed in ("numeric", "numeric_irregular"):
                # Always record the documented range — probed only sampled
                # raw=0..15 which under-reports both min (for bipolar knobs
                # like LOW DAMP -100..0) and max (for unipolar 0..100).
                knob["value_min_documented"] = guide_spec["min"]
                knob["value_max_documented"] = guide_spec["max"]
                step = knob.get("step", 1)
                offset = knob.get("offset", 0)
                if step and step != 0:
                    knob["raw_min_documented"] = round((guide_spec["min"] - offset) / step)
                    knob["raw_max_documented"] = round((guide_spec["max"] - offset) / step)
                if guide_spec.get("unit") and not knob.get("unit"):
                    knob["unit"] = guide_spec["unit"]
                knobs_extended += 1
            elif kind_doc in ("enum", "onoff") and kind_probed == "enum":
                doc_vals = guide_spec["values"]
                # Replace whenever doc looks more authoritative (more values
                # OR contains values not in probed set).
                probed_vals = knob.get("values", [])
                if len(doc_vals) >= len(probed_vals) or set(doc_vals) - set(probed_vals):
                    knob["values_documented"] = doc_vals
                    enums_filled += 1
            elif kind_doc == "numeric" and kind_probed == "enum":
                # Probed thinks enum but guide says numeric — likely BTS shows
                # values like "20.0Hz" that we treat as enum strings. Document
                # the numeric range alongside.
                knob["documented_numeric_range"] = {
                    "min": guide_spec["min"],
                    "max": guide_spec["max"],
                    "unit": guide_spec.get("unit", ""),
                }
            elif kind_doc in ("enum", "onoff") and kind_probed in ("numeric", "numeric_irregular"):
                knob["documented_enum_values"] = guide_spec["values"]
            elif kind_doc == "ratio":
                knob["documented_value_format"] = guide_spec["raw"]
                knobs_extended += 1
            elif kind_doc == "freq_range":
                knob["documented_value_format"] = guide_spec["raw"]
                knobs_extended += 1

    CATALOG.write_text(json.dumps(catalog, indent=2))
    print()
    print(f"  numeric knobs extended with documented range: {knobs_extended}")
    print(f"  enum knobs filled with documented values: {enums_filled}")


if __name__ == "__main__":
    merge()
