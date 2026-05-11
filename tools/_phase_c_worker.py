"""Phase C worker: for ONE effect, cycle the variant byte 0..N-1
and capture visible knob labels per variant. Bulk-write neutral
ordinals after each variant change so BTS refreshes the panel."""
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


def extract_labels(elements):
    """Pick the knob label rows (y=637..760-ish) plus dropdown labels
    (y=494-ish). Use simple y-band classification."""
    knob_labels = []
    dropdown_labels = []
    for x, y, n in elements:
        # Label rows for knobs cluster around y=637 and y=757
        # (and y=585/705 for values).
        if 480 <= y <= 520:
            dropdown_labels.append(n)
        elif 620 <= y <= 770 and not n.replace('+','').replace('-','').replace('.','').isdigit() \
                and not any(suf in n for suf in ('Hz','kHz','ms','dB','%')):
            # Likely a knob label (text, not a number/unit)
            knob_labels.append(n)
    return knob_labels, dropdown_labels


def label_set_from_elements(elements):
    """Return the union of all visible labels (knob + dropdown) so we
    can build the per-variant visibility map."""
    kl, dl = extract_labels(elements)
    return set(kl) | set(dl)


def main():
    job = json.loads(sys.argv[1])
    t = job['t']
    nv = int(job['n_variants'])

    out_idx, _ = midi_send.find_output_port('GX-10')
    in_idx, _  = midi_sniff.find_port('GX-10')
    out = midi_send.MidiOut(out_idx)
    log = Path('captures/bts_lifecycle/phasec_probe.jsonl')
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
        time.sleep(0.025)

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

    dt1(base, bytes([t]))
    time.sleep(0.5)

    # Bootstrap: bulk-write all 19 offsets RIGHT AFTER the TYPE byte
    # write so BTS commits to the new effect. Without this, BTS may
    # interpret subsequent variant-byte writes against the OLD effect
    # state.
    knob_offsets = list(range(0x03, 0x50, 0x04))
    for i, off in enumerate(knob_offsets):
        dt1(base + off, encode_4nibble(i + 1 if off != 0x03 else 0))
    time.sleep(0.8)

    # Per variant V: write V to variant byte (offset 0x03), then
    # bulk-write all 19 offsets again to force BTS panel refresh.
    labels_per_variant = {}
    iterations = 0
    for V in range(nv):
        dt1(base + 0x03, encode_4nibble(V))
        # Bulk-write the rest with ordinals to trigger refresh
        for i, off in enumerate(knob_offsets):
            if off == 0x03:
                continue
            dt1(base + off, encode_4nibble(i + 1))
        time.sleep(0.6)
        elements = dump_panel()
        labels = sorted(label_set_from_elements(elements))
        labels_per_variant[str(V)] = labels
        iterations += 1

    print("WORKER_RESULT_BEGIN", flush=True)
    print(json.dumps({
        "iterations": iterations,
        "labels_per_variant": labels_per_variant,
    }), flush=True)
    print("WORKER_RESULT_END", flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    import traceback
    try: main()
    except Exception:
        print("WORKER_RESULT_BEGIN", flush=True)
        traceback.print_exc()
        print("WORKER_RESULT_END", flush=True)
        sys.stdout.flush()
        os._exit(3)
