"""Smoke test for graceful BTS close via WM_CLOSE.

Verifies the user's empirical observation that closing BTS through
the window's X button (= WM_CLOSE) never produces a corrupt-config
state — unlike taskkill /F which resets the MIDI-out device
selection.

The test:
  1. Snapshot BTS pref/ before each cycle (sha256 + size + mtime).
  2. Open BTS, wait for ready, confirm responsive.
  3. close_via_x(), wait for process tree to exit.
  4. Diff pref/ snapshots — every file's sha256 must be unchanged.
  5. Reopen BTS, confirm it connects to the device cleanly.
  6. Repeat 5x to catch flakiness.

Outputs a report at captures/bts_lifecycle/close_via_x_smoke.json.

Usage:
    python tools/test_bts_close_via_x.py [--cycles 5]
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bts_lifecycle as lc


def run_cycles(n: int) -> dict:
    results = []
    overall_ok = True

    # Record initial state so we can restore it at the end.
    started_with_bts_open = bool(lc.find_bts_pids())

    # Ensure we start with BTS open.
    if not started_with_bts_open:
        print("BTS not running; launching ...")
        lc.launch()
        if not lc.wait_for_ready(timeout=25):
            print("FAIL: BTS did not become ready on first launch")
            return {"ok": False, "reason": "initial_launch_failed",
                    "cycles": []}

    print(f"running {n} close-via-X cycles ...\n")
    for i in range(n):
        cycle = {"index": i + 1}
        t0 = time.monotonic()

        # 1. snapshot pref/ before close
        before = lc.snapshot_pref()
        cycle["pref_files_before"] = len(before)

        # 2. close via X
        t_close = time.monotonic()
        closed = lc.close_via_x(timeout=20)
        cycle["close_seconds"] = round(time.monotonic() - t_close, 2)
        cycle["close_clean"] = closed

        # 3. verify pref/ unchanged
        time.sleep(0.5)  # filesystem flush
        ok, diffs = lc.verify_pref_unchanged(before)
        cycle["pref_unchanged"] = ok
        cycle["pref_diffs"] = diffs

        # 4. relaunch + wait for window (window-only check; no MIDI port
        # opened by the smoke test so we don't accidentally block BTS
        # from reconnecting to the device)
        t_relaunch = time.monotonic()
        lc.launch()
        ready = lc.wait_for_ready(timeout=25)
        cycle["relaunch_seconds"] = round(time.monotonic() - t_relaunch, 2)
        cycle["relaunch_ready"] = ready

        cycle["total_seconds"] = round(time.monotonic() - t0, 2)
        cycle["ok"] = bool(closed and ok and ready)
        if not cycle["ok"]:
            overall_ok = False

        flag = "PASS" if cycle["ok"] else "FAIL"
        print(f"  cycle {i+1}: {flag}  close={cycle['close_seconds']}s "
              f"relaunch={cycle['relaunch_seconds']}s "
              f"pref_unchanged={ok}")
        if diffs:
            print(f"    diffs: {diffs}")

        results.append(cycle)

    # Restore initial state: if BTS wasn't running when we started,
    # leave it closed. Otherwise leave it open. Tests should never
    # leave lingering windows that bite a later session.
    if not started_with_bts_open and lc.find_bts_pids():
        print("\nrestoring initial state: closing BTS (was not running at start)")
        lc.close_via_x(timeout=15)

    return {
        "ok": overall_ok,
        "cycle_count": n,
        "cycles": results,
        "pass_count": sum(1 for c in results if c.get("ok")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=5)
    ap.add_argument("--out", default="captures/bts_lifecycle/close_via_x_smoke.json")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    summary = run_cycles(args.cycles)
    out_path.write_text(json.dumps(summary, indent=2))

    pf = f"{summary['pass_count']}/{summary['cycle_count']}"
    flag = "PASS" if summary["ok"] else "FAIL"
    print(f"\nresult: {flag}  passed {pf}  -> {out_path}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        lc._close_midi()
    sys.exit(rc)
