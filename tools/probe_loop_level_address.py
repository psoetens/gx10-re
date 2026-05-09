"""Find the LOOP LEVEL knob address for DIV_MIX trio (DIVIDER 0x1D,
SPLITTER 0x1E, MIXER 0x1F) by writing distinct distinctive values to
candidate FxItem offsets and reading BTS UI.

The 3 known dropdowns occupy offsets 0x03/0x07/0x0B. We probe the next
12 stride positions (0x0F..0x3B) by writing 80, 81, 82, ..., 91 to each.
After bulk-write, BTS refreshes; whichever displayed knob value matches
N tells us its offset = 0x0F + (N-80)*4.

Output:
  captures/bts_loop_level_probe/results.json
"""
from __future__ import annotations
import json
import os
import queue
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


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def collect_panel(win, win_l, win_t):
    """Return all visible (lx, ly, name) text elements within the panel band."""
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
    return elements


def main():
    out_dir = Path("captures/bts_loop_level_probe")
    out_dir.mkdir(parents=True, exist_ok=True)

    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / "sniff.jsonl"
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

    win = auto.WindowControl(searchDepth=1, Name="BOSS TONE STUDIO for GX-10")
    if not win.Exists(maxSearchSeconds=2):
        print("BTS not found"); os._exit(1)
    win_l = win.BoundingRectangle.left
    win_t = win.BoundingRectangle.top

    out.send_sysex(midi_send.build_rq1(CHAIN_LIST_BASE, 0x32))
    chain = get(CHAIN_LIST_BASE, 0.5)
    if chain is None or chain[0] == 0:
        print("no effect in slot 0"); os._exit(1)
    head_fx = chain[0] - 1
    base = FXITEM_BASE + head_fx * FXITEM_STRIDE

    out.send_sysex(midi_send.build_rq1(base, 0x140))
    snap = get(base, 0.6)
    if snap is None:
        print("no FxItem read"); os._exit(1)
    (out_dir / "snapshot.bin").write_bytes(snap)
    print(f"slot 0 FxItem #{head_fx}, original TYPE 0x{snap[0]:02X}")

    # Bulk-write distinct values to ALL 19 standard FxItem param offsets
    # (0x03, 0x07, ..., 0x4F). Writing to all 19 reliably triggers BTS UI
    # refresh (single-knob writes don't). With distinct values per offset,
    # we can map a displayed value back to its source address.
    candidate_offsets = list(range(0x03, 0x50, 0x04))  # 0x03..0x4F = 19 offsets
    distinctive_values = [70 + i for i in range(len(candidate_offsets))]
    # offset_for_value[v] = offset that received value v
    offset_for_value = dict(zip(distinctive_values, candidate_offsets))

    results = {}
    try:
        for type_byte in (0x1D, 0x1E, 0x1F):
            label = {0x1D: "DIVIDER", 0x1E: "SPLITTER", 0x1F: "MIXER"}[type_byte]
            print(f"\n--- TYPE 0x{type_byte:02X} ({label}) ---")
            # Set TYPE
            dt1(base, bytes([type_byte]))
            time.sleep(0.5)
            # Bulk-write distinctive values
            for off, v in zip(candidate_offsets, distinctive_values):
                dt1(base + off, encode_4nibble(v))
            time.sleep(1.0)

            elements = collect_panel(win, win_l, win_t)
            # Find LOOP LEVEL label (textual) and the value displayed near it
            # Strategy: find label "LOOP LEVEL" then find the closest text
            # element above it that's a candidate value (80..91).
            ll_pos = None
            for lx, ly, name in elements:
                if name.strip().upper() == "LOOP LEVEL":
                    ll_pos = (lx, ly)
                    break
            if ll_pos is None:
                print(f"  LOOP LEVEL label not found in BTS UI panel")
                print(f"  all panel elements:")
                for lx, ly, name in sorted(elements, key=lambda e: (e[1], e[0])):
                    print(f"    ({lx:>4}, {ly:>4}) {name!r}")
                results[f"0x{type_byte:02X}"] = {
                    "label": label, "loop_level_address": None,
                    "reason": "BTS panel did not show LOOP LEVEL label",
                    "elements_seen": [(int(lx), int(ly), n)
                                      for lx, ly, n in elements],
                }
                continue
            print(f"  LOOP LEVEL label at ({ll_pos[0]}, {ll_pos[1]})")
            # Find value text within ~70px above the label and within 50px x-distance
            best = None
            for lx, ly, name in elements:
                if (ll_pos[1] - 90 <= ly <= ll_pos[1] - 20
                        and abs(lx - ll_pos[0]) <= 80):
                    val_str = name.strip()
                    if val_str.isdigit() and int(val_str) in offset_for_value:
                        v = int(val_str)
                        d = abs(ll_pos[1] - ly)
                        if best is None or d < best[2]:
                            best = (v, (lx, ly), d)
            if best is None:
                # Show all candidate elements seen, for diagnostic
                near = [(lx, ly, name) for (lx, ly, name) in elements
                        if (ll_pos[1] - 100 <= ly <= ll_pos[1] - 10
                            and abs(lx - ll_pos[0]) <= 100)]
                print(f"  No matching distinctive value found near LOOP LEVEL.")
                print(f"  nearby texts: {near}")
                results[f"0x{type_byte:02X}"] = {
                    "label": label, "loop_level_address": None,
                    "nearby_texts_seen": [(int(lx), int(ly), n)
                                          for lx, ly, n in near],
                }
                continue
            v = best[0]
            offset = offset_for_value[v]
            addr = FXITEM_BASE + offset
            print(f"  LOOP LEVEL display = {v}  ->  offset 0x{offset:02X}"
                  f"  ->  address 0x{addr:08X}")
            results[f"0x{type_byte:02X}"] = {
                "label": label,
                "loop_level_address": f"0x{addr:08X}",
                "loop_level_offset": f"0x{offset:02X}",
                "distinctive_value_observed": v,
            }

        # Restore
        print("\nrestoring snapshot ...")
        for off in range(min(3, len(snap))):
            dt1(base + off, bytes([snap[off]]))
        for offset in range(0x03, min(len(snap) - 3, 0x7C), 0x04):
            p = snap[offset:offset+4]
            if len(p) != 4 or any(b > 0x7F for b in p): continue
            dt1(base + offset, p)
        time.sleep(0.3)

        out_path = out_dir / "results.json"
        out_path.write_text(json.dumps(results, indent=2))
        print(f"\nresults: {out_path}")
        print(json.dumps(results, indent=2))
    finally:
        try: out.close()
        except Exception: pass
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
