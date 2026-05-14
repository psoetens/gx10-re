"""Cross-platform BOSS TONE STUDIO process launcher.

Resolves a BTS executable for the current OS, launches it, and provides
graceful + forceful close primitives so the BTS-orchestration tools
work on macOS and Windows without per-tool conditionals.

  find_bts_exe()      -> Path | None
  launch(exe=None)    -> subprocess.Popen  (the BTS process)
  kill(proc, graceful=True, timeout=8.0) -> int  (returncode)

The graceful path on macOS uses `osascript` to send an Apple Events
"quit" message; this preserves BTS's on-disk config (memory entry
`bts_force_kill_corrupts_config` documents the SIGKILL-on-Windows
config-reset bug). On Windows the graceful path falls back to the
existing `taskkill` behaviour the original tools used.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"

# Default BTS install paths per OS. The macOS path points at the inner
# Mach-O executable rather than the .app — running .app/Contents/MacOS/...
# directly gives us a PID we can subsequently terminate. `open -a` would
# return immediately and not yield a usable process handle.
WINDOWS_DEFAULT = Path(r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe")
MACOS_DEFAULT_APP  = Path("/Applications/BOSS/GX-10/BOSS TONE STUDIO for GX-10.app")
MACOS_DEFAULT_EXE  = MACOS_DEFAULT_APP / "Contents" / "MacOS" / "BOSS TONE STUDIO for GX-10"
MACOS_APP_BUNDLE_NAME = "BOSS TONE STUDIO for GX-10"   # for osascript quit


def find_bts_exe() -> Path | None:
    """Return the BTS executable path for the current OS, or None."""
    if _IS_WIN:
        return WINDOWS_DEFAULT if WINDOWS_DEFAULT.exists() else None
    if _IS_MAC:
        return MACOS_DEFAULT_EXE if MACOS_DEFAULT_EXE.exists() else None
    return None


def launch(exe: Path | str | None = None) -> subprocess.Popen:
    """Launch BTS. Returns the Popen handle so callers can later kill it."""
    if exe is None:
        exe = find_bts_exe()
    if exe is None:
        raise FileNotFoundError(
            "No BTS executable found. Pass exe= or install BTS:\n"
            f"  Windows:  {WINDOWS_DEFAULT}\n"
            f"  macOS:    {MACOS_DEFAULT_APP}"
        )
    exe = Path(exe)
    if not exe.exists():
        raise FileNotFoundError(f"BTS executable not at: {exe}")
    return subprocess.Popen([str(exe)], close_fds=True)


def kill(proc: subprocess.Popen, graceful: bool = True, timeout: float = 8.0) -> int:
    """Close BTS.

    graceful=True: try the OS-native polite-quit first (Apple Events
        on macOS, kept WIP on Windows). Falls back to terminate/kill
        if the app doesn't exit within `timeout` seconds.
    graceful=False: terminate immediately (equivalent to taskkill /F).

    Returns the exit code.
    """
    if proc.poll() is not None:
        return proc.returncode

    if graceful and _IS_MAC:
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{MACOS_APP_BUNDLE_NAME}" to quit'],
                check=False, capture_output=True, timeout=5.0,
            )
        except Exception:
            pass
    elif graceful and _IS_WIN:
        # On Windows, true graceful-close needs WM_CLOSE via Win32; the
        # original tools used taskkill /F. We preserve that here as the
        # "graceful" path because the existing capture flows expect a
        # quick force-kill, not a save-prompt dialog.
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(proc.pid)],
                check=False, capture_output=True, timeout=5.0,
            )
        except Exception:
            pass

    # Wait briefly for the polite path to land
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass

    # Force terminate (SIGTERM on POSIX, TerminateProcess on Windows)
    proc.terminate()
    try:
        return proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        pass

    # Last resort
    proc.kill()
    try:
        return proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        return -1


def is_bts_running() -> bool:
    """Best-effort: is any BTS instance currently running on this host?

    Used by the orchestration tools to refuse to launch a second BTS
    on top of one already started by the user — that case confuses
    CoreMIDI port ownership.
    """
    if _IS_MAC:
        try:
            r = subprocess.run(
                ["pgrep", "-f", MACOS_APP_BUNDLE_NAME],
                capture_output=True, text=True, timeout=2.0,
            )
            return r.returncode == 0 and r.stdout.strip() != ""
        except Exception:
            return False
    if _IS_WIN:
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq BOSS TONE STUDIO for GX-10.exe"],
                capture_output=True, text=True, timeout=3.0,
            )
            return "BOSS TONE STUDIO for GX-10.exe" in r.stdout
        except Exception:
            return False
    return False


if __name__ == "__main__":
    # CLI for quick smoke-testing of the launcher itself.
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--show", action="store_true", help="just print the detected BTS path")
    ap.add_argument("--launch", action="store_true", help="launch BTS and exit (leaves it running)")
    ap.add_argument("--kill", action="store_true", help="find a running BTS via pgrep and kill it")
    args = ap.parse_args()

    if args.show:
        exe = find_bts_exe()
        print(exe if exe else "(no BTS found)")
        running = is_bts_running()
        print(f"running: {running}")
    elif args.launch:
        p = launch()
        print(f"launched PID={p.pid}, exe={find_bts_exe()}")
    elif args.kill:
        if _IS_MAC:
            try:
                subprocess.run(
                    ["osascript", "-e", f'tell application "{MACOS_APP_BUNDLE_NAME}" to quit'],
                    check=False, timeout=5.0,
                )
                print("quit signal sent")
            except Exception as e:
                print(f"failed: {e}")
        else:
            print("(--kill is only implemented for macOS in this CLI; use the BTS UI)")
    else:
        ap.print_help()
