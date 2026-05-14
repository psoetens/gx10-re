"""For each TYPE 0x00..0x52: write the TYPE byte to FxItem 0, read
the FX Param cells, check decoded values against the documented
ranges in captures/bts_effect_catalog.json. Saves and restores
FxItem 0 byte-for-byte.

This answers the "98 out-of-range" artifact from
reports/catalog_validation_2026-05-10.md by setting the right TYPE
into the slot before each per-effect range check.

Usage:  python tools/per_type_range_check.py [--out /tmp/per_type.json]
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_io import GxMidi, parse_dt1_payload


ROOT = Path(__file__).parent.parent
EFFECT_CATALOG = ROOT / "captures" / "bts_effect_catalog.json"
FXITEM0_BASE   = 0x10001100
FXITEM0_SIZE   = 0x40   # device limit on FxItem-region RQ1 size


def parse_addr(s: str) -> int:
    s = str(s).replace("0X", "0x").replace("0x", "")
    return int(s, 16)


def decode_4nib(payload: bytes) -> int:
    return ((payload[0] & 0xF) << 12) | ((payload[1] & 0xF) << 8) \
         | ((payload[2] & 0xF) << 4) | (payload[3] & 0xF)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/per_type_range.json")
    args = ap.parse_args()

    catalog = json.loads(EFFECT_CATALOG.read_text())

    g = GxMidi()
    print(f"port: {g.port_name}", file=sys.stderr)

    # Save FxItem 0 via cell-aligned reads. Bulk reads at offset 0x40
    # are silently dropped (device quirk), so we save each cell
    # separately. Header bytes 0x00, 0x01, 0x02 (TYPE, ON/OFF, DupNum)
    # are 1-byte; FX Params from offset 0x03 are 4-nibble cells at
    # stride 4 up to ~offset 0x83 covering all known knobs.
    print("saving FxItem 0 state...", file=sys.stderr)
    saved_header = {}
    for off in (0x00, 0x01, 0x02):
        msg = g.rq1(FXITEM0_BASE + off, 1, timeout=1.0)
        p = parse_dt1_payload(msg) if msg else None
        saved_header[off] = bytes(p) if p else b"\x00"
    saved_cells = {}  # offset -> 4 bytes
    for off in range(0x03, 0x83, 4):
        msg = g.rq1(FXITEM0_BASE + off, 4, timeout=0.5)
        p = parse_dt1_payload(msg) if msg else None
        if p and len(p) >= 4:
            saved_cells[off] = bytes(p[:4])
    saved_type = saved_header[0x00][0] if saved_header[0x00] else 0
    print(f"saved {len(saved_header)} header bytes + {len(saved_cells)} cells, "
          f"original TYPE = 0x{saved_type:02X}", file=sys.stderr)

    results_per_type = {}
    n_in_range_total = 0
    n_out_range_total = 0
    n_no_reply_total = 0
    n_no_doc_range = 0

    for type_hex in sorted(catalog):
        try:
            type_byte = int(type_hex, 16)
        except ValueError:
            continue
        entry = catalog[type_hex]
        knobs = entry.get("knobs", [])
        title = entry.get("title", type_hex)

        # Write TYPE byte to FxItem 0
        g.dt1(FXITEM0_BASE, bytes([type_byte]))
        time.sleep(0.06)
        # Verify write took
        rt = parse_dt1_payload(g.rq1(FXITEM0_BASE, 1, timeout=0.5))
        actual_type = rt[0] if rt else None

        # Read each knob with its own 4-byte RQ1 — the device only
        # responds to cell-aligned starts, not arbitrary 0x40-chunk
        # offsets (offset 0x40 returns no reply, 0x47/0x4B do).
        per_knob = []
        n_in_range = 0
        n_out_range = 0
        n_no_reply = 0
        n_no_doc = 0
        for k in knobs:
            addr = parse_addr(k["address"])
            msg = g.rq1(addr, 4, timeout=0.5)
            cell = parse_dt1_payload(msg) if msg else b""
            if len(cell) < 4:
                n_no_reply += 1
                per_knob.append({
                    "addr_hex": f"0x{addr:08X}",
                    "label": k.get("label", "?"),
                    "status": "no_reply",
                })
                continue
            raw = decode_4nib(cell)
            disp = raw - 0x8000
            doc_min = k.get("value_min_documented")
            doc_max = k.get("value_max_documented")
            if isinstance(doc_min, (int, float)) and isinstance(doc_max, (int, float)):
                if doc_min <= disp <= doc_max:
                    status = "in_range"
                    n_in_range += 1
                else:
                    status = f"out_range[{disp} not in {doc_min}..{doc_max}]"
                    n_out_range += 1
            else:
                status = "no_doc_range"
                n_no_doc += 1
            per_knob.append({
                "addr_hex": f"0x{addr:08X}",
                "label": k.get("label", "?"),
                "cell_hex": cell.hex(),
                "raw": raw,
                "display": disp,
                "doc_min": doc_min,
                "doc_max": doc_max,
                "status": status,
            })

        results_per_type[type_hex] = {
            "title": title,
            "type_byte": type_byte,
            "type_after_write": actual_type,
            "n_knobs": len(knobs),
            "in_range": n_in_range,
            "out_range": n_out_range,
            "no_reply": n_no_reply,
            "no_doc_range": n_no_doc,
            "knobs": per_knob,
        }
        n_in_range_total += n_in_range
        n_out_range_total += n_out_range
        n_no_reply_total += n_no_reply
        n_no_doc_range += n_no_doc

        flag = "✓" if n_out_range == 0 and n_no_reply == 0 else "⚠"
        print(f"  {flag} {type_hex} {title:30s}  "
              f"{n_in_range}/{n_in_range + n_out_range + n_no_reply + n_no_doc} "
              f"in-range  ({n_out_range} out, {n_no_reply} no-reply, "
              f"{n_no_doc} no-doc)",
              file=sys.stderr)

    # Restore FxItem 0 via per-cell writes. Write TYPE FIRST (the
    # device may reset cell defaults when TYPE changes), then write
    # cells/header to overwrite those defaults with saved values.
    print("\nrestoring FxItem 0...", file=sys.stderr)
    # TYPE byte first
    if 0x00 in saved_header:
        g.dt1(FXITEM0_BASE + 0x00, saved_header[0x00])
        time.sleep(0.1)
    # ON/OFF and DupNum
    for off in (0x01, 0x02):
        if off in saved_header:
            g.dt1(FXITEM0_BASE + off, saved_header[off])
            time.sleep(0.02)
    # Then all the FX Param cells
    for off, cell in saved_cells.items():
        g.dt1(FXITEM0_BASE + off, cell)
        time.sleep(0.02)
    rt = parse_dt1_payload(g.rq1(FXITEM0_BASE, 1, timeout=1.0))
    print(f"restored TYPE: 0x{rt[0]:02X}" if rt else "restored TYPE: ?",
          file=sys.stderr)
    g.close()

    # Summary
    total = n_in_range_total + n_out_range_total + n_no_reply_total + n_no_doc_range
    print()
    print("=== summary ===")
    print(f"Total knob checks:    {total}")
    print(f"In documented range:  {n_in_range_total}")
    print(f"Out of doc range:     {n_out_range_total}")
    print(f"No reply:             {n_no_reply_total}")
    print(f"No documented range:  {n_no_doc_range}")
    print()
    in_pct = 100 * n_in_range_total / max(1, n_in_range_total + n_out_range_total)
    print(f"In-range / (in+out): {in_pct:.1f}%")
    print()

    # Effects with any out-of-range
    out_effects = [(k, v) for k, v in results_per_type.items() if v["out_range"]]
    if out_effects:
        print(f"⚠ {len(out_effects)} effects with at least one out-of-range knob:")
        for k, v in out_effects:
            print(f"  {k} {v['title']}: {v['out_range']} out-of-range knob(s)")
    print()

    Path(args.out).write_text(json.dumps(results_per_type, indent=2))
    print(f"Full results: {args.out}")


if __name__ == "__main__":
    main()
