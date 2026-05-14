"""
Inspect Tone Studio's UIA tree so we know what's clickable.

Walks the top-level Tone Studio window and dumps the accessible-element tree
to stdout. WebView2-hosted UI typically appears as a child Document with
button/checkbox/radio elements that have their HTML aria-labels exposed.
"""
import sys
import time
from pathlib import Path

sys.path.insert(
    0,
    str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"),
)
import uiautomation as auto

TARGET_NAME = "BOSS TONE STUDIO for GX-10"

def label(ctrl) -> str:
    try:
        cls = ctrl.ClassName
    except Exception:
        cls = "?"
    try:
        name = ctrl.Name
    except Exception:
        name = "?"
    try:
        ctype = ctrl.ControlTypeName
    except Exception:
        ctype = "?"
    try:
        aid = ctrl.AutomationId
    except Exception:
        aid = ""
    rect = ""
    try:
        r = ctrl.BoundingRectangle
        rect = f"({r.left},{r.top},{r.right - r.left}x{r.bottom - r.top})"
    except Exception:
        pass
    return f"{ctype} cls={cls!r} name={name!r} aid={aid!r} rect={rect}"

def walk(ctrl, depth=0, max_depth=12, limit=[2000]):
    if limit[0] <= 0:
        return
    limit[0] -= 1
    print("  " * depth + label(ctrl))
    if depth >= max_depth:
        return
    try:
        for child in ctrl.GetChildren():
            walk(child, depth + 1, max_depth, limit)
    except Exception as e:
        print("  " * (depth + 1) + f"<error: {e!r}>")

def main():
    win = auto.WindowControl(searchDepth=1, Name=TARGET_NAME)
    if not win.Exists(maxSearchSeconds=5):
        print(f"ERROR: window '{TARGET_NAME}' not found", file=sys.stderr)
        sys.exit(2)

    print(f"=== {TARGET_NAME} ===")
    print(label(win))
    walk(win)

if __name__ == "__main__":
    main()
