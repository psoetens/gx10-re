"""Crop small regions around suspected click coordinates from the
v4 baseline screenshot, so we can see what's actually there."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "chain_buttons"

img = Image.open(OUT / "v4_00_baseline.png")
print(f"Full image: {img.size}")

points = {
    "BTN_DELETE_582_109": (582, 109),
    "BTN_INSERT_685_109": (685, 109),
    "BTN_OVERWRITE_786_109": (786, 109),
    "TYPEBAR_255_155": (255, 155),
    "CHAIN_SLOT0_290_312": (290, 312),
}
for name, (x, y) in points.items():
    half = 80
    box = (max(0, x - half), max(0, y - half),
           min(img.width, x + half), min(img.height, y + half))
    crop = img.crop(box).copy()
    d = ImageDraw.Draw(crop)
    cx = x - box[0]; cy = y - box[1]
    d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), outline="red", width=2)
    d.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill="red")
    crop.save(OUT / f"inspect_{name}.png")
    print(f"  saved inspect_{name}.png (box={box})")
