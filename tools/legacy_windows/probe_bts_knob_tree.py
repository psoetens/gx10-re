"""Find BTS knob labels + values via UIA tree walk.

Filters the tree to elements within the knob area (window-local
y between 460 and 680).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import uiautomation as auto


TARGET_NAME = "BOSS TONE STUDIO for GX-10"


def main():
    win = auto.WindowControl(searchDepth=1, Name=TARGET_NAME)
    if not win.Exists(maxSearchSeconds=5):
        print("ERROR: window not found"); return 2
    win_rect = win.BoundingRectangle
    win_l, win_t = win_rect.left, win_rect.top
    print(f"window at ({win_l},{win_t})")

    # Walk all elements
    elements = []
    def walk(ctrl, depth=0, limit=[5000]):
        if limit[0] <= 0:
            return
        limit[0] -= 1
        try:
            r = ctrl.BoundingRectangle
            local_y = r.top - win_t
            local_x = r.left - win_l
            if 440 < local_y < 700:
                name = ""
                try: name = ctrl.Name
                except Exception: pass
                ctype = ""
                try: ctype = ctrl.ControlTypeName
                except Exception: pass
                if name or ctype not in ("Pane", "Group", ""):
                    elements.append((local_x, local_y, ctype, name))
            for child in ctrl.GetChildren():
                walk(child, depth + 1, limit)
        except Exception:
            pass

    walk(win)
    elements.sort(key=lambda e: (e[1], e[0]))   # by y then x
    print(f"\n{len(elements)} elements in knob area:")
    for (x, y, t, n) in elements:
        print(f"  x={x:>4d} y={y:>4d}  {t:14s}  {n!r}")


if __name__ == "__main__":
    sys.exit(main())
