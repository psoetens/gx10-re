"""Cross-reference captured knobs against the chunked Parameter_Guide.md files.

The five chunks (`docs/manuals/GX-10_Parameter_Guide_0[1-5]_*.md`) are
clean Markdown with one table per effect. Each effect section looks like:

    COMPRESSOR

    | Chain  | Palette |
    | :---- | :---- |
    | **** | **** |

    This is an effect that produces a long sustain ...

    | Parameter  | Value  | Explanation |
    | :---- | :---- | :---- |
    | ON/OFF       | OFF, ON  | Turns this effect on/off. |
    | TYPE         | BOSS COMP  | ... |
    |              | D-COMP     | ... |
    |              | ORANGE     | ... |
    | SUSTAIN      | 0–100      | ... |
    | ATTACK       | 0–100      | ... |
    | ...

The Parameter column may be bold-wrapped (`**NAME**`) or plain. Empty
Parameter cells are continuation rows of the previous parameter's enum
(typically TYPE).

This script:
  1. Parses every effect section from the 5 chunks.
  2. Builds {effect_name: [param_dict, ...]}.
  3. Maps each captured effect (summary.json) to its manual entry by
     looking up our internal name in MANUAL_ALIAS and assigns names to
     knobs in GUI position order.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANUALS = ROOT / "docs" / "manuals"
TYPEBAR = ROOT / "captures" / "typebar_full"

CHUNKS = [
    "GX-10_Parameter_Guide_01_effects_distortion_p001-p011.md",
    "GX-10_Parameter_Guide_02_effects_mod_pitch_p012-p030.md",
    "GX-10_Parameter_Guide_03_effects_delay_misc_p031-p050.md",
    "GX-10_Parameter_Guide_04_effects_bass_master_p051-p067.md",
]

# Map our internal effect name → manual section heading (ALL-CAPS).
# Multi-name aliases let us match either spelling.
INTERNAL_TO_MANUAL = {
    "COMP":          ["COMPRESSOR"],
    "X-COMP":        ["X-COMPRESSOR"],
    "BOOST":         ["BOOSTER"],
    "OD":            ["OVERDRIVE"],
    "X-OD":          ["X OVERDRIVE", "X-OVERDRIVE"],
    "DIST":          ["DISTORTION"],
    "X-DIST":        ["X DISTORTION", "X-DISTORTION"],
    "METAL":         ["METAL DISTORTION"],
    "FUZZ":          ["FUZZ"],
    "AMP":           ["AIRD PREAMP"],
    "PEQ":           ["PARAMETRIC EQUALIZER"],
    "GEQ":           ["GRAPHIC EQUALIZER"],
    "CHO":           ["CHORUS"],
    "CHO_PRIME":     ["PRIME CHORUS"],
    "FL":            ["FLANGER"],
    "FL_PRIME":      ["PRIME FLANGER"],
    "PH":            ["PHASER"],
    "PH_SCRIPT":     ["SCRIPT PHASER"],
    "PH_PRIME":      ["PRIME PHASER"],
    "CLASS_VIBE":    ["CLASSIC-VIBE", "CLASSIC VIBE"],
    "ROTARY":        ["ROTARY"],
    "VIB":           ["VIBRATO"],
    "VIB_PRIME":     ["PRIME VIBRATO"],
    "TREM":          ["TREMOLO"],
    "PAN":           ["PAN"],
    "RING_MOD":      ["RING MODULATOR"],
    "SLICER":        ["SLICER"],
    "HMN":           ["HUMANIZER"],
    "PS":            ["PITCH SHIFTER"],
    "HARM":          ["HARMONIST"],
    "OVER_TONE":     ["OVERTONE"],
    "OCT":           ["OCTAVE"],
    "OCT_POLY":      ["POLY OCTAVE"],
    "DELAY":         ["DELAY"],
    "DELAY_PLUS":    ["DELAY PLUS"],
    "DELAY_ANALOG":  ["ANALOG DELAY"],
    "SPACE_ECHO":    ["SPACE ECHO"],
    "DELAY_SHIMMER": ["SHIMMER DELAY"],
    "TERA_ECHO":     ["TERA ECHO"],
    "DELAY_TWIST":   ["TWIST"],
    "DELAY_WARP":    ["WARP"],
    "REV":           ["REVERB"],
    "REV_PLUS":      ["REVERB PLUS"],
    "REV_SHIMMER":   ["SHIMMER REVERB"],
    "AC_SIM":        ["AC GUITAR SIMULATOR"],
    "AC_RESO":       ["AC RESONANCE"],
    "FB":            ["FEEDBACKER"],
    "SITAR_SIM":     ["SITAR SIMULATOR"],
    "SG":            ["SLOW GEAR"],
    "DEFRET":        ["DEFRETTER"],
    "T_WAH":         ["TOUCH WAH", "TOUCH WAH"],  # nbsp seen in PDF outline
    "A_WAH":         ["AUTO WAH"],
    "S_BEND":        ["S-BEND"],
    "WAH":           ["WAH"],
    "PB":            ["PEDAL BEND"],
    "FOOT_VOL":      ["FOOT VOLUME"],
    "NS":            ["NOISE SUPPRESSOR"],
    "DIV_MIX":       ["DIVIDER/MIXER"],
    "SEND_RETURN":   ["SEND/RETURN"],
    "LOOP":          ["PHRASE LOOP"],
    "X_COMP_BASS":   ["X-BASS COMPRESSOR"],
    "OD_BASS":       ["BASS OVERDRIVE"],
    "X_OD_BASS":     ["X BASS OVERDRIVE", "X-BASS OVERDRIVE"],
    "DIST_BASS":     ["BASS DISTORTION"],
    "METAL_BASS":    ["BASS METAL DISTORTION"],
    "FUZZ_BASS":     ["BASS FUZZ"],
    "AMP_BASS":      ["AIRD BASS PREAMP"],
    "CHO_BASS":      ["BASS CHORUS"],
    "FL_BASS":       ["BASS FLANGER"],
    "FL_PRIME_BASS": ["PRIME BASS FLANGER"],
    "PH_BASS":       ["BASS PHASER"],
    "PH_PRIME_BASS": ["PRIME BASS PHASER"],
    "PS_BASS":       ["BASS PITCH SHIFTER"],
    "HARM_BASS":     ["BASS HARMONIST"],
    "OCT_BASS":      ["BASS OCTAVE"],
    "SG_BASS":       ["BASS SLOW GEAR"],
    "DEFRET_BASS":   ["BASS DEFRETTER"],
    "T_WAH_BASS":    ["BASS TOUCH WAH"],
    "S_BEND_BASS":   ["BASS S-BEND"],
    "WAH_BASS":      ["BASS WAH"],
    "PB_BASS":       ["BASS PEDAL BEND"],
}

# Names of params that aren't visible knobs (always skip)
SKIP_AS_KNOB = {"ON/OFF"}

# Names that are dropdowns when the captured summary indicates one
DROPDOWN_NAMES = {"TYPE", "SP TYPE", "MIC TYPE", "VOICE", "MODE",
                   "WAH TYPE", "FILTER MODE", "PATTERN", "STAGE",
                   "INTELLIGENT", "POLARITY", "OUTPUT MODE",
                   "SPEED SELECT", "DIVIDER MODE", "MIXER MODE", "MIX MODE",
                   "CH SELECT", "WAVEFORM", "TRIGGER"}


def strip_md_formatting(s: str) -> str:
    """Remove **bold** wrapping and stray escapes from a cell value."""
    s = s.strip()
    s = re.sub(r"^\*\*(.*?)\*\*$", r"\1", s)
    s = s.replace("\\-", "-").replace("\\*", "*")
    return s.strip()


def parse_chunk(text: str):
    """Parse one chunk into [(effect_name, [param_dict, ...]), ...].

    Effect-section heading is detected as a non-table line that's all
    UPPER (with allowed punctuation) followed soon by a `| Chain | Palette |`
    table marker. The Parameter table is the second `|...|...|` table
    in each section.
    """
    lines = text.splitlines()
    sections = []  # (heading, start_line)
    heading_re = re.compile(r"^[A-Z][A-Z0-9 \-/+:'_\. ]*[A-Z0-9]\s*$")
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not heading_re.match(s):
            continue
        # Skip page-running headers and TOC-ish headings
        if s in ("EFFECTS", "MENU", "CONTENTS"):
            continue
        # Look ahead for the "| Chain  | Palette |" marker within ~10 lines
        for j in range(i + 1, min(i + 12, len(lines))):
            if "Chain" in lines[j] and "Palette" in lines[j] and lines[j].strip().startswith("|"):
                sections.append((s, i))
                break

    results = []
    for k, (heading, start) in enumerate(sections):
        end = sections[k + 1][1] if k + 1 < len(sections) else len(lines)
        section_lines = lines[start:end]

        # Walk through the section and harvest EVERY "| Parameter | Value |
        # Explanation |" table (page breaks may split one logical table into
        # multiple physical tables under the same heading).
        params = []
        last_param_name = None
        j = 0
        while j < len(section_lines):
            t = section_lines[j].strip()
            if not t.startswith("|"):
                j += 1
                continue
            cells = [c.strip() for c in t.strip("|").split("|")]
            # Is this a Parameter table header?
            if cells and cells[0] == "Parameter":
                # Skip header + alignment row
                j += 1
                if j < len(section_lines) and re.match(
                        r"^\|[\s:\-]+\|", section_lines[j].strip()):
                    j += 1
                # Read rows until non-table
                while j < len(section_lines):
                    tt = section_lines[j].strip()
                    if not tt.startswith("|"):
                        break
                    rcells = [strip_md_formatting(c)
                              for c in tt.strip("|").split("|")]
                    if len(rcells) < 2:
                        j += 1
                        continue
                    name, value = rcells[0], rcells[1]
                    explanation = rcells[2] if len(rcells) >= 3 else ""
                    if not name:
                        if params and last_param_name:
                            params[-1].setdefault("enum_values", []).append(value)
                    else:
                        last_param_name = name
                        params.append({
                            "name": name,
                            "value": value,
                            "explanation": explanation,
                        })
                    j += 1
                continue
            j += 1
        results.append((heading, params))
    return results


def build_effect_db():
    db = {}
    for chunk in CHUNKS:
        path = MANUALS / chunk
        if not path.exists():
            print(f"  WARN: missing chunk {chunk}", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        for heading, params in parse_chunk(text):
            db[heading] = params
    return db


def lookup_manual(internal_name: str, db):
    aliases = INTERNAL_TO_MANUAL.get(internal_name, [])
    for a in aliases:
        if a in db:
            return a, db[a]
    # Last-ditch: case-insensitive contains match
    for k in db:
        for a in aliases:
            if a.upper() == k.upper():
                return k, db[k]
    return None, None


def expand_paired_params(params):
    """Some manual rows pair two params in one cell (e.g. "1: HARMONY  2: HARMONY").
    Expand each such row into two separate entries."""
    out = []
    for p in params:
        n = p["name"]
        # Detect "1: NAME  2: NAME" pattern
        m = re.match(r"^(1:\s*\S.*?)\s+(2:\s*\S.*)$", n)
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            out.append({**p, "name": a})
            out.append({**p, "name": b})
            continue
        # Detect "HR1:X  HR2:X" pattern (USER SCALE)
        m = re.match(r"^(HR1:\s*\S.*?)\s+(HR2:\s*\S.*)$", n)
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            out.append({**p, "name": a})
            out.append({**p, "name": b})
            continue
        out.append(p)
    return out


def filter_for_knobs(params, summary):
    """Return [param_name, ...] in manual order, dropping non-knob entries.

    - Always drops ON/OFF.
    - Drops TYPE if the effect has a TYPE dropdown (has_type=True).
    - Drops SP TYPE if the effect has SP TYPE (has_sp_type=True).
    - Drops other generic dropdown labels (MODE, VOICE, etc.) when their
      enum is large enough to look like a TS-popup dropdown rather than a
      knob-style enum.
    """
    has_type = summary.get("has_type", False)
    has_sp = summary.get("has_sp_type", False)
    out = []
    for p in params:
        n = p["name"]
        if n in SKIP_AS_KNOB:
            continue
        if n == "TYPE" and has_type:
            continue
        # HARMONIST/PITCH SHIFTER call their TYPE dropdown "VOICE"
        if n == "VOICE" and has_type:
            continue
        if n == "SP TYPE" and has_sp:
            continue
        # MIC TYPE in AMP family is a dropdown
        if n == "MIC TYPE" and has_sp:
            continue
        out.append(n)
    return out


def main():
    from gui_override import get_override
    db = build_effect_db()
    print(f"Parsed {len(db)} effect sections from manual chunks.")

    matched = 0
    mismatch = []
    no_manual = []
    overridden = []
    for sp in sorted(TYPEBAR.glob("page*/*/summary.json")):
        s = json.loads(sp.read_text())
        name = s["name"]
        manual_heading, params = lookup_manual(name, db)
        if not params:
            no_manual.append(name)
            continue
        # Apply hard-coded GUI override when defined (HARM, PS, etc.)
        ov = get_override(manual_heading)
        if ov is not None:
            knob_names = list(ov)
            overridden.append(name)
        else:
            params_expanded = expand_paired_params(params)
            knob_names = filter_for_knobs(params_expanded, s)
        # If the effect has a captured BPM knob (master, addr 0x10000F02)
        # and the manual list doesn't include "BPM", append it.
        # Skip this for overridden effects since override already names BPM.
        captured_addrs = {k.get("address") for k in s.get("knobs", [])}
        captured_addrs |= {k.get("address") for k in s.get("knobs_extra", [])}
        if ov is None and "10000F02" in captured_addrs and "BPM" not in knob_names:
            knob_names = knob_names + ["BPM"]
        # Collect captured knobs + extras, ordered by (y, x) (GUI top-left
        # to bottom-right reading order).
        captured = list(s.get("knobs", []))
        captured += list(s.get("knobs_extra", []))
        # Dedupe by (x,y) keeping first occurrence
        seen = set()
        ordered = []
        for k in captured:
            xy = (k["knob_x"], k["knob_y"])
            if xy in seen:
                continue
            seen.add(xy)
            ordered.append(k)
        ordered.sort(key=lambda k: (k["knob_y"], k["knob_x"]))

        # Pad name list with "?" if mismatch
        n_got, n_want = len(ordered), len(knob_names)
        names = list(knob_names)
        if n_got > n_want:
            names += ["?"] * (n_got - n_want)
        else:
            names = names[:n_got]
        for k, nm in zip(ordered, names):
            k["name_manual_v2"] = nm

        # Save back into summary
        sp.write_text(json.dumps(s, indent=2, default=list))
        matched += 1
        if n_got != n_want:
            mismatch.append((name, manual_heading, n_got, n_want))

    print(f"Matched {matched} effects against manual chunks.")
    if overridden:
        print(f"GUI override applied to {len(overridden)}: {', '.join(overridden)}")
    if no_manual:
        print(f"\nNo manual entry found for {len(no_manual)} effects:")
        for n in no_manual:
            print(f"  {n}")
    if mismatch:
        print(f"\nKnob count mismatches ({len(mismatch)}):")
        for name, heading, got, want in mismatch:
            print(f"  {name:18s} (manual: {heading:24s})  captured={got}  manual={want}")


if __name__ == "__main__":
    main()
