"""Phase B-2 — extend truncated numeric_irregular knob lookup tables.

The original probe sampled raw 0..15, capturing the lower half of
frequency knobs (LOW CUT, HIGH CUT, *-MID FREQ etc.) but missing the
upper half (the doc range extends to 12.5 kHz, the probe stopped at
~630 Hz). Linux flagged these as `_probe_likely_truncated` (17 knobs
across ~12 effects).

Strategy per effect:
  1. Set FxItem 0 TYPE = T.
  2. For raw N = 16 .. 50 (35 iterations):
     - Bulk-write same value N to all 19 standard offsets so BTS
       refreshes the panel and the targeted knob shows its display
       for value N.
     - Read BTS panel and record (raw N) -> displayed value for each
       truncated knob in this effect.
  3. Stop early once N+2 consecutive samples return the same display
     (indicates we've hit the device's clamp).
  4. Extend the catalog's raw_to_display lookup with the new entries.

Architecture mirrors phase_b_bipolar.py: orchestrator + per-effect
subprocess worker, incremental save.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bts_lifecycle as lc


REPO = Path(__file__).parent.parent
CATALOG = REPO / "captures/bts_effect_catalog.json"
OUT_OVERLAY = REPO / "captures/effect_catalog_corrections_phase_b2.json"
WORKER = Path(__file__).parent / "_phase_b2_worker.py"
PER_EFFECT_TIMEOUT_S = 180.0  # 17 iters × ~5s + UIA ≈ 90-120s; safety margin


def parse_addr(s: str) -> int:
    return int(s.replace("0x", "").replace("0X", ""), 16)


def collect_truncated_knobs(catalog: dict) -> dict:
    out = {}
    for tkey, e in catalog.items():
        if tkey.startswith("_"):
            continue
        trunc = []
        for k in e["knobs"]:
            if not k.get("_probe_likely_truncated"):
                continue
            trunc.append({
                "address": k["address"],
                "label": k["label"],
                "raw_to_display": k.get("raw_to_display", {}),
            })
        if trunc:
            out[tkey] = trunc
    return out


def run_one_effect(t: int, knobs: list[dict]) -> dict:
    job = json.dumps({"t": t, "knobs": knobs})
    try:
        proc = subprocess.run(
            [sys.executable, str(WORKER), job],
            capture_output=True, text=True, timeout=PER_EFFECT_TIMEOUT_S,
        )
        diag = REPO / f"captures/bts_lifecycle/phaseb2_TYPE0x{t:02X}.txt"
        diag.parent.mkdir(parents=True, exist_ok=True)
        diag.write_text(
            f"=== rc={proc.returncode} ===\n"
            f"--- STDOUT ---\n{proc.stdout}\n"
            f"--- STDERR ---\n{proc.stderr}\n",
            encoding="utf-8",
        )
        out = proc.stdout
        b = out.find("WORKER_RESULT_BEGIN")
        e = out.find("WORKER_RESULT_END")
        if b < 0 or e < 0:
            return {"error": "no_result_marker", "rc": proc.returncode,
                    "stderr_tail": proc.stderr[-500:]}
        json_text = out[b + len("WORKER_RESULT_BEGIN"):e].strip()
        try:
            return json.loads(json_text)
        except Exception as ex:
            return {"error": "parse_failed", "exception": str(ex)}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}


def snapshot_and_restore_fns():
    """Reuse Phase B snapshot/restore via inline subprocess."""
    # Just import them by including phase_b_bipolar (it has the same logic).
    sys.path.insert(0, str(Path(__file__).parent))
    from phase_b_bipolar import snapshot_fxitem0, restore_fxitem0
    return snapshot_fxitem0, restore_fxitem0


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    trunc_by_effect = collect_truncated_knobs(catalog)
    n_knobs = sum(len(ks) for ks in trunc_by_effect.values())
    print(f"  truncated lookup tables: {len(trunc_by_effect)} effects, "
          f"{n_knobs} knobs", flush=True)
    if n_knobs == 0:
        return

    snap_path = REPO / "captures/bts_lifecycle/phaseb2_snap.bin"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_fn, restore_fn = snapshot_and_restore_fns()

    findings: dict = {}
    if OUT_OVERLAY.exists():
        try:
            findings = json.loads(OUT_OVERLAY.read_text()).get("findings", {})
            print(f"  resuming ({len(findings)} effects already done)",
                  flush=True)
        except Exception:
            findings = {}

    with lc.Session(verbose=True) as _bts:
        print("  snapshotting FxItem 0 ...", flush=True)
        if not snapshot_fn(snap_path):
            print("  ERROR: snapshot failed", flush=True)
            return

        try:
            for tkey, knobs in trunc_by_effect.items():
                t = parse_addr(tkey)
                title = catalog[tkey].get("title", "?")
                if tkey in findings and "extended_knobs" in findings[tkey]:
                    print(f"=== {tkey} {title} — skip (done) ===", flush=True)
                    continue
                t_eff = time.monotonic()
                print(f"\n=== {tkey} {title} — {len(knobs)} truncated knobs ===",
                      flush=True)

                result = run_one_effect(t, knobs)
                elapsed = time.monotonic() - t_eff

                if "error" in result:
                    print(f"  ERROR: {result['error']}  ({elapsed:.2f}s)",
                          flush=True)
                    findings[tkey] = {"title": title,
                                      "error": result["error"],
                                      "elapsed_s": round(elapsed, 2)}
                    OUT_OVERLAY.write_text(json.dumps(
                        {"findings": findings}, indent=2), encoding="utf-8")
                    continue

                # Print summary
                ek = result.get("extended_knobs", {})
                tot_new = sum(len(v.get("new_entries", {})) for v in ek.values())
                print(f"  iterations={result.get('iterations', 0)}  "
                      f"new entries={tot_new}  ({elapsed:.2f}s)",
                      flush=True)
                for label, info in ek.items():
                    new = info.get("new_entries", {})
                    if new:
                        items = sorted(new.items(), key=lambda x: int(x[0]))
                        sample = ', '.join(f"{r}->{v!r}" for r, v in items[:3])
                        if len(items) > 3:
                            sample += f", ..., {items[-1][0]}->{items[-1][1]!r}"
                        print(f"    {label}: {len(new)} new ({sample})",
                              flush=True)
                findings[tkey] = {
                    "title": title,
                    "extended_knobs": ek,
                    "iterations": result.get("iterations"),
                    "elapsed_s": round(elapsed, 2),
                }
                OUT_OVERLAY.write_text(json.dumps(
                    {"_doc": "Phase B-2 truncated numeric_irregular probe",
                     "_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "findings": findings}, indent=2), encoding="utf-8")
        finally:
            print("\nrestoring FxItem 0 ...", flush=True)
            restore_fn(snap_path)

    n_ext = sum(1 for f in findings.values() for k in f.get("extended_knobs", {}))
    n_new = sum(len(k.get("new_entries", {}))
                for f in findings.values()
                for k in f.get("extended_knobs", {}).values())
    print(f"\n  extended {n_ext} knobs with {n_new} new lookup entries",
          flush=True)
    print(f"  wrote {OUT_OVERLAY}", flush=True)


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        os._exit(0)
