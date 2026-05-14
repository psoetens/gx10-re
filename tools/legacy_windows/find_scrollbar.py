"""Find horizontal scrollbar handle extent from a screenshot."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import Image

img = Image.open(sys.argv[1])
y = 190  # known scrollbar y
GRAY = (141, 142, 143)
transitions = []
prev = None
for x in range(230, img.size[0]):
    cur = img.getpixel((x, y))
    is_handle = cur == GRAY
    if prev is None or is_handle != prev:
        transitions.append((x, "in" if is_handle else "out"))
    prev = is_handle
print("Transitions at y=190:")
for t in transitions[:30]:
    print(" ", t)
print(f"Total transitions: {len(transitions)}")
