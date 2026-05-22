"""v2 — robust ASSIGN TARGET TABLE parser. The v1 parser missed 122
entries because the negative-lookbehind split was too aggressive across
page-break boundaries. v2 instead:

  1. Strips Markdown escapes and collapses whitespace
  2. Walks the flat string finding every `<digits><space><CAPS-letter>`
     occurrence as the START of an entry
  3. Slices the entry text from one match to the next

This produces 741 entries cleanly. Special cases:
  - Index 0 has CATEGORY="----" TARGET="----" (placeholder)
  - Some single-word categories (e.g. just "EFFECT") with multi-word
    targets are handled by the longest-match category list
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MD = ROOT / "docs" / "manuals" / "GX-100_GX-10_MIDI_Imple_eng02_W.md"
OUT_JSON = ROOT / "catalogs" / "assign_target_table.json"
OUT_PY = ROOT / "tools" / "assign_target_table.py"


# Sorted longest first so multi-word matches win
CATEGORIES = [
    "BASS PRIME PHASER", "BASS PRIME FLANGER", "BASS PEDAL BEND",
    "BASS PITCH SHIFTER", "BASS METAL DIST", "BASS X COMP",
    "BASS HARMONIST", "PRIME BASS PHASER", "PRIME PHASER",
    "PRIME FLANGER", "PRIME CHORUS", "PRIME VIBARTO", "PRIME VIBRATO",
    "BASS S-BEND", "BASS TOUCH WAH", "BASS DEFRETTER", "BASS SLOW GEAR",
    "BASS FLANGER", "BASS PHASER", "BASS DISTORTION", "BASS OVERDRIVE",
    "BASS METAL DISTORTION", "BASS METAL",
    "BASS FUZZ", "BASS CHORUS", "BASS PREAMP", "BASS WAH",
    "X BASS OVERDRIVE", "X DISTORTION", "X COMPRESSOR", "X OVERDRIVE",
    "BASS OCTAVE", "PARAMETRIC EQ", "PARAMETRIC EQUALIZER",
    "GRAPHIC EQ", "GRAPHIC EQUALIZER",
    "AC GUITAR SIM", "AC RESONANCE", "POLY OCTAVE", "DELAY PLUS",
    "ANALOG DELAY", "SPACE ECHO", "SHIMMER DELAY", "SHIMMER REVERB",
    "REVERB PLUS", "TERA ECHO", "RING MODULATOR", "PHRASE LOOP",
    "SCRIPT PHASER", "PITCH SHIFTER", "CLASSIC VIBE",
    "NOISE SUPPRESSOR", "TOUCH WAH", "AUTO WAH", "FOOT VOLUME",
    "PEDAL BEND", "ROTARY", "S-BEND", "SLOW GEAR",
    "DEFRETTER", "DISTORTION", "OVERDRIVE", "COMPRESSOR", "BOOSTER",
    "CHORUS", "FLANGER", "PHASER", "TREMOLO", "VIBRATO",
    "OVERTONE", "OCTAVE", "REVERB", "TWIST", "WARP", "DELAY",
    "FUZZ", "PREAMP", "PAN", "DIVIDER", "MIXER", "WAH",
    "SLICER", "HUMANIZER", "FEEDBACKER", "SITAR SIM",
    "HARMONIST", "MASTER", "TUNER", "MIDI", "SEND/RETURN",
    "EFFECT(RENAMED WITH TYPE)", "EFFECT",
]


def extract_table_text(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    start = text.find("*2 ASSIGN TARGET TABLE")
    if start < 0:
        raise RuntimeError("ASSIGN TARGET TABLE marker not found")
    next_section = text.find("\\* \\[SystemEfct", start)
    if next_section < 0:
        next_section = len(text)
    return text[start:next_section]


def normalize_text(raw: str) -> str:
    s = raw
    # Strip Markdown escapes
    s = s.replace("\\#", "#").replace("\\-", "-").replace("\\*", "*")
    s = s.replace("\\\\", "")
    # Strip ONLY the dashes and the literal "INDEX CATEGORY TARGET" header
    # text. Don't use ^...$ MULTILINE — these headers can sit inline on
    # the same physical line as real table entries (page-break artifact).
    s = re.sub(r"-{5,}", " ", s)
    s = re.sub(r"INDEX\s+CATEGORY\s+TARGET", " ", s)
    # Strip the title and any "Date:" or "Version:" footer text
    s = re.sub(r"\*2 ASSIGN TARGET TABLE", " ", s)
    # Collapse all whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def find_entries(flat: str):
    """Find all entry start positions (digit followed by uppercase or '-').
    Returns list of (start_pos, index, body_start, body_end-of-segment)."""
    # Match: word boundary, 1-3 digits, space, then [A-Z-] for category start
    # Note: allow '-' for the dummy '----' entry at index 0
    pattern = re.compile(r"\b(\d{1,3}) ([A-Z\-])")
    matches = list(pattern.finditer(flat))
    entries = []
    for i, m in enumerate(matches):
        idx = int(m.group(1))
        body_start = m.start(2)
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(flat)
        body = flat[body_start:body_end].strip()
        entries.append((idx, body))
    return entries


def split_category_target(body: str):
    """Split into (CATEGORY, TARGET). Try longest matching CATEGORY prefix."""
    body = body.strip()
    if not body:
        return "", ""
    # Special case: "---- ----" → category="----" target="----"
    if body.startswith("----"):
        return "----", body[4:].strip() or "----"
    for cat in CATEGORIES:
        if body == cat:
            return cat, ""
        if body.startswith(cat + " "):
            return cat, body[len(cat) + 1:].strip()
    # Fallback: first word as category
    parts = body.split(None, 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def main():
    raw = extract_table_text(MD)
    flat = normalize_text(raw)
    entries = find_entries(flat)
    print(f"Found {len(entries)} entries (first index={entries[0][0]}, last={entries[-1][0]})")

    parsed = {}
    for idx, body in entries:
        if idx in parsed:
            # Duplicate — keep first occurrence
            continue
        cat, tgt = split_category_target(body)
        parsed[idx] = {"category": cat, "target": tgt}

    missing = [i for i in range(741) if i not in parsed]
    if missing:
        print(f"WARNING: {len(missing)} indices missing: {missing[:30]}")
    else:
        print("All 741 indices covered.")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {str(k): v for k, v in sorted(parsed.items())},
        indent=2, ensure_ascii=False))
    print(f"Wrote {OUT_JSON} ({len(parsed)} entries)")

    lines = [
        '"""Official ASSIGN TARGET TABLE (741 entries) from the GX-100/GX-10',
        'MIDI Implementation chart. Maps assign-table index -> (category, target).',
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
