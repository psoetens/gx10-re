"""Model-specific differences between GX-10 and GX-100.

The DT1/RQ1 SysEx framing, the chart's MemoryCommon/MemoryEfct/
MemoryFxItem/MemoryLed layouts, and the per-effect parameter map are
all SHARED between the two models — same addresses, same byte meanings.
What differs is:
  - Which physical pedals/switches exist on the front panel
  - Which bits of MemoryLed.ON_OFF_STATE correspond to which pedal
    (the chart's *3 ON_OFF_STATE_TABLE is GX-100-centric and gets
     BANK DOWN/UP wrong on GX-10 hardware)
  - The user-memory count: GX-100 has 200 user memories (U01-1..U50-4),
    GX-10 has 198 (U01-1..U66-3) plus 2 NIU
  - Which BANK EXTENT MIN/MAX field is authoritative (chart provides
    a separate pair for each model at SystemCommon offsets 0x09/0x0A
    [GX-100] and 0x19/0x1A [GX-10])

NAMING — GX-10 ▼/▲ + C1 vs GX-100 BANK ▼/▲: the GX-10's two
memory-navigation footswitches are silkscreened **▼ / ▲** on the device
(written as DOWN/▼ and UP/▲ in text); one press steps a single memory.
They are NOT the GX-100's **BANK ▼ / BANK ▲** (which carry the "BANK"
prefix and step a whole bank). The GX-10's third front footswitch is
labelled **C1** and is the **CTL 1** control. The arrows occupy the
same wire positions as the GX-100 BANK switches, so the profiles below
key them under the shared source-enum name "BANK DOWN" / "BANK UP"
(matching `tools/source_names.py` and the chart's Function tables) —
but a GX-10-facing UI should render them as **▼ / ▲** (DOWN/UP) and
**C1**. See docs/protocol.md §5.8.

This module exports a `get_profile(device)` helper that returns the
right profile, and a `detect_and_profile()` that does both at once.
"""
from typing import Optional


# ON_OFF_STATE bit -> pedal label
GX100_LED_BITS = {
    0: "(NIU)", 1: "NUM 1", 2: "NUM 2", 3: "NUM 3", 4: "NUM 4",
    5: "BANK DOWN", 6: "BANK UP",
    7: "CTL 1", 8: "CTL 2", 9: "CTL 3", 10: "CTL 4",
    11: "CUR NUM", 12: "EXP 1 SW",
}

# GX-10 mapping verified empirically 2026-05-03. The chart's GX-100
# bits 5/6 (BANK DOWN/UP) read 0 on GX-10; the same physical buttons
# are at bits 18/19 instead. Bits 15, 20, 21, 26 are status/indicator
# LEDs that are always set (not user-pressable).
GX10_LED_BITS = {
    7: "CTL 1", 12: "EXP 1 SW",
    18: "BANK DOWN", 19: "BANK UP",
    15: "(status)", 20: "(status)", 21: "(status)", 26: "(status)",
}

# Pedals physically present on each model (used by readers to filter
# the per-pedal report — Function/Mode bytes exist in MemoryCommon for
# all listed positions on both models, but only the listed pedals on a
# given model are accessible from the hardware).
GX100_PHYSICAL_PEDALS = {
    "NUM 1", "NUM 2", "NUM 3", "NUM 4",
    "BANK DOWN", "BANK UP",
    "CTL 1", "CTL 2", "CTL 3", "CTL 4",      # CTL 2-4 are external jacks
    "EXP 1 SW", "EXP 1", "EXP 2",            # EXP 2 is external jack
    "CUR NUM",
}
GX10_PHYSICAL_PEDALS = {
    "BANK DOWN", "BANK UP", "CTL 1",
    "EXP 1 SW", "EXP 1",
    # Plus one more on-device footswitch (likely MEMORY/MAN-equivalent)
    # — the chart's MemoryCommon Function fields cover them via
    # CUR NUM / Manual Num roles.
    "CUR NUM",
}

PROFILES = {
    "GX-100": {
        "name": "GX-100",
        "led_bits": GX100_LED_BITS,
        "physical_pedals": GX100_PHYSICAL_PEDALS,
        "memory_count": 200,         # U01-1..U50-4
        "preset_count": 100,         # P01-1..P25-4
        "patches_per_bank": 4,       # NUM 1..4 selects within bank
        # In BANK/NUM mode the 4 NUM-row footswitches act as patch-slot
        # indicators 0..3. The one matching (cur_patch % 4) lights blue.
        "bank_num_slot_pedals": ["NUM 1", "NUM 2", "NUM 3", "NUM 4"],
        "bank_extent_min_offset": 0x09,
        "bank_extent_max_offset": 0x0A,
    },
    "GX-10": {
        "name": "GX-10",
        "led_bits": GX10_LED_BITS,
        "physical_pedals": GX10_PHYSICAL_PEDALS,
        "memory_count": 198,         # U01-1..U66-3 (+2 NIU = 200 total slots)
        "preset_count": 100,         # P01-1..P33-3 (+1 NIU = 100 total slots)
        "patches_per_bank": 3,       # 3 patches per bank
        # On GX-10 the 3 hardware footswitches double as bank-slot
        # indicators in BANK/NUM mode: BANK DOWN=slot 0, BANK UP=slot 1,
        # CTL 1=slot 2. The one matching (cur_patch % 3) lights blue.
        "bank_num_slot_pedals": ["BANK DOWN", "BANK UP", "CTL 1"],
        # In MANUAL mode (ControlMode=3) the GX-10's 3 hardware pedals
        # also act as the GX-100's MAN NUM 1/2/3 virtual sources for
        # the assign block. So an Assign with SOURCE=MAN 1 actually
        # drives the GX-10's BANK DOWN pedal.
        "manual_mode_source_aliases": {
            "BANK DOWN": ["BANK DOWN", "MAN 1"],
            "BANK UP":   ["BANK UP",   "MAN 2"],
            "CTL 1":     ["CTL 1",     "MAN 3"],
            "EXP 1 SW":  ["EXP 1 SW",  "MAN 4"],
        },
        "bank_extent_min_offset": 0x19,
        "bank_extent_max_offset": 0x1A,
    },
}


def get_profile(model: str) -> dict:
    """Return the profile dict for `model` ('GX-10' or 'GX-100').
    Falls back to GX-100 (chart-default) on unknown input."""
    if model in PROFILES:
        return PROFILES[model]
    return PROFILES["GX-100"]


def detect_and_profile(port_substr: str = "GX-10") -> tuple:
    """Send Identity Request, parse Identity Reply, return
    (model_name, profile). Returns ('GX-100', PROFILES['GX-100']) as
    a safe default if detection fails (chart is GX-100-default)."""
    # Lazy import so this module stays usable in offline contexts
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from detect_device import detect_device
    except Exception:
        return "GX-100", PROFILES["GX-100"]
    model, _ = detect_device(port_substr=port_substr)
    if model is None:
        return "GX-100", PROFILES["GX-100"]
    return model, get_profile(model)
