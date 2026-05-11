"""Phase B-3 — extend truncated enum knob value lists.

8 knobs were probed with fewer raw values than the documented enum
length (e.g. BRIGHT SW probed only 1 value, doc says 2). Probe each
with raw 0..(len(doc)+2) to find the full enum.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bts_lifecycle as lc


REPO = Path(__file__).parent.parent
CATALOG = REPO / "captures/bts_effect_catalog.json"
OUT_OVERLAY = REPO / "captures/effect_catalog_corrections_phase_b3.json"
WORKER = Path(__file__).parent / "_phase_b3_worker.py"
PER_EFFECT_TIMEOUT_S = 60.0


def parse_addr(s: str) -> int:
    return int(s.replace("0x", "").replace("0X", ""), 16)


def collect_truncated_enums(catalog: dict) -> dict:
    out = {}
    for tkey, e in catalog.items():
        if tkey.startswith("_"):
            continue
        ts = []
        for k in e["knobs"]:
            if k.get("kind") != "enum":
                continue
            vp = k.get("values", [])
            vd = k.get("values_documented", [])
            if vd and len(vd) > len(vp):
                ts.append({
                    "address": k["address"],
                    "label": k["label"],
                    "probed_values": vp,
                    "documented_values": vd,
                })
        if ts:
            out[tkey] = ts
    return out


def run_one_effect(t: int, knobs: list[dict]) -> dict:
    job = json.dumps({"t": t, "knobs": knobs})
    try:
        proc = subprocess.run(
            [sys.executable, str(WORKER), job],
            capture_output=True, text=True, timeout=PER_EFFECT_TIMEOUT_S,
        )
        diag = REPO / f"captures/bts_lifecycle/phaseb3_TYPE0x{t:02X}.txt"
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
            return {"error": "no_result_marker"}
        json_text = out[b + len("WORKER_RESULT_BEGIN"):e].strip()
        try:
            return json.loads(json_text)
        except Exception as ex:
            return {"error": "parse_failed", "exception": str(ex)}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}


def main():
    from phase_b_bipolar import snapshot_fxitem0, restore_fxitem0
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_eff = collect_truncated_enums(catalog)
    n_knobs = sum(len(ks) for ks in by_eff.values())
    print(f"  truncated enums: {len(by_eff)} effects, {n_knobs} knobs",
          flush=True)
    if n_knobs == 0:
        return

    snap_path = REPO / "captures/bts_lifecycle/phaseb3_snap.bin"
    snap_path.parent.mkdir(parents=True, exist_ok=True)

    findings: dict = {}
    if OUT_OVERLAY.exists():
        try:
            findings = json.loads(OUT_OVERLAY.read_text()).get("findings", {})
            print(f"  resuming ({len(findings)} effects done)", flush=True)
        except Exception:
            findings = {}

    with lc.Session(verbose=True) as _bts:
        print("  snapshotting FxItem 0 ...", flush=True)
        if not snapshot_fxitem0(snap_path):
            print("  ERROR: snapshot failed"); return
        try:
            for tkey, knobs in by_eff.items():
                t = parse_addr(tkey)
                title = catalog[tkey].get("title", "?")
                if tkey in findings and "results" in findings[tkey]:
                    print(f"=== {tkey} {title} — skip ===", flush=True)
                    continue
                t0 = time.monotonic()
                print(f"\n=== {tkey} {title} — {len(knobs)} knobs ===",
                      flush=True)
                result = run_one_effect(t, knobs)
                el = time.monotonic() - t0
                if "error" in result:
                    print(f"  ERROR: {result['error']}  ({el:.2f}s)",
                          flush=True)
                    findings[tkey] = {"title": title,
                                      "error": result["error"]}
                    OUT_OVERLAY.write_text(json.dumps({"findings": findings},
                        indent=2), encoding="utf-8")
                    continue
                rs = result.get("results", {})
                tot = sum(len(r.get("new_values", [])) for r in rs.values())
                print(f"  iterations={result.get('iterations', 0)}  "
                      f"new values={tot}  ({el:.2f}s)", flush=True)
                for label, r in rs.items():
                    new = r.get("new_values", [])
                    full = r.get("full_values", [])
                    if new:
                        print(f"    {label}: full={full!r}  new={new!r}",
                              flush=True)
                    else:
                        print(f"    {label}: full={full!r}  (no new)",
                              flush=True)
                findings[tkey] = {"title": title, "results": rs,
                                  "elapsed_s": round(el, 2)}
                OUT_OVERLAY.write_text(json.dumps(
                    {"_doc": "Phase B-3 truncated enum probe",
                     "_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "findings": findings}, indent=2),
                    encoding="utf-8")
        finally:
            print("\nrestoring FxItem 0 ...", flush=True)
            restore_fxitem0(snap_path)

    print(f"\n  wrote {OUT_OVERLAY}", flush=True)


if __name__ == "__main__":
    import traceback
    try: main()
    except Exception: traceback.print_exc()
    finally:
        sys.stdout.flush()
        os._exit(0)
