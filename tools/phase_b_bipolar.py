"""Phase B — extend bipolar knob ranges from the documented spec.

The BTS bulk-enum probe only sampled raw 0..15, missing the negative
half of every bipolar knob (range -N..+N where N>15). The Linux side
flagged these as `_range_inconsistent` (82 knobs across 36 effects).

This tool verifies the bipolar encoding generalizes for each flagged
knob by writing the documented min via `encode_4nibble(min)` and
checking that BTS displays the expected value. If verified, the
catalog's raw_min/raw_max get set to the documented min/max and the
`_range_inconsistent` flag is cleared.

Architecture: orchestrator + per-effect subprocess (same pattern as
probe_gap_addresses.py). The worker writes doc_min to all bipolar
knobs of the effect simultaneously, reads BTS panel, returns
verification results.

Output: captures/effect_catalog_corrections_phase_b.json
        reports/phase_b_bipolar_audit.md
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
OUT_OVERLAY = REPO / "captures/effect_catalog_corrections_phase_b.json"
OUT_REPORT = REPO / "reports/phase_b_bipolar_audit.md"
WORKER = Path(__file__).parent / "_phase_b_worker.py"
PER_EFFECT_TIMEOUT_S = 20.0


def parse_addr(s: str) -> int:
    return int(s.replace("0x", "").replace("0X", ""), 16)


def collect_bipolar_knobs(catalog: dict) -> dict:
    """Return {tkey: [{address, label, doc_min, doc_max, kind}]} for
    every effect that has bipolar knobs flagged _range_inconsistent."""
    out = {}
    for tkey, e in catalog.items():
        if tkey.startswith("_"):
            continue
        biks = []
        for k in e["knobs"]:
            if not k.get("_range_inconsistent"):
                continue
            if not k.get("address"):
                continue
            biks.append({
                "address": k["address"],
                "label": k["label"],
                "doc_min": k.get("value_min_documented"),
                "doc_max": k.get("value_max_documented"),
                "kind": k.get("kind"),
                "unit": k.get("unit", ""),
            })
        if biks:
            out[tkey] = biks
    return out


def run_one_effect(t: int, knobs: list[dict]) -> dict:
    """Spawn _phase_b_worker.py for one effect's bipolar knob set."""
    job = json.dumps({"t": t, "knobs": knobs})
    try:
        proc = subprocess.run(
            [sys.executable, str(WORKER), job],
            capture_output=True, text=True, timeout=PER_EFFECT_TIMEOUT_S,
        )
        diag = REPO / f"captures/bts_lifecycle/phaseb_TYPE0x{t:02X}.txt"
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
            return {"error": "no_result_marker",
                    "rc": proc.returncode,
                    "stdout_tail": out[-500:],
                    "stderr_tail": proc.stderr[-500:]}
        json_text = out[b + len("WORKER_RESULT_BEGIN"):e].strip()
        try:
            return json.loads(json_text)
        except Exception as ex:
            return {"error": "parse_failed",
                    "json_text": json_text[:500],
                    "exception": str(ex)}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}


def snapshot_fxitem0(snap_path: Path) -> bool:
    """Snapshot via subprocess so MIDI handle releases cleanly."""
    code = (
        "import sys, time, queue, json\n"
        f"sys.path.insert(0, r{str(Path(__file__).parent)!r})\n"
        "from pathlib import Path\n"
        "import midi_send, midi_sniff\n"
        "out_idx, _ = midi_send.find_output_port('GX-10')\n"
        "in_idx, _ = midi_sniff.find_port('GX-10')\n"
        "out = midi_send.MidiOut(out_idx)\n"
        f"sn = midi_sniff.Sniffer(in_idx, Path(r{str(REPO / 'captures/bts_lifecycle/phaseb_snap.jsonl')!r}), 'GX-10')\n"
        "sn.open()\n"
        "q = queue.Queue()\n"
        "def emit(o):\n"
        "    if o.get('kind')=='sysex':\n"
        "        try: q.put(bytes.fromhex(o['hex']))\n"
        "        except Exception: pass\n"
        "sn._emit = emit\n"
        "out.send_sysex(midi_send.build_dt1(0x7F000001, bytes([0x01])))\n"
        "time.sleep(0.3)\n"
        "out.send_sysex(midi_send.build_rq1(0x10000F0C, 0x32))\n"
        "deadline = time.monotonic() + 1.0\n"
        "chain = None\n"
        "while time.monotonic() < deadline:\n"
        "    try: m = q.get_nowait()\n"
        "    except queue.Empty: time.sleep(0.005); continue\n"
        "    if len(m)>=14 and m[0]==0xF0 and m[8]==0x12 and (m[9]<<24|m[10]<<16|m[11]<<8|m[12])==0x10000F0C:\n"
        "        chain = bytes(m[13:-2]); break\n"
        "if chain is None or chain[0]==0:\n"
        "    print('NO_SLOT0'); import os; os._exit(2)\n"
        "head_fx = chain[0]-1\n"
        "base = 0x10001100 + head_fx*0x200\n"
        "out.send_sysex(midi_send.build_rq1(base, 0x140))\n"
        "deadline = time.monotonic() + 1.0\n"
        "snap = None\n"
        "while time.monotonic() < deadline:\n"
        "    try: m = q.get_nowait()\n"
        "    except queue.Empty: time.sleep(0.005); continue\n"
        "    if len(m)>=14 and m[0]==0xF0 and m[8]==0x12 and (m[9]<<24|m[10]<<16|m[11]<<8|m[12])==base:\n"
        "        snap = bytes(m[13:-2]); break\n"
        "if snap is None:\n"
        "    print('NO_SNAP'); import os; os._exit(2)\n"
        f"Path(r{str(snap_path)!r}).write_bytes(snap)\n"
        "print('OK', flush=True)\n"
        "import os; os._exit(0)\n"
    )
    try:
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=15)
        return "OK" in proc.stdout
    except subprocess.TimeoutExpired:
        return False


def restore_fxitem0(snap_path: Path) -> None:
    code = (
        "import sys, time, queue\n"
        f"sys.path.insert(0, r{str(Path(__file__).parent)!r})\n"
        "from pathlib import Path\n"
        "import midi_send, midi_sniff\n"
        f"snap = Path(r{str(snap_path)!r}).read_bytes()\n"
        "out_idx, _ = midi_send.find_output_port('GX-10')\n"
        "in_idx, _ = midi_sniff.find_port('GX-10')\n"
        "out = midi_send.MidiOut(out_idx)\n"
        f"sn = midi_sniff.Sniffer(in_idx, Path(r{str(REPO / 'captures/bts_lifecycle/phaseb_restore.jsonl')!r}), 'GX-10')\n"
        "sn.open()\n"
        "q = queue.Queue()\n"
        "def emit(o):\n"
        "    if o.get('kind')=='sysex':\n"
        "        try: q.put(bytes.fromhex(o['hex']))\n"
        "        except Exception: pass\n"
        "sn._emit = emit\n"
        "out.send_sysex(midi_send.build_rq1(0x10000F0C, 0x32))\n"
        "deadline = time.monotonic() + 1.0\n"
        "chain = None\n"
        "while time.monotonic() < deadline:\n"
        "    try: m = q.get_nowait()\n"
        "    except queue.Empty: time.sleep(0.005); continue\n"
        "    if len(m)>=14 and m[0]==0xF0 and m[8]==0x12 and (m[9]<<24|m[10]<<16|m[11]<<8|m[12])==0x10000F0C:\n"
        "        chain = bytes(m[13:-2]); break\n"
        "if chain is None or chain[0]==0:\n"
        "    import os; os._exit(2)\n"
        "head_fx = chain[0]-1\n"
        "base = 0x10001100 + head_fx*0x200\n"
        "for off in range(min(3, len(snap))):\n"
        "    out.send_sysex(midi_send.build_dt1(base+off, bytes([snap[off]])))\n"
        "    time.sleep(0.04)\n"
        "for off in range(0x03, min(len(snap)-3, 0x7C), 0x04):\n"
        "    p = snap[off:off+4]\n"
        "    if len(p)!=4 or any(b>0x7F for b in p): continue\n"
        "    out.send_sysex(midi_send.build_dt1(base+off, p))\n"
        "    time.sleep(0.04)\n"
        "time.sleep(0.3)\n"
        "import os; os._exit(0)\n"
    )
    try:
        subprocess.run([sys.executable, "-c", code], timeout=15)
    except subprocess.TimeoutExpired:
        pass


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    bipolar_by_effect = collect_bipolar_knobs(catalog)
    n_knobs = sum(len(ks) for ks in bipolar_by_effect.values())
    print(f"  bipolar verification: {len(bipolar_by_effect)} effects, "
          f"{n_knobs} knobs", flush=True)

    snap_path = REPO / "captures/bts_lifecycle/phaseb_fxitem0_snap.bin"
    snap_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing findings to support resume.
    findings: dict = {}
    if OUT_OVERLAY.exists():
        try:
            findings = json.loads(OUT_OVERLAY.read_text()).get("findings", {})
            print(f"  resuming from {OUT_OVERLAY} ({len(findings)} effects "
                  f"already done)", flush=True)
        except Exception:
            findings = {}

    verified_count = sum(
        sum(1 for v in f.get("knobs", {}).values() if v.get("verified"))
        for f in findings.values() if "knobs" in f
    )
    failed_count = sum(
        sum(1 for v in f.get("knobs", {}).values() if not v.get("verified"))
        for f in findings.values() if "knobs" in f
    )

    with lc.Session(verbose=True) as _bts:
        print("  snapshotting FxItem 0 ...", flush=True)
        if not snapshot_fxitem0(snap_path):
            print("  ERROR: snapshot failed", flush=True)
            return

        try:
            for tkey, knobs in bipolar_by_effect.items():
                t = parse_addr(tkey)
                title = catalog[tkey].get("title", "?")
                if tkey in findings and "knobs" in findings[tkey]:
                    # Already done, skip
                    print(f"=== {tkey} {title} — skip (already done) ===",
                          flush=True)
                    continue
                t_eff = time.monotonic()
                print(f"\n=== {tkey} {title} — {len(knobs)} bipolar knobs ===",
                      flush=True)

                result = run_one_effect(t, knobs)
                elapsed = time.monotonic() - t_eff

                if "error" in result:
                    print(f"  ERROR: {result['error']}  ({elapsed:.2f}s)",
                          flush=True)
                    findings[tkey] = {
                        "title": title,
                        "error": result["error"],
                        "elapsed_s": round(elapsed, 2),
                    }
                    continue

                verifications = result.get("verifications", [])
                eff_verified = 0
                eff_failed = 0
                per_knob = {}
                for v in verifications:
                    if v["verified"]:
                        eff_verified += 1
                    else:
                        eff_failed += 1
                    per_knob[v["label"]] = v

                verified_count += eff_verified
                failed_count += eff_failed
                print(f"  panel_elements={result.get('panel_elements', 0)}  "
                      f"verified={eff_verified}/{len(knobs)}  "
                      f"({elapsed:.2f}s)", flush=True)
                for v in verifications:
                    if v["verified"]:
                        flag = "OK"
                    else:
                        flag = f"FAIL (got {v.get('displayed', None)!r})"
                    print(f"    {v['label']:<20} doc_min={v['doc_min']} "
                          f"-> {flag}", flush=True)
                findings[tkey] = {
                    "title": title,
                    "knobs": per_knob,
                    "elapsed_s": round(elapsed, 2),
                }
                # Incremental save so partial runs are usable
                OUT_OVERLAY.write_text(json.dumps({
                    "_doc": "Phase B bipolar verification (incremental save).",
                    "_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "findings": findings,
                }, indent=2), encoding="utf-8")
        finally:
            print("\nrestoring FxItem 0 ...", flush=True)
            restore_fxitem0(snap_path)

    # Build corrections overlay
    OUT_OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    OUT_OVERLAY.write_text(json.dumps({
        "_doc": "Phase B bipolar verification: write doc_min to each "
                "bipolar knob flagged _range_inconsistent, check BTS "
                "displays it. Verified knobs become eligible for "
                "raw_min/raw_max = doc_min/doc_max in the catalog.",
        "_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": {
            "effects_audited": len(findings),
            "knobs_verified": verified_count,
            "knobs_failed": failed_count,
        },
        "findings": findings,
    }, indent=2), encoding="utf-8")
    print(f"\nresults: verified={verified_count}, failed={failed_count}",
          flush=True)
    print(f"  wrote {OUT_OVERLAY}", flush=True)


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        print("", flush=True)
        traceback.print_exc()
        sys.stdout.flush()
    finally:
        sys.stdout.flush()
        os._exit(0)
