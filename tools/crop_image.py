"""Crop a region from a screenshot for closer visual inspection."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--box", required=True, help="x1,y1,x2,y2")
args = ap.parse_args()

box = tuple(int(v) for v in args.box.split(","))
img = Image.open(args.src)
img.crop(box).save(args.out, "PNG")
print(f"cropped {box} -> {args.out}")
