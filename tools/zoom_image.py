"""Crop and 4x scale an image region for inspection."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image

src, out = sys.argv[1], sys.argv[2]
box = tuple(int(v) for v in sys.argv[3].split(","))
scale = int(sys.argv[4]) if len(sys.argv) > 4 else 4

img = Image.open(src).crop(box)
img = img.resize((img.size[0]*scale, img.size[1]*scale), Image.NEAREST)
img.save(out, "PNG")
print(f"saved {img.size} -> {out}")
