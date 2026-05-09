"""Crop each filled.png to just the effect detail panel
(effect title + type dropdown + knob row).

Output: <orig>_cropped.png alongside originals.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image


# The original screenshots are 1450x220 starting at window-local
# (50, 460). The interesting region (effect title + type bar + knob
# row) is roughly:
#   from window-local x=240 (skip chain panel) to x=1300
#   from window-local y=425 (include effect title) to y=730 (include
#   second row of knobs + their labels)
# In screenshot coords (origin at 50, 460):
#   x: 190..1250 (= width 1060)
#   y: 0..220 of the existing 220 (full)
# But we also want to include slightly above for the title — the
# original screenshots cut off the title at y≈460 window-local.
# So we'll crop within the existing screenshot frame.
CROP_X = 190
CROP_Y = 0
CROP_W = 1100
CROP_H = 220


def main():
    src_dir = Path("captures/bts_typebar_resweep")
    out_dir = Path("captures/bts_typebar_resweep_cropped")
    out_dir.mkdir(parents=True, exist_ok=True)

    n = 0
    for src in sorted(src_dir.glob("*_filled.png")):
        img = Image.open(src)
        right = min(CROP_X + CROP_W, img.width)
        bottom = min(CROP_Y + CROP_H, img.height)
        cropped = img.crop((CROP_X, CROP_Y, right, bottom))
        cropped.save(out_dir / src.name)
        n += 1
    print(f"cropped {n} files into {out_dir}")


if __name__ == "__main__":
    main()
