"""Per-effect Phase B-2 truncated-lookup-table extension worker.

Iterates raw N = 16..50. Per iteration:
  - Bulk-write raw N to all 19 standard FxItem param offsets (forces
    BTS panel refresh and writes N to every offset including the
    truncated knob's offset).
  - Read BTS panel via nested subprocess.
  - Record (raw N, displayed value) for each target knob.

Stops early when 3 consecutive iterations return the same display
(device clamp / saturation).
"""
import json, os, queue, sys, time, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


CHAIN_LIST_BASE = 0x10000F0C
FXITEM_BASE     = 0x10001100
FXITEM_STRIDE   = 0x200


PANEL_DUMP_CODE = '''
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
import uiautomation as auto
win = auto.WindowControl(searchDepth=1, Name="BOSS TONE STUDIO for GX-10")
if not win.Exists(maxSearchSeconds=1):
    print(json.dumps({"error": "no_window"}), flush=True); import os; os._exit(0)
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
print(json.dumps({"elements": in_band}), flush=True)
import os; os._exit(0)
'''


def encode_4nibble(d):
    raw = (d + 0x8000) & 0xFFFF
    return bytes([(raw>>12)&0xF, (raw>>8)&0xF, (raw>>4)&0xF, raw&0xF])


def parse_dt1(m):
    if len(m) < 14 or m[0] != 0xF0 or m[-1] != 0xF7 or m[8] != 0x12:
        return None
    a = (m[9]<<24) | (m[10]<<16) | (m[11]<<8) | m[12]
    return a, bytes(m[13:-2])


def cluster_rows(elements, y_tol=10):
    if not elements: return []
    elements = sorted(elements, key=lambda e: e[1])
    clusters, cur = [], [elements[0]]
    for el in elements[1:]:
        if el[1] - cur[-1][1] <= y_tol: cur.append(el)
        else:
            clusters.append(sorted(cur, key=lambda e: e[0])); cur = [el]
    clusters.append(sorted(cur, key=lambda e: e[0]))
    clusters.sort(key=lambda c: sum(e[1] for e in c)/len(c))
    return clusters


def dump_panel(timeout_s=8):
    proc = subprocess.run([sys.executable, '-c', PANEL_DUMP_CODE],
                          capture_output=True, text=True, timeout=timeout_s)
    out = proc.stdout.strip()
    if not out: return []
    try:
        d = json.loads(out.splitlines()[-1])
        return d.get('elements', [])
    except Exception:
        return []


def collect_pairs(elements):
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


def main():
    job = json.loads(sys.argv[1])
    t = job['t']
    knobs = job['knobs']
    target_labels = [k['label'] for k in knobs]
    target_addresses = [int(k['address'], 16) for k in knobs]
    existing_tables = {k['label']: k.get('raw_to_display', {}) for k in knobs}

    out_idx, _ = midi_send.find_output_port('GX-10')
    in_idx, _  = midi_sniff.find_port('GX-10')
    out = midi_send.MidiOut(out_idx)
    log = Path('captures/bts_lifecycle/phaseb2_probe.jsonl')
    log.parent.mkdir(parents=True, exist_ok=True)
    sn = midi_sniff.Sniffer(in_idx, log, 'GX-10')
    sn.open()
    q = queue.Queue()
    def emit(o):
        if o.get('kind') == 'sysex':
            try: q.put(bytes.fromhex(o['hex']))
            except Exception: pass
    sn._emit = emit

    def get(addr, timeout=0.5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: m = q.get_nowait()
            except queue.Empty: time.sleep(0.005); continue
            p = parse_dt1(m)
            if p and p[0] == addr: return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.02)

    # Editor-attach
    dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.3)

    out.send_sysex(midi_send.build_rq1(CHAIN_LIST_BASE, 0x32))
    chain = get(CHAIN_LIST_BASE, 0.5)
    if chain is None or chain[0] == 0:
        print("WORKER_RESULT_BEGIN", flush=True)
        print(json.dumps({"error": "no_slot0_effect"}), flush=True)
        print("WORKER_RESULT_END", flush=True)
        os._exit(2)
    head_fx = chain[0] - 1
    base = FXITEM_BASE + head_fx * FXITEM_STRIDE

    # Set TYPE byte
    dt1(base, bytes([t]))
    time.sleep(0.5)

    # Iterate raw 16..50. For each, bulk-write same N to all 19 offsets
    # so the panel refreshes uniformly. Record displays per target label.
    knob_offsets = list(range(0x03, 0x50, 0x04))
    new_tables = {lab: {} for lab in target_labels}
    consecutive_same = {lab: 0 for lab in target_labels}
    last_display = {lab: None for lab in target_labels}
    iterations = 0

    # Probe raw 16..40 — covers up to the device max for documented
    # 20Hz..12.5kHz frequency tables (~29 entries) plus FLAT sentinels.
    for N in range(16, 41):
        for off in knob_offsets:
            dt1(base + off, encode_4nibble(N))
        time.sleep(0.5)

        elements = dump_panel()
        pairs = collect_pairs(elements)
        label_to_value = {lab: val for lab, val in pairs}

        iterations += 1
        all_clamped = True
        for lab in target_labels:
            display = label_to_value.get(lab)
            if display is None:
                continue
            new_tables[lab][str(N)] = display
            if display == last_display[lab]:
                consecutive_same[lab] += 1
            else:
                consecutive_same[lab] = 0
                last_display[lab] = display
            if consecutive_same[lab] < 3:
                all_clamped = False
        # Stop if all knobs clamped
        if all_clamped and all(consecutive_same[l] >= 3 for l in target_labels):
            break

    # Build result: only include entries NOT already in existing_tables
    extended = {}
    for lab in target_labels:
        existing = existing_tables[lab]
        new_only = {r: v for r, v in new_tables[lab].items()
                    if r not in existing}
        extended[lab] = {
            "new_entries": new_only,
            "all_probed": new_tables[lab],
        }

    print("WORKER_RESULT_BEGIN", flush=True)
    print(json.dumps({
        "iterations": iterations,
        "panel_elements_last": len(elements),
        "extended_knobs": extended,
    }), flush=True)
    print("WORKER_RESULT_END", flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        print("WORKER_RESULT_BEGIN", flush=True)
        traceback.print_exc()
        print("WORKER_RESULT_END", flush=True)
        sys.stdout.flush()
        os._exit(3)
