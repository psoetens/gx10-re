"""
Autonomous Tone Studio driver. Walks a sequence of UI actions, each labelled
into the capture log via the label fifo, so the resulting JSONL has clear
markers of what UI action produced which traffic.

Coordinates are in client-area pixels relative to the Tone Studio window's
top-left corner. The window can be off-screen at (-9, -9) on Windows; we
translate to screen coordinates before clicking.

Why no UI Automation: Tone Studio renders inside a WebView2 whose DOM is
not exposed via UIA, so we drive by coordinates derived from screenshots.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(
    0,
    str(Path.home() / "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"),
)
import uiautomation as auto
import pyautogui

TARGET_NAME = "BOSS TONE STUDIO for GX-10"

pyautogui.FAILSAFE = False  # corner-of-screen triggers cancel the run otherwise
pyautogui.PAUSE = 0.05


class Driver:
    def __init__(self, label_path: Path, screenshot_dir: Path):
        self.label_path = label_path
        self.screenshot_dir = screenshot_dir
        self.label_path.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        # Truncate existing label file
        self.label_path.write_text("")
        self.win = None
        self.origin = (0, 0)
        self.shot_idx = 0

    def acquire_window(self):
        win = auto.WindowControl(searchDepth=1, Name=TARGET_NAME)
        if not win.Exists(maxSearchSeconds=10):
            raise RuntimeError(f"Tone Studio window '{TARGET_NAME}' not found")
        # Don't call SetActive — that can pop a Start menu via misrouted keys.
        # Just record the origin.
        r = win.BoundingRectangle
        self.win = win
        self.origin = (r.left, r.top)
        print(f"window at {r.left},{r.top} size {r.right - r.left}x{r.bottom - r.top}", file=sys.stderr)

    def label(self, text: str):
        with self.label_path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    def screen_xy(self, win_x: int, win_y: int):
        return (self.origin[0] + win_x, self.origin[1] + win_y)

    def click(self, win_x: int, win_y: int, dwell: float = 0.0):
        sx, sy = self.screen_xy(win_x, win_y)
        pyautogui.click(sx, sy)
        if dwell:
            time.sleep(dwell)

    def shot(self, tag: str):
        # Lightweight: only when it's useful for diagnostics.
        from PIL import ImageGrab
        self.shot_idx += 1
        path = self.screenshot_dir / f"{self.shot_idx:03d}_{tag}.png"
        try:
            r = self.win.BoundingRectangle
            img = ImageGrab.grab(bbox=(max(0, r.left), max(0, r.top), r.right, r.bottom))
            img.save(path, "PNG")
        except Exception as e:
            print(f"shot failed: {e}", file=sys.stderr)


# Coordinates derived from screenshot ui_002.png (window at -9,-9, size 1938x1158).
# All in window-local pixels.
PATCHES_USER = [
    ("U01-1 NATURAL AMP HB", 110, 153),
    ("U01-2 BOUTIQUE AMP HB", 110, 203),
    ("U01-3 SUPREME AMP HB", 110, 253),
    ("U02-1 MAXIMUM AMP HB", 110, 303),
    ("U02-2 JUGGERNAUT HB", 110, 353),
    ("U02-3 X-CRUNCH AMP HB", 110, 403),
]
PRESET_TAB = (60, 108)
USER_TAB = (168, 108)

EFFECT_BLOCKS = [
    ("WAH", 285, 312),
    ("FOOT_VOL", 358, 312),
    ("OD", 432, 312),
    ("DIV", 505, 312),
    ("AMP1", 541, 248),
    ("PEQ1", 615, 248),
    ("NS1", 689, 248),
    ("MIX", 725, 312),
    ("DELAY", 798, 312),
    ("REV", 871, 312),
    ("MASTER", 990, 312),
    ("AMP2", 541, 376),
    ("PEQ2", 615, 376),
    ("NS2", 689, 376),
]

EFFECT_TYPE_BAR = [  # selects the "type" of the highlighted slot
    ("COMP", 254, 156),
    ("X-COMP", 308, 156),
    ("BOOST", 363, 156),
    ("OD", 418, 156),
    ("X-OD", 472, 156),
    ("DIST", 533, 156),
    ("X-DIST", 590, 156),
    ("METAL", 645, 156),
    ("FUZZ", 703, 156),
    ("AMP", 759, 156),
]

TOOLBAR = {
    "EDITOR": (240, 60),
    "LIBRARIAN": (320, 60),
    "TONE_EXCHANGE": (399, 60),
    "TUNER": (482, 60),
    "IR_LOADER": (542, 60),
    "MENU": (605, 60),
}


def script_patch_sweep(d: Driver):
    d.label("== SCRIPT: patch sweep through user bank 1 ==")
    time.sleep(0.5)
    d.label("click USER tab")
    d.click(*USER_TAB, dwell=1.0)
    for name, x, y in PATCHES_USER:
        d.label(f"click patch {name}")
        d.click(x, y, dwell=1.5)


def script_effect_block_sweep(d: Driver):
    d.label("== SCRIPT: effect block sweep on current patch ==")
    time.sleep(0.5)
    for name, x, y in EFFECT_BLOCKS:
        d.label(f"click effect block {name}")
        d.click(x, y, dwell=0.8)


def script_toolbar_sweep(d: Driver):
    d.label("== SCRIPT: toolbar tab sweep ==")
    for name in ["EDITOR", "LIBRARIAN", "EDITOR"]:
        x, y = TOOLBAR[name]
        d.label(f"click toolbar {name}")
        d.click(x, y, dwell=2.0)


def script_preset_browse(d: Driver):
    d.label("== SCRIPT: preset bank browse ==")
    d.label("click PRESET tab")
    d.click(*PRESET_TAB, dwell=1.5)
    for i in range(8):
        wy = 153 + i * 50
        d.label(f"click preset row {i}")
        d.click(110, wy, dwell=0.8)
    d.label("click USER tab back")
    d.click(*USER_TAB, dwell=1.0)


def script_effect_type_sweep(d: Driver):
    d.label("== SCRIPT: change effect type via type bar ==")
    d.label("first ensure first slot selected (click WAH)")
    d.click(*EFFECT_BLOCKS[0][1:], dwell=0.6)
    for name, x, y in EFFECT_TYPE_BAR[:6]:
        d.label(f"select effect type {name}")
        d.click(x, y, dwell=1.0)


def script_knob_drag(d: Driver):
    """Drag the EFFECT LEVEL knob to generate continuous DT1 parameter traffic.

    Pre-roll: settle for a moment to avoid races with foreground transitions
    (e.g. user just alt-tabbed to bring Tone Studio forward).
    """
    time.sleep(1.0)
    d.label("== SCRIPT: knob drag (effect level) ==")
    d.label("focus WAH slot by clicking its hex block")
    d.click(*EFFECT_BLOCKS[0][1:], dwell=1.0)
    knob = (308, 590)  # EFFECT LEVEL knob center
    sx, sy = d.screen_xy(*knob)
    for delta, tag in [(150, "down 150"), (-150, "up 150"), (60, "down 60"), (-60, "up 60")]:
        d.label(f"knob drag {tag}")
        pyautogui.moveTo(sx, sy, duration=0.1)
        pyautogui.mouseDown()
        # Walk in many small steps to produce many discrete parameter events
        steps = 30
        for i in range(1, steps + 1):
            pyautogui.moveTo(sx, sy + int(delta * i / steps), duration=0.0)
            time.sleep(0.025)
        pyautogui.mouseUp()
        time.sleep(0.6)


def script_wah_toggle(d: Driver):
    """Toggle the WAH on/off power icon in the bottom parameter panel."""
    time.sleep(1.0)
    d.label("== SCRIPT: WAH on/off toggle ==")
    d.label("focus WAH slot")
    d.click(*EFFECT_BLOCKS[0][1:], dwell=1.0)
    # Power icon next to "WAH" header in bottom panel
    for i in range(4):
        d.label(f"toggle WAH on/off (#{i+1})")
        d.click(266, 446, dwell=1.0)


def script_wah_type(d: Driver):
    """Open the WAH TYPE dropdown and pick different items by arrow keys."""
    time.sleep(1.0)
    d.label("== SCRIPT: WAH TYPE dropdown sweep ==")
    d.label("focus WAH slot")
    d.click(*EFFECT_BLOCKS[0][1:], dwell=1.0)
    d.label("click WAH TYPE dropdown")
    d.click(425, 494, dwell=1.0)
    for i in range(6):
        d.label(f"arrow-down ({i+1})")
        pyautogui.press("down")
        time.sleep(0.5)
    d.label("press Enter to confirm")
    pyautogui.press("enter")
    time.sleep(1.0)


def script_knob_drag_v2(d: Driver):
    """Use pyautogui.dragRel which generates real drag events."""
    time.sleep(1.0)
    d.label("== SCRIPT: knob dragRel v2 ==")
    d.label("focus WAH slot")
    d.click(*EFFECT_BLOCKS[0][1:], dwell=1.0)
    knob = (308, 590)
    sx, sy = d.screen_xy(*knob)
    pyautogui.moveTo(sx, sy, duration=0.2)
    for delta, tag in [(120, "down 120"), (-120, "up 120"), (50, "down 50")]:
        d.label(f"dragRel {tag}")
        pyautogui.dragRel(0, delta, duration=1.2, button="left", mouseDownUp=True)
        time.sleep(0.6)


SCRIPTS = {
    "patches": script_patch_sweep,
    "blocks": script_effect_block_sweep,
    "toolbar": script_toolbar_sweep,
    "presets": script_preset_browse,
    "types": script_effect_type_sweep,
    "knob": script_knob_drag,
    "wah-toggle": script_wah_toggle,
    "wah-type": script_wah_type,
    "knob2": script_knob_drag_v2,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label-fifo", required=True)
    ap.add_argument("--shots", default="captures/shots")
    ap.add_argument("--scripts", nargs="+", choices=list(SCRIPTS) + ["all"], default=["patches"])
    args = ap.parse_args()

    d = Driver(Path(args.label_fifo), Path(args.shots))
    d.acquire_window()

    scripts = list(SCRIPTS) if "all" in args.scripts else args.scripts
    for name in scripts:
        d.label(f"--- start script: {name} ---")
        SCRIPTS[name](d)
        d.label(f"--- end script: {name} ---")
        time.sleep(0.5)

    d.label("DONE")


if __name__ == "__main__":
    main()
