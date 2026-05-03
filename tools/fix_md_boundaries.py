"""Fix split-chunk boundaries: move orphaned content from the head of
the next chunk back to the tail of the previous chunk.

Each chunk has:
- A chapter-running-header line at the top (e.g. "**EFFECTS**") which is
  a page-header artifact, not a real section.
- A page-number line at the bottom (e.g. "**11**", "**50**").

Boundaries to fix in this guide:
- 01 ↔ 02: PARAMETRIC EQUALIZER — header in 01 (last lines), parameter
  table at start of 02. Move chunk 02's lines 1..(GRAPHIC EQUALIZER - 1)
  to chunk 01 (before its trailing page marker).
- 03 ↔ 04: PHRASE LOOP — header in 03 (last lines), body at start of 04.
  Move chunk 04's lines 1..(X-BASS COMPRESSOR - 1) to chunk 03.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANUALS = ROOT / "docs" / "manuals"

# Per-boundary spec: (donor chunk, header that marks start of donor's own
# content; everything BEFORE that is orphaned and belongs in the previous
# chunk)
BOUNDARIES = [
    # (donor_filename, recipient_filename, regex marking start of donor's own content)
    (
        "GX-10_Parameter_Guide_02_effects_mod_pitch_p012-p030.md",
        "GX-10_Parameter_Guide_01_effects_distortion_p001-p011.md",
        re.compile(r"^GRAPHIC EQUALIZER\s*$"),
    ),
    (
        "GX-10_Parameter_Guide_04_effects_bass_master_p051-p067.md",
        "GX-10_Parameter_Guide_03_effects_delay_misc_p031-p050.md",
        re.compile(r"^X-BASS COMPRESSOR\s*$"),
    ),
]


def split_donor(donor_text: str, marker_re):
    """Return (orphan, kept). orphan = lines from start up to (but not
    including) the line matching marker_re. kept = remaining lines."""
    lines = donor_text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if marker_re.match(ln.strip()):
            return "".join(lines[:i]), "".join(lines[i:])
    raise RuntimeError(f"marker {marker_re.pattern} not found in donor")


def attach_to_recipient(recipient_text: str, orphan: str) -> str:
    """Append orphan to recipient, BEFORE its trailing page-number
    marker line (e.g. "**11**"). The page marker (and any blank line
    after it) stays at the end."""
    lines = recipient_text.rstrip("\n").splitlines(keepends=True)
    # Find the LAST line that is a page-number marker like **NN** (with optional spaces)
    marker_re = re.compile(r"^\s*\*\*\d+\*\*\s*$")
    insert_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if marker_re.match(lines[i]):
            insert_idx = i
            break
    head = "".join(lines[:insert_idx])
    tail = "".join(lines[insert_idx:])
    # Drop a leading "**EFFECTS**" line on the orphan (it's a duplicate
    # running header, not real content).
    o = orphan
    o = re.sub(r"^\*\*[A-Z][A-Z ]+\*\*\s*\n+", "", o, count=1)
    return head.rstrip() + "\n\n" + o.strip() + "\n\n" + tail


def main():
    for donor_name, recipient_name, marker_re in BOUNDARIES:
        donor_path = MANUALS / donor_name
        recipient_path = MANUALS / recipient_name
        donor_text = donor_path.read_text(encoding="utf-8")
        recipient_text = recipient_path.read_text(encoding="utf-8")
        orphan, kept = split_donor(donor_text, marker_re)
        if not orphan.strip():
            print(f"  no orphan content in {donor_name} -- skipping")
            continue
        new_recipient = attach_to_recipient(recipient_text, orphan)
        recipient_path.write_text(new_recipient, encoding="utf-8")
        donor_path.write_text(kept, encoding="utf-8")
        print(f"  moved {len(orphan.splitlines())} lines  "
              f"{donor_name}  ->  {recipient_name}")


if __name__ == "__main__":
    main()
