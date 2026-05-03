"""Split a PDF into chapter-sized chunks for Google Drive → Docs → .md export.

Usage:
  python split_pdf.py <input.pdf> <output_dir> [--ranges p1-p2,p3-p4,...]

If --ranges is not given, prints the PDF outline and exits.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import pypdf


def show_outline(reader):
    def walk(items, depth=0):
        for it in items:
            if isinstance(it, list):
                walk(it, depth + 1)
                continue
            try:
                page = reader.get_destination_page_number(it) + 1
                print(f"{'  '*depth}p{page:3d} - {it.title}")
            except Exception:
                pass
    print(f"Total pages: {len(reader.pages)}")
    if reader.outline:
        walk(reader.outline)


def split(reader, ranges, out_dir, base_name):
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, (start, end, label) in enumerate(ranges):
        writer = pypdf.PdfWriter()
        for p in range(start - 1, end):
            writer.add_page(reader.pages[p])
        safe = label.lower().replace(" ", "_").replace("/", "-")
        fn = out_dir / f"{base_name}_{i+1:02d}_{safe}_p{start:03d}-p{end:03d}.pdf"
        with fn.open("wb") as f:
            writer.write(f)
        size_mb = fn.stat().st_size / 1024 / 1024
        print(f"  wrote {fn.name}  ({end-start+1} pages, {size_mb:.1f} MB)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    in_pdf = Path(sys.argv[1])
    reader = pypdf.PdfReader(str(in_pdf))

    if len(sys.argv) < 3 or sys.argv[2] == "--outline":
        show_outline(reader)
        return

    out_dir = Path(sys.argv[2])
    ranges_arg = None
    for a in sys.argv[3:]:
        if a.startswith("--ranges="):
            ranges_arg = a.split("=", 1)[1]
        elif a == "--ranges":
            ranges_arg = sys.argv[sys.argv.index(a) + 1]
    if not ranges_arg:
        print("ERROR: pass --ranges <p1-p2:label>,<p3-p4:label>,...")
        sys.exit(2)

    ranges = []
    for tok in ranges_arg.split(","):
        rng, _, label = tok.partition(":")
        if not label:
            label = rng
        s, _, e = rng.partition("-")
        ranges.append((int(s), int(e), label))

    split(reader, ranges, out_dir, in_pdf.stem)


if __name__ == "__main__":
    main()
