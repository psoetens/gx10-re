"""Crop INSERT button area from v4 baseline AND post-typebar screenshots
side by side to see if it actually became enabled."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "chain_buttons"

shots = [
    ("v4_00_baseline.png", "v4 BASELINE (no selection)"),
    ("v4_01_after_typebar.png", "v4 after typebar COMP click"),
    ("v4_04_after_chain.png", "v4 after chain slot click"),
]

# Wider crop to see DELETE/INSERT/OVERWRITE all together
crop_box = (470, 60, 920, 160)  # x_start=470, y_start=60, x_end=920, y_end=160

for src, label in shots:
    p = OUT / src
    if not p.exists():
        continue
    img = Image.open(p)
    region = img.crop(crop_box)
    # Save with explicit name
    out_name = f"buttoncrop_{Path(src).stem}.png"
    region.save(OUT / out_name)
    print(f"  -> {out_name}  ({label})")
