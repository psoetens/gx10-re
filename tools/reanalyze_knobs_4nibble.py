"""Re-analyze every captured knob sweep pcap with proper 4-nibble decoding.

The official MIDI Implementation Chart says every FX Parameter is 4
nibbles big-endian, encoding a value in [12768, 52768] which maps to
displayed values [-20000, +20000] (offset binary, V_display = V - 32768).

Our original pipeline used `int(payload[-2:], 16)` which only read the
last byte. This rewrite reads the full 4-byte payload and computes:

    V_raw = b[0]*4096 + b[1]*256 + b[2]*16 + b[3]
    V_display = V_raw - 32768  (offset binary)

For each effect's `summary.json`, we update the `min` / `max` /
`n_dt1_*` fields under `knobs` and `knobs_extra` to use V_raw values.
The per-knob `address` fields remain unchanged.

Usage:  python reanalyze_knobs_4nibble.py
"""
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"


def decode_4nibble(payload: bytes) -> int:
    """Decode 4-byte payload as 4 nibbles big-endian → signed offset value."""
    if len(payload) < 4:
        # Fall back: take whatever bytes there are
        v = 0
        for b in payload:
            v = (v << 4) | (b & 0x0F)
        return v
    return ((payload[0] & 0x0F) << 12) | ((payload[1] & 0x0F) << 8) \
         | ((payload[2] & 0x0F) << 4) | (payload[3] & 0x0F)


def read_dt1_events_for_addr(jsonl_path: Path, target_addr: int):
    """Yield payloads for DT1 events at the given address."""
    if not jsonl_path.exists():
        return
    with jsonl_path.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex" or ev.get("dir") != "host->dev":
                continue
            raw = bytes.fromhex(ev["hex"])
            if len(raw) < 16 or raw[8] != 0x12:
                continue
            addr = int.from_bytes(raw[9:13], "big")
            if addr != target_addr:
                continue
            payload = raw[13:-2]
            yield payload


def update_knob_records(records, eff_dir: Path):
    """For each knob with an address, re-decode its captured min/max
    from the appropriate jsonl files."""
    if not records:
        return 0
    fixed = 0
    # Determine which pcaps to use: knobs_all_up.jsonl + knobs_all_down.jsonl
    # for base sweeps; per-TYPE / per-SP / per-HARMONY-step extras have their
    # own pcaps.
    base_jsonls = [eff_dir / "knobs_all_up.jsonl",
                    eff_dir / "knobs_all_down.jsonl"]
    for r in records:
        addr_str = r.get("address")
        if not addr_str:
            continue
        addr = int(addr_str, 16)
        # Pick the right jsonl — by default scan base + any extras
        jsonls = list(base_jsonls)
        # extras may have associated newknobs_*.jsonl files
        if "first_seen_at_type" in r:
            tv = r["first_seen_at_type"]
            jsonls.extend([eff_dir / f"newknobs_type{tv:02d}_up.jsonl",
                            eff_dir / f"newknobs_type{tv:02d}_down.jsonl"])
        if "first_seen_at_sp_type" in r:
            sv = r["first_seen_at_sp_type"]
            jsonls.extend([eff_dir / f"sp_newknobs_{sv:02d}_up.jsonl",
                            eff_dir / f"sp_newknobs_{sv:02d}_down.jsonl"])
        if "first_seen_at_harmony_step" in r:
            hs = r["first_seen_at_harmony_step"]
            jsonls.extend([eff_dir / f"harm_newknobs_step{hs:02d}_up.jsonl",
                            eff_dir / f"harm_newknobs_step{hs:02d}_down.jsonl"])
        if r.get("first_seen_at") == "2:HARMONY=USER":
            jsonls.extend([eff_dir / "hr2_newknobs_up.jsonl",
                            eff_dir / "hr2_newknobs_down.jsonl"])

        all_vals = []
        for jl in jsonls:
            for payload in read_dt1_events_for_addr(jl, addr):
                v = decode_4nibble(payload)
                all_vals.append(v)
        if not all_vals:
            continue
        # Update the record. Keep raw V values; display = V - 32768
        v_min = min(all_vals)
        v_max = max(all_vals)
        r["min_raw"] = v_min
        r["max_raw"] = v_max
        r["min_display"] = v_min - 32768
        r["max_display"] = v_max - 32768
        r["n_events_total"] = len(all_vals)
        # Keep the legacy "min"/"max" for backward compat but mark that they
        # were last-byte values (incorrect)
        # r["min"] / r["max"] left as-is for legacy
        fixed += 1
    return fixed


def main():
    total = 0
    for sp in sorted(TYPEBAR.glob("page*/*/summary.json")):
        try:
            s = json.loads(sp.read_text())
        except Exception:
            continue
        eff_dir = sp.parent
        f1 = update_knob_records(s.get("knobs", []), eff_dir)
        f2 = update_knob_records(s.get("knobs_extra", []), eff_dir)
        if f1 + f2:
            sp.write_text(json.dumps(s, indent=2, default=list))
            total += f1 + f2
            print(f"  {s.get('name', '?'):18s} updated {f1+f2:3d} knobs "
                  f"({f1} base + {f2} extra)")
    print(f"\nTotal updated: {total} knob records")


if __name__ == "__main__":
    main()
