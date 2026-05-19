"""Build a comprehensive per-effect knob catalog as docs/effect_catalog.md.

Sources:
  - captures/typebar_full/page*/*/summary.json (captured knobs + addresses)
  - tools/per_effect_types.py (TYPE/SP TYPE/MIC TYPE enums)
  - tools/manual_xref_v2 (manual heading + manual knob list)
  - tools/gui_override.py (GUI knob ordering for HARM/PS family)
  - tools/effect_conditional_knobs.py (this file's companion: which knobs
    are conditional on TYPE / MODE / HARMONY=USER and why)

Output is a single Markdown document with one section per effect:
  - Internal name + manual heading + chart FX TYPE byte
  - TYPE / SP TYPE / MIC TYPE enums
  - "Always-visible" knob table  (name | offset addr | range)
  - "Conditional" knob tables (one per condition)
  - Notes (BPM unit-toggle, etc.)

Mismatches between captured count and manual count are classified into:
  A. BPM-as-time-toggle  (manual lists BPM but it's a TIME-knob unit)
  B. TYPE-conditional    (knobs visible only when TYPE=<x>)
  C. MODE-conditional    (knobs visible only when MODE=<x>)
  D. HARMONY=USER scale  (HR1/HR2 entries visible only in USER mode)
  E. Captured-extra      (capture sees a knob the manual doesn't list)
  F. Unexplained         (genuine gap; flagged for follow-up)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"

sys.path.insert(0, str(Path(__file__).parent))
from manual_xref_v2 import (
    build_effect_db, lookup_manual, expand_paired_params,
    filter_for_knobs,
)
from gui_override import GUI_OVERRIDE
try:
    from per_effect_types import PER_EFFECT_TYPES   # name -> {type: [..], sp_type: [..], mic_type: [..]}
except ImportError:
    PER_EFFECT_TYPES = {}


# ---- Mismatch classification rules ---------------------------------

# Effects where the manual lists "BPM" but the GUI doesn't render it as
# a separate clickable knob — it's the units side of a TIME/RATE knob.
BPM_AS_TIME_TOGGLE = {
    "PH", "PH_BASS", "PH_PRIME", "PH_PRIME_BASS",
    "CHO", "CLASS_VIBE", "A_WAH", "WAH",
    "SEND_RETURN", "DELAY_TWIST",
}

# Effects whose knobs_extra hold conditional knobs visible only when
# a specific TYPE/MODE is selected. Used to reduce the +N positive gap.
HARMONY_USER_NOTES = {"HR1:", "HR2:"}

# Effects with TYPE-conditional knobs (visible only when TYPE=<value>).
TYPE_CONDITIONAL = {
    "DELAY_PLUS": "DUAL TYPE adds 7 conditional knobs (1:/2: pairs for "
                   "TYPE/TIME/FEEDBACK/EFFECT LEVEL/HIGH CUT plus MODE)",
}

# Effects with MODE-conditional knobs (visible only when MODE=<value>).
MODE_CONDITIONAL = {
    "FB":      ("MODE=OSC adds 6 conditional knobs (RISE TIME, OCT RISE TIME, "
                 "FEEDBACK, OCT FEEDBACK, VIB RATE, VIB DEPTH)"),
    "HMN":     ("MODE selects between PICKING / VOWEL — MODE-conditional "
                 "vowels add up to 2 extra knob slots"),
    "PB_BASS": ("MODE-conditional knob set; manual lists 11 but only 5 "
                 "visible in default MODE"),
    "DIV_MIX": ("DIVIDER MODE / MIXER MODE selectors hide 3 conditional "
                 "knobs not present in default mode"),
}

# Effects with USER-scale conditional knobs (HARMONY=USER).
USER_SCALE_CONDITIONAL = {
    "HARM":      "HARMONY=USER mode adds 27 scale-step knobs (HR1:C..HR2:B)",
    "HARM_BASS": "HARMONY=USER mode adds 27 scale-step knobs (HR1:C..HR2:B)",
    "PS":        "VOICE=2 adds 5 conditional knobs (2:* mirrors of 1:*)",
    "PS_BASS":   "VOICE=2 adds 5 conditional knobs (2:* mirrors of 1:*)",
}

# Effects where capture sees a knob the manual doesn't expose.
CAPTURED_EXTRA = {
    "AMP":         "+1 captured knob beyond AIRD PREAMP manual (likely an "
                    "internal MIC/SAG/RES sub-knob exposed in BTS)",
    "AMP_BASS":    "+1 captured knob beyond AIRD BASS PREAMP manual",
    "REV_SHIMMER": "+2 captured knobs (likely SHIMMER LEVEL + MOD that the "
                    "manual tucks under the description rather than as rows)",
}


def classify(name, gap):
    """Return ("category", "explanation") for a captured-vs-manual gap."""
    if gap == 0:
        return None, None
    if name in BPM_AS_TIME_TOGGLE and gap == -1:
        return "A. BPM unit-toggle", \
            "Manual lists BPM as a row but it's a TIME/RATE-knob unit toggle, not a separate knob"
    if name in TYPE_CONDITIONAL:
        return "B. TYPE-conditional", TYPE_CONDITIONAL[name]
    if name in MODE_CONDITIONAL:
        return "C. MODE-conditional", MODE_CONDITIONAL[name]
    if name in USER_SCALE_CONDITIONAL:
        return "D. USER-scale conditional", USER_SCALE_CONDITIONAL[name]
    if name in CAPTURED_EXTRA:
        return "E. Captured-extra", CAPTURED_EXTRA[name]
    return "F. Unexplained", f"Gap of {gap:+d} not yet classified"


# ---- Knob enumeration ----------------------------------------------

def captured_knobs(s):
    """Return ordered list of captured knobs (knobs + knobs_extra),
    deduped by (x,y), sorted top-left to bottom-right."""
    captured = list(s.get("knobs", []))
    captured += list(s.get("knobs_extra", []))
    seen = set()
    ordered = []
    for k in captured:
        xy = (k.get("knob_x", -1), k.get("knob_y", -1))
        if xy in seen:
            continue
        seen.add(xy)
        ordered.append(k)
    ordered.sort(key=lambda k: (k.get("knob_y", 0), k.get("knob_x", 0)))
    return ordered


def manual_knobs(name, s, db):
    heading, params = lookup_manual(name, db)
    if not params:
        return None, []
    if heading in GUI_OVERRIDE:
        return heading, list(GUI_OVERRIDE[heading])
    expanded = expand_paired_params(params)
    return heading, filter_for_knobs(expanded, s)


# ---- Markdown rendering --------------------------------------------

def fmt_knob_row(k, fallback_name=""):
    name = (k.get("name_manual_v2") or k.get("name_manual")
            or fallback_name or "?").replace("|", "\\|")
    addr = k.get("address", "?")
    rng = ""
    if "min_display" in k and "max_display" in k:
        rng = f"{k['min_display']}..{k['max_display']}"
    raw = f"{k.get('min_raw','?')}..{k.get('max_raw','?')}"
    return f"| `{addr}` | {name:<22s} | {rng:<10s} | {raw} |"


def render_effect_section(s, heading, manual_names, gap_class):
    name = s["name"]
    fx_type = s.get("fx_type_byte", "?")
    fx_official = s.get("fx_type_official", "?")
    has_type = s.get("has_type", False)
    has_sp = s.get("has_sp_type", False)

    out = []
    out.append(f"## {name}  ({fx_official})")
    out.append("")
    out.append(f"- Manual heading: **{heading or '(no manual entry)'}**")
    out.append(f"- FX TYPE byte: `{fx_type}` ({fx_official})")
    if has_type:
        type_max = s.get("type_max", -1)
        type_addr = s.get("type_address", "?")
        out.append(f"- TYPE selector at `{type_addr}` (0..{type_max})")
    if has_sp:
        out.append(f"- SP TYPE selector at `{s.get('sp_type_address','?')}` "
                   f"(0..{s.get('sp_type_max',-1)})")

    # TYPE / SP TYPE / MIC TYPE enum tables when known
    pet = PER_EFFECT_TYPES.get(name) if PER_EFFECT_TYPES else None
    if pet:
        for kind in ("type", "sp_type", "mic_type"):
            vals = pet.get(kind)
            if vals:
                out.append(f"- {kind.upper().replace('_',' ')}: "
                           + ", ".join(f"{i}={v}" for i, v in enumerate(vals)))

    knobs = captured_knobs(s)
    if not knobs:
        out.append("")
        out.append("(no captured knobs)")
        return "\n".join(out)

    # Always-visible knobs (those in `knobs`, not `knobs_extra`)
    base_knobs = list(s.get("knobs", []))
    extra_knobs = list(s.get("knobs_extra", []))

    out.append("")
    out.append(f"### Knobs ({len(base_knobs)} always-visible"
               + (f", {len(extra_knobs)} conditional)" if extra_knobs else ")"))
    out.append("")
    out.append("| Address | Name                  | Display    | Raw          |")
    out.append("|---------|------------------------|------------|--------------|")
    for i, k in enumerate(base_knobs):
        nm_fallback = (manual_names[i] if i < len(manual_names) else "?")
        out.append(fmt_knob_row(k, nm_fallback))

    if extra_knobs:
        out.append("")
        out.append("**Conditional knobs (visible in alt TYPE / MODE / USER state):**")
        out.append("")
        out.append("| Address | Name                  | Display    | Raw          |")
        out.append("|---------|------------------------|------------|--------------|")
        for k in extra_knobs:
            out.append(fmt_knob_row(k))

    if gap_class and gap_class[0] is not None:
        cat, expl = gap_class
        out.append("")
        out.append(f"**Mismatch:** {cat} — {expl}")

    out.append("")
    return "\n".join(out)


def main():
    db = build_effect_db()
    print(f"Parsed {len(db)} manual effect sections.", file=sys.stderr)

    sections = []
    summaries_by_name = {}
    for sp in sorted(TYPEBAR.glob("page*/*/summary.json")):
        s = json.loads(sp.read_text())
        summaries_by_name[s["name"]] = s

    classification_table = []
    for name, s in sorted(summaries_by_name.items(), key=lambda kv: (
            kv[1].get("page", 99), kv[1].get("idx", 99))):
        heading, manual_names = manual_knobs(name, s, db)
        captured = captured_knobs(s)
        gap = len(captured) - len(manual_names)
        gap_class = classify(name, gap) if gap != 0 else (None, None)
        sections.append(render_effect_section(s, heading, manual_names, gap_class))
        if gap != 0:
            cat, expl = gap_class
            classification_table.append((name, heading, len(captured),
                                          len(manual_names), gap, cat or "",
                                          expl or ""))

    # Header + classification summary
    header = []
    header.append("# GX-10 / GX-100 Effect Knob Catalogue")
    header.append("")
    header.append("Auto-generated by `tools/build_effect_catalog.py` from "
                   "`captures/typebar_full/page*/*/summary.json` cross-referenced "
                   "with the chunked Parameter Guide (`docs/manuals/`) and the "
                   "BTS GUI overrides (`tools/gui_override.py`).")
    header.append("")
    header.append("Each effect section lists:")
    header.append("- The **always-visible** knobs (from the captured base array).")
    header.append("- Any **conditional** knobs (TYPE / MODE / HARMONY=USER), "
                   "captured into `knobs_extra` during sweep.")
    header.append("- The TYPE / SP TYPE / MIC TYPE enum values where applicable.")
    header.append("")
    header.append("## Per-patch placement limits")
    header.append("")
    header.append("From the GX-10 Parameter Guide, *\"Maximum number of effects "
                  "and functional devices that can be placed\"* "
                  "(<https://static.roland.com/manuals/gx-10_parameter/en-US/"
                  "158050315161293707.html>):")
    header.append("")
    header.append("| Item | Upper limit per patch |")
    header.append("|------|----------------------:|")
    header.append("| Same effect (any single TYPE) | **9** |")
    header.append("| AMP (AIRD PREAMP / AIRD BASS PREAMP) | 2 |")
    header.append("| LOOPER (PHRASE LOOP) | 1 |")
    header.append("| DIVIDER / MIXER | 1 |")
    header.append("| SEND / RETURN | 1 |")
    header.append("| Total effects + functional devices in the chain | 15 |")
    header.append("")
    header.append("> \"You can arrange up to 15 effects and functional devices "
                  "such as DIVIDER/MIXER, LOOPER, SEND/RETURN and so on within "
                  "the effect chain.\"")
    header.append("")
    header.append("The Parameter Guide also warns that DSP capacity is an "
                  "additional, dynamic constraint: *\"you may not be able to "
                  "insert or overwrite an effect, even when the number of "
                  "connected effects falls within the limits.\"*")
    header.append("")
    header.append("These manual-published caps match the protocol encoding: "
                  "the `MemoryFxItem` field `DuplicationNumber` at offset "
                  "`0x02` has range **0–9** (see `docs/protocol.md` "
                  "MemoryFxItem layout and `docs/official_xref.md` "
                  "\"MemoryFxItem layout\"), exactly enough to index the 9 "
                  "allowed copies of one effect type. The 15-item chain cap "
                  "likewise fits comfortably inside the 20 hardware FxItem "
                  "storage slots at `0x10001100..0x10003700`.")
    header.append("")
    header.append("## Mismatch summary")
    header.append("")
    header.append(f"{len(classification_table)} effect(s) have a captured-vs-manual "
                   "knob count gap. Each gap is classified below; un-resolved "
                   "ones are tagged 'F. Unexplained' for follow-up.")
    header.append("")
    header.append("| Internal | Manual heading | captured | manual | gap | category |")
    header.append("|----------|----------------|---------:|-------:|----:|----------|")
    for name, heading, cn, mn, gap, cat, _expl in classification_table:
        header.append(f"| `{name}` | {heading or '(none)'} | {cn} | {mn} | "
                       f"{gap:+d} | {cat} |")
    header.append("")
    header.append("---")
    header.append("")

    out_path = ROOT / "docs" / "effect_catalog.md"
    out_path.write_text("\n".join(header) + "\n\n".join(sections) + "\n",
                        encoding="utf-8")
    print(f"Wrote {out_path} ({len(sections)} effect sections, "
          f"{len(classification_table)} classified mismatches)")
    # Print mismatch summary to stderr
    print(f"\n{'Internal':<18} {'Manual':<28} {'cap':>3} {'man':>3} {'gap':>4} category",
          file=sys.stderr)
    for name, heading, cn, mn, gap, cat, _ in classification_table:
        print(f"{name:<18} {(heading or '(none)'):<28} {cn:>3} {mn:>3} {gap:>+4d} {cat}",
              file=sys.stderr)
    unresolved = [r for r in classification_table if r[5].startswith("F.")]
    print(f"\nUnresolved (category F): {len(unresolved)}", file=sys.stderr)


if __name__ == "__main__":
    main()
