"""Analyze captures/bts_full_sweep/sweep.json — find active knob addresses
per TYPE, cross-reference against typebar_full to name effects.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict


FXITEM0_BASE = 0x10001100


def parse_block(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str)


def find_active_slots(block: bytes, all_blocks: list[bytes]) -> list[tuple[int, str]]:
    """A 4-byte slot is 'active' if its value differs from the all-zeros pattern
    for at least one TYPE. Returns [(offset, payload_hex), ...] for slots
    whose payload is non-zero in this block.
    """
    active = []
    for off in range(0x03, len(block) - 3, 0x04):
        slot = block[off:off + 4]
        # Skip if all zeros (definitely unused)
        if slot == b"\x00\x00\x00\x00":
            continue
        # Skip if it's the "default" 08 00 00 00 marker for an unused slot
        # (some effects pad unused params with 0x80000 = display 0)
        active.append((off, slot.hex()))
    return active


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", default="captures/bts_full_sweep/sweep.json")
    ap.add_argument("--typebar", default="captures/typebar_full")
    ap.add_argument("--out", default="captures/bts_full_sweep/analysis.json")
    args = ap.parse_args()

    sweep_path = Path(args.sweep)
    if sweep_path.exists():
        sweep = json.loads(sweep_path.read_text())
        results = sweep["results"]  # {"0x00": "<block_hex>", ...}
    else:
        # Fallback: read sweep.jsonl (incremental output, written even if main script hung)
        jsonl = sweep_path.parent / "sweep.jsonl"
        if not jsonl.exists():
            print(f"ERROR: neither {sweep_path} nor {jsonl} exists")
            return 2
        results = {}
        for line in jsonl.read_text().splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if "type" not in rec:
                continue
            results[f"0x{rec['type']:02X}"] = rec.get("block")
        print(f"loaded {len(results)} TYPEs from sweep.jsonl (fallback path)")

    # Parse blocks
    blocks: dict[int, bytes] = {}
    for k, v in results.items():
        if v is None:
            continue
        type_byte = int(k, 16)
        blocks[type_byte] = parse_block(v)

    print(f"loaded {len(blocks)} TYPEs from sweep")

    # 1) Group TYPEs by their FX-Param section (bytes 3..end) to find distinct effects
    #    Two TYPEs with the same param layout => same effect category
    by_layout: dict[bytes, list[int]] = defaultdict(list)
    for t, blk in blocks.items():
        # Compare bytes 3+ (skip header which always starts with the TYPE byte)
        layout_key = blk[3:]
        by_layout[layout_key].append(t)

    print(f"distinct param-layouts: {len(by_layout)}")

    # 2) Load typebar_full reference for cross-reference
    typebar_data = []
    typebar_dir = Path(args.typebar)
    if typebar_dir.exists():
        for f in sorted(typebar_dir.glob("page*/*/summary.json")):
            try:
                typebar_data.append(json.loads(f.read_text()))
            except Exception:
                pass
    print(f"typebar_full reference: {len(typebar_data)} effects")

    # Build a map of (first 4 bytes after header) -> typebar effect name
    # The typebar's "triplet_at_10001100" is bytes 0..2; we want a fingerprint
    # that uniquely identifies the effect from our sweep output.
    typebar_by_fingerprint: dict[str, str] = {}
    for fx in typebar_data:
        # The effect's TYPE byte after drag
        triplet = fx.get("triplet_at_10001100", "")
        if not triplet:
            continue
        type_byte_hex = triplet[:2]
        typebar_by_fingerprint[type_byte_hex] = fx.get("name", "?")

    # 3) For each distinct layout, find active param offsets and TYPE bytes
    layouts = []
    for layout_key, types in sorted(by_layout.items(), key=lambda x: -len(x[1])):
        # Pick the first TYPE for this layout to read default values
        rep_type = types[0]
        rep_block = blocks[rep_type]
        # Compute slot fingerprint: list of (offset, payload) where payload != 00000000
        active = find_active_slots(rep_block, list(blocks.values()))
        # Try to identify the effect via first TYPE's 2-hex value
        type_hex = f"{rep_type:02X}"
        effect_name = typebar_by_fingerprint.get(type_hex)
        layouts.append({
            "type_bytes": [f"0x{t:02X}" for t in types],
            "type_count": len(types),
            "rep_type": f"0x{rep_type:02X}",
            "rep_type_dec": rep_type,
            "effect_name": effect_name,
            "block_first_32": rep_block[:32].hex(),
            "active_slots": [
                {
                    "offset": f"0x{off:02X}",
                    "address": f"0x{(FXITEM0_BASE + off):08X}",
                    "param_n": (off - 0x03) // 4 + 1,
                    "payload": payload,
                    "raw_4nibble": int(payload[1] + payload[3] + payload[5] + payload[7], 16) if all(c in "0123456789abcdefABCDEF" for c in payload) else None,
                }
                for off, payload in active
            ],
            "n_active_slots": len(active),
        })

    # 4) Output
    out_data = {
        "n_types_total": 128,
        "n_types_replied": len(blocks),
        "n_distinct_layouts": len(by_layout),
        "layouts": layouts,
    }
    Path(args.out).write_text(json.dumps(out_data, indent=2))
    print(f"\nWrote: {args.out}")

    # 5) Pretty-print
    print(f"\n=== Distinct effect layouts ({len(layouts)}) ===")
    for i, lay in enumerate(layouts):
        name = lay["effect_name"] or "?"
        print(f"\n--- layout #{i:02d}: {name} (TYPE {lay['rep_type']}) ---")
        if lay["type_count"] > 1:
            others = ', '.join(lay['type_bytes'][1:6])
            extra = f" + {lay['type_count']-6} more" if lay['type_count'] > 6 else ""
            print(f"    also matched by TYPEs: {others}{extra}")
        print(f"    active slots ({lay['n_active_slots']}): "
              f"{', '.join(s['address'] for s in lay['active_slots'][:8])}"
              f"{'...' if lay['n_active_slots'] > 8 else ''}")


if __name__ == "__main__":
    main()
