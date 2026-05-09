"""Automated per-TYPE BTS-screenshot resweep via SysEx writes only.

Assumes BTS is open and connected to the GX-10. For each effect TYPE
0x00..0x52:
  1. SysEx: set FxItem #0 TYPE byte (0x10001100)
  2. SysEx: set Param 1 (sub-type) to 0
  3. Wait for BTS to redraw
  4. Screenshot slot-0 knob area → "<idx>_<name>_default.png"
  5. SysEx: write distinctive values 1, 2, 3, ... to consecutive
     param offsets 0x07, 0x0B, 0x0F, … up to ~21 params.
  6. Wait for BTS to redraw
  7. Screenshot → "<idx>_<name>_filled.png"

Snapshots FxItem #0 first, restores at end.

The screenshots become the dataset: each "_filled.png" pairs a
distinctive value with the BTS label sitting next to it, giving a
ground-truth label→address map (since we know which address received
which value). No OCR needed at run-time — visual inspection or
post-hoc OCR works fine.

Usage:
    python tools/bts_resweep_via_sysex.py
"""
from __future__ import annotations
import argparse
import json
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))
from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
import focus_ts
from effect_catalog import PAGE_0, PAGE_1, PAGE_2


FXITEM0_BASE = 0x10001100
SUB_TYPE_ADDR = 0x10001103
# Knob row in BTS, in window-local coords: y=494 (labels) to y=640 (knob
# bottoms); x covers a wide strip across the slot-detail panel.
KNOB_AREA_X = 50
KNOB_AREA_Y = 460
KNOB_AREA_W = 1450
KNOB_AREA_H = 220


def encode_4nibble(display: int) -> bytes:
    raw = (display + 0x8000) & 0xFFFF
    return bytes([(raw >> 12) & 0x0F, (raw >> 8) & 0x0F,
                  (raw >> 4) & 0x0F, raw & 0x0F])


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def screenshot_window(hwnd, out_path: Path, x: int, y: int, w: int, h: int):
    l, t, _, _ = focus_ts.get_window_rect(hwnd)
    bbox = (l + x, t + y, l + x + w, t + y + h)
    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="captures/bts_typebar_resweep")
    ap.add_argument("--start-from", type=lambda x: int(x, 0), default=0x00)
    ap.add_argument("--end-at", type=lambda x: int(x, 0), default=0x52)
    ap.add_argument("--settle-ms", type=int, default=900)
    ap.add_argument("--n-distinctive", type=int, default=12,
                    help="number of consecutive params to write distinctive values to")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build {type_byte: name} map from effect_catalog
    name_by_type: dict[int, str] = {}
    for page in (PAGE_0, PAGE_1, PAGE_2):
        for entry in page:
            # entry is (idx, name, color, x_pos) per effect_catalog.py
            # Use the order to assign successive TYPE bytes…
            pass
    # Actually use typebar_full's per-effect summary triplets
    import glob
    for f in sorted(glob.glob("captures/typebar_full/page*/*/summary.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        triplet = d.get("triplet_at_10001100", "")
        if len(triplet) >= 2:
            name_by_type[int(triplet[:2], 16)] = d.get("name", "?")

    print("focusing BTS window...")
    hwnd = focus_ts.focus_tone_studio()

    # MIDI setup
    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    if out_idx is None or in_idx is None:
        print("ERROR: no GX-10 port"); return 2
    out = midi_send.MidiOut(out_idx)
    sn_log = out_dir / "sniff.jsonl"
    sniffer = midi_sniff.Sniffer(in_idx, sn_log, "GX-10")
    sniffer.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    def silent_emit(obj):
        import json as _j
        obj.setdefault("t", round(sniffer._ts(), 6))
        obj.setdefault("label", sniffer.label)
        sniffer.log_fp.write(_j.dumps(obj, ensure_ascii=False) + "\n")
        if obj.get("kind") == "sysex":
            try: q.put(bytes.fromhex(obj["hex"]))
            except: pass
    sniffer._emit = silent_emit

    def drain(secs=0.05):
        time.sleep(secs); msgs = []
        while not q.empty():
            try: msgs.append(q.get_nowait())
            except: break
        return msgs

    def rq1(addr, size, timeout=1.0):
        drain(0)
        out.send_sysex(midi_send.build_rq1(addr, size))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in drain(0.02):
                p = parse_dt1(m)
                if p and p[0] == addr: return p[1]
        return None

    def dt1(addr, payload):
        out.send_sysex(midi_send.build_dt1(addr, payload))
        time.sleep(0.04)

    try:
        # Snapshot
        print("snapshotting FxItem #0 ...")
        snap = rq1(FXITEM0_BASE, 0x140, 1.5)
        if snap is None:
            print("ERROR: no snapshot"); return 2
        (out_dir / "_emergency_snapshot.bin").write_bytes(snap)
        print(f"  snapshot: {len(snap)} bytes; original TYPE = 0x{snap[0]:02X}")

        # Editor-attach
        dt1(0x7F000001, bytes([0x01]))
        dt1(0x7F000001, bytes([0x01]))

        for t in range(args.start_from, args.end_at + 1):
            name = name_by_type.get(t, f"unk_0x{t:02X}")
            slug = f"{t:02X}_{name}".replace("/", "_").replace(" ", "_")
            print(f"\n=== TYPE 0x{t:02X}: {name} ===")
            # Set TYPE + sub-type
            dt1(FXITEM0_BASE, bytes([t]))
            time.sleep(0.15)
            dt1(SUB_TYPE_ADDR, encode_4nibble(0))
            time.sleep(args.settle_ms / 1000.0)

            # Screenshot 1 — defaults + labels
            try:
                focus_ts.focus_tone_studio()
                time.sleep(0.1)
            except Exception:
                pass
            screenshot_window(hwnd, out_dir / f"{slug}_default.png",
                              KNOB_AREA_X, KNOB_AREA_Y, KNOB_AREA_W, KNOB_AREA_H)

            # Write distinctive values 1..N
            for i in range(args.n_distinctive):
                offset = 0x07 + i * 4   # Param 2..N+1
                if offset >= 0x80:  # past Roland 7-bit byte boundary
                    break
                addr = FXITEM0_BASE + offset
                dt1(addr, encode_4nibble(i + 1))
            time.sleep(args.settle_ms / 1000.0)

            # Screenshot 2 — distinctive values, label↔value mapping visible
            try:
                focus_ts.focus_tone_studio()
                time.sleep(0.1)
            except Exception:
                pass
            screenshot_window(hwnd, out_dir / f"{slug}_filled.png",
                              KNOB_AREA_X, KNOB_AREA_Y, KNOB_AREA_W, KNOB_AREA_H)
            print(f"  saved {slug}_default.png + {slug}_filled.png")

        # Restore
        print("\nrestoring FxItem #0 ...")
        for off in range(min(3, len(snap))):
            dt1(FXITEM0_BASE + off, bytes([snap[off]]))
        for offset in range(0x03, min(len(snap) - 3, 0x7C), 0x04):
            payload = snap[offset:offset + 4]
            if len(payload) != 4 or any(b > 0x7F for b in payload):
                continue
            dt1(FXITEM0_BASE + offset, payload)
        time.sleep(0.2)
        after = rq1(FXITEM0_BASE, 0x140, 1.5)
        if after == snap:
            print("  restore VERIFIED")
        else:
            print("  WARNING: restore mismatch")

        dt1(0x7F000001, bytes([0x00]))
    finally:
        try: sniffer.close()
        except Exception: pass
        try: out.close()
        except Exception: pass

    print(f"\nDONE. Screenshots in {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
