"""Convert .docx files to .md, stripping base64 embedded image data
(which mammoth otherwise emits as inline data: URIs).

Usage:  python docx_to_md.py <file.docx>...
"""
import re
import sys
from pathlib import Path

import mammoth


IMG_RE = re.compile(r'!\[\]\(data:image/[^)]+\)')
EMPTY_LINK_RE = re.compile(r'\[(\s*)\]\([^)]*\)')


def convert(docx_path: Path) -> Path:
    md_path = docx_path.with_suffix(".md")
    with docx_path.open("rb") as f:
        result = mammoth.convert_to_markdown(f)
    text = result.value
    # Drop embedded image data URIs
    text = IMG_RE.sub("", text)
    # Drop empty image link reference markers
    text = re.sub(r'\n{3,}', '\n\n', text)
    md_path.write_text(text, encoding="utf-8")
    return md_path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"  not found: {p}")
            continue
        out = convert(p)
        size_kb = out.stat().st_size / 1024
        print(f"  {p.name} → {out.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
