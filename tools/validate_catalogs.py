"""Wire-level existence + range validation of every address in
captures/bts_effect_catalog.json and captures/menu_catalog.json
against a live GX-10. Read-only RQ1; no DT1 writes. Sets the
editor-attach bit at start, restores at end.

For each address:
  - issue RQ1 of the appropriate size
  - mark replied / no-reply
  - decode payload (1-byte raw / 2-nib / 4-nib offset binary)
  - if catalog has numeric range, check the live value falls inside
  - if catalog has enum values, check the live value is one of them

Outputs:
  - stdout: per-region summary + counts
  - JSON file: full per-address result (default: /tmp/validation.json)

Usage:
    python tools/validate_catalogs.py [--out /tmp/validation.json]
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from midi_io_linux import GxMidi, parse_dt1_payload


ROOT = Path(__file__).parent.parent
EFFECT_CATALOG = ROOT / "captures" / "bts_effect_catalog.json"
MENU_CATALOG   = ROOT / "captures" / "menu_catalog.json"


def decode_payload(payload: bytes, size: int) -> int | None:
    """Decode a payload into a single integer.

    For size==4: 4-nibble big-endian (offset binary -> raw before subtracting).
    For size==2: 2-nibble big-endian.
    For size==1: raw byte.
    Other sizes returned as None (caller can inspect raw bytes).
    """
    if not payload:
        return None
    if size == 1 and len(payload) >= 1:
        return payload[0] & 0x7F
    if size == 2 and len(payload) >= 2:
        return ((payload[0] & 0x0F) << 4) | (payload[1] & 0x0F)
    if size == 4 and len(payload) >= 4:
        return ((payload[0] & 0x0F) << 12) | ((payload[1] & 0x0F) << 8) \
             | ((payload[2] & 0x0F) << 4) | (payload[3] & 0x0F)
    return None


def parse_addr(s: str) -> int:
    s = str(s).replace("0X", "0x").replace("0x", "")
    return int(s, 16)


def collect_effect_targets():
    """List of (address, size_bytes, source_label, expected_range_dict).

    For knob_cell entries we use cell_size=4 by default (4-nibble),
    matching the device's documented FX Parameter format.
    """
    cat = json.loads(EFFECT_CATALOG.read_text())
    out = []
    for type_hex, entry in cat.items():
        title = entry.get("title", "?")
        for k in entry.get("knobs", []):
            addr = parse_addr(k["address"])
            # Effect cells are all 4 bytes per the BTS sweep
            size = 4
            label = f"{title}: {k.get('label','?')}"
            expected = {}
            if "value_min_documented" in k:
                expected["doc_min"] = k["value_min_documented"]
            if "value_max_documented" in k:
                expected["doc_max"] = k["value_max_documented"]
            if "raw_min" in k:
                expected["probe_raw_min"] = k["raw_min"]
            if "raw_max" in k:
                expected["probe_raw_max"] = k["raw_max"]
            if k.get("_address_inferred"):
                expected["address_inferred"] = True
            out.append({
                "addr": addr, "size": size, "label": label,
                "source": "effect_catalog", "type_hex": type_hex,
                "expected": expected,
            })
    return out


def collect_menu_targets():
    """Walk menu_catalog.json and pull out every field-with-address."""
    cat = json.loads(MENU_CATALOG.read_text())
    out = []
    for region_name, region in cat.items():
        if not isinstance(region, dict):
            continue
        # Region structure varies; some have "fields", some inline
        fields = region.get("fields", [])
        if not fields and "members" in region:
            fields = region.get("members", [])
        # Fallback: if region itself has nested addressed entries
        if not fields:
            # walk all sub-dicts
            for k, v in region.items():
                if isinstance(v, dict) and "address" in v:
                    fields.append({"label": k, **v})
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict) and "address" in item:
                            fields.append(item)
        for f in fields:
            if not isinstance(f, dict):
                continue
            addr_str = f.get("address") or f.get("addr")
            if not addr_str:
                continue
            try:
                addr = parse_addr(addr_str)
            except (ValueError, TypeError):
                continue
            # Most menu fields are 1 byte; some are 4-byte (Memory Number)
            # or 2-byte. Use the field's size hint if present.
            size = f.get("size_bytes") or f.get("size") or 1
            if isinstance(size, str):
                try:
                    size = int(size)
                except ValueError:
                    size = 1
            label = f.get("label") or f.get("name") or f.get("id") or "?"
            expected = {}
            for k in ("value_min", "value_max", "values", "raw_min", "raw_max"):
                if k in f:
                    expected[k] = f[k]
            out.append({
                "addr": addr, "size": size, "label": label,
                "source": "menu_catalog", "region": region_name,
                "expected": expected,
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/validation.json")
    ap.add_argument("--max-rq1-size", type=int, default=0x40,
                    help="protocol §3.1.2: 0x10001000-0x10003FFF only "
                         "replies for size<=0x40")
    args = ap.parse_args()

    effect_targets = collect_effect_targets()
    menu_targets   = collect_menu_targets()
    all_targets    = effect_targets + menu_targets
    print(f"effect_catalog: {len(effect_targets)} addresses")
    print(f"menu_catalog:   {len(menu_targets)} addresses")
    print(f"total:          {len(all_targets)} RQ1 reads")
    print()

    g = GxMidi()
    print(f"port: {g.port_name}", file=sys.stderr)

    # Set editor-attach so 0x7F0xxxxx and the broadcast channel reply
    g.dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.005)
    g.dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.05)
    g.dt1(0x7F000703, bytes([0x00]))
    time.sleep(0.005)
    g.dt1(0x7F000703, bytes([0x01]))
    time.sleep(0.1)
    g.drain()

    results = []
    n_replied = 0
    n_no_reply = 0
    n_in_range = 0
    n_out_range = 0
    by_source = defaultdict(lambda: {"replied": 0, "no_reply": 0,
                                     "in_range": 0, "out_range": 0,
                                     "no_check": 0})
    by_region = defaultdict(lambda: {"replied": 0, "no_reply": 0})
    no_reply_inferred = []

    start = time.monotonic()
    for i, t in enumerate(all_targets):
        size = min(t["size"], args.max_rq1_size)
        msg = g.rq1(t["addr"], size, timeout=0.3)
        payload = parse_dt1_payload(msg) if msg else b""
        replied = bool(msg) and len(payload) > 0
        decoded = decode_payload(payload, t["size"]) if replied else None

        # If documented range, check
        rng_status = None
        exp = t.get("expected", {})
        if replied and decoded is not None:
            doc_min = exp.get("doc_min", exp.get("value_min"))
            doc_max = exp.get("doc_max", exp.get("value_max"))
            values = exp.get("values")
            if t["source"] == "effect_catalog" and t["size"] == 4 and (
                    isinstance(doc_min, (int, float))
                    and isinstance(doc_max, (int, float))):
                # 4-nibble offset binary: display = raw - 0x8000
                disp = decoded - 0x8000
                if doc_min <= disp <= doc_max:
                    rng_status = "in_range"
                else:
                    rng_status = f"out_range:{disp} not in [{doc_min},{doc_max}]"
            elif isinstance(values, list) and values:
                if decoded < len(values):
                    rng_status = "in_enum"
                else:
                    rng_status = f"out_enum:{decoded} >= {len(values)}"
            elif (isinstance(doc_min, (int, float))
                  and isinstance(doc_max, (int, float))):
                if doc_min <= decoded <= doc_max:
                    rng_status = "in_range"
                else:
                    rng_status = f"out_range:{decoded} not in [{doc_min},{doc_max}]"

        rec = {
            "addr_hex":   f"0x{t['addr']:08X}",
            "size":       t["size"],
            "label":      t["label"],
            "source":     t["source"],
            "replied":    replied,
            "payload_hex": payload.hex() if payload else "",
            "decoded":    decoded,
            "range_status": rng_status,
            "expected":   exp,
        }
        if "type_hex" in t: rec["type_hex"] = t["type_hex"]
        if "region"   in t: rec["region"]   = t["region"]

        results.append(rec)
        src_b = by_source[t["source"]]
        if replied:
            n_replied += 1
            src_b["replied"] += 1
            if rng_status == "in_range" or rng_status == "in_enum":
                n_in_range += 1
                src_b["in_range"] += 1
            elif rng_status and rng_status.startswith("out_"):
                n_out_range += 1
                src_b["out_range"] += 1
            else:
                src_b["no_check"] += 1
        else:
            n_no_reply += 1
            src_b["no_reply"] += 1
            if exp.get("address_inferred"):
                no_reply_inferred.append(t)

        if "region" in t:
            rb = by_region[t["region"]]
            rb["replied" if replied else "no_reply"] += 1

        if (i + 1) % 100 == 0:
            elapsed = time.monotonic() - start
            print(f"  {i+1}/{len(all_targets)} ({elapsed:.1f}s, "
                  f"replied={n_replied}, no_reply={n_no_reply})",
                  file=sys.stderr)

    # Restore handshake
    g.dt1(0x7F000703, bytes([0x00])); time.sleep(0.05)
    g.dt1(0x7F000001, bytes([0x00])); time.sleep(0.05)
    g.close()

    elapsed = time.monotonic() - start
    print()
    print(f"=== validation complete in {elapsed:.1f}s ===")
    print(f"Total reads:      {len(all_targets)}")
    print(f"Replied:          {n_replied} ({100*n_replied/max(1,len(all_targets)):.1f}%)")
    print(f"No reply:         {n_no_reply}")
    print(f"In documented range: {n_in_range}")
    print(f"Out of documented range: {n_out_range}")
    print()
    print("Per source:")
    for src, b in sorted(by_source.items()):
        total = b["replied"] + b["no_reply"]
        print(f"  {src:18s}  {b['replied']}/{total} replied  "
              f"({b['in_range']} in-range, {b['out_range']} out, "
              f"{b['no_check']} no-check)")
    print()
    print("Per menu region:")
    for region, b in sorted(by_region.items()):
        total = b["replied"] + b["no_reply"]
        print(f"  {region:40s}  {b['replied']:4d}/{total} replied")
    print()
    if no_reply_inferred:
        print(f"⚠ {len(no_reply_inferred)} stride-inferred addresses didn't reply:")
        for t in no_reply_inferred[:20]:
            print(f"  0x{t['addr']:08X}  {t['label']}")
        if len(no_reply_inferred) > 20:
            print(f"  ... ({len(no_reply_inferred) - 20} more)")
    else:
        print("✓ All stride-inferred addresses replied")
    print()

    # Out-of-range entries (limited list)
    out_list = [r for r in results if r["range_status"]
                and r["range_status"].startswith("out_")]
    if out_list:
        print(f"⚠ {len(out_list)} out-of-documented-range entries (top 20):")
        for r in out_list[:20]:
            print(f"  0x{r['addr_hex']}  {r['label']}  decoded={r['decoded']}  "
                  f"(expected {r['expected']})  status={r['range_status']}")
    print()

    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"Full results: {args.out}")


if __name__ == "__main__":
    main()
