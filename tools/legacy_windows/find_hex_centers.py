"""
Find centers of effect-bar hexagons in a screenshot by scanning y=156.

Hexes are non-black pixels at y=156. Background is dark RGB <= 35.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image


def find_hexes(img_path, y_scan=140):
    """Hexes span roughly y=128..184. y=140 is the top widening which is
    full color (not text). Text is ~y=160 (white pixels)."""
    img = Image.open(img_path)
    in_hex = False
    starts = []
    ends = []
    for x in range(220, 1920):
        r, g, b = img.getpixel((x, y_scan))[:3]
        # Background is dark (~26,28,31). Hex fills are bright color.
        bright = max(r, g, b) > 70
        if bright and not in_hex:
            starts.append(x)
            in_hex = True
        elif not bright and in_hex:
            ends.append(x - 1)
            in_hex = False
    if in_hex:
        ends.append(1920)
    pairs = [(s, e) for s, e in zip(starts, ends) if (e - s) > 20]
    centers = [(s + e) // 2 for s, e in pairs]
    return centers, pairs


if __name__ == "__main__":
    for f in sys.argv[1:]:
        c, pairs = find_hexes(f)
        print(f"{f}: {len(c)} hexes")
        for i, ((s, e), ctr) in enumerate(zip(pairs, c)):
            print(f"  [{i:2d}] x={s:4d}..{e:4d} center={ctr}")
