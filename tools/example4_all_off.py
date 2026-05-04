"""Example 4: turn every effect in the current patch OFF.

For most effects this is a 1-byte write of 0x00 to MemoryFxItem
offset 0x01 (ON/OFF). Special handling:

  - DIVIDER (FX TYPE 29) doesn't have a meaningful ON/OFF — it's a
    routing element. Per the user's spec, "off" for DIVIDER means
    "send the signal through the A path only", which we encode as:
      DIVIDER MODE        = SINGLE (0)   — FX Param 1, offset 0x03
      DIVIDER CH SELECT   = A      (0)   — FX Param 2, offset 0x07
    Everything on the B path then gets bypassed naturally because no
    signal flows through it.

  - SPLITTER (FX TYPE 30) is the A/B boundary marker inside the
    parallel section. Its ON/OFF byte still exists and we set it OFF
    for completeness, though the effect is decorative.

  - MIXER (FX TYPE 31) we leave alone if it's ON (it's needed to
    recombine the parallel section after DIVIDER's mode change).

Reverts: any patch-button press on the device.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import (
    GX10Session, read_chain, fx_item_addr,
    encode_4nib_offset,
    ON_OFF_OFFSET, FX_PARAM_BASE_OFFSET, FX_PARAM_STRIDE,
)


DIVIDER_FX_TYPE = 29
SPLITTER_FX_TYPE = 30
MIXER_FX_TYPE = 31

# DIVIDER FX Parameter offsets (per the per-effect-types catalogue and
# the parameter guide):
#   FX Param 1 = MODE (0=SINGLE, 1=DUAL)
#   FX Param 2 = CH SELECT (0=A, 1=B)
DIV_MODE_OFFSET = FX_PARAM_BASE_OFFSET + 0 * FX_PARAM_STRIDE     # 0x03
DIV_CH_SELECT_OFFSET = FX_PARAM_BASE_OFFSET + 1 * FX_PARAM_STRIDE  # 0x07


def main():
    sess = GX10Session()
    chain = read_chain(sess)
    if not chain:
        print("(empty chain)")
        sys.exit(2)

    print(f"Turning off all {len(chain)} effects in the chain...")
    print()

    for entry in chain:
        slot = entry["slot"]
        type_byte = entry["fx_type_byte"]
        type_name = entry["fx_type_name"]
        cur_on_off = entry["on_off"]

        if type_byte == DIVIDER_FX_TYPE:
            # MODE = SINGLE (0), CH SELECT = A (0)
            sess.write(fx_item_addr(slot, DIV_MODE_OFFSET),
                       encode_4nib_offset(0))
            sess.write(fx_item_addr(slot, DIV_CH_SELECT_OFFSET),
                       encode_4nib_offset(0))
            print(f"  slot {slot:2d}  {type_name:<22s}  set MODE=SINGLE, "
                  f"CH SELECT=A  (signal routes through A path only)")
        elif type_byte == MIXER_FX_TYPE and cur_on_off == 1:
            # Leave the mixer ON if it was on — turning it off would
            # break the chain's routing in some configurations.
            print(f"  slot {slot:2d}  {type_name:<22s}  left ON (needed to "
                  f"close the parallel section)")
        else:
            sess.write(fx_item_addr(slot, ON_OFF_OFFSET), b"\x00")
            print(f"  slot {slot:2d}  {type_name:<22s}  ON/OFF -> 0")

    print()
    print("Done. The patch should now sound dry (modulo input level/FOOT VOL).")
    print("Press any patch button to revert.")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
