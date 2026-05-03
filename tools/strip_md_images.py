"""Strip embedded base64 image data and image references from a .md file.

Google Docs export inlines images as `[imageN]: <data:image/png;base64,...>`
references at the bottom of the file plus `![][imageN]` placeholders in
the body. We drop both.
"""
import re
import sys
from pathlib import Path


REF_RE = re.compile(r'^\[image\d+\]:\s*<data:image/[^>]+>\s*$', re.MULTILINE)
PLACEHOLDER_RE = re.compile(r'!\[\]\[image\d+\]')
DATAURI_INLINE_RE = re.compile(r'!\[\]\(data:image/[^)]+\)')


def strip(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    before = len(text)
    text = REF_RE.sub("", text)
    text = PLACEHOLDER_RE.sub("", text)
    text = DATAURI_INLINE_RE.sub("", text)
    text = re.sub(r'\n{3,}', "\n\n", text)
    after = len(text)
    path.write_text(text, encoding="utf-8")
    return before, after


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"  not found: {p}")
            continue
        b, a = strip(p)
        print(f"  {p.name:60s}  {b//1024} KB -> {a//1024} KB")


if __name__ == "__main__":
    main()
