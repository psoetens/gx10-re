"""Phase C — variant-conditional knob sweep.

For each effect with a sub-type dropdown, cycle the variant byte
(FxItem offset 0x03) through all documented values and capture the
set of knob labels BTS shows in the editor for each variant. A
knob that appears in only some variants is variant-conditional and
gets `visible_on_variants: [list of indices]` populated.

This covers:
- Variant-invariant effects (most): same labels across all sub-types
  -> nothing to change.
- Variant-conditional knobs (e.g. AMP BRIGHT SW visible only on
  certain amp models, FEEDBACKER OSC-only knobs): populate the new
  schema field.

Sub-effects:
1. Recovers labels for some knobs that didn't surface in Phase B
   probes (the variant byte was at a value that hid them).
2. Generates the canonical visible_on_variants overlay so editor
   clients can hide knobs that don't apply to the current variant.

Output:
  reports/phase_c_variant_sweep.md
  captures/effect_catalog_corrections_phase_c.json
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
OUT_OVERLAY = REPO / "captures/effect_catalog_corrections_phase_c.json"
OUT_REPORT = REPO / "reports/phase_c_variant_sweep.md"
WORKER = Path(__file__).parent / "_phase_c_worker.py"
PER_EFFECT_TIMEOUT_S = 120.0


def parse_addr(s: str) -> int:
    return int(s.replace("0x", "").replace("0X", ""), 16)


def collect_effects_with_variants(catalog: dict) -> dict:
    """Return {tkey: {title, variant_count}} for effects whose first
    dropdown has multiple values (i.e. a sub-type selector)."""
    out = {}
    for tkey, e in catalog.items():
        if tkey.startswith("_"):
            continue
        for d in e.get("dropdowns", []):
            vals = d.get("values") or d.get("values_documented") or []
            if len(vals) >= 2:
                out[tkey] = {
                    "title": e.get("title", "?"),
                    "variant_count": len(vals),
                    "variant_names": list(vals),
                    "dropdown_label": d.get("label", "TYPE"),
                }
                break
    return out


def run_one_effect(t: int, n_variants: int) -> dict:
    job = json.dumps({"t": t, "n_variants": n_variants})
    try:
        proc = subprocess.run(
            [sys.executable, str(WORKER), job],
            capture_output=True, text=True, timeout=PER_EFFECT_TIMEOUT_S,
        )
        diag = REPO / f"captures/bts_lifecycle/phasec_TYPE0x{t:02X}.txt"
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


def labels_look_right(captured_labels: set, expected_labels: set,
                      min_overlap: int = 2) -> bool:
    """Heuristic: BTS panel is synced to the effect iff the captured
    label set shares at least `min_overlap` labels with the expected
    set (from the catalog). If they don't overlap, BTS is showing a
    different effect's panel — desynced from device state."""
    if not expected_labels:
        return True  # no expectation, can't verify
    overlap = captured_labels & expected_labels
    return len(overlap) >= min_overlap


def auto_recover_bts():
    """Close BTS via X and relaunch with handshake grace."""
    print("  [recovery] BTS desynced from device — close-via-X + relaunch",
          flush=True)
    lc.close_via_x(timeout=20)
    time.sleep(1)
    lc.launch()
    return lc.wait_for_ready(timeout=30, handshake_grace_s=10, verbose=True)


def main():
    from phase_b_bipolar import snapshot_fxitem0, restore_fxitem0
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_eff = collect_effects_with_variants(catalog)
    total_variants = sum(e["variant_count"] for e in by_eff.values())
    print(f"  variant sweep: {len(by_eff)} effects, "
          f"{total_variants} total variants", flush=True)

    snap_path = REPO / "captures/bts_lifecycle/phasec_snap.bin"
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

        recycle_state = {"effects_since_recycle": 0, "recycle_count": 0,
                         "stuck_log": REPO / "captures/bts_lifecycle/stuck_log.jsonl"}

        try:
            effect_idx = 0
            for tkey, info in by_eff.items():
                effect_idx += 1
                t = parse_addr(tkey)
                title = info["title"]
                nv = info["variant_count"]
                if tkey in findings and "labels_per_variant" in findings[tkey]:
                    print(f"=== {tkey} {title} — skip ({nv} variants) ===",
                          flush=True)
                    continue
                t0 = time.monotonic()
                print(f"\n=== {tkey} {title} — {nv} variants ===",
                      flush=True)

                # Expected labels from catalog: union of knob labels + dropdown labels
                eff = catalog[tkey]
                expected = set()
                for k in eff.get("knobs", []):
                    expected.add(k.get("label"))
                for d in eff.get("dropdowns", []):
                    expected.add(d.get("label"))
                expected.discard(None)
                # Strip "1: "/"2: " prefixes for matching
                expected = {l.split(": ", 1)[1] if l and ":" in l[:3] else l
                            for l in expected}

                # Try up to 3 times with auto-recovery on desync
                result = None
                for attempt in range(3):
                    result = run_one_effect(t, nv)
                    if "error" in result:
                        break  # worker failed for another reason
                    # Check sync: at least one variant's labels should
                    # overlap with effect's expected labels
                    lpv = result.get("labels_per_variant", {})
                    captured = set()
                    for labs in lpv.values():
                        captured.update(labs)
                    if labels_look_right(captured, expected, min_overlap=2):
                        if attempt > 0:
                            print(f"  [recovery] synced after attempt "
                                  f"{attempt+1}", flush=True)
                        break
                    # Desynced — recycle BTS
                    print(f"  [recovery] attempt {attempt+1}/3: "
                          f"BTS desync (got {sorted(captured)[:8]}, "
                          f"expected overlap with {sorted(expected)[:8]})",
                          flush=True)
                    if not auto_recover_bts():
                        print("  [recovery] BTS relaunch failed", flush=True)
                        result = {"error": "recovery_failed"}
                        break
                    # Re-snapshot since FxItem 0 state may have changed
                    snapshot_fxitem0(snap_path)

                el = time.monotonic() - t0

                if "error" in result:
                    print(f"  ERROR: {result['error']}  ({el:.2f}s)",
                          flush=True)
                    findings[tkey] = {"title": title,
                                      "error": result["error"]}
                    OUT_OVERLAY.write_text(json.dumps(
                        {"findings": findings}, indent=2),
                        encoding="utf-8")
                    continue

                lpv = result.get("labels_per_variant", {})
                # Variant names also appear as labels (the dropdown
                # shows its currently-selected value); filter those out.
                variant_name_set = set(info["variant_names"])
                # Classify each label
                all_labels = set()
                for v, labs in lpv.items():
                    all_labels.update(labs)
                all_labels -= variant_name_set
                conditional = {}
                universal = []
                for lab in all_labels:
                    visible_in = sorted(int(v) for v, labs in lpv.items()
                                        if lab in labs)
                    if len(visible_in) == nv:
                        universal.append(lab)
                    else:
                        conditional[lab] = visible_in
                findings[tkey] = {
                    "title": title,
                    "variant_count": nv,
                    "variant_names": info["variant_names"],
                    "labels_per_variant": lpv,
                    "universal_labels": sorted(universal),
                    "conditional_labels": conditional,
                    "elapsed_s": round(el, 2),
                }
                print(f"  labels seen: universal={len(universal)} "
                      f"conditional={len(conditional)}  ({el:.2f}s)",
                      flush=True)
                for lab, visible_in in conditional.items():
                    print(f"    {lab}: visible_on_variants={visible_in}",
                          flush=True)
                OUT_OVERLAY.write_text(json.dumps({
                    "_doc": "Phase C variant-conditional sweep",
                    "_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "findings": findings,
                }, indent=2), encoding="utf-8")

                # Preventive recycle disabled: relaunched BTS may load
                # a different patch than the user's test setup, which
                # invalidates our FxItem 0 snapshot. Rely on the user
                # to keep BTS open; if it gets stuck mid-run, partial
                # findings are preserved via incremental save and
                # `--resume` continues from where we left off.
        finally:
            print("\nrestoring FxItem 0 ...", flush=True)
            restore_fxitem0(snap_path)

    # Build a summary report
    lines = [
        "# Phase C variant-conditional sweep",
        "",
        f"Source: live BTS-UIA sweep at {time.strftime('%Y-%m-%d %H:%M')}.",
        f"Effects probed: **{len(findings)}**",
        "",
        "## Variant-conditional knobs",
        "",
        "Each row is `(effect, knob_label, visible_on_variants)`.",
        "",
    ]
    cnd_total = 0
    for tkey, f in findings.items():
        if "conditional_labels" not in f:
            continue
        for lab, vs in f["conditional_labels"].items():
            cnd_total += 1
            names = [f["variant_names"][i] for i in vs
                     if i < len(f["variant_names"])]
            lines.append(f"- `{tkey}` {f['title']}: **{lab}** -> "
                         f"visible_on_variants={vs} ({', '.join(names)})")
    lines.insert(7, f"Total conditional entries: **{cnd_total}**")
    lines.insert(8, "")
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n  conditional entries found: {cnd_total}", flush=True)
    print(f"  wrote {OUT_REPORT}", flush=True)
    print(f"  wrote {OUT_OVERLAY}", flush=True)


if __name__ == "__main__":
    import traceback
    try: main()
    except Exception: traceback.print_exc()
    finally:
        sys.stdout.flush()
        os._exit(0)
