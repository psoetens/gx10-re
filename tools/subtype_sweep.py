"""Sub-type knob-order smoke test.

For one effect TYPE, cycle through each documented sub-type and write
distinctive ascending values (1, 2, 3, ...) to the knobs in the
catalog's listed order. The user looks at the device's display and
confirms y/n whether the displayed knob values appear in the same
order — i.e. the catalog's knob list matches the device's UI for this
sub-type.

Sub-types where the user says 'n' get tagged for per-(TYPE, sub-type)
re-capture on the Windows side (where BTS UI gives knob labels).

Usage:
    python tools/subtype_sweep.py --type 0x35              # WAH
    python tools/subtype_sweep.py --type 0x08 --auto       # no prompts
    python tools/subtype_sweep.py --type 0x35 --out /tmp/wah_sweep.json

Output: {type_hex: str, sub_type: int, sub_type_name: str,
         knob_order: [labels...], user_match: bool|null}
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_io import GxMidi, parse_dt1_payload
from encoding import encode_fx_param
from device_id import require_alive_gxmidi


ROOT = Path(__file__).parent.parent
EFFECT_CATALOG = ROOT / "captures" / "bts_effect_catalog.json"
FXITEM0_BASE   = 0x10001100


def parse_addr(s: str) -> int:
    return int(str(s).replace("0X", "0x").replace("0x", ""), 16)


def pick_test_value(knob, ordinal: int) -> tuple[int, str]:
    """Return (raw_value_to_write, expected_display_string) for a knob.

    Strategy: try to write the ordinal directly, but clamp to the knob's
    actual raw range. For numeric knobs with display range that matches
    the raw range (typical), the displayed value equals the raw written.
    For enum/dropdown knobs, the displayed label comes from the
    raw_to_display map.
    """
    kind = knob.get("kind", "numeric")
    raw_max = knob.get("raw_max")
    raw_min = knob.get("raw_min")
    rtd = knob.get("raw_to_display", {})

    target = ordinal
    if isinstance(raw_max, int) and target > raw_max:
        target = raw_max
    if isinstance(raw_min, int) and target < raw_min:
        target = raw_min

    expected = rtd.get(str(target))
    if expected is None:
        # Fall back to the documented display range linearly.
        doc_min = knob.get("value_min_documented")
        doc_max = knob.get("value_max_documented")
        if (kind == "numeric"
                and isinstance(doc_min, (int, float))
                and isinstance(doc_max, (int, float))
                and isinstance(raw_min, int)
                and isinstance(raw_max, int)
                and raw_max > raw_min):
            frac = (target - raw_min) / (raw_max - raw_min)
            disp_val = doc_min + frac * (doc_max - doc_min)
            # Format integers as ints, floats with one decimal
            if abs(disp_val - round(disp_val)) < 0.05:
                expected = str(int(round(disp_val)))
            else:
                expected = f"{disp_val:.1f}"
        else:
            expected = str(target)

    return target, expected


def save_fxitem0(g: GxMidi) -> dict:
    """Save the first ~0x80 bytes of FxItem 0 via per-cell reads."""
    saved = {"header": {}, "cells": {}}
    for off in (0x00, 0x01, 0x02):
        msg = g.rq1(FXITEM0_BASE + off, 1, timeout=1.0)
        p = parse_dt1_payload(msg) if msg else None
        saved["header"][off] = bytes(p) if p else b"\x00"
    for off in range(0x03, 0x83, 4):
        msg = g.rq1(FXITEM0_BASE + off, 4, timeout=0.5)
        p = parse_dt1_payload(msg) if msg else None
        if p and len(p) >= 4:
            saved["cells"][off] = bytes(p[:4])
    return saved


def restore_fxitem0(g: GxMidi, saved: dict) -> None:
    """Restore FxItem 0 from a saved dict (TYPE first, then header
    bytes, then 4-nibble cells)."""
    if 0x00 in saved["header"]:
        g.dt1(FXITEM0_BASE + 0x00, saved["header"][0x00])
        time.sleep(0.1)
    for off in (0x01, 0x02):
        if off in saved["header"]:
            g.dt1(FXITEM0_BASE + off, saved["header"][off])
            time.sleep(0.02)
    for off, cell in saved["cells"].items():
        g.dt1(FXITEM0_BASE + off, cell)
        time.sleep(0.02)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True,
                    help="effect TYPE byte, hex string e.g. 0x35")
    ap.add_argument("--auto", action="store_true",
                    help="don't prompt; tag every entry as 'unknown' "
                         "(useful for Windows-side automation)")
    ap.add_argument("--out", default=None,
                    help="JSON output path (default: /tmp/subtype_sweep_<type>.json)")
    args = ap.parse_args()

    type_hex = args.type.lower()
    if not type_hex.startswith("0x"):
        type_hex = "0x" + type_hex
    type_byte = int(type_hex, 16)
    out_path = Path(args.out or f"/tmp/subtype_sweep_{type_hex}.json")

    catalog = json.loads(EFFECT_CATALOG.read_text())
    # Catalog keys are like "0x35" or "0x08"
    norm = type_hex if type_hex in catalog else f"0x{type_byte:02x}"
    if norm not in catalog:
        norm = f"0x{type_byte:02X}"  # try uppercase hex
    if norm not in catalog:
        sys.exit(f"TYPE {type_hex} not in {EFFECT_CATALOG}")
    entry = catalog[norm]
    title = entry.get("title", norm)
    knobs = entry.get("knobs", [])
    dropdowns = entry.get("dropdowns", [])

    # Find the sub-type dropdown if there is one (its raw range gives
    # us the number of variants). Some effects have no sub-type — for
    # those we still do one pass at sub-type 0 for symmetry.
    sub_type_dropdown = None
    for d in dropdowns:
        # Heuristic: a sub-type selector lives at FxItem offset 0x03
        # (the FX Param 1 cell — offset relative to FxItem base).
        if parse_addr(d["address"]) == FXITEM0_BASE + 0x03:
            sub_type_dropdown = d
            break
    if sub_type_dropdown is None:
        sub_types = [(0, "(no sub-type selector)")]
    else:
        names = sub_type_dropdown.get("values", [])
        max_st = sub_type_dropdown.get("raw_max", len(names) - 1)
        sub_types = [(i, names[i] if i < len(names) else f"#{i}")
                     for i in range(max_st + 1)]

    if not knobs:
        sys.exit(f"TYPE {type_hex} ({title}) has no knobs — nothing to sweep")

    g = GxMidi()
    require_alive_gxmidi(g)
    print(f"port: {g.port_name}", file=sys.stderr)
    print()
    print(f"=== {type_hex} {title} — sub-type sweep ===")
    print(f"  knobs in catalog order ({len(knobs)} total):")
    for i, k in enumerate(knobs, start=1):
        print(f"    {i:2d}. {k['label']:30s} @ {k['address']}  "
              f"(raw {k.get('raw_min','?')}..{k.get('raw_max','?')})")
    print(f"  sub-types ({len(sub_types)} total):")
    for st_i, st_name in sub_types:
        print(f"    {st_i}: {st_name}")
    print()

    print("saving FxItem 0 state...", file=sys.stderr)
    saved = save_fxitem0(g)

    results = []
    try:
        for st_i, st_name in sub_types:
            # Write TYPE byte
            g.dt1(FXITEM0_BASE + 0x00, bytes([type_byte]))
            time.sleep(0.06)
            # Write sub-type (4-nibble offset binary, like all FxItem cells)
            if sub_type_dropdown is not None:
                g.dt1(FXITEM0_BASE + 0x03, encode_fx_param(st_i))
                time.sleep(0.04)
            # Write each knob with a value picked to fit its range.
            # For numeric knobs with display 0..100, the value equals the
            # ordinal. For enum/small-range knobs, we clamp into range
            # and report the expected display value so the user can
            # check by enum-label if needed.
            expected = []
            for i, k in enumerate(knobs, start=1):
                addr = parse_addr(k["address"])
                if addr == FXITEM0_BASE + 0x03:
                    continue
                raw_val, exp_disp = pick_test_value(k, i)
                g.dt1(addr, encode_fx_param(raw_val))
                expected.append({
                    "ordinal": i,
                    "label": k["label"],
                    "address": k["address"],
                    "raw_written": raw_val,
                    "expected_display": exp_disp,
                    "kind": k.get("kind", "numeric"),
                })
                time.sleep(0.02)

            # Show the user what they should see
            print()
            print("-" * 60)
            print(f"  sub-type {st_i}: {st_name}")
            print(f"  device should now display the following knobs in "
                  f"catalog order:")
            for e in expected:
                kind_marker = "" if e["kind"] == "numeric" else f" [{e['kind']}]"
                print(f"    {e['label']:28s}  =  {e['expected_display']:20s}"
                      f"  (raw={e['raw_written']}, {e['address']}){kind_marker}")
            print()

            if args.auto:
                user_match = None
                print("  [--auto] skipping prompt; tagged 'unknown'")
            else:
                while True:
                    ans = input("  match? y / n / s (skip) > ").strip().lower()
                    if ans in ("y", "n", "s"):
                        break
                    print("  please answer y, n, or s")
                user_match = (
                    True  if ans == "y"
                    else False if ans == "n"
                    else None  # 's' = skip
                )
            results.append({
                "type_hex":   type_hex,
                "sub_type":   st_i,
                "sub_type_name": st_name,
                "knob_order": expected,
                "user_match": user_match,
            })
    finally:
        print()
        print("restoring FxItem 0...", file=sys.stderr)
        restore_fxitem0(g, saved)
        rt = parse_dt1_payload(g.rq1(FXITEM0_BASE, 1, timeout=1.0))
        print(f"restored TYPE: 0x{rt[0]:02X}" if rt else "restored TYPE: ?",
              file=sys.stderr)
        g.close()

    # Summary
    print()
    print("=" * 60)
    print(f"summary for {type_hex} {title}")
    n_match    = sum(1 for r in results if r["user_match"] is True)
    n_mismatch = sum(1 for r in results if r["user_match"] is False)
    n_skipped  = sum(1 for r in results if r["user_match"] is None)
    print(f"  matches:    {n_match}")
    print(f"  mismatches: {n_mismatch}  (need per-sub-type re-capture)")
    print(f"  skipped:    {n_skipped}")
    if n_mismatch:
        print()
        print("  mismatches (need Windows-side re-capture):")
        for r in results:
            if r["user_match"] is False:
                print(f"    sub-type {r['sub_type']} ({r['sub_type_name']})")

    out_path.write_text(json.dumps({
        "type_hex": type_hex,
        "title":    title,
        "n_knobs":  len(knobs),
        "n_sub_types": len(sub_types),
        "results":  results,
    }, indent=2))
    print()
    print(f"  results: {out_path}")


if __name__ == "__main__":
    main()
