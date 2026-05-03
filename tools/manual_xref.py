"""Cross-reference captured knobs with the GX-10 Parameter Guide TARGET list.

The manual's TARGET list (pages 83-106) lists every parameter for every
effect category. The list is in MANUAL canonical order, which for ~80%
of effects matches the GUI knob order. We:

  1. Parse the TARGET list into {category: [param, param, ...]}.
  2. Map our internal effect names (COMP, OD, ...) to manual category
     names (COMPRESSOR, OVERDRIVE, ...).
  3. Strip the parameters that are dropdowns / on-off buttons
     (ON/OFF, TYPE, SP TYPE, MODE, VOICE — these are captured separately
     and not knobs in our pipeline).
  4. Assign names to knob_idx in order. If counts don't match, flag the
     effect for manual review.

Discrepancies known up front:
  - HARM / HARM_BASS: TARGET has paired (1:/2:) ordering interleaved,
    GUI groups all 1: together then all 2:. Manual override applied.
  - PS / PS_BASS: same paired-vs-grouped issue.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANUAL = ROOT / "docs" / "manuals" / "GX-10_Parameter_Guide.txt"
TYPEBAR = ROOT / "captures" / "typebar_full"

# Map from our internal effect name → manual TARGET-list category
INTERNAL_TO_MANUAL = {
    "COMP": "COMPRESSOR",
    "X-COMP": "X COMPRESSOR",
    "BOOST": "BOOSTER",
    "OD": "OVERDRIVE",
    "X-OD": "X OVERDRIVE",
    "DIST": "DISTORTION",
    "X-DIST": "X DISTORTION",
    "METAL": "METAL DISTORTION",
    "FUZZ": "FUZZ",
    "AMP": "PREAMP",
    "PEQ": "PARAMETRIC EQ",
    "GEQ": "GRAPHIC EQ",
    "CHO": "CHORUS",
    "CHO_PRIME": "PRIME CHORUS",
    "FL": "FLANGER",
    "FL_PRIME": "PRIME FLANGER",
    "PH": "PHASER",
    "PH_SCRIPT": "SCRIPT PHASER",
    "PH_PRIME": "PRIME PHASER",
    "CLASS_VIBE": "CLASSIC VIBE",
    "ROTARY": "ROTARY",
    "VIB": "VIBRATO",
    "VIB_PRIME": "PRIME VIBRATO",
    "TREM": "TREMOLO",
    "PAN": "PAN",
    "RING_MOD": "RING MODULATOR",
    "SLICER": "SLICER",
    "HMN": "HUMANIZER",
    "PS": "PITCH SHIFTER",
    "HARM": "HARMONIST",
    "OVER_TONE": "OVERTONE",
    "OCT": "OCTAVE",
    "OCT_POLY": "POLY OCTAVE",
    "DELAY": "DELAY",
    "DELAY_PLUS": "DELAY PLUS",
    "DELAY_ANALOG": "ANALOG DELAY",
    "SPACE_ECHO": "SPACE ECHO",
    "DELAY_SHIMMER": "SHIMMER DELAY",
    "TERA_ECHO": "TERA ECHO",
    "DELAY_TWIST": "TWIST",
    "DELAY_WARP": "WARP",
    "REV": "REVERB",
    "REV_PLUS": "REVERB PLUS",
    "REV_SHIMMER": "SHIMMER REVERB",
    "AC_SIM": "AC GUITAR SIM",
    "AC_RESO": "AC RESONANCE",
    "FB": "FEEDBACKER",
    "SITAR_SIM": "SITAR SIM",
    "SG": "SLOW GEAR",
    "DEFRET": "DEFRETTER",
    "T_WAH": "TOUCH WAH",
    "A_WAH": "AUTO WAH",
    "S_BEND": "S-BEND",
    "WAH": "WAH",
    "PB": "PEDAL BEND",
    "FOOT_VOL": "FOOT VOLUME",
    "NS": "NOISE SUPPRESSOR",
    "DIV_MIX": "DIVIDER",   # special — has DIVIDER and MIXER sections
    "SEND_RETURN": "SEND/RETURN",
    "LOOP": "LOOP",
    "X_COMP_BASS": "BASS X COMP",
    "OD_BASS": "BASS OVERDRIVE",
    "X_OD_BASS": "X BASS OVERDRIVE",
    "DIST_BASS": "BASS DISTORTION",
    "METAL_BASS": "BASS METAL DIST",
    "FUZZ_BASS": "BASS FUZZ",
    "AMP_BASS": "BASS PREAMP",
    "CHO_BASS": "BASS CHORUS",
    "FL_BASS": "BASS FLANGER",
    "FL_PRIME_BASS": "BASS PRIME FLANGER",
    "PH_BASS": "BASS PHASER",
    "PH_PRIME_BASS": "BASS PRIME PHASER",
    "PS_BASS": "BASS PITCH SHIFTER",
    "HARM_BASS": "BASS HARMONIST",
    "OCT_BASS": "BASS OCTAVE",
    "SG_BASS": "BASS SLOW GEAR",
    "DEFRET_BASS": "BASS DEFRETTER",
    "T_WAH_BASS": "BASS TOUCH WAH",
    "S_BEND_BASS": "BASS S-BEND",
    "WAH_BASS": "BASS WAH",
    "PB_BASS": "BASS PEDAL BEND",
    "T_WAH": "TOUCH WAH",  # TOUCH WAH, not TWAH
}

# Always-filtered (these are not knobs, never appear as visible param):
ALWAYS_FILTER = {"ON/OFF"}

# These are TYPE-style dropdowns at y=494 in TS. We capture them as
# separate `type_address` / `sp_type_address` fields in summary.json,
# so they're NOT in the knob list. Per-effect handling because some
# effects (like CHORUS) expose TYPE as a knob in non-default GUI rows.
# Filter only when summary.has_type / has_sp_type indicates a dropdown.

# Effects with paired (1:/2:) ordering that GUI groups instead of
# interleaves. Override the TARGET-list order for these.
GUI_OVERRIDE = {
    "HARM": [
        "1: HARMONY", "1: LEVEL", "1: PRE-DELAY", "1: FEEDBACK",
        "KEY", "DIRECT LEVEL", "BPM",
        "2: HARMONY", "2: LEVEL", "2: PRE-DELAY",
        "HR1: C", "HR1: D ³", "HR1: D", "HR1: E ³", "HR1: E",
        "HR1: F", "HR1: F ´", "HR1: G", "HR1: A ³", "HR1: A",
        "HR1: B ³", "HR1: B",
        "HR2: C", "HR2: D ³", "HR2: D", "HR2: E ³", "HR2: E",
        "HR2: F", "HR2: F ´", "HR2: G", "HR2: A ³", "HR2: A",
        "HR2: B ³", "HR2: B",
    ],
    "HARM_BASS": [
        "1: HARMONY", "1: LEVEL", "1: PRE-DELAY", "1: FEEDBACK",
        "KEY", "DIRECT LEVEL", "BPM",
        "2: HARMONY", "2: LEVEL", "2: PRE-DELAY",
        "HR1: C", "HR1: D ³", "HR1: D", "HR1: E ³", "HR1: E",
        "HR1: F", "HR1: F ´", "HR1: G", "HR1: A ³", "HR1: A",
        "HR1: B ³", "HR1: B",
        "HR2: C", "HR2: D ³", "HR2: D", "HR2: E ³", "HR2: E",
        "HR2: F", "HR2: F ´", "HR2: G", "HR2: A ³", "HR2: A",
        "HR2: B ³", "HR2: B",
    ],
    # PS: similar 1:/2: pattern — TBD, leave to TARGET order for now
}


def parse_target_list():
    """Parse TARGET list section from the manual. Returns
    {category_name: [param_name, ...]}."""
    text = MANUAL.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    # Find start of TARGET list section: line starting "TARGET list"
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "TARGET list":
            start = i; break
    if start is None:
        raise RuntimeError("TARGET list not found")

    cats = {}
    cur_cat = None
    cur_list = None
    for ln in lines[start + 2:]:  # skip "TARGET list" and "CATEGORY TARGET"
        s = ln.rstrip()
        if not s or s.startswith("==="):
            continue
        if s.strip() == "CATEGORY TARGET":
            continue
        # Skip page header noise
        if s.strip() in ("MENU", "EFFECTS"):
            continue
        # Bare numeric lines (page numbers)
        if re.fullmatch(r"\d{1,3}", s.strip()):
            continue
        # New category line: "<NAME> ON/OFF"
        m = re.match(r"^(.+?)\s+ON/OFF\s*$", s)
        if m:
            cur_cat = m.group(1).strip()
            cur_list = ["ON/OFF"]
            cats[cur_cat] = cur_list
            continue
        # Special-case categories without ON/OFF.
        # "DIVIDER MODE" / "MIXER MODE" both occur in DIV_MIX section;
        # "MASTER MEMORY LEVEL" starts the MASTER block.
        sl = s.strip()
        if sl == "DIVIDER MODE":
            cur_cat = "DIVIDER"; cur_list = ["MODE"]; cats[cur_cat] = cur_list
            continue
        if sl == "MIXER MODE":
            cur_cat = "MIXER"; cur_list = ["MODE"]; cats[cur_cat] = cur_list
            continue
        if sl == "MASTER MEMORY LEVEL":
            cur_cat = "MASTER"; cur_list = ["MEMORY LEVEL"]; cats[cur_cat] = cur_list
            continue
        if cur_list is not None:
            # End of TARGET list (KNOB SETTINGS section etc.)
            if "KNOB SETTINGS" in s or "TUNER ON/OFF" in s:
                # TUNER ON/OFF marks the MASTER block end
                if "TUNER ON/OFF" in s:
                    cur_list.append(s.strip())
                cur_cat = None
                cur_list = None
                break
            cur_list.append(s.strip())
    return cats


def filter_to_knobs(params, has_type=False, has_sp_type=False):
    """Strip ON/OFF and TYPE/SP TYPE dropdowns (when present as
    dropdowns in GUI). Other params (MODE, VOICE, WAVEFORM, etc.)
    remain since they're knob-style enum cyclers in the GUI."""
    out = []
    for p in params:
        if p in ALWAYS_FILTER:
            continue
        # Only filter "TYPE" if effect has a TYPE dropdown
        if p == "TYPE" and has_type:
            continue
        if p == "SP TYPE" and has_sp_type:
            continue
        out.append(p)
    return out


def main():
    cats = parse_target_list()
    print(f"Parsed {len(cats)} categories from TARGET list")

    matched = 0
    mismatched = []
    for sp in sorted(TYPEBAR.glob("page*/*/summary.json")):
        s = json.loads(sp.read_text())
        name = s["name"]
        manual_name = INTERNAL_TO_MANUAL.get(name)
        if not manual_name or manual_name not in cats:
            print(f"  {name}: no manual entry ({manual_name})")
            continue
        if name in GUI_OVERRIDE:
            ordered = GUI_OVERRIDE[name]
        else:
            ordered = filter_to_knobs(
                cats[manual_name],
                has_type=s.get("has_type", False),
                has_sp_type=s.get("has_sp_type", False))
        # All knobs (base + extras) in display order
        all_knobs = list(s.get("knobs", []))
        # Sort extras by knob position (row, col) and append
        extras = sorted(s.get("knobs_extra", []),
                        key=lambda k: (k["knob_y"], k["knob_x"]))
        for k in extras:
            all_knobs.append(k)
        # Deduplicate by (x, y)
        seen = set()
        ordered_knobs = []
        for k in all_knobs:
            xy = (k["knob_x"], k["knob_y"])
            if xy in seen:
                continue
            seen.add(xy)
            ordered_knobs.append(k)
        # Sort by row (y) then column (x) for canonical display order
        ordered_knobs.sort(key=lambda k: (k["knob_y"], k["knob_x"]))

        # Common mismatch: BPM knob (master, address 0x10000F02) appears
        # in many effects' GUI but is listed in manual as MASTER BPM, not
        # under each effect. If we have exactly one more captured knob
        # than manual lists, and one of our knobs hits that address,
        # append "BPM" (master).
        if len(ordered_knobs) == len(ordered) + 1:
            has_bpm_knob = any(
                k.get("address") == "10000F02" for k in ordered_knobs
            )
            if has_bpm_knob:
                ordered = ordered + ["BPM"]
        if len(ordered_knobs) != len(ordered):
            mismatched.append((name, len(ordered_knobs), len(ordered)))
            # Save partial: pad with "?" if too few names
            while len(ordered) < len(ordered_knobs):
                ordered.append("?")
            ordered = ordered[:len(ordered_knobs)]
        # Assign names
        for k, pname in zip(ordered_knobs, ordered):
            k["name_manual"] = pname
        # Save back: rewrite knobs / knobs_extra preserving original
        # (x,y) → keep mutated dicts in place
        sp.write_text(json.dumps(s, indent=2, default=list))
        matched += 1

    print(f"\nMatched {matched} effects with manual TARGET names.")
    if mismatched:
        print(f"\nMismatches ({len(mismatched)}):")
        for name, got, expected in mismatched:
            print(f"  {name}: captured {got} knobs, manual lists {expected} after filter")


if __name__ == "__main__":
    main()
