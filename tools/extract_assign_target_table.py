"""Parse the 740-entry ASSIGN TARGET TABLE from the official MIDI chart.

Source: GX-100_GX-10_MIDI_Imple_eng02_W.md, the section starting with
"\\*2 ASSIGN TARGET TABLE" at line 414. The table runs as one
continuous block of "INDEX CATEGORY TARGET" rows, with periodic
"INDEX CATEGORY TARGET" header lines as section separators (every
~106 entries due to PDF page boundaries).

Each row looks like:
    "  N CATEGORY ... TARGET ..."
where N is the index, CATEGORY is the effect family name, and TARGET
is the parameter name within that category.

The parser tokenises the line by index numbers (an integer at start
of a "word" indicates a new entry). It handles multi-word CATEGORYs
(e.g. "BASS PRIME PHASER") and TARGETs (e.g. "1:HARMONY").
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MD = ROOT / "docs" / "manuals" / "GX-100_GX-10_MIDI_Imple_eng02_W.md"
OUT_JSON = ROOT / "docs" / "assign_target_table.json"
OUT_PY = ROOT / "tools" / "assign_target_table.py"


# Categories recognized in the table (longest first so multi-word
# matches win over single-word).
CATEGORIES = [
    "BASS PRIME PHASER", "BASS PRIME FLANGER", "BASS PEDAL BEND",
    "BASS PITCH SHIFTER", "BASS METAL DIST", "BASS X COMP",
    "BASS HARMONIST", "PRIME BASS PHASER", "PRIME PHASER",
    "PRIME FLANGER", "PRIME CHORUS", "PRIME VIBARTO", "PRIME VIBRATO",
    "BASS S-BEND", "BASS TOUCH WAH", "BASS DEFRETTER", "BASS SLOW GEAR",
    "BASS FLANGER", "BASS PHASER", "BASS DISTORTION", "BASS OVERDRIVE",
    "BASS METAL DISTORTION", "BASS METAL DIST",
    "BASS METAL", "BASS FUZZ", "BASS CHORUS", "BASS PREAMP", "BASS WAH",
    "X BASS OVERDRIVE", "X DISTORTION", "X COMPRESSOR", "X OVERDRIVE",
    "BASS OCTAVE", "PARAMETRIC EQ", "PARAMETRIC EQUALIZER",
    "GRAPHIC EQ", "GRAPHIC EQUALIZER",
    "AC GUITAR SIM", "AC RESONANCE", "POLY OCTAVE", "DELAY PLUS",
    "ANALOG DELAY", "SPACE ECHO", "SHIMMER DELAY", "SHIMMER REVERB",
    "REVERB PLUS", "TERA ECHO", "RING MODULATOR", "PHRASE LOOP",
    "SCRIPT PHASER", "PITCH SHIFTER", "CLASSIC VIBE",
    "NOISE SUPPRESSOR", "TOUCH WAH", "AUTO WAH", "FOOT VOLUME",
    "PEDAL BEND", "RING MODULATOR", "ROTARY", "S-BEND", "SLOW GEAR",
    "DEFRETTER", "DISTORTION", "OVERDRIVE", "COMPRESSOR", "BOOSTER",
    "CHORUS", "FLANGER", "PHASER", "TREMOLO", "VIBRATO",
    "OVERTONE", "OCTAVE", "REVERB", "TWIST", "WARP", "DELAY",
    "FUZZ", "PREAMP", "PAN", "DIVIDER", "MIXER", "WAH",
    "SLICER", "HUMANIZER", "FEEDBACKER", "SITAR SIM",
    "HARMONIST", "MASTER", "TUNER", "MIDI", "SEND/RETURN",
    "EFFECT(RENAMED WITH TYPE)", "EFFECT",
]


def extract_table_text(md_path: Path) -> str:
    """Pull the lines from the *2 ASSIGN TARGET TABLE marker until the
    closing horizontal-rule (the next "\\* \\[" major section marker)."""
    text = md_path.read_text(encoding="utf-8")
    start = text.find("*2 ASSIGN TARGET TABLE")
    if start < 0:
        raise RuntimeError("ASSIGN TARGET TABLE marker not found")
    # Find next "\\* \\[" major heading after that
    next_section = text.find("\\* \\[SystemEfct", start)
    if next_section < 0:
        next_section = len(text)
    return text[start:next_section]


def normalize_text(raw: str) -> str:
    """Strip Markdown escapes and collapse whitespace."""
    s = raw
    s = s.replace("\\#", "#").replace("\\-", "-").replace("\\*", "*")
    s = s.replace("\\\\", "")
    # Strip header separator lines
    s = re.sub(r"^-{5,}.*$", "", s, flags=re.MULTILINE)
    s = re.sub(r"INDEX +CATEGORY +TARGET", "", s)
    # Collapse all whitespace to single spaces
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def tokenize_entries(flat: str):
    """Split the flat-text into entries of `(index, body)`. An entry
    starts at each integer that is followed by ALL CAPS / category
    text. We use the regex of `\\b(\\d{1,3})\\s+([A-Z])` to find them."""
    # Find all `<index> <body>` runs
    parts = re.split(r"(?<!\\d)(\d{1,3})\s+(?=[A-Z\-])", flat)
    # parts[0] is preamble, then alternating (idx, body)
    entries = []
    i = 1
    while i + 1 <= len(parts) - 1:
        idx = int(parts[i])
        body = parts[i + 1].strip()
        # Trim trailing fragments that belong to the next entry
        # (the regex split already isolates them)
        # Cap the body at 80 chars to prevent runaway joins
        entries.append((idx, body))
        i += 2
    return entries


def split_category_target(body: str):
    """Given 'AC GUITAR SIM BODY' or 'BASS HARMONIST 1:Db', split into
    (CATEGORY, TARGET). We try the longest matching CATEGORY prefix."""
    for cat in CATEGORIES:
        if body.startswith(cat + " "):
            return cat, body[len(cat) + 1:].strip()
        if body == cat:
            return cat, ""
    # Fallback: take first word as category
    parts = body.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def main():
    raw = extract_table_text(MD)
    flat = normalize_text(raw)
    entries = tokenize_entries(flat)
    print(f"Tokenised {len(entries)} entries")

    parsed = {}
    for idx, body in entries:
        cat, tgt = split_category_target(body)
        parsed[idx] = {"category": cat, "target": tgt}

    # Sanity check: should cover 0..740
    missing = [i for i in range(741) if i not in parsed]
    if missing:
        print(f"WARNING: {len(missing)} indices missing: {missing[:20]}...")

    # Save JSON
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {str(k): v for k, v in sorted(parsed.items())},
        indent=2, ensure_ascii=False))
    print(f"Wrote {OUT_JSON} ({len(parsed)} entries)")

    # Save Python module
    lines = [
        '"""Official ASSIGN TARGET TABLE (740 entries) from the GX-100/GX-10',
        'MIDI Implementation chart. Maps assign-table index → (category, target).',
        '',
        'Used by the [Assign] block at MemoryCommon offset 0x000200..0x000B40.',
        'Setting an assign\'s TARGET field to one of these indices selects the',
        'parameter to be controlled by the assigned source.',
        '"""',
        "ASSIGN_TARGET = {",
    ]
    for k in sorted(parsed):
        v = parsed[k]
        c = v["category"].replace('"', '\\"')
        t = v["target"].replace('"', '\\"')
        lines.append(f'    {k}: ("{c}", "{t}"),')
    lines.append("}")
    lines.append("")
    OUT_PY.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PY}")


if __name__ == "__main__":
    main()
