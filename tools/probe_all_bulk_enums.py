"""For each effect TYPE 0x00..0x52, run the bulk-write enum probe to
capture full {raw: BTS-display} maps for every knob and dropdown.

Auto-restarts BTS if it gets stuck mid-sweep (dropdown value doesn't
change across iterations).

Output: captures/bts_bulk_enum/all_effects.json
        + per-effect captures/bts_bulk_enum/<TT>_<NAME>_TYPE<TT>.json

Run with BTS open; needs ~1-2 hours to complete all 83 effects.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import queue
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import uiautomation as auto

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


CHAIN_LIST_BASE = 0x10000F0C
FXITEM_BASE = 0x10001100
FXITEM_STRIDE = 0x200
DROPDOWN_Y_BAND = (480, 520)
BTS_EXE = r"C:\Program Files (x86)\BOSS\BOSS TONE STUDIO for GX-10\BOSS TONE STUDIO for GX-10.exe"


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def cluster_rows(elements, y_tol=10):
    if not elements: return []
    elements = sorted(elements, key=lambda e: e[1])
    clusters = []
    cur = [elements[0]]
    for el in elements[1:]:
        if el[1] - cur[-1][1] <= y_tol:
            cur.append(el)
        else:
            clusters.append(sorted(cur, key=lambda e: e[0]))
            cur = [el]
    clusters.append(sorted(cur, key=lambda e: e[0]))
    clusters.sort(key=lambda c: sum(e[1] for e in c) / len(c))
    return clusters


def collect_panel(win, win_l, win_t):
    elements = []
    def walk(ctrl, limit=[5000]):
        if limit[0] <= 0: return
        limit[0] -= 1
        try:
            if ctrl.ControlTypeName == "TextControl":
                name = ctrl.Name
                if name:
                    r = ctrl.BoundingRectangle
                    lx, ly = r.left - win_l, r.top - win_t
                    if 250 <= lx <= 1450 and 480 <= ly <= 900:
                        elements.append((lx, ly, name))
            for child in ctrl.GetChildren():
                walk(child, limit)
        except Exception: pass
    walk(win)

    dd_band = sorted([e for e in elements
                      if DROPDOWN_Y_BAND[0] <= e[1] <= DROPDOWN_Y_BAND[1]],
                     key=lambda e: e[0])
    dropdowns = []
    i = 0
    while i < len(dd_band) - 1:
        if dd_band[i+1][0] - dd_band[i][0] < 200:
            dropdowns.append((dd_band[i][2], dd_band[i+1][2]))
            i += 2
        else:
            i += 1

    knob_elts = [e for e in elements
                 if not (DROPDOWN_Y_BAND[0] <= e[1] <= DROPDOWN_Y_BAND[1])]
    rows = cluster_rows(knob_elts, y_tol=10)
    knobs = []
    used = set()
    for i, vrow in enumerate(rows):
        if i in used: continue
        v_y = sum(e[1] for e in vrow) / len(vrow)
        for j in range(i+1, len(rows)):
            l_y = sum(e[1] for e in rows[j]) / len(rows[j])
            diff = l_y - v_y
            if 35 <= diff <= 95:
                for vx, vy, vn in vrow:
                    lbl = min(rows[j], key=lambda e: abs(e[0]-vx),
                              default=None)
                    if lbl: knobs.append((lbl[2], vn))
                used.add(j)
                break
            elif diff > 95:
                break
    return dropdowns, knobs


def kill_bts():
    subprocess.run(["powershell", "-NonInteractive", "-Command",
                    "Get-Process | Where-Object { $_.ProcessName -like '*BOSS*' "
                    "-or $_.ProcessName -like '*TONE*' "
                    "-or $_.ProcessName -like '*msedgewebview*' } | "
                    "Stop-Process -Force -ErrorAction SilentlyContinue"],
                   capture_output=True, timeout=10)


def launch_bts():
    subprocess.Popen([BTS_EXE], close_fds=True)
    time.sleep(13.0)  # wait for BTS connect


def bts_window():
    win = auto.WindowControl(searchDepth=1, Name="BOSS TONE STUDIO for GX-10")
    if not win.Exists(maxSearchSeconds=3):
        return None, None, None
    return win, win.BoundingRectangle.left, win.BoundingRectangle.top


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type-min", type=lambda x: int(x, 0), default=0x00)
    ap.add_argument("--type-max", type=lambda x: int(x, 0), default=0x52)
    ap.add_argument("--max-raw", type=int, default=15)
    ap.add_argument("--settle-ms", type=int, default=500)
    ap.add_argument("--out", default="captures/bts_bulk_enum")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip TYPEs whose JSON already exists")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / "sweep_sniff.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    sniffer.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    def silent(o):
        if o.get("kind") == "sysex":
            try: q.put(bytes.fromhex(o["hex"]))
            except: pass
    sniffer._emit = silent

    def get(addr, timeout=0.4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: msg = q.get_nowait()
            except queue.Empty: time.sleep(0.005); continue
            p = parse_dt1(msg)
            if p and p[0] == addr: return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.04)

    win, win_l, win_t = bts_window()
    if win is None:
        print("BTS not found — please open it first"); os._exit(1)

    # Catalog for effect names
    catalog_path = Path(__file__).parent.parent / "captures/bts_typebar_resweep_v2/catalog_visual_extraction.json"
    catalog = {}
    if catalog_path.exists():
        try: catalog = json.loads(catalog_path.read_text())
        except Exception: pass

    # Find slot 0's FxItem
    out.send_sysex(midi_send.build_rq1(CHAIN_LIST_BASE, 0x32))
    chain = get(CHAIN_LIST_BASE, 0.5)
    if chain is None or chain[0] == 0:
        print("no effect in slot 0"); os._exit(1)
    head_fx = chain[0] - 1
    base = FXITEM_BASE + head_fx * FXITEM_STRIDE

    # Master snapshot
    out.send_sysex(midi_send.build_rq1(base, 0x140))
    master_snap = get(base, 0.6)
    if master_snap is None:
        print("no FxItem read"); os._exit(1)
    (out_dir / "master_snap.bin").write_bytes(master_snap)

    knob_offsets = list(range(0x03, 0x50, 0x04))  # Param 1..19

    all_results = {}
    bts_restart_count = 0

    for t in range(args.type_min, args.type_max + 1):
        slug = f"{t:02X}_{catalog.get(f'0x{t:02X}', {}).get('title', 'unk').replace(' ', '_').replace('/', '_')}"
        per_path = out_dir / f"{slug}_TYPE{t:02X}.json"
        if args.skip_existing and per_path.exists():
            print(f"  TYPE 0x{t:02X}: skip (existing)")
            try: all_results[f"0x{t:02X}"] = json.loads(per_path.read_text())
            except Exception: pass
            continue

        try:
            # Set TYPE
            dt1(base, bytes([t]))
            time.sleep(args.settle_ms / 1000.0)
            # Initial bulk-write to force BTS refresh
            for offset in knob_offsets:
                dt1(base + offset, encode_4nibble(0))
            time.sleep(args.settle_ms / 1000.0 * 1.5)

            # Verify BTS is showing the right effect (best-effort)
            dropdowns0, knobs0 = collect_panel(win, win_l, win_t)
            print(f"\nTYPE 0x{t:02X} ({catalog.get(f'0x{t:02X}', {}).get('title', '?')}) — "
                  f"{len(knobs0)} knobs, {len(dropdowns0)} dropdowns",
                  flush=True)

            per_knob = {}
            per_dropdown = {}
            for raw_v in range(args.max_raw + 1):
                for offset in knob_offsets:
                    dt1(base + offset, encode_4nibble(raw_v))
                time.sleep(args.settle_ms / 1000.0)
                dd_now, knobs_now = collect_panel(win, win_l, win_t)
                for lab, val in dd_now:
                    per_dropdown.setdefault(lab, {})[raw_v] = val
                for lab, val in knobs_now:
                    per_knob.setdefault(lab, {})[raw_v] = val

            # Detect BTS stuck: if every dropdown only has 1 unique value over
            # all probe iterations, AND we expected sub-types, BTS likely stale.
            stuck = (per_dropdown and
                     all(len(set(v.values())) <= 1 for v in per_dropdown.values())
                     and args.max_raw >= 3)
            if stuck:
                print(f"  STUCK detected — restarting BTS", flush=True)
                # Restore device state first
                for off in range(min(3, len(master_snap))):
                    dt1(base + off, bytes([master_snap[off]]))
                for offset in range(0x03, min(len(master_snap) - 3, 0x7C), 0x04):
                    p = master_snap[offset:offset+4]
                    if len(p) != 4 or any(b > 0x7F for b in p): continue
                    dt1(base + offset, p)
                time.sleep(0.5)
                # Kill + restart BTS
                try: sniffer.close()
                except: pass
                kill_bts()
                time.sleep(2)
                launch_bts()
                bts_restart_count += 1
                # Reopen sniffer
                sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
                sniffer.open()
                sniffer._emit = silent
                # Refresh window
                win, win_l, win_t = bts_window()
                if win is None:
                    print("BTS reopen failed; exiting"); break
                # Skip this TYPE; mark as needs retry
                all_results[f"0x{t:02X}"] = {"stuck": True}
                per_path.write_text(json.dumps(all_results[f"0x{t:02X}"], indent=2))
                continue

            result = {
                "type_byte": f"0x{t:02X}",
                "fxitem_index": head_fx,
                "max_raw_probed": args.max_raw,
                "dropdowns": {
                    lab: {"raw_to_display": {str(k): v for k, v in vals.items()}}
                    for lab, vals in per_dropdown.items()
                },
                "knobs": {
                    lab: {"raw_to_display": {str(k): v for k, v in vals.items()}}
                    for lab, vals in per_knob.items()
                },
            }
            all_results[f"0x{t:02X}"] = result
            per_path.write_text(json.dumps(result, indent=2))
            (out_dir / "all_effects.json").write_text(json.dumps(all_results, indent=2))
            # Quick log
            for lab, vals in per_dropdown.items():
                u = list(dict.fromkeys(vals.values()))
                print(f"    [DD] {lab}: {len(u)} unique = {u[:6]}", flush=True)
        except Exception as e:
            print(f"  ERROR: {e!r}", flush=True)
            all_results[f"0x{t:02X}"] = {"error": repr(e)}

    # Restore master snapshot
    print(f"\nrestoring master snapshot ...", flush=True)
    for off in range(min(3, len(master_snap))):
        dt1(base + off, bytes([master_snap[off]]))
    for offset in range(0x03, min(len(master_snap) - 3, 0x7C), 0x04):
        p = master_snap[offset:offset+4]
        if len(p) != 4 or any(b > 0x7F for b in p): continue
        dt1(base + offset, p)
    time.sleep(0.5)

    print(f"\nDONE. BTS restarted {bts_restart_count} times.")
    print(f"  results: {out_dir / 'all_effects.json'}")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
