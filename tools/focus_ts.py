"""
Reliably bring Tone Studio's window to the foreground.

SetForegroundWindow alone fails when another process is in foreground —
Windows blocks "focus stealing" unless the caller has foreground rights.
The well-known workaround is to attach the calling thread's input to the
foreground window's thread, call SetForegroundWindow, then detach.

This module exposes:
    focus_tone_studio() -> hwnd        # raises if not found
    get_window_rect(hwnd) -> (l,t,r,b)
    screen_xy(hwnd, x, y) -> (sx, sy)  # client-relative -> screen-absolute
"""
import ctypes
from ctypes import wintypes
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shcore = None
try:
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:
    pass

# Make this process per-monitor DPI aware. Without this, GetWindowRect and
# the screenshots return logical pixels (scaled), while pyautogui clicks at
# physical pixels — coordinates do not line up. With it, both use physical.
PROCESS_PER_MONITOR_DPI_AWARE = 2
try:
    if shcore is not None:
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
    else:
        user32.SetProcessDPIAware()
except Exception:
    pass

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.SwitchToThisWindow.restype = None
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

SW_RESTORE = 9
SW_SHOW = 5
SW_MAXIMIZE = 3
TARGET_TITLE = "BOSS TONE STUDIO for GX-10"


def maximize_tone_studio() -> int:
    hwnd = find_tone_studio()
    if not hwnd:
        raise RuntimeError(f"Window not found: {TARGET_TITLE!r}")
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    return hwnd


def find_tone_studio():
    hwnd = user32.FindWindowW(None, TARGET_TITLE)
    if not hwnd:
        # Try by class name as fallback (Tone Studio main window)
        hwnd = user32.FindWindowW("jp.co.roland.BOSS TONE STUDIO for GX-10.wndclass", None)
    return hwnd


def focus_tone_studio(verify_seconds: float = 0.5) -> int:
    """Raise Tone Studio to foreground. Returns hwnd. Raises if not found
    or if focus did not transfer (rare).

    Uses the AttachThreadInput trick to bypass focus-steal blocking.
    """
    hwnd = find_tone_studio()
    if not hwnd:
        raise RuntimeError(f"Window not found: {TARGET_TITLE!r}")

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return hwnd

    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    cur_thread = kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)

    attached = []
    if fg_thread and fg_thread != cur_thread:
        if user32.AttachThreadInput(cur_thread, fg_thread, True):
            attached.append((cur_thread, fg_thread))
    if target_thread and target_thread not in (cur_thread, fg_thread):
        if user32.AttachThreadInput(cur_thread, target_thread, True):
            attached.append((cur_thread, target_thread))

    try:
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.SetForegroundWindow(hwnd)
        # Belt-and-braces: SwitchToThisWindow ignores SPI_GETFOREGROUNDLOCKTIMEOUT
        user32.SwitchToThisWindow(hwnd, True)
    finally:
        for src, dst in attached:
            user32.AttachThreadInput(src, dst, False)

    # Verify
    deadline = time.time() + verify_seconds
    while time.time() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return hwnd
        time.sleep(0.02)
    raise RuntimeError("Tone Studio did not become foreground within %.2fs" % verify_seconds)


def get_window_rect(hwnd):
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        raise RuntimeError("GetWindowRect failed")
    return (r.left, r.top, r.right, r.bottom)


def screen_xy(hwnd, x: int, y: int):
    """Convert window-local coords (matching the screenshots) to absolute
    screen coords. Tone Studio's window is normally at -9,-9 with its
    drawable area starting at 0,0 — so add the window's left/top."""
    l, t, _, _ = get_window_rect(hwnd)
    return (l + x, t + y)


if __name__ == "__main__":
    import sys
    hwnd = focus_tone_studio()
    print(f"focused hwnd={hwnd:#x} rect={get_window_rect(hwnd)}", file=sys.stderr)
