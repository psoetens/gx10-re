"""Scrape Roland's online GX-100 v1 Parameter Guide and produce 6 chunked
Markdown files matching the GX-10 / GX-100 v2 Parameter_Guide chunking.

The v1 manual is hosted at the older URL style:
    https://static.roland.com/manuals/gx-100_parameter/eng/INDEX.html
Each effect / section gets its own numerically-named .html. The pages
have proper <table> markup, so HTML→Markdown is straightforward.

Output:
    docs/manuals/GX-100_v1_Parameter_Guide_01_effects_distortion.md
    docs/manuals/GX-100_v1_Parameter_Guide_02_effects_mod_pitch.md
    docs/manuals/GX-100_v1_Parameter_Guide_03_effects_delay_misc.md
    docs/manuals/GX-100_v1_Parameter_Guide_04_effects_bass_master.md
    docs/manuals/GX-100_v1_Parameter_Guide_05_menu.md
    docs/manuals/GX-100_v1_Parameter_Guide_06_write_soundlist.md

(.gitignore already keeps these out of git.)
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path


BASE_URL = "https://static.roland.com/manuals/gx-100_parameter/eng"
INDEX_PAGE = "25629758.html"


# Chunk membership rules — keyed off section-header titles that appear in
# the TOC. A page belongs to the current chunk until a "next chunk header"
# is encountered. Mirrors the chapter splits used for the GX-10 PDF / v2
# chunks so v1 / v2 / GX-10 are byte-comparable.
SECTION_TO_CHUNK = [
    # (toc-section-title, chunk-label-suffix)
    # Boundaries are *inclusive* of the section header itself.
    ("EFFECTS",                          "01_effects_distortion"),
    ("PARAMETRIC EQUALIZER",             "02_effects_mod_pitch"),
    ("DELAY",                            "03_effects_delay_misc"),
    ("X-BASS COMPRESSOR",                "04_effects_bass_master"),
    ("CTL/EXP",                          "05_menu"),
    ("WRITE",                            "06_write_soundlist"),
]


# ---- HTTP -----------------------------------------------------------

def fetch(rel: str, sleep_ms: int = 80) -> str:
    """Fetch BASE_URL/rel with a polite delay between calls."""
    url = f"{BASE_URL}/{rel}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (gx10-re manual archive)",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read().decode("utf-8", errors="replace")
    if sleep_ms:
        time.sleep(sleep_ms / 1000.0)
    return data


# ---- TOC parser -----------------------------------------------------

def parse_toc(index_html: str) -> list[tuple[str, str]]:
    """Return [(filename, title), ...] in document order, deduped."""
    pairs = []
    seen = set()
    for m in re.finditer(r'href="(\d+\.html)"[^>]*>([^<]+)<', index_html):
        fn, title = m.group(1), unescape(m.group(2)).strip()
        key = (fn, title)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    # Drop the entry for the index page itself
    pairs = [p for p in pairs if p[0] != INDEX_PAGE]
    return pairs


# ---- HTML → Markdown ------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
WS_RE = re.compile(r"\s+")


def strip_tags(s: str) -> str:
    return WS_RE.sub(" ", unescape(TAG_RE.sub("", s))).strip()


def cell_to_md(cell_html: str) -> str:
    """Convert one <td> / <th> body to a single-line markdown cell.

    Inline images become `[img]` markers. `<br>` is treated as a soft
    item-separator: split on `<br>`, drop empty pieces (Confluence pads
    cells with `<br /><br />` for spacing), join the rest with ' / '."""
    s = cell_html
    s = re.sub(r"<img[^>]*alt=\"([^\"]*)\"[^>]*/?>",
               lambda m: f"[img:{m.group(1) or 'img'}]", s)
    s = re.sub(r"<img[^>]*/?>", "[img]", s)
    # Split on <br>; clean each piece; drop empties; join.
    parts = re.split(r"<br\s*/?>", s, flags=re.I)
    parts = [strip_tags(p) for p in parts]
    parts = [p for p in parts if p]
    text = " / ".join(parts)
    # bold / italic preserved as markdown (re-apply after strip_tags)
    # NB: strip_tags already removed all tags above, so this is a no-op
    # in practice; keeping the regex for clarity.
    text = text.replace("|", "\\|")
    return text   # may legitimately be empty (continuation rows)


def table_to_md(table_html: str) -> str:
    """Convert one <table>…</table> block to a Markdown table.

    Honors rowspan/colspan by tracking which columns are still "owned"
    by a cell from a previous row. When a continuation row is missing
    cells because they're being spanned down from above, the spanned
    cells are filled with an empty marker so the column alignment of
    the existing manual_xref_v2 parser is preserved (continuation rows
    keep an empty Parameter column).
    """
    # Use thead/tbody markers to split and order
    thead_m = re.search(r"<thead[^>]*>(.*?)</thead>", table_html,
                         re.DOTALL | re.I)
    tbody_m = re.search(r"<tbody[^>]*>(.*?)</tbody>", table_html,
                         re.DOTALL | re.I)
    segments: list[str] = []
    if thead_m or tbody_m:
        if thead_m:
            segments.append(thead_m.group(1))
        if tbody_m:
            segments.append(tbody_m.group(1))
        else:
            outside = re.sub(r"<thead[^>]*>.*?</thead>", "", table_html,
                              flags=re.DOTALL | re.I)
            segments.append(outside)
    else:
        segments.append(table_html)

    # Walk every <tr>, expand rowspan/colspan into the row layout.
    # Track per-column "still spanning" counters so the next row can
    # insert empty cells at those positions.
    rows_md: list[list[str]] = []
    spans_left: dict[int, int] = {}   # col_idx -> rows still active
    span_text: dict[int, str] = {}     # col_idx -> continuation marker
    for segment in segments:
        for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", segment,
                              re.DOTALL | re.I):
            cell_iter = list(re.finditer(
                r"<t([hd])([^>]*)>(.*?)</t[hd]>", tr.group(1),
                re.DOTALL | re.I))
            if not cell_iter:
                continue

            row: list[str] = []
            col = 0

            def consume_spans():
                # Insert continuation markers for any columns still active
                nonlocal col
                while spans_left.get(col, 0) > 0:
                    row.append(span_text.get(col, ""))
                    spans_left[col] -= 1
                    col += 1

            for m in cell_iter:
                consume_spans()
                attrs = m.group(2)
                body = m.group(3)
                rs_m = re.search(r'rowspan\s*=\s*"?(\d+)"?', attrs, re.I)
                cs_m = re.search(r'colspan\s*=\s*"?(\d+)"?', attrs, re.I)
                rowspan = int(rs_m.group(1)) if rs_m else 1
                colspan = int(cs_m.group(1)) if cs_m else 1
                cleaned = cell_to_md(body)
                row.append(cleaned)
                # If this cell spans more columns, fill them with empty
                for k in range(1, colspan):
                    row.append("")
                # Record rowspan for this column
                if rowspan > 1:
                    # The continuation rows should show empty in this col
                    spans_left[col] = rowspan - 1
                    span_text[col] = ""
                col += colspan
            consume_spans()
            rows_md.append(row)

    if not rows_md:
        return ""

    # Pad to uniform column count
    width = max(len(r) for r in rows_md)
    rows_md = [r + [""] * (width - len(r)) for r in rows_md]

    out = []
    out.append("| " + " | ".join(rows_md[0]) + " |")
    out.append("|" + "|".join([" :---- "] * width) + "|")
    for row in rows_md[1:]:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def page_to_md(html: str) -> tuple[str, str]:
    """Return (title, markdown-body) for one chapter page.

    Output format matches what `tools/manual_xref_v2.py` expects from
    the existing GX-10 / GX-100-v2 chunks:
      - Effect / section title as a plain ALL-CAPS line (NOT `## TITLE`).
      - Sub-headings (e.g. "What is MDP?") rendered with `#####`.
      - Paragraphs as plain prose.
      - Tables as standard pipe-delimited Markdown.
    """
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = unescape(title_m.group(1)).strip() if title_m else "(untitled)"

    body_m = re.search(
        r'<div\s+class="page\s+view"\s+id="content"[^>]*>(.*?)<div\s+id="nav"',
        html, re.DOTALL | re.I)
    if not body_m:
        body_m = re.search(
            r'<div[^>]*class="[^"]*wiki-content[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.I)
    body = body_m.group(1) if body_m else ""

    if "<kod" in body and "<table" not in body:
        return title, ""

    # Confluence puts the page <h1> OUTSIDE the content div (in
    # #title-text). The content body itself rarely contains an h1, so
    # emit the page title as the first ALL-CAPS line ourselves.
    pieces: list[str] = []
    if title:
        pieces.append(title)
    saw_title_h1 = True
    pat = re.compile(
        r"<(h[1-6])[^>]*>(.*?)</\1>"
        r"|<p[^>]*>(.*?)</p>"
        r"|<table[^>]*>(.*?)</table>",
        re.DOTALL | re.I,
    )
    for m in pat.finditer(body):
        tag = m.group(1)
        if tag and tag.startswith("h"):
            level = int(tag[1])
            text = strip_tags(m.group(2))
            if not text:
                continue
            # The first h1 IS the page title; emit it as a plain
            # ALL-CAPS line (matching the GX-10 / v2 chunk convention so
            # manual_xref_v2.py recognises it as an effect heading).
            # Lower-level headings stay as Markdown for visual structure.
            if level == 1 and not saw_title_h1:
                pieces.append(text)
                saw_title_h1 = True
            else:
                pieces.append(("#" * max(level, 4)) + " " + text)
        elif m.group(3) is not None:
            text = strip_tags(m.group(3))
            if text:
                pieces.append(text)
        elif m.group(4) is not None:
            md = table_to_md("<table>" + m.group(4) + "</table>")
            if md:
                pieces.append(md)
    return title, "\n\n".join(pieces).strip() + "\n"


# ---- chunking -------------------------------------------------------

def chunk_index(toc: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Walk the TOC; emit {chunk_label: [(fn, title), ...]} in TOC order."""
    chunk_starts = {h: lbl for h, lbl in SECTION_TO_CHUNK}
    out: dict[str, list[tuple[str, str]]] = {}
    cur_label = None
    for fn, title in toc:
        if title in chunk_starts:
            cur_label = chunk_starts[title]
            out.setdefault(cur_label, [])
        if cur_label is None:
            continue
        out[cur_label].append((fn, title))
    return out


# ---- main -----------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/manuals",
                    help="output directory (default: docs/manuals)")
    ap.add_argument("--prefix", default="GX-100_v1_Parameter_Guide_",
                    help="filename prefix for chunks")
    ap.add_argument("--cache", default="_scrape",
                    help="local HTML cache dir (skip refetch if present)")
    ap.add_argument("--sleep-ms", type=int, default=80)
    args = ap.parse_args()

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Index
    idx_path = cache / INDEX_PAGE
    if idx_path.exists():
        idx_html = idx_path.read_text(encoding="utf-8", errors="replace")
    else:
        idx_html = fetch(INDEX_PAGE, sleep_ms=args.sleep_ms)
        idx_path.write_text(idx_html, encoding="utf-8")
    toc = parse_toc(idx_html)
    print(f"TOC: {len(toc)} pages", flush=True)

    chunks = chunk_index(toc)
    print(f"Chunks: {sum(len(v) for v in chunks.values())} pages "
          f"across {len(chunks)} chunks", flush=True)
    for lbl in sorted(chunks):
        print(f"  {lbl}: {len(chunks[lbl])} pages "
              f"(first={chunks[lbl][0][1]}, last={chunks[lbl][-1][1]})",
              flush=True)

    # 2. Fetch + convert each chunk's pages
    for label, pages in sorted(chunks.items()):
        print(f"\n--- {label} ({len(pages)} pages) ---", flush=True)
        md_parts = [
            f"<!-- GX-100 Parameter Guide ({label}) — scraped from "
            f"{BASE_URL}/{INDEX_PAGE} -->\n\n",
        ]
        for fn, title in pages:
            page_path = cache / fn
            if page_path.exists():
                html = page_path.read_text(encoding="utf-8", errors="replace")
            else:
                html = fetch(fn, sleep_ms=args.sleep_ms)
                page_path.write_text(html, encoding="utf-8")
            actual_title, body = page_to_md(html)
            display_title = actual_title or title
            print(f"  {fn:<18s}  {display_title}", flush=True)
            if not body.strip():
                continue   # skip empty section-header pages
            md_parts.append(body + "\n")

        out_path = out / f"{args.prefix}{label}.md"
        out_path.write_text("".join(md_parts), encoding="utf-8")
        size = out_path.stat().st_size
        print(f"  -> wrote {out_path} ({size} B)", flush=True)


if __name__ == "__main__":
    main()
