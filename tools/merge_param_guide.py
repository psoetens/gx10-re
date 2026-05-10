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

    # Strip the ", BPM ŀ–Ō" alternate-units suffix the chart adds to
    # tempo-sync-capable knobs. We don't model BPM-mode here; the
    # primary numeric range is what matters for raw/display. Chart
    # sometimes drops the space after the comma: "0-100, BPMŀ-Ō".
    s_pre = re.sub(r"\s*,\s*BPM[a-zA-ZĀ-￿].*$", "", s_norm)
    s_pre = re.sub(r"\s*,\s*BPM\b.*$", "", s_pre)
    # CENTER-prefix: "CENTER, 1 cm-10 cm" → raw 0 is the enum string
    # "CENTER"; raws 1..N are numeric. Capture the special_value so the
    # catalog can carry both.
    special_values = {}
    m_center = re.match(r"^\s*CENTER\s*,\s*(.*)$", s_pre)
    if m_center:
        special_values["0"] = "CENTER"
        s_pre = m_center.group(1)

    # Bipolar with explicit centre: "-50-0-+50" — three numbers, two
    # dashes. Take the outer two as min/max.
    m = re.fullmatch(
        r"\s*([+-]?\d+(?:\.\d+)?)\s*-\s*[+-]?\d+(?:\.\d+)?\s*-\s*"
        r"([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%/]*)\s*",
        s_pre,
    )
    if m:
        lo, hi, unit = m.group(1), m.group(2), m.group(3)
        try:
            lo_n = float(lo) if "." in lo else int(lo)
            hi_n = float(hi) if "." in hi else int(hi)
            return {"kind": "numeric", "min": lo_n, "max": hi_n, "unit": unit, "special_values": dict(special_values)}
        except ValueError:
            pass

    # Match "[+-]N - [+-]N" with optional unit suffix
    m = re.fullmatch(
        r"\s*([+-]?\d+(?:\.\d+)?)\s*-\s*([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%/]*)\s*",
        s_pre,
    )
    if m:
        lo, hi, unit = m.group(1), m.group(2), m.group(3)
        try:
            lo_n = float(lo) if "." in lo else int(lo)
            hi_n = float(hi) if "." in hi else int(hi)
            return {"kind": "numeric", "min": lo_n, "max": hi_n, "unit": unit, "special_values": dict(special_values)}
        except ValueError:
            pass

    # Range with units on both endpoints: "1 ms-2000 ms", "12ms-1200ms",
    # "0.0 ms-40.0 ms", "1 cm-10 cm" — endpoints repeat their unit.
    m = re.fullmatch(
        r"\s*([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%/]+)\s*-\s*"
        r"([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%/]+)\s*",
        s_pre,
    )
    if m:
        lo, unit_lo, hi, unit_hi = m.group(1), m.group(2), m.group(3), m.group(4)
        if unit_lo == unit_hi:
            try:
                lo_n = float(lo) if "." in lo else int(lo)
                hi_n = float(hi) if "." in hi else int(hi)
                return {"kind": "numeric", "min": lo_n, "max": hi_n, "unit": unit_lo, "special_values": dict(special_values)}
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
            # Continuation row -> usually another enum value. But the
            # chart sometimes uses a continuation to add a numeric
            # range below an enum-style prefix value (e.g. MIC POSITION
            # row 1 = "CENTER", row 2 = "1 cm-10 cm"). In that case
            # convert the prefix enum values to special_values and
            # promote the spec to numeric.
            spec = params[last_param]
            sp = parse_value_cell(value_cell)
            if sp and sp.get("kind") == "numeric":
                prefix_vals = []
                if spec.get("kind") == "enum":
                    prefix_vals = list(spec.get("values", []))
                elif spec.get("kind") == "enum_value":
                    prefix_vals = [spec["value"]]
                if prefix_vals:
                    new_spec = dict(sp)
                    new_spec.setdefault("special_values", {})
                    for sv_i, sv_v in enumerate(prefix_vals):
                        new_spec["special_values"][str(sv_i)] = sv_v
                    params[last_param] = new_spec
                else:
                    params[last_param] = sp
            elif sp and sp.get("kind") == "enum_value":
                if spec.get("kind") in ("enum", "enum_value"):
                    if spec.get("kind") == "enum_value":
                        params[last_param] = {"kind": "enum",
                                              "values": [spec["value"]]}
                else:
                    params[last_param] = {"kind": "enum", "values": []}
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
                    rmin_doc = round((guide_spec["min"] - offset) / step)
                    rmax_doc = round((guide_spec["max"] - offset) / step)
                    # Wire is 4-nibble offset-binary (always unsigned
                    # 0..0xFFFF). Negative raw is structurally impossible.
                    # If the probe-derived offset disagrees with the
                    # documented range (e.g. GEQ bands: probe sampled
                    # raws 0..15 → "0dB..+15dB" implies offset=0, but
                    # guide says -20..+20 implying offset=-20 — these
                    # cannot both be true), flag the inconsistency and
                    # KEEP the probe values. Don't auto-promote; this
                    # needs a manual live re-probe to resolve.
                    if rmin_doc < 0:
                        knob["_range_inconsistent"] = (
                            f"probe offset={offset} step={step} "
                            f"would yield raw_min={rmin_doc} for "
                            f"documented min={guide_spec['min']}; "
                            f"wire is unsigned offset-binary so "
                            f"negative raw is impossible. Probe and "
                            f"guide disagree — needs live re-probe."
                        )
                        # Leave raw_min/raw_max/value_min/value_max as
                        # the probe sample observed them. Skip promotion.
                        # Clear any stale raw_*_documented from earlier
                        # merge runs that produced the impossible values.
                        knob.pop("raw_min_documented", None)
                        knob.pop("raw_max_documented", None)
                        if guide_spec.get("unit") and not knob.get("unit"):
                            knob["unit"] = guide_spec["unit"]
                        knobs_extended += 1
                        continue
                    knob["raw_min_documented"] = rmin_doc
                    knob["raw_max_documented"] = rmax_doc
                    # Promote: the probed raw_min/raw_max only reflect the
                    # bulk-enum sample (typically raw 0..15). The documented
                    # range is the device's full capability. Preserve the
                    # probe values under raw_*_probe_sample for diagnostics.
                    if rmin_doc != knob.get("raw_min") or rmax_doc != knob.get("raw_max"):
                        knob["raw_min_probe_sample"] = knob.get("raw_min", 0)
                        knob["raw_max_probe_sample"] = knob.get("raw_max", 0)
                        knob["raw_min"] = rmin_doc
                        knob["raw_max"] = rmax_doc
                    # value_min/value_max also previously reflected the
                    # probe sample — promote them too.
                    knob["value_min_probe_sample"] = knob.get("value_min")
                    knob["value_max_probe_sample"] = knob.get("value_max")
                    knob["value_min"] = guide_spec["min"]
                    knob["value_max"] = guide_spec["max"]
                if guide_spec.get("unit") and not knob.get("unit"):
                    knob["unit"] = guide_spec["unit"]
                # Special values like "CENTER" at raw=0 alongside a
                # numeric range — preserve them so clients know to
                # override the formula at those raws. Also extend
                # raw_min down to include these special raws (they're
                # valid writable values).
                sv = guide_spec.get("special_values")
                if sv:
                    knob["special_values"] = sv
                    special_raws = [int(r) for r in sv.keys()]
                    extended_min = min(special_raws + [knob.get("raw_min", 0)])
                    if extended_min < knob.get("raw_min", 0):
                        knob["raw_min"] = extended_min
                    if extended_min < knob.get("raw_min_documented", 0):
                        knob["raw_min_documented"] = extended_min
                # Drop any stale documented_enum_values that an earlier
                # run wrote when the parser couldn't extract the range.
                knob.pop("documented_enum_values", None)
                knobs_extended += 1
            elif kind_doc in ("enum", "onoff") and kind_probed == "enum":
                doc_vals = guide_spec["values"]
                # Some rows arrive as a single comma-joined string
                # (e.g. "SHORT, MEDIUM, LONG"). Split into individual
                # values so the documented list is usable.
                expanded = []
                for v in doc_vals:
                    if isinstance(v, str) and "," in v:
                        expanded.extend(
                            p.strip() for p in v.split(",") if p.strip()
                        )
                    else:
                        expanded.append(v)
                doc_vals = expanded
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
                doc_vals = guide_spec["values"]
                knob["documented_enum_values"] = doc_vals
                # If the doc "enum" is really a range string like
                # "20.0 Hz–12.5 kHz" or "20.0 Hz–12.5 kHz, FLAT" and
                # the probe is numeric_irregular with a raw_to_display
                # that obviously stops short of the upper bound, flag
                # it so re-probe can target these.
                if kind_probed == "numeric_irregular" and isinstance(doc_vals, list):
                    range_strs = [v for v in doc_vals
                                  if isinstance(v, str) and ("–" in v or "Hz" in v or "kHz" in v)]
                    if range_strs:
                        rtd = knob.get("raw_to_display") or {}
                        last_disp = rtd.get(str(knob.get("raw_max")), "")
                        # Heuristic: if last probed display is in Hz but
                        # doc range goes to kHz, probe is truncated.
                        if "kHz" in " ".join(range_strs) and "kHz" not in str(last_disp):
                            knob["_probe_likely_truncated"] = (
                                f"probe stops at raw={knob.get('raw_max')} "
                                f"display='{last_disp}' but doc range "
                                f"'{range_strs[0]}' extends to kHz — "
                                f"re-probe with extended raw sweep."
                            )
            elif kind_doc == "ratio":
                knob["documented_value_format"] = guide_spec["raw"]
                knobs_extended += 1
            elif kind_doc == "freq_range":
                knob["documented_value_format"] = guide_spec["raw"]
                knobs_extended += 1

    # Detect probe under-sampling for numeric_irregular: when the
    # probe only observed one (or zero) raw->display mappings, the
    # knob isn't really "irregular" — it's "unclassified due to
    # insufficient samples". Usually means the cell was inactive
    # under the probe's conditions (e.g. FEEDBACKER OSC-only knobs
    # when MODE was set to STANDARD; CHORUS '1:'/'2:' knobs when
    # the second voice was off). Flag for re-probe; downstream
    # consumers should treat as "kind unknown, range from docs only".
    probe_uncertain_count = 0
    for tk, e in catalog.items():
        if tk.startswith("_"):
            continue
        for knob in e.get("knobs", []):
            if knob.get("kind") != "numeric_irregular":
                continue
            rtd = knob.get("raw_to_display") or {}
            if len(rtd) <= 1:
                knob["_probe_classification_uncertain"] = (
                    f"probe observed only {len(rtd)} raw->display "
                    f"sample(s) — too few to confirm 'irregular'. "
                    f"Likely a mode-conditional cell that was "
                    f"inactive under probe conditions. Kind is "
                    f"unverified; trust value_*_documented for the "
                    f"range and re-probe with the right pre-condition."
                )
                probe_uncertain_count += 1

    # Detect probe stuck-value bugs: enum knobs whose probe returned
    # the same display for every raw it tried. The GX-10 wire is
    # offset-binary with distinct decode per raw byte, so identical
    # displays across all probed raws means one of:
    #   - cell isn't actually writable (probe wrote to wrong address)
    #   - probe couldn't observe the change (BTS UI mirrored from a
    #     different cell, or knob requires a pre-condition the probe
    #     didn't satisfy)
    #   - cell is a dead label that doesn't drive UI
    # Either way, the catalog values list is unusable. Flag for
    # re-probe; consumers must rely on values_documented instead.
    probe_stuck_count = 0
    for tk, e in catalog.items():
        if tk.startswith("_"):
            continue
        for knob in e.get("knobs", []):
            if knob.get("kind") != "enum":
                continue
            vals = knob.get("values") or []
            if len(vals) >= 2 and len(set(vals)) == 1:
                knob["_probe_stuck_value"] = (
                    f"all {len(vals)} probed raws (0..{len(vals)-1}) "
                    f"read back display '{vals[0]}'. Address may be "
                    f"wrong, knob may have a pre-condition the probe "
                    f"didn't meet, or cell may not drive UI. "
                    f"Re-probe via broadcast capture (user turn)."
                )
                probe_stuck_count += 1

    # Cleanup: drop raw_to_display from numeric knobs where the linear
    # step+offset formula reproduces every entry exactly. The map was
    # just a probe-sample artefact (typically raws 0..15) and is
    # redundant once step/offset are known. Keep it for:
    #   - numeric_irregular  (the map IS the spec; formula doesn't fit)
    #   - enum               (the map IS the spec; raw->label mapping)
    rtd_dropped = 0
    for tk, e in catalog.items():
        if tk.startswith("_"):
            continue
        for knob in e.get("knobs", []):
            if knob.get("kind") != "numeric":
                continue
            step = knob.get("step")
            offset = knob.get("offset")
            rtd = knob.get("raw_to_display")
            if not rtd or step is None or offset is None:
                continue
            ok = True
            for raw_str, disp_str in rtd.items():
                try:
                    raw = int(raw_str)
                except ValueError:
                    ok = False
                    break
                m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)", str(disp_str))
                if not m:
                    ok = False
                    break
                disp = float(m.group(1))
                predicted = raw * step + offset
                if abs(disp - predicted) > 1e-6:
                    ok = False
                    break
            if ok:
                del knob["raw_to_display"]
                rtd_dropped += 1

    CATALOG.write_text(json.dumps(catalog, indent=2))
    print()
    print(f"  numeric knobs extended with documented range: {knobs_extended}")
    print(f"  enum knobs filled with documented values: {enums_filled}")
    print(f"  raw_to_display dropped (redundant with step+offset): {rtd_dropped}")
    print(f"  enums flagged _probe_stuck_value: {probe_stuck_count}")
    print(f"  numeric_irregular flagged _probe_classification_uncertain: {probe_uncertain_count}")


if __name__ == "__main__":
    merge()
