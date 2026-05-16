"""Example 2: zero out the 4 main-display knobs of the currently
loaded patch.

Each of the 4 physical rotary knobs under the GX-10's main display is
mapped to a parameter on a specific FxItem. The mapping is stored in
MemoryCommon at offsets 0x69..0x7C (see protocol.md §5.10):
  0x69..0x6C  KnobN SettingFxItem  (FxItem storage slot 0..19)
  0x6D..0x7C  KnobN SETTING        (TARGET enum 0..740, 4 nibbles each)

This example reads those mappings, resolves each TARGET to the byte
offset of the controlled parameter inside its FxItem, and writes the
display value 0 (= raw 0x8000 in offset-binary) to all four.

For continuous knobs whose displayed range is e.g. -50..+50, "zero" is
the centre point. For 0..100 ranges, zero is the minimum. For enum-
style knobs (TYPE selectors), zero is the first entry. The chart
guarantees offset-binary FX-Parameter encoding so writing 0x8000 is
safe across all numeric knob types.

Reverts: any patch-button press on the device.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import (
    GX10Session, read_knob_settings, encode_4nib_offset,
    ON_OFF_OFFSET, DUP_NUMBER_OFFSET, FX_PARAM_BASE_OFFSET,
)
from device_id import require_alive


def main():
    sess = GX10Session()
    require_alive(sess)
    knobs = read_knob_settings(sess)
    if not knobs:
        print("ERROR: device did not reply to knob-setting reads")
        sys.exit(2)

    print(f"{'Knob':<5} {'slot':<5} {'target':<7} "
          f"{'category':<22} {'param':<18} {'fx_type':<14} "
          f"{'addr':<12} {'action'}")
    print("-" * 110)

    for k in knobs:
        addr = k["abs_addr"]
        if addr is None:
            note = ("unmapped" if k["target_idx"] == 0
                    else f"can't resolve {k['target_name']!r} on "
                         f"{k['fx_type_name']}")
            print(f"{k['knob']:<5} {k['slot']:<5} {k['target_idx']:<7} "
                  f"{k['target_category']:<22} {k['target_name']:<18} "
                  f"{k['fx_type_name']:<14} {'-':<12} skip ({note})")
            continue

        # Choose payload by parameter kind:
        # - offset 0x01 (generic EFFECT ON/OFF target) is a 1-byte field.
        # - offset 0x02 (DuplicationNumber) is also 1 byte. Should never
        #   come up as a knob target in practice but we handle it.
        # - offset >= 0x03 is an FX Parameter, 4 nibbles, offset-binary.
        rel_offset = addr - (addr & ~0x1FF) - 0x100   # quick FxItem-relative
        # actually easier: derive from the 'offset' field returned earlier
        rel = k["offset"]
        if rel in (ON_OFF_OFFSET, DUP_NUMBER_OFFSET):
            payload = b"\x00"
            payload_desc = "00 (1 byte)"
        else:
            payload = encode_4nib_offset(0)
            payload_desc = "08 00 00 00 (4 nibbles, =0)"

        sess.write(addr, payload)
        print(f"{k['knob']:<5} {k['slot']:<5} {k['target_idx']:<7} "
              f"{k['target_category']:<22} {k['target_name']:<18} "
              f"{k['fx_type_name']:<14} 0x{addr:08X}   wrote {payload_desc}")

    print()
    print("Done. Look at the device — the 4 main-display knobs should now")
    print("read 0 (or the centre/min of their displayed range).")
    print("Press any patch button to revert.")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
