"""Take a screenshot of Tone Studio's window (or full screen) and save as PNG.

When --cursor is passed, overlays a red crosshair at the current mouse
position so you can see exactly where the next click would land.
"""
import argparse
import ctypes
from ctypes import wintypes
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"),
)
import uiautomation as auto
from PIL import ImageGrab, ImageDraw

# DPI awareness so coordinates match the screenshot pixels.
try:
    ctypes.WinDLL("shcore", use_last_error=True).SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.WinDLL("user32", use_last_error=True).SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.WinDLL("user32", use_last_error=True)


def get_cursor_pos():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


def draw_crosshair(img, sx, sy, win_left, win_top):
    """Overlay a red crosshair at screen coords (sx, sy) on img which was
    captured starting at (win_left, win_top)."""
    cx = sx - win_left
    cy = sy - win_top
    if not (0 <= cx < img.size[0] and 0 <= cy < img.size[1]):
        return
    d = ImageDraw.Draw(img)
    L = 30
    d.line([(cx - L, cy), (cx + L, cy)], fill=(255, 0, 0), width=2)
    d.line([(cx, cy - L), (cx, cy + L)], fill=(255, 0, 0), width=2)
    d.ellipse([(cx - 6, cy - 6), (cx + 6, cy + 6)],
              outline=(255, 0, 0), width=2)
    d.text((cx + 8, cy + 8), f"{sx},{sy}", fill=(255, 0, 0))

TARGET_NAME = "BOSS TONE STUDIO for GX-10"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--full", action="store_true", help="full screen instead of just the Tone Studio window")
    ap.add_argument("--bring-to-front", action="store_true")
    ap.add_argument("--cursor", action="store_true",
                    help="overlay a red crosshair at the current mouse position")
    args = ap.parse_args()

    if args.full:
        img = ImageGrab.grab()
        win_left = win_top = 0
    else:
        win = auto.WindowControl(searchDepth=1, Name=TARGET_NAME)
        if not win.Exists(maxSearchSeconds=5):
            print(f"ERROR: window '{TARGET_NAME}' not found", file=sys.stderr)
            sys.exit(2)
        if args.bring_to_front:
            try:
                win.SetActive()
            except Exception:
                pass
        r = win.BoundingRectangle
        # Clamp to screen
        left = max(0, r.left)
        top = max(0, r.top)
        right = r.right
        bottom = r.bottom
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        win_left = left
        win_top = top
        print(f"window rect: ({r.left},{r.top},{r.right - r.left}x{r.bottom - r.top})", file=sys.stderr)

    if args.cursor:
        cx, cy = get_cursor_pos()
        draw_crosshair(img, cx, cy, win_left, win_top)
        print(f"cursor: {cx},{cy}", file=sys.stderr)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out, "PNG")
    print(f"saved {img.size[0]}x{img.size[1]} -> {args.out}")

if __name__ == "__main__":
    main()
