"""Scrape the CONTROL-behaviour pages of Roland's online GX-10 v1.0
Parameter Guide (en-US) into a single Markdown reference.

Targeted extraction for the gxnarly stage-view pedal state machine:
CONTROL MODE, CONTROL FUNCTION, ASSIGN SETTING (+ range/mode notes),
PLAY OPTION (BANK CHANGE MODE etc.), EXP HOLD, COLOR MODE.

Reuses the HTML→Markdown helpers from scrape_gx100_v1_manual.py.

Output (git-ignored, per docs/manuals/README.md policy):
    docs/manuals/GX-10_Parameter_Guide_control_behavior.md

Usage:
    python tools/scrape_gx10_control_pages.py
"""
from __future__ import annotations

import re
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scrape_gx100_v1_manual import table_to_md  # rowspan-aware table conv

BASE_URL = "https://static.roland.com/manuals/gx-10_parameter/en-US"

# (filename, TOC title) — document order
PAGES = [
    ("91559691158981771.html", "CTL/EXP"),
    ("95921291158984075.html", "CONTROL FUNCTION"),
    ("158988683161249163.html", "ASSIGN SETTING"),
    ("159000971161251211.html", "ASSIGN parameter list"),
    ("158993675161249675.html", "About the range of a target's change"),
    ("158995979161250443.html", "About the range of a controller's change"),
    ("159051147161251979.html", "Virtual expression pedal system"),
    ("95927947159002507.html", "CONTROL MODE"),
    ("95934859159017867.html", "PLAY OPTION"),
    ("159005579162004363.html", "EXP HOLD"),
    ("159014795162007435.html", "COLOR MODE"),
    ("159035531162008843.html", "TUNER"),
]

CACHE = Path(__file__).resolve().parent.parent / "docs/manuals/_scrape_gx10"
OUT = Path(__file__).resolve().parent.parent / \
    "docs/manuals/GX-10_Parameter_Guide_control_behavior.md"


def fetch(fn: str) -> str:
    cached = CACHE / fn
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    req = urllib.request.Request(f"{BASE_URL}/{fn}", headers={
        "User-Agent": "Mozilla/5.0 (gx10-re manual archive)",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read().decode("utf-8", errors="replace")
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(data, encoding="utf-8")
    time.sleep(0.08)
    return data


# The SCHEMA ST4 pages embed footswitch glyphs via a Roland icon font:
# [É] renders as ▼ and [Ç] as ▲ on the printed page.
GLYPHS = {"É": "▼", "Ç": "▲"}


def _strip(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    for k, v in GLYPHS.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip()


def article_to_md(html: str) -> str:
    m = re.search(r'<article[^>]*>(.*?)</article>', html, re.S)
    if not m:
        return ""
    body = m.group(1)
    for k, v in GLYPHS.items():
        body = body.replace(k, v)
    out = []
    # walk top-level-ish elements in order
    pat = re.compile(
        r'<(h[1-4])[^>]*>(.*?)</\1>|<table[^>]*>.*?</table>'
        r'|<p[^>]*>(.*?)</p>|<li[^>]*>(.*?)</li>', re.S)
    pos = 0
    for m2 in pat.finditer(body):
        tagtxt = m2.group(0)
        if tagtxt.startswith("<table"):
            out.append(table_to_md(tagtxt))
        elif m2.group(1):  # heading
            lvl = int(m2.group(1)[1])
            out.append("#" * (lvl + 2) + " " + _strip(m2.group(2)))
        elif m2.group(3) is not None:
            # skip <p> that live inside a table (already rendered)
            if "<table" not in body[:m2.start()] or \
                    body.rfind("</table>", 0, m2.start()) > \
                    body.rfind("<table", 0, m2.start()):
                t = _strip(m2.group(3))
                if t:
                    out.append(t)
        elif m2.group(4) is not None:
            if body.rfind("</table>", 0, m2.start()) >= \
                    body.rfind("<table", 0, m2.start()):
                t = _strip(m2.group(4))
                if t:
                    out.append("- " + t)
        pos = m2.end()
    return "\n\n".join(x for x in out if x.strip())


def main():
    parts = ["# GX-10 Parameter Guide — control behaviour pages",
             f"# Scraped from {BASE_URL} (© Roland — do not commit)", ""]
    for fn, title in PAGES:
        html = fetch(fn)
        md = article_to_md(html)
        parts.append(f"\n---\n\n## {title}\n\n{md.strip()}\n")
        print(f"  ok  {title}  ({fn})  {len(md)} chars")
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
