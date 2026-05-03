"""Re-attribute mis-assigned knob addresses using the official MemoryFxItem layout.

The original pipeline (analyze_type_pcap) sometimes assigns master-block
addresses (0x10000F02 BPM, 0x10000F06 KEY) to a knob because those DT1s
leaked into the down-sweep before any FX-item DT1.

Per the official chart, FX Parameter N (1-based) sits at slot_base +
0x03 + (N-1)*4 (4 nibbles each). Empirically, GUI knob 0 corresponds
to FX Parameter 2 (FX Parameter 1 appears unused for most effects).
So:

    predicted_addr = slot_base + 0x07 + knob_idx * 4

(slot 0 base = 0x10001100, slot 1 = 0x10001300, …, stride 0x200.)

This tool only overwrites an address if:
  - The captured address is in the master-block range
    (`0x10000F00..0x10000F3D`), AND
  - The predicted FX-item address differs from the captured one.

It also writes back `address_legacy` to preserve the original.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"

SLOT_BASE = 0x10001100  # slot 0 base


def is_master_block(addr_str: str) -> bool:
    if not addr_str:
        return False
    a = int(addr_str, 16)
    return 0x10000F00 <= a <= 0x10000F3D


def predict_addr(knob_idx: int) -> int:
    return SLOT_BASE + 0x07 + knob_idx * 4


def main():
    """Recompute every base-knob's address from its knob_idx using the
    official MemoryFxItem layout. The original sequence-based attribution
    is unreliable because master-block DT1 events can shift the whole
    address->knob mapping.

    knobs_extra entries are left alone — their addresses came from
    targeted secondary sweeps (per-TYPE, per-SP, per-HARMONY) and
    typically don't have master-block leakage.
    """
    fixed = 0
    effects_touched = 0
    for sp in sorted(TYPEBAR.glob("page*/*/summary.json")):
        s = json.loads(sp.read_text())
        knobs = s.get("knobs", [])
        if not knobs:
            continue
        eff_name = s.get("name", "?")
        any_fix = False
        for k in knobs:
            old = k.get("address")
            knob_idx = k.get("knob_idx", -1)
            if knob_idx < 0:
                continue
            predicted = predict_addr(knob_idx)
            new_addr = f"{predicted:08X}"
            if new_addr != old:
                if "address_legacy" not in k and old:
                    k["address_legacy"] = old
                k["address"] = new_addr
                fixed += 1
                any_fix = True
        if any_fix:
            sp.write_text(json.dumps(s, indent=2, default=list))
            effects_touched += 1
            print(f"  {eff_name:18s}: {sum(1 for k in knobs if k.get('address') != k.get('address_legacy', k.get('address'))):2d}/{len(knobs)} knob addresses re-attributed")
    print(f"\nRe-attributed {fixed} knob addresses across {effects_touched} effects.")


if __name__ == "__main__":
    main()
