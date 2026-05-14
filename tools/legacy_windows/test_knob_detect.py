"""Test knob detection on saved drag screenshots."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from sweep_all_knobs import detect_knobs_from_screenshot

ROOT = Path(__file__).parent.parent

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "captures/typebar_full/page0/00_COMP/drag.png"
    img = Image.open(ROOT / target)
    knobs = detect_knobs_from_screenshot(img)
    print(f"{target}: {len(knobs)} knobs")
    for x, y in knobs:
        print(f"  ({x},{y})")
    # Annotate
    out = ROOT / target.replace(".png", "_knobs.png")
    annot = img.copy()
    d = ImageDraw.Draw(annot)
    for x, y in knobs:
        d.ellipse([(x-30, y-30), (x+30, y+30)], outline=(255,0,0), width=3)
    annot.save(out, "PNG")
    print(f"annotated: {out}")
