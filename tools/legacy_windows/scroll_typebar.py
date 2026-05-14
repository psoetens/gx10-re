"""
Scroll Tone Studio's effect type bar to a given page (0, 1, or 2).

The bar has a horizontal scrollbar whose visible-handle is gray (RGB 141)
at y=186..194 in screenshot pixels, but the ACTIVE click hit-zone is at
y≈200 (10 px below the visual). Drag at y=200, target the handle's center.

Implementation:
  1. Take a quick screenshot, find the current handle x-extent.
  2. Compute target-x for the requested page (0,1,2).
  3. Drag handle from current center -> target center at y=200.
  4. Verify with a second screenshot.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import ImageGrab
import pyautogui

sys.path.insert(0, str(Path(__file__).parent))
import focus_ts

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

# Scroll bar metadata (in window-local pixels of the maximised TS).
TRACK_X_LEFT = 230
TRACK_X_RIGHT = 1920
SCROLL_CLICK_Y = 200       # hit zone (10 px below visual handle)
HANDLE_GRAY = (141, 142, 143)
HANDLE_VISUAL_Y = 190      # row where the gray handle is visible


def find_handle_extent(img):
    """Return (x_start, x_end) of the gray handle on row HANDLE_VISUAL_Y.
    Coordinates are in screenshot pixels (which equal window-local pixels
    since the window is at -9..-9 and we crop only inside)."""
    y = HANDLE_VISUAL_Y
    in_handle = False
    start = end = None
    for x in range(TRACK_X_LEFT, TRACK_X_RIGHT):
        is_h = img.getpixel((x, y)) == HANDLE_GRAY
        if is_h and not in_handle:
            start = x
            in_handle = True
        elif not is_h and in_handle:
            end = x - 1
            break
    if in_handle and end is None:
        end = TRACK_X_RIGHT - 1
    return start, end


def take_local_screenshot(hwnd):
    rect = focus_ts.get_window_rect(hwnd)
    return ImageGrab.grab(bbox=(max(0, rect[0]), max(0, rect[1]),
                                rect[2], rect[3]))


def scroll_to_page(page: int):
    """Page is 0, 1, or 2. Scrollbar travel for one page = handle width."""
    if page not in (0, 1, 2):
        raise ValueError("page must be 0, 1, or 2")

    hwnd = focus_ts.focus_tone_studio()
    time.sleep(0.3)
    img = take_local_screenshot(hwnd)
    h_start, h_end = find_handle_extent(img)
    if h_start is None:
        raise RuntimeError("scrollbar handle not found")

    handle_w = h_end - h_start + 1
    # 3 pages assumed. Track usable: (TRACK_X_RIGHT - TRACK_X_LEFT) - handle_w.
    # For page 0: handle starts at TRACK_X_LEFT.
    # For page 2: handle ends at TRACK_X_RIGHT.
    usable = (TRACK_X_RIGHT - TRACK_X_LEFT) - handle_w
    target_handle_start = TRACK_X_LEFT + (page * usable // 2)
    target_center = target_handle_start + handle_w // 2
    cur_center = (h_start + h_end) // 2

    if abs(target_center - cur_center) < 5:
        print(f"already on page {page} (handle {h_start}-{h_end})", file=sys.stderr)
        return

    # Convert to absolute screen coords. Note: focus_ts.screen_xy uses the
    # window's left/top which is -9; pyautogui clicks at *physical* pixels.
    src_x, src_y = focus_ts.screen_xy(hwnd, cur_center, SCROLL_CLICK_Y)
    dst_x, dst_y = focus_ts.screen_xy(hwnd, target_center, SCROLL_CLICK_Y)
    pyautogui.moveTo(src_x, src_y, duration=0.2)
    time.sleep(0.2)
    pyautogui.mouseDown()
    time.sleep(0.2)
    pyautogui.moveTo(dst_x, dst_y, duration=0.8)
    time.sleep(0.2)
    pyautogui.mouseUp()
    time.sleep(1.5)

    # Verify
    img2 = take_local_screenshot(hwnd)
    h2_start, h2_end = find_handle_extent(img2)
    print(f"scrolled: handle {h_start}-{h_end} -> {h2_start}-{h2_end}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, required=True, choices=[0, 1, 2])
    args = ap.parse_args()
    scroll_to_page(args.page)


if __name__ == "__main__":
    main()
