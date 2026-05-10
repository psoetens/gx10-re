"""Parse the GX-10 MIDI Implementation chart into a consolidated menu
catalog at captures/menu_catalog.json.

The chart (docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md) documents
every settable register on the device. Each region is given a section
header like '[SystemCommon]' followed by a markdown-table-flattened
into one line that lists offsets, bit-mask encoding, field names, and
range/enum text. This tool extracts those entries.

Output schema (per region):
  {
    "0x00000000 SystemCommon": {
      "base_address": "0x00000000",
      "fields": [
        {
          "address": "0x00000004",
          "offset": "0x04",
          "label": "PLAYPAGE MODE",
          "encoding": "0000 00aa",
          "size_bits": 2,
          "range_text": "0 - 3",
          "values": ["LARGE NUMBER", "LARGE NAME", "CONTROL", "CHAIN"]
        }, ...
      ],
      "total_size": "0x2D"
    }, ...
  }
"""
from __future__ import annotations
import json
import re
from pathlib import Path


REPO = Path(__file__).parent.parent
CHART = REPO / "docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md"
OUT = REPO / "captures/menu_catalog.json"


# Top-level region map from the chart's "System Exclusive Address Map"
# (chart section 3, line ~298). These are the BASE addresses; offsets in
# each region table are relative to these.
REGIONS = [
    # System-wide
    (0x00000000, "SystemCommon"),
    (0x00001000, "SystemControl"),
    (0x00003000, "SystemMidi"),
    (0x00004000, "SystemInOut"),
    (0x00005000, "SystemEfct"),
    (0x00006000, "SystemPitch"),
    # SysteminputSetting 1..10 at 0x00006100, 0x00006200, ... 0x00006A00
    # (single template — annotated below)
    (0x00006100, "SysteminputSetting"),
    (0x00006B00, "SystemGlobalEq"),
    # Bank PC maps
    (0x00100000, "PcmapPc"),  # bank1; bank2 at 0x00100400, bank3 at 0x00100800
    # Memory (temporary) — same layout for memory 1..200 starting at 0x20000000
    (0x10000000, "Memory_temp"),
]

# Within a Memory region, sub-offsets:
MEMORY_SUBREGIONS = [
    (0x000000, "MemoryCommon"),
    (0x000140, "MemoryLed"),
    (0x000200, "Assign"),       # 1..20 with stride 0x40 — see below
    (0x000F00, "MemoryEfct"),
    (0x001100, "MemoryFxItem"), # 1..20 with stride 0x200
]


def parse_value_range(text: str) -> dict:
    """Extract enum list, numeric range, or unit from the chart's
    'range/values' free text."""
    out: dict = {}
    text = text.strip().replace("\\-", "-").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    # Numeric range like "(0 - 3)" or "(0 - 100)"
    m = re.match(r".*?\((\-?\d+)\s*-\s*(\-?\d+)\)", text)
    if m:
        out["min"] = int(m.group(1))
        out["max"] = int(m.group(2))
    # Enum list — comma-separated tokens after the range
    after = re.sub(r".*?\(\-?\d+\s*-\s*\-?\d+\)\s*", "", text).strip()
    if after and not re.match(r"^[\d.\s]*$", after):
        # Split on commas, respect quoted phrases minimally
        parts = [p.strip() for p in after.split(",") if p.strip()]
        if parts:
            out["values"] = parts
    return out


def parse_region_table(text: str, region_name: str) -> list[dict]:
    """Parse a region's table from a single chart line.

    The chart embeds tables as:
       | OFFSET | ENCODING | LABEL (RANGE) values |
    flattened with extra '|' delimiters. We split, group every 3 cells
    into a row, and parse.

    Multi-byte cells appear as N consecutive rows with the same
    encoding letter and only the FIRST row carrying a label. We
    track these as the parser walks rows: the previous-field's
    `size_bytes` is incremented for each label-less continuation row.
    """
    raw_cells = [c.strip() for c in text.split("|")]
    # Drop horizontal-rule cells but KEEP empty cells — they are
    # significant (continuation-row markers).
    cells = [c for c in raw_cells if not re.match(r"^[-:\s+]+$", c)]
    fields = []
    i = 0
    pending_label_buf = []  # accumulates multi-cell label text
    last_field = None       # most recent labelled field (for size tracking)
    while i < len(cells) - 2:
        offset_cell = cells[i]
        # Match offset like "00 04" or "# 00 1D"
        m = re.match(r"^\\?#?\s*([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})$", offset_cell)
        if not m:
            i += 1
            continue
        off_high, off_low = int(m.group(1), 16), int(m.group(2), 16)
        offset = (off_high << 8) | off_low
        encoding = cells[i+1].strip()
        label_and_range = cells[i+2].strip()
        i += 3
        # Continuation row: empty label, encoding starts with "0000 "
        # AND the offset is exactly previous-field-offset + previous-size.
        if (last_field is not None and not label_and_range
                and re.match(r"^0000\s+[01a-z]{4}", encoding)
                and offset == last_field["offset_int"]
                + last_field.get("size_bytes", 1)):
            # Cap by what last_field's documented value range needs.
            v_min = last_field.get("value_min")
            v_max = last_field.get("value_max")
            new_size = last_field.get("size_bytes", 1) + 1
            if isinstance(v_min, (int, float)) and isinstance(v_max, (int, float)):
                # 4 bits per nibble byte; need ceil(log16(span+1)) bytes
                span = max(abs(v_max), abs(v_min))
                if span <= 0xF:        max_size = 1
                elif span <= 0xFF:     max_size = 2
                elif span <= 0xFFF:    max_size = 3
                else:                  max_size = 4
                if new_size > max_size:
                    # Don't extend beyond what range needs.
                    last_field = None
                else:
                    last_field["size_bytes"] = new_size
                    continue
            else:
                last_field["size_bytes"] = new_size
                continue
            continue
        # Skip "fixed value" / NIU placeholders
        if "N/A" in label_and_range or "fixed" in label_and_range.lower():
            continue
        # Continuation rows: subsequent cells until next offset are
        # additional descriptive text or enum values for this field.
        # Look ahead for "Total Size" or next "##" offset marker.
        # Get following text cells until next offset line:
        extra = []
        while i < len(cells) - 2:
            c = cells[i]
            if re.match(r"^\\?#?\s*[0-9A-Fa-f]{2}\s+[0-9A-Fa-f]{2}$", c):
                break
            if "Total" in c or c.startswith("00 00 00"):
                break
            extra.append(c)
            i += 1
        full_text = label_and_range + " " + " ".join(extra)
        # Strip markdown backslash escapes the chart uses for hyphens,
        # parens, brackets, etc.
        full_text = (full_text.replace("\\-", "-").replace("\\)", ")")
                              .replace("\\(", "(").replace("\\[", "[")
                              .replace("\\]", "]"))
        # Parse label = everything before "(N - M)"
        m = re.match(r"^([A-Z][A-Z0-9 :/\\\-_+&\.]*?)\s*\((\-?\d+)\s*-\s*(\-?\d+)\)\s*(.*)$",
                     full_text)
        if m:
            label = m.group(1).strip().replace("\\n", " ").replace("\\\\n", " ")
            v_min = int(m.group(2))
            v_max = int(m.group(3))
            tail = m.group(4).strip()
            values = None
            if tail:
                # Comma-separated enum list
                vs = [p.strip() for p in tail.split(",")
                      if p.strip() and not re.match(r"^[*\s]*$", p.strip())]
                if vs:
                    values = vs
            new_field = {
                "offset": f"0x{offset:04X}",
                "offset_int": offset,
                "encoding": encoding,
                "label": label,
                "value_min": v_min,
                "value_max": v_max,
                "values": values,
                "size_bytes": 1,
            }
            fields.append(new_field)
            last_field = new_field
        else:
            # No clear range — might be a name/string field or odd format.
            # Keep raw label.
            label_clean = full_text.split("(")[0].strip().replace("\\n", " ")
            if label_clean and len(label_clean) < 60:
                new_field = {
                    "offset": f"0x{offset:04X}",
                    "offset_int": offset,
                    "encoding": encoding,
                    "label": label_clean,
                    "raw_text": full_text[:200],
                    "size_bytes": 1,
                }
                fields.append(new_field)
                last_field = new_field
            else:
                last_field = None
    return fields


def find_region_block(chart_text: str, region_name: str) -> str | None:
    """Find the chart line that contains the field table for the named
    region. Region tables are introduced by a line like
    '\\* \\[REGIONNAME\\]' (with backslash-escaped brackets in the
    extracted markdown) and the table follows."""
    # Match the marker; backslashes are literal in the source, so escape
    # them as \\\\ in the raw-string regex.
    pat = re.compile(rf"\\\*\s*\\\[{re.escape(region_name)}\\\]")
    m = pat.search(chart_text)
    if not m:
        return None
    rest = chart_text[m.end():]
    # Cut at next "\* \[" marker
    next_marker = re.search(r"\\\*\s*\\\[", rest)
    block = rest[: next_marker.start()] if next_marker else rest[:8000]
    return block


_BIT_PATTERN_LABEL_RE = re.compile(
    r"^\s*[0-9A-Fa-f]{2}\s+[0-9A-Fa-f]{2}\s+[01a-z]{4}",
    re.IGNORECASE,
)


def filter_and_coalesce_fields(fields: list[dict]) -> list[dict]:
    """Post-process pass — currently a no-op since parse_region_table
    now tracks multi-byte continuations inline. Kept as a hook for
    future cleanups.
    """
    return fields


def main():
    text = CHART.read_text(encoding="utf-8")
    catalog = {}
    for base, name in REGIONS:
        block = find_region_block(text, name)
        if not block:
            print(f"  MISS {name}")
            continue
        fields = parse_region_table(block, name)
        fields = filter_and_coalesce_fields(fields)
        # Compute absolute address
        for f in fields:
            f["address"] = f"0x{base + f['offset_int']:08X}"
        catalog[f"0x{base:08X} {name}"] = {
            "base_address": f"0x{base:08X}",
            "field_count": len(fields),
            "fields": fields,
        }
        print(f"  OK   {name:<20} base=0x{base:08X}  fields={len(fields)}")

    # Memory subregions (chart's [MemoryCommon], [Assign], etc.)
    # We compute the temp-memory absolute base, then enumerate sub-regions.
    memory_temp_base = 0x10000000
    for sub_off, sub_name in MEMORY_SUBREGIONS:
        block = find_region_block(text, sub_name)
        if not block:
            print(f"  MISS Memory.{sub_name}")
            continue
        fields = parse_region_table(block, sub_name)
        fields = filter_and_coalesce_fields(fields)
        # Use offset from temp memory + subregion offset
        sub_base = memory_temp_base + sub_off
        for f in fields:
            f["address"] = f"0x{sub_base + f['offset_int']:08X}"
        key = f"0x{sub_base:08X} Memory_temp.{sub_name}"
        catalog[key] = {
            "base_address": f"0x{sub_base:08X}",
            "field_count": len(fields),
            "_note": f"Sub-region of Memory_temp (0x10000000) at +0x{sub_off:06X}. Same layout repeats for user memory 1..200 at 0x20000000 + (mem-1)*0x60000.",
            "fields": fields,
        }
        print(f"  OK   Memory.{sub_name:<14} sub_off=0x{sub_off:06X}  fields={len(fields)}")

    OUT.write_text(json.dumps(catalog, indent=2))
    total = sum(c["field_count"] for c in catalog.values())
    print(f"\n  wrote {OUT}")
    print(f"  regions: {len(catalog)}, total fields: {total}")


if __name__ == "__main__":
    main()
