"""Crop the button bar region from v3 screenshots to inspect at full res."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image

ROOT = Path(__file__).parent.parent
OUT = ROOT / "captures" / "chain_buttons"

shots = [
    "v3_after_preset_load.png",
    "v3_after_typebar_select.png",
    "v3_after_INSERT_typebar.png",
    "v3_after_OVERWRITE_typebar.png",
    "v3_after_chain_select.png",
    "v3_after_DELETE_chain.png",
]

# Crop top button bar (DELETE/INSERT/OVERWRITE/etc.) which is around y=80..160
# at full 1929-wide resolution. Also crop typebar/chain area y=120..280.
for s in shots:
    p = OUT / s
    if not p.exists():
        continue
    img = Image.open(p)
    # Top button bar
    bar = img.crop((150, 80, 1100, 160))
    bar.save(OUT / f"crop_topbar_{s}")
    # Typebar+chain area
    chain = img.crop((150, 120, 1900, 350))
    chain.save(OUT / f"crop_chain_{s}")
print("Done")
