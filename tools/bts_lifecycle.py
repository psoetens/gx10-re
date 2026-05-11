"""BTS lifecycle management for long-running probe sessions.

Replaces the unreliable Stop-Process / taskkill /F dance with graceful
WM_CLOSE on the BTS main window. Per memory bts_force_kill_corrupts_config:
force-kill resets the MIDI-out device selection on disk; the X-button close
preserves config.

Public API:
  - find_bts_window()         -> uiautomation.WindowControl | None
  - close_via_x(timeout=20)   -> bool       (graceful close)
  - wait_for_ready(timeout=25)-> bool       (start + wait for connect)
  - is_responsive(timeout=1)  -> bool       (health probe via RQ1)
  - recycle_if_due(state, N=10) -> None     (preventive recycle every N effects)
  - snapshot_pref() -> dict                 (hash + mtime of every pref file)
  - verify_pref_unchanged(snap) -> bool

State for `recycle_if_due` is a plain dict the caller owns:
  state = {"effects_since_recycle": 0, "recycle_count": 0,
           "stuck_log": Path("captures/bts_lifecycle/stuck_log.jsonl")}
"""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
import queue
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import uiautomation as auto

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


BTS_EXE = r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"
BTS_WINDOW_NAME = "BOSS TONE STUDIO for GX-10"
BTS_PREF_DIR = Path(os.environ["LOCALAPPDATA"]) / "Roland" / "BOSS TONE STUDIO for GX-10" / "pref"
LIFECYCLE_DIR = Path(__file__).parent.parent / "captures" / "bts_lifecycle"

WM_CLOSE = 0x0010

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# ───────────── window discovery ─────────────

def find_bts_window() -> "auto.WindowControl | None":
    """Return the BTS top-level WindowControl, or None if not present."""
    try:
        win = auto.WindowControl(searchDepth=1, Name=BTS_WINDOW_NAME)
        if win.Exists(maxSearchSeconds=1):
            return win
    except Exception:
        pass
    return None


def find_bts_pids() -> list[int]:
    """All running BTS-related PIDs (main exe + msedgewebview2 children)."""
    out = subprocess.run(
        ["powershell", "-NonInteractive", "-Command",
         "Get-Process | Where-Object { $_.ProcessName -like '*BOSS*' "
         "-or $_.ProcessName -like '*TONE*' } | "
         "Select-Object -ExpandProperty Id"],
        capture_output=True, text=True, timeout=10,
    )
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


# ───────────── pref snapshot (corruption detection) ─────────────

def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def snapshot_pref() -> dict:
    """Return {filename: {sha256, size, mtime_ns}} for every pref file.
    Used to confirm graceful close doesn't disturb on-disk config."""
    snap = {}
    if not BTS_PREF_DIR.exists():
        return snap
    for p in sorted(BTS_PREF_DIR.iterdir()):
        if p.is_file():
            try:
                st = p.stat()
                snap[p.name] = {
                    "sha256": _hash_file(p),
                    "size": st.st_size,
                    "mtime_ns": st.st_mtime_ns,
                }
            except Exception:
                pass
    return snap


def verify_pref_unchanged(prev: dict) -> tuple[bool, list[str]]:
    """True iff every file in prev still has the same sha256.
    Returns (ok, list_of_diffs)."""
    cur = snapshot_pref()
    diffs = []
    for name, prev_meta in prev.items():
        if name not in cur:
            diffs.append(f"{name}: deleted")
        elif cur[name]["sha256"] != prev_meta["sha256"]:
            diffs.append(
                f"{name}: sha changed "
                f"({prev_meta['size']} -> {cur[name]['size']} bytes)"
            )
    for name in cur:
        if name not in prev:
            diffs.append(f"{name}: new file")
    return len(diffs) == 0, diffs


# ───────────── close via X ─────────────

def close_via_x(timeout: float = 20.0) -> bool:
    """Send WM_CLOSE to the BTS main window and wait for the process tree
    to exit. Returns True on clean exit, False on timeout.

    Key property (per session memory): this preserves on-disk config,
    unlike taskkill /F which resets MIDI-out device selection."""
    win = find_bts_window()
    if win is None:
        # Already gone, nothing to do.
        return True
    try:
        hwnd = win.NativeWindowHandle
    except Exception:
        return False
    if not hwnd:
        return False

    user32.PostMessageW(wintypes.HWND(hwnd), wintypes.UINT(WM_CLOSE),
                        wintypes.WPARAM(0), wintypes.LPARAM(0))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not find_bts_pids():
            return True
        time.sleep(0.5)
    return False


# ───────────── start + readiness ─────────────

def launch() -> int | None:
    """Spawn BTS and return its PID. Does NOT wait for ready."""
    if find_bts_pids():
        return find_bts_pids()[0]
    proc = subprocess.Popen([BTS_EXE], close_fds=True)
    return proc.pid


def wait_for_ready(timeout: float = 30.0, check_midi: bool = False,
                   handshake_grace_s: float = 10.0,
                   verbose: bool = False) -> bool:
    """Wait until the BTS window appears AND has had time to handshake
    with the GX-10 device.

    Why the handshake_grace: if the caller sends MIDI to the device
    while BTS is still in its startup handshake, BTS can enter a stuck
    state. Empirical safe minimum: 10s after window appearance. The
    user's instruction trumps any optimistic shorter wait.

    With check_midi=True (default False), additionally verify the
    device responds to an RQ1 via subprocess (slower; for diagnostic
    use)."""
    deadline = time.monotonic() + timeout
    win = None
    while time.monotonic() < deadline:
        win = find_bts_window()
        if win is not None:
            break
        if verbose:
            print(f"  [bts] waiting for window ...", flush=True)
        time.sleep(0.5)
    if win is None:
        return False
    if verbose:
        print(f"  [bts] window up; waiting {handshake_grace_s}s for "
              f"BTS-to-device handshake before any MIDI", flush=True)
    # CRITICAL: do NOT send MIDI to the device during this window.
    # BTS does its own handshake with the GX-10 over the same USB-MIDI
    # port. Any traffic from us racing that handshake can leave BTS
    # in a stuck state.
    settled = time.monotonic() + handshake_grace_s
    while time.monotonic() < settled:
        if verbose:
            remaining = settled - time.monotonic()
            print(f"  [bts] handshake grace ... {remaining:.1f}s",
                  flush=True)
        time.sleep(1.0)
    if not check_midi:
        return True
    while time.monotonic() < deadline:
        if is_responsive(timeout=0.6):
            return True
        time.sleep(0.5)
    return False


# ───────────── responsiveness probe ─────────────
#
# `is_responsive` is intentionally implemented as a subprocess so the
# main lifecycle process never holds a WinMM input handle across BTS
# restarts. midiInClose is known to hang on this stack (workaround
# pattern in midi_sniff users is os._exit) — by spawning a one-shot
# child, we get clean port release via process-exit every time.
#
# Callers that already hold their own MIDI handles should NOT use
# this; they should send their own RQ1 + poll their own queue.


def _close_midi() -> None:
    """Compatibility no-op. Earlier versions cached MIDI handles on this
    module; the refactor removes that cache so there's nothing to close.
    Kept so existing callers don't break."""
    return


_RESPONSIVENESS_CHILD = """
import sys, time, queue
sys.path.insert(0, r{tools_dir!r})
import midi_send, midi_sniff
from pathlib import Path

probe_addr = {probe_addr}
probe_size = {probe_size}
timeout = {timeout}

try:
    out_idx, _ = midi_send.find_output_port('GX-10')
    in_idx, _ = midi_sniff.find_port('GX-10')
except Exception as e:
    print('NO_PORT', e)
    sys.exit(2)

out = midi_send.MidiOut(out_idx)
sn = midi_sniff.Sniffer(in_idx, Path(r{log_path!r}), 'GX-10')
sn.open()
q = queue.Queue()
def _emit(o):
    if o.get('kind') == 'sysex':
        try: q.put(bytes.fromhex(o['hex']))
        except Exception: pass
sn._emit = _emit

out.send_sysex(midi_send.build_rq1(probe_addr, probe_size))
deadline = time.monotonic() + timeout
ok = False
while time.monotonic() < deadline:
    try: msg = q.get_nowait()
    except queue.Empty: time.sleep(0.02); continue
    if (len(msg) >= 14 and msg[0] == 0xF0 and msg[-1] == 0xF7
            and msg[8] == 0x12):
        addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
        if addr == probe_addr:
            ok = True; break
print('RESPONSIVE' if ok else 'NO_REPLY')
import os
os._exit(0 if ok else 1)
"""


def is_responsive(timeout: float = 1.0,
                  probe_addr: int = 0x10000F02,
                  probe_size: int = 4) -> bool:
    """Check whether the GX-10 DEVICE responds to RQ1.

    Important: this tests the device, NOT BTS. The GX-10 answers
    SysEx requests over USB-MIDI regardless of whether BTS is open —
    BTS is just a UI on top. So this returning True means "wire path
    to the device works"; it does not mean BTS is up or healthy. For
    BTS UI health, use a UIA-based check (read a panel label).

    Subprocess isolation ensures the WinMM input handle is always
    released cleanly after each check. Default probe is BPM at
    MemoryEfct +0x02 — present on every patch and cheap to read."""
    log = LIFECYCLE_DIR / "responsive_probe.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    code = _RESPONSIVENESS_CHILD.format(
        tools_dir=str(Path(__file__).parent),
        probe_addr=probe_addr,
        probe_size=probe_size,
        timeout=timeout,
        log_path=str(log),
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


# ───────────── recycle policy ─────────────

def _log_stuck(state: dict, reason: str, **extra) -> None:
    log = state.get("stuck_log") or (LIFECYCLE_DIR / "stuck_log.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.time(),
        "reason": reason,
        "effects_since_recycle": state.get("effects_since_recycle", 0),
        "recycle_count": state.get("recycle_count", 0),
        **extra,
    }
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def recycle(state: dict, reason: str = "preventive") -> bool:
    """Close BTS via X, relaunch, wait for ready. Caches state; returns
    True on success."""
    _log_stuck(state, reason)
    # Close MIDI handles before BTS exits to avoid stale port references.
    _close_midi()
    if not close_via_x(timeout=20):
        # Graceful close failed — escalate. Per memory, force-kill is
        # known to corrupt config; log and return False so the caller
        # can decide.
        _log_stuck(state, "close_via_x_timeout")
        return False
    time.sleep(1.0)
    launch()
    ok = wait_for_ready(timeout=25)
    if ok:
        state["effects_since_recycle"] = 0
        state["recycle_count"] = state.get("recycle_count", 0) + 1
    else:
        _log_stuck(state, "wait_for_ready_failed")
    return ok


def recycle_if_due(state: dict, N: int = 10) -> bool:
    """Increment counter; recycle if it reached N. Returns True if a
    recycle happened."""
    state["effects_since_recycle"] = state.get("effects_since_recycle", 0) + 1
    if state["effects_since_recycle"] >= N:
        return recycle(state, reason="preventive")
    return False


def reactive_recycle_if_unhealthy(state: dict) -> bool:
    """Health check + reactive recycle if BTS isn't responsive. Returns
    True if a recycle happened."""
    if not is_responsive(timeout=1.5):
        return recycle(state, reason="reactive_unhealthy")
    return False


# ───────────── BTS UI health check ─────────────


def ui_panel_text_count(timeout_s: float = 2.0) -> int | None:
    """Walk the BTS panel via UIA with a hard timeout. Returns the
    number of TextControl labels found in the standard panel band, or
    None if the walk hung or BTS isn't open. Use this as a fast stuck
    detector — if BTS UI is healthy, the walk completes in well under
    1s and returns ≥1 element. If it returns 0 or None, BTS is stuck
    and a recycle is warranted.

    Subprocess-isolated so a hang in uiautomation doesn't kill the
    caller. The check itself is read-only."""
    code = (
        "import sys, time\n"
        f"sys.path.insert(0, r{str(Path(__file__).parent)!r})\n"
        "import uiautomation_path  # noqa: F401\n"
        "import uiautomation as auto\n"
        f"win = auto.WindowControl(searchDepth=1, Name={BTS_WINDOW_NAME!r})\n"
        "if not win.Exists(maxSearchSeconds=0.5):\n"
        "    print(0, flush=True); sys.exit(0)\n"
        "win_l = win.BoundingRectangle.left\n"
        "win_t = win.BoundingRectangle.top\n"
        "count = 0\n"
        "limit = [3000]\n"
        "def walk(c):\n"
        "    global count\n"
        "    if limit[0] <= 0: return\n"
        "    limit[0] -= 1\n"
        "    try:\n"
        "        if c.ControlTypeName == 'TextControl' and c.Name:\n"
        "            r = c.BoundingRectangle\n"
        "            lx, ly = r.left - win_l, r.top - win_t\n"
        "            if 250 <= lx <= 1450 and 480 <= ly <= 900:\n"
        "                count += 1\n"
        "        for child in c.GetChildren(): walk(child)\n"
        "    except Exception: pass\n"
        "walk(win)\n"
        "print(count, flush=True)\n"
        "sys.stdout.flush()\n"
        "import os; os._exit(0)\n"
    )
    # Bootstrap the python path so uiautomation is importable
    helper_dir = Path(__file__).parent
    bootstrap = helper_dir / "uiautomation_path.py"
    if not bootstrap.exists():
        bootstrap.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path.home() / "
            "'AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages'))\n"
        )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=timeout_s,
        )
        if proc.returncode != 0:
            return None
        return int(proc.stdout.strip() or "0")
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def is_ui_stuck(min_text_elements: int = 1, timeout_s: float = 2.0) -> bool:
    """True iff BTS panel UI is missing or non-responsive. The
    panel-walk subprocess is bounded by `timeout_s`; a hung walk
    returns None and is treated as stuck."""
    n = ui_panel_text_count(timeout_s=timeout_s)
    return n is None or n < min_text_elements


# ───────────── lifecycle session helper ─────────────


class Session:
    """Context manager for any tool that touches BTS. Records whether
    BTS was running on entry, ensures it's running for the body, and
    restores the initial state on exit. Tools should NEVER leave a
    lingering BTS window — it bites later sessions.

    Usage:
        from bts_lifecycle import Session
        with Session() as bts:
            # BTS is guaranteed up here AND has had its handshake
            # grace; safe to send MIDI now
            ...probe stuff...
        # back to whatever state it was when we entered
    """

    def __init__(self, ensure_ready: bool = True, ready_timeout: float = 30.0,
                 handshake_grace_s: float = 10.0, verbose: bool = True):
        self.was_running = False
        self.ensure_ready = ensure_ready
        self.ready_timeout = ready_timeout
        self.handshake_grace_s = handshake_grace_s
        self.verbose = verbose

    def __enter__(self):
        self.was_running = bool(find_bts_pids())
        if self.verbose:
            print(f"  [bts] starting session  (was_running={self.was_running})",
                  flush=True)
        if not self.was_running:
            if self.verbose:
                print("  [bts] launching ...", flush=True)
            launch()
        else:
            # Already running — assume the user has had it open for a
            # while, no need for the full handshake grace. Still wait a
            # little for any in-flight changes to settle.
            self.handshake_grace_s = min(self.handshake_grace_s, 1.0)
        if self.ensure_ready:
            ok = wait_for_ready(
                timeout=self.ready_timeout,
                handshake_grace_s=self.handshake_grace_s,
                verbose=self.verbose,
            )
            if not ok:
                raise RuntimeError("BTS did not become ready in time")
        if self.verbose:
            print("  [bts] session ready", flush=True)
        return self

    def __exit__(self, *_exc):
        if self.verbose:
            print(f"  [bts] exiting session  (restore_close={not self.was_running})",
                  flush=True)
        if not self.was_running and find_bts_pids():
            close_via_x(timeout=20)
        return False  # don't swallow exceptions


if __name__ == "__main__":
    # CLI smoke: print state + run one cycle.
    print(f"BTS PIDs: {find_bts_pids()}")
    print(f"window: {find_bts_window()}")
    print(f"responsive: {is_responsive()}")
    if "--cycle" in sys.argv:
        state: dict = {"effects_since_recycle": 0}
        ok = recycle(state, reason="cli_smoke")
        print(f"cycle ok: {ok}")
    _close_midi()
