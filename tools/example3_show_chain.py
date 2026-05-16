"""Example 3: read the current patch's effect chain and print it as a list.

The chain is a linked list at MemoryEfct (0x10000F0C, 50 bytes). Each
byte is `slot_index + 1`, with 0 = end-of-chain. Walk it in order and
look up each FxItem's TYPE byte.

DIVIDER / MIXER pairing: when DIVIDER (FX TYPE 29) appears in a chain,
the signal splits into two paths "A" and "B" until MIXER (FX TYPE 31)
recombines them. Effects between DIVIDER and MIXER live on one of the
two parallel paths, and the device tags channel by **the per-FxItem
`DuplicationNumber` byte at MemoryFxItem offset 0x02**:

    dup=1 -> path A (first parallel-section copy)
    dup=2 -> path B (second parallel-section copy)
    dup=0 -> not in a parallel section / single-path effect

The chain linked-list interleaves both paths in playback order,
visually separated by a SPLITTER (FX TYPE 30) at the A/B boundary.
Verified against an "JC120 AMP HB" preset (preamp + EQ + NS doubled
on both paths).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import GX10Session, read_chain, fx_item_addr
from device_id import require_alive


DIVIDER_FX_TYPE = 29
SPLITTER_FX_TYPE = 30      # default "empty slot" marker
MIXER_FX_TYPE = 31


def main():
    sess = GX10Session()
    require_alive(sess)
    chain = read_chain(sess)
    if not chain:
        print("(empty chain or read failed)")
        sys.exit(2)

    # Read patch name for context
    name_b = sess.request(0x10000000, 16)
    name = (name_b.decode("ascii", "replace").rstrip()
            if name_b else "(unknown)")

    print(f"Patch: '{name}'")
    print(f"Chain has {len(chain)} effect(s):")
    print()

    in_parallel = False
    parallel_effects = []   # holds entries during DIV..MIX section

    chain_pos = 0
    for entry in chain:
        slot = entry["slot"]
        type_byte = entry["fx_type_byte"]
        type_name = entry["fx_type_name"]
        on_off = entry["on_off"]
        on_str = "ON " if on_off == 1 else "off"

        # Read the per-effect DuplicationNumber byte — chart says 0..9; we
        # suspect it might double as a channel marker inside DIV..MIX
        # sections. Show it so the user can see what's there.
        dup_b = sess.request(fx_item_addr(slot, 0x02), 1)
        dup_n = dup_b[0] if dup_b else None

        # State-machine for DIV..MIX section
        if type_byte == DIVIDER_FX_TYPE:
            print(f"  [{chain_pos:2d}] slot {slot:2d}  "
                  f"FX#{type_byte:3d}  {type_name:<22s} {on_str}  dup={dup_n}")
            print(f"       |\\")
            print(f"       | \\----- begin parallel section (A / B paths) -----")
            in_parallel = True
            parallel_effects = []
        elif type_byte == MIXER_FX_TYPE and in_parallel:
            print(f"       |  -----  end parallel section  -----------/")
            print(f"       |/")
            print(f"  [{chain_pos:2d}] slot {slot:2d}  "
                  f"FX#{type_byte:3d}  {type_name:<22s} {on_str}  dup={dup_n}")
            in_parallel = False
            parallel_effects = []
        elif in_parallel:
            # Inside DIV..MIX: dup=1 -> path A, dup=2 -> path B,
            # dup=0 -> path boundary (typically the SPLITTER).
            if dup_n == 1:
                ch = "A"
            elif dup_n == 2:
                ch = "B"
            else:
                ch = "-"
            print(f"       |   [{chain_pos:2d}] slot {slot:2d}  "
                  f"FX#{type_byte:3d}  {type_name:<22s} {on_str}  "
                  f"dup={dup_n}  path={ch}")
            parallel_effects.append(entry)
        else:
            print(f"  [{chain_pos:2d}] slot {slot:2d}  "
                  f"FX#{type_byte:3d}  {type_name:<22s} {on_str}  dup={dup_n}")

        chain_pos += 1

    if in_parallel:
        print(f"  (parallel section never closed — DIVIDER without MIXER?)")

    # Quick legend
    print()
    print("Legend: chain index in [], FxItem storage slot, global FX TYPE byte,")
    print("        effect name, ON/OFF, DuplicationNumber.")
    print("DIVIDER/MIXER mark the parallel section. Inside it,")
    print("dup=1 -> path A, dup=2 -> path B, SPLITTER (FX 30) is the boundary.")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
