"""Compare chain hex row before/after the action button clicks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "chain_buttons"

shots = [
    "v4_00_baseline.png",
    "v4_01_after_typebar.png",
    "v4_02_after_INSERT.png",
    "v4_03_after_OVERWRITE.png",
    "v4_04_after_chain.png",
    "v4_05_after_DELETE.png",
]
# Chain hex row should be around y=270..360 at full res, full width
crop_box = (150, 250, 1900, 380)
for s in shots:
    p = OUT / s
    if not p.exists():
        continue
    img = Image.open(p)
    img.crop(crop_box).save(OUT / f"chaincrop_{Path(s).stem}.png")
print("done")
