"""Probe the 9 catalog address-gaps with BTS open and FxItem 0 set
to each candidate effect's TYPE.

Architecture: ORCHESTRATOR + PER-EFFECT SUBPROCESS.

The orchestrator (this file's `main`) does NOT hold any MIDI handles
or BTS UIA references. It iterates the gap list and forks a child
python (`_per_effect_worker`) for each effect. Each child opens its
own MIDI ports, does ONE effect's probe, writes a JSON result line
to stdout, and exits — which releases the WinMM input handle via OS
process teardown (the only reliable way around the midiInClose hang).

If a child times out (default 8s per effect), the orchestrator
TerminateProcess's it and forces a BTS recycle via `bts_lifecycle`
before the next effect.

Output:
  reports/address_gaps_audit.md
  captures/effect_catalog_corrections_phase_a.json
"""
from __future__ import annotations
import json
import os
import sys
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bts_lifecycle as lc


REPO = Path(__file__).parent.parent
GAPS_REPORT = REPO / "reports/address_gaps.md"
CATALOG = REPO / "captures/bts_effect_catalog.json"
OUT_REPORT = REPO / "reports/address_gaps_audit.md"
OUT_OVERLAY = REPO / "captures/effect_catalog_corrections_phase_a.json"
PER_EFFECT_TIMEOUT_S = 8.0


# ─────────────── per-effect worker (runs in subprocess) ───────────────

WORKER_CODE = r"""
import json, os, queue, sys, time, subprocess
from pathlib import Path
sys.path.insert(0, r{tools_dir!r})
import midi_send, midi_sniff

CHAIN_LIST_BASE = 0x10000F0C
FXITEM_BASE     = 0x10001100
FXITEM_STRIDE   = 0x200

def encode_4nibble(d):
    raw = (d + 0x8000) & 0xFFFF
    return bytes([(raw>>12)&0xF, (raw>>8)&0xF, (raw>>4)&0xF, raw&0xF])

def parse_dt1(m):
    if len(m)<14 or m[0]!=0xF0 or m[-1]!=0xF7 or m[8]!=0x12: return None
    a=(m[9]<<24)|(m[10]<<16)|(m[11]<<8)|m[12]
    return a, bytes(m[13:-2])


PANEL_DUMP_CODE = '''
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import uiautomation as auto
win = auto.WindowControl(searchDepth=1, Name="BOSS TONE STUDIO for GX-10")
if not win.Exists(maxSearchSeconds=1):
    print(json.dumps({{"error": "no_window"}}), flush=True)
    import os; os._exit(0)
wl, wt = win.BoundingRectangle.left, win.BoundingRectangle.top
els = []
limit = [4000]
def walk(c):
    if limit[0] <= 0: return
    limit[0] -= 1
    try:
        if c.ControlTypeName == "TextControl" and c.Name:
            r = c.BoundingRectangle
            els.append((r.left - wl, r.top - wt, c.Name))
        for ch in c.GetChildren(): walk(ch)
    except Exception: pass
walk(win)
in_band = [(int(x), int(y), str(n)) for x, y, n in els
           if 250 <= x <= 1450 and 480 <= y <= 900]
print(json.dumps({{"elements": in_band}}), flush=True)
import os; os._exit(0)
'''


def dump_panel_via_subprocess(timeout_s=8):
    proc = subprocess.run([sys.executable, '-c', PANEL_DUMP_CODE],
                          capture_output=True, text=True, timeout=timeout_s)
    out = proc.stdout.strip()
    if not out: return []
    try:
        d = json.loads(out.splitlines()[-1])
        return d.get('elements', [])
    except Exception:
        return []


def cluster_rows(elements, y_tol=10):
    if not elements: return []
    elements = sorted(elements, key=lambda e: e[1])
    clusters, cur = [], [elements[0]]
    for el in elements[1:]:
        if el[1]-cur[-1][1] <= y_tol: cur.append(el)
        else:
            clusters.append(sorted(cur, key=lambda e: e[0])); cur=[el]
    clusters.append(sorted(cur, key=lambda e: e[0]))
    clusters.sort(key=lambda c: sum(e[1] for e in c)/len(c))
    return clusters


def collect_pairs_from_elements(elements):
    rows = cluster_rows(elements, 10)
    knob_rows = [r for r in rows
                 if not (480 <= sum(e[1] for e in r)/len(r) <= 520)]
    pairs = []
    used = set()
    for i, vrow in enumerate(knob_rows):
        if i in used: continue
        v_y = sum(e[1] for e in vrow)/len(vrow)
        for j in range(i+1, len(knob_rows)):
            l_y = sum(e[1] for e in knob_rows[j])/len(knob_rows[j])
            d = l_y - v_y
            if 40 <= d <= 65:
                for vx, vy, vn in vrow:
                    lbl = min(knob_rows[j], key=lambda e: abs(e[0]-vx),
                              default=None)
                    if lbl: pairs.append((lbl[2], vn))
                used.add(j); break
            elif d > 65: break
    return pairs


def collect_dropdowns_from_elements(elements):
    # Extract dropdown (label, value) pairs at y=480..520 by x-pairing.
    dd = sorted([e for e in elements if 480 <= e[1] <= 520],
                key=lambda e: e[0])
    pairs, i = [], 0
    while i < len(dd) - 1:
        if dd[i+1][0] - dd[i][0] < 200:
            pairs.append((dd[i][2], dd[i+1][2]))
            i += 2
        else:
            i += 1
    return pairs


def main():
    job = json.loads(sys.argv[1])
    t = job['t']
    missing_offsets = [int(o, 16) for o in job['missing']]

    out_idx, _ = midi_send.find_output_port('GX-10')
    in_idx, _  = midi_sniff.find_port('GX-10')
    out = midi_send.MidiOut(out_idx)
    sn  = midi_sniff.Sniffer(in_idx, Path(r{log_path!r}), 'GX-10')
    sn.open()
    q = queue.Queue()
    def emit(o):
        if o.get('kind')=='sysex':
            try: q.put(bytes.fromhex(o['hex']))
            except Exception: pass
    sn._emit = emit

    def get(addr, timeout=0.5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: m = q.get_nowait()
            except queue.Empty: time.sleep(0.005); continue
            p = parse_dt1(m)
            if p and p[0]==addr: return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.04)

    # Editor-attach handshake — without this, BTS does NOT update the
    # editor panel when we change TYPE byte via SysEx.
    dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.3)

    out.send_sysex(midi_send.build_rq1(CHAIN_LIST_BASE, 0x32))
    chain = get(CHAIN_LIST_BASE, 0.5)
    if chain is None or chain[0]==0:
        print(json.dumps({{'error': 'no_slot0_effect'}})); os._exit(2)
    head_fx = chain[0]-1
    base = FXITEM_BASE + head_fx * FXITEM_STRIDE

    # Set TYPE byte
    dt1(base, bytes([t]))
    time.sleep(0.5)
    # Bulk-write distinct ordinals 1..19 to ALL standard offsets
    knob_offsets = list(range(0x03, 0x50, 0x04))
    for i, off in enumerate(knob_offsets):
        dt1(base + off, encode_4nibble(i + 1))
    time.sleep(1.2)  # generous BTS settle

    # Read panel via NESTED subprocess so UIA isn't called from a
    # process holding WinMM input handle.
    elements = dump_panel_via_subprocess()
    pairs = collect_pairs_from_elements(elements)
    dropdowns = collect_dropdowns_from_elements(elements)

    # For each gap offset, find any label whose value matches the
    # ordinal we wrote there. Check both knob pairs and dropdowns.
    findings = {{}}
    for off in missing_offsets:
        expected = (off - 0x03)//4 + 1
        labels_at = []
        for label, value in pairs:
            try: n = int(str(value).strip().lstrip('+'))
            except (TypeError, ValueError): continue
            if n == expected:
                labels_at.append(label)
        # Dropdowns: ordinal value is the dropdown's INDEX, not its
        # text. We can't directly match; record the dropdown content
        # for diagnostics.
        findings[f'0x{{off:02X}}'] = {{
            'address': f'0x{{FXITEM_BASE + off:08X}}',
            'expected_value': expected,
            'labels_at_this_value': labels_at,
        }}

    print(json.dumps({{
        'panel_elements': len(elements),
        'pairs_found': len(pairs),
        'dropdowns_found': len(dropdowns),
        'pairs': pairs,
        'dropdowns': dropdowns,
        'findings': findings,
    }}))
    os._exit(0)

main()
"""


def parse_addr(s: str) -> int:
    return int(s.replace("0x", "").replace("0X", ""), 16)


def parse_gaps_report() -> list[dict]:
    text = GAPS_REPORT.read_text(encoding="utf-8", errors="replace")
    out = []
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            if cur:
                out.append(cur)
            parts = line[3:].split(" ", 1)
            cur = {"tkey": parts[0], "title": parts[1], "missing": []}
        elif cur and line.startswith("- Missing:"):
            cur["missing"] = [s.strip() for s in line.split(":", 1)[1].split(",")]
    if cur:
        out.append(cur)
    return out


def restore_fxitem_via_subprocess(snap_path: Path) -> None:
    """Restore FxItem 0 from a snapshot bin file via subprocess (so we
    don't hold MIDI handles in the orchestrator)."""
    code = (
        "import sys, time, queue\n"
        f"sys.path.insert(0, r{str(Path(__file__).parent)!r})\n"
        "from pathlib import Path\n"
        "import midi_send, midi_sniff\n"
        f"snap = Path(r{str(snap_path)!r}).read_bytes()\n"
        "out_idx, _ = midi_send.find_output_port('GX-10')\n"
        "in_idx, _  = midi_sniff.find_port('GX-10')\n"
        "out = midi_send.MidiOut(out_idx)\n"
        f"sn = midi_sniff.Sniffer(in_idx, Path(r{str(REPO / 'captures/bts_lifecycle/restore.jsonl')!r}), 'GX-10')\n"
        "sn.open()\n"
        "q = queue.Queue()\n"
        "def emit(o):\n"
        "    if o.get('kind')=='sysex':\n"
        "        try: q.put(bytes.fromhex(o['hex']))\n"
        "        except Exception: pass\n"
        "sn._emit = emit\n"
        "out.send_sysex(midi_send.build_rq1(0x10000F0C, 0x32))\n"
        "deadline = time.monotonic() + 0.5\n"
        "chain = None\n"
        "while time.monotonic() < deadline:\n"
        "    try: m = q.get_nowait()\n"
        "    except queue.Empty: time.sleep(0.005); continue\n"
        "    if len(m)>=14 and m[0]==0xF0 and m[8]==0x12:\n"
        "        a = (m[9]<<24)|(m[10]<<16)|(m[11]<<8)|m[12]\n"
        "        if a == 0x10000F0C:\n"
        "            chain = bytes(m[13:-2]); break\n"
        "if chain is None or chain[0]==0:\n"
        "    print('no_slot0'); import os; os._exit(0)\n"
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
        subprocess.run([sys.executable, "-c", code], timeout=20)
    except subprocess.TimeoutExpired:
        pass


def snapshot_fxitem0_to_file(path: Path) -> tuple[bool, str]:
    """Snapshot the chain-slot-0 FxItem to disk via subprocess. Returns
    (success, stdout) so the caller can see what went wrong."""
    code = (
        "import sys, time, queue\n"
        f"sys.path.insert(0, r{str(Path(__file__).parent)!r})\n"
        "from pathlib import Path\n"
        "import midi_send, midi_sniff\n"
        "out_idx, _ = midi_send.find_output_port('GX-10')\n"
        "in_idx, _  = midi_sniff.find_port('GX-10')\n"
        "out = midi_send.MidiOut(out_idx)\n"
        f"sn = midi_sniff.Sniffer(in_idx, Path(r{str(REPO / 'captures/bts_lifecycle/snap.jsonl')!r}), 'GX-10')\n"
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
        "    if len(m)>=14 and m[0]==0xF0 and m[8]==0x12:\n"
        "        a = (m[9]<<24)|(m[10]<<16)|(m[11]<<8)|m[12]\n"
        "        if a == 0x10000F0C:\n"
        "            chain = bytes(m[13:-2]); break\n"
        "if chain is None:\n"
        "    print('FAIL: no chain DT1 reply', flush=True); import os; os._exit(2)\n"
        "if chain[0]==0:\n"
        "    print(f'FAIL: chain[0]==0 (no effect in slot 0); chain={chain.hex()}', flush=True)\n"
        "    import os; os._exit(2)\n"
        "head_fx = chain[0]-1\n"
        "base = 0x10001100 + head_fx*0x200\n"
        "print(f'chain head_fx={head_fx}, base=0x{base:08X}', flush=True)\n"
        "out.send_sysex(midi_send.build_rq1(base, 0x140))\n"
        "deadline = time.monotonic() + 1.0\n"
        "snap = None\n"
        "while time.monotonic() < deadline:\n"
        "    try: m = q.get_nowait()\n"
        "    except queue.Empty: time.sleep(0.005); continue\n"
        "    if len(m)>=14 and m[0]==0xF0 and m[8]==0x12:\n"
        "        a = (m[9]<<24)|(m[10]<<16)|(m[11]<<8)|m[12]\n"
        "        if a == base:\n"
        "            snap = bytes(m[13:-2]); break\n"
        "if snap is None:\n"
        "    print('FAIL: no FxItem snap', flush=True); import os; os._exit(2)\n"
        f"Path(r{str(path)!r}).write_bytes(snap)\n"
        "print('ok', flush=True)\n"
        "import os; os._exit(0)\n"
    )
    try:
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=15)
        return (proc.returncode == 0 and "ok" in proc.stdout,
                proc.stdout + ("\nSTDERR: " + proc.stderr if proc.stderr else ""))
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"


def run_one_effect(t: int, missing_hex: list[str]) -> dict:
    """Spawn _gap_worker.py to probe one effect. Returns the parsed
    JSON result, or {'error': ...} on failure."""
    worker = Path(__file__).parent / "_gap_worker.py"
    log_path = REPO / "captures/bts_lifecycle/gap_probe.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    job = json.dumps({"t": t, "missing": missing_hex,
                      "log_path": str(log_path)})
    try:
        proc = subprocess.run(
            [sys.executable, str(worker), job],
            capture_output=True, text=True, timeout=PER_EFFECT_TIMEOUT_S,
        )
        diag = REPO / f"captures/bts_lifecycle/worker_TYPE0x{t:02X}.txt"
        diag.write_text(
            f"=== rc={proc.returncode} ===\n"
            f"--- STDOUT ---\n{proc.stdout}\n"
            f"--- STDERR ---\n{proc.stderr}\n",
            encoding="utf-8",
        )
        # Extract the framed result
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


def main():
    gaps = parse_gaps_report()
    print(f"  loaded {len(gaps)} effects with gaps", flush=True)

    snap_path = REPO / "captures/bts_lifecycle/fxitem0_snapshot.bin"
    snap_path.parent.mkdir(parents=True, exist_ok=True)

    findings: dict = {}

    with lc.Session() as _bts:
        # Snapshot FxItem 0 once.
        print("  snapshotting FxItem 0 ...", flush=True)
        ok, snap_log = snapshot_fxitem0_to_file(snap_path)
        if not ok:
            print(f"  ERROR: snapshot failed:\n{snap_log}", flush=True)
            return

        try:
            for gap in gaps:
                tkey = gap["tkey"]
                t = parse_addr(tkey)
                title = gap["title"]
                t_eff = time.monotonic()
                print(f"\n=== {tkey} {title} — missing {gap['missing']} ===",
                      flush=True)

                # No pre-check: subprocess timeout is the safety net.
                result = run_one_effect(t, gap["missing"])
                elapsed = time.monotonic() - t_eff

                if "error" in result:
                    print(f"  ERROR: {result['error']}  ({elapsed:.2f}s)",
                          flush=True)
                    findings[tkey] = {
                        "title": title,
                        "missing_offsets": gap["missing"],
                        "error": result["error"],
                        "elapsed_s": round(elapsed, 2),
                    }
                    if result["error"] == "timeout":
                        # Recycle BTS for next effect
                        print("  forcing recycle after timeout", flush=True)
                        lc.close_via_x(timeout=15)
                        lc.launch()
                        if not lc.wait_for_ready(timeout=25):
                            print("  recycle failed, aborting", flush=True)
                            break
                    continue

                gf = result.get("findings", {})
                n_panel = result.get("panel_elements", 0)
                print(f"  panel_elements={n_panel}  "
                      f"({elapsed:.2f}s)", flush=True)
                for off, info in gf.items():
                    labs = info["labels_at_this_value"]
                    if labs:
                        print(f"    offset {off} (addr {info['address']}, "
                              f"value {info['expected_value']}) -> "
                              f"{labs}", flush=True)
                    else:
                        print(f"    offset {off} (addr {info['address']}, "
                              f"value {info['expected_value']}) -> "
                              f"no label", flush=True)
                findings[tkey] = {
                    "title": title,
                    "missing_offsets": gap["missing"],
                    "panel_elements": n_panel,
                    "gap_findings": gf,
                    "elapsed_s": round(elapsed, 2),
                }
        finally:
            print("\nrestoring FxItem 0 ...", flush=True)
            restore_fxitem_via_subprocess(snap_path)

    # Write reports
    OUT_OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    OUT_OVERLAY.write_text(json.dumps({
        "_doc": "Phase A address-gap audit findings.",
        "_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "findings": findings,
    }, indent=2), encoding="utf-8")

    lines = [
        "# Address-gap audit",
        "",
        f"Source: subprocess-isolated BTS-UIA probe at {time.strftime('%Y-%m-%d %H:%M')}.",
        f"Effects probed: **{len(findings)}**",
        "",
    ]
    for tkey, f in findings.items():
        lines.append(f"## {tkey} {f['title']}")
        lines.append("")
        if "error" in f:
            lines.append(f"_skipped: {f['error']}_")
            lines.append("")
            continue
        for off, gf in f.get("gap_findings", {}).items():
            labs = gf["labels_at_this_value"]
            if labs:
                lines.append(f"- `{gf['address']}` (offset {off}, "
                             f"probed value {gf['expected_value']}): "
                             f"**{' / '.join(labs)}**")
            else:
                lines.append(f"- `{gf['address']}` (offset {off}, "
                             f"probed value {gf['expected_value']}): "
                             f"_no label_")
        lines.append("")
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n  wrote {OUT_REPORT}", flush=True)
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
