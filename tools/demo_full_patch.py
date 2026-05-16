"""End-to-end protocol demo: build BOOST CLEAN + PEQ + REV PLATE chain
in memory_temp, configure all 4 main-display knobs, and write Assign #1
to toggle REV ON/OFF from MIDI CC#64.

Reversible: writes only touch memory_temp (`0x10000000+`). Press any
patch button on the device to discard everything.

Why CC#64 instead of CC#32: Roland's SOURCE enum deliberately excludes
CC#32..CC#63 (CC#32 is MIDI Bank-Select LSB). CC#64 is the closest
valid substitute.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1
from example_lib import GX10Session
from device_id import require_alive


# ---- chain config ----------------------------------------------------

# Global FX TYPE bytes (from tools/fx_type_enum.py)
BOOSTER_FX_TYPE     = 0x24   # 36
PARAMETRIC_EQ_TYPE  = 0x14   # 20
REVERB_FX_TYPE      = 0x3E   # 62

# Per-effect TYPE selector values (from tools/per_effect_types.py)
BOOSTER_CLEAN_BOOST = 1      # MID=0, CLEAN=1, TREBLE=2
REVERB_PLATE        = 2      # HALL_S=0, HALL_M=1, PLATE=2, ROOM=3, STUDIO=4

# FxItem storage slots we'll use (each slot is at 0x10001100 + slot * 0x200)
SLOT_BOOST = 0
SLOT_PEQ   = 1
SLOT_REV   = 2

# ASSIGN TARGET TABLE indices for the 4-knob mapping
TARGET_BOOSTER_TYPE       = 73    # BOOSTER section row 1 = TYPE
TARGET_PEQ_HIGH_GAIN      = 221   # PARAMETRIC EQ row 2 = HIGH GAIN
TARGET_REVERB_PRE_DELAY   = 374   # REVERB row 3 = PRE-DELAY
TARGET_NONE               = 0     # ---- (no target)

# Generic ON/OFF target for assigns
TARGET_EFFECT_ONOFF = 1

# SOURCE byte for CC#64 (= position 52 in the 84-entry SOURCE enum)
SOURCE_CC64 = 52


# ---- address / value helpers ----------------------------------------

def fx_item_addr(slot, offset=0):
    return 0x10001100 + slot * 0x200 + offset


def encode_4nibble_offset(value):
    """4 nibbles of (value + 0x8000), big-endian. For FX Parameters."""
    raw = value + 0x8000
    return bytes([(raw >> 12) & 0xF, (raw >> 8) & 0xF,
                  (raw >> 4) & 0xF, raw & 0xF])


def encode_4nibble_direct(value):
    """4 nibbles of value, big-endian. For TARGET / ACT RANGE / etc."""
    return bytes([(value >> 12) & 0xF, (value >> 8) & 0xF,
                  (value >> 4) & 0xF, value & 0xF])


def encode_2nibble(value):
    """2 nibbles of value, big-endian. For MIDI BANK MSB / LSB."""
    return bytes([(value >> 4) & 0xF, value & 0xF])


def build_chain_payload(top_slot, *next_slots):
    """50-byte chain linked list. byte = slot_index + 1; 0 = end."""
    payload = bytearray(50)
    payload[0] = top_slot + 1
    cur = top_slot
    for nxt in next_slots:
        payload[1 + cur] = nxt + 1
        cur = nxt
    # next of last slot stays 0 (= end)
    return bytes(payload)


def write_assign_fields(out, base, target_fx_item, target_idx,
                         source_byte, mode_toggle=True,
                         target_min=0, target_max=1):
    """Write the 19 assign fields one DT1 at a time, ending at MIDI BANK LSB.

    LESSON LEARNED: a single bulk DT1 of all 45 bytes does NOT commit the
    TARGET sub-group — each chart-listed field must be its own DT1, because
    the chart's "group parameter" pipeline pends each field's DT1 separately
    and only commits when the *final field's address* is hit. A bulk DT1
    spanning multiple fields lands at the first address only.
    """
    out.send_sysex(build_dt1(base + 0x00, b"\x01"))                              # SW=ON
    out.send_sysex(build_dt1(base + 0x01, bytes([target_fx_item])))              # TARGET_FX_ITEM
    out.send_sysex(build_dt1(base + 0x02, encode_4nibble_direct(target_idx)))    # TARGET
    out.send_sysex(build_dt1(base + 0x06, encode_4nibble_offset(target_min)))    # MIN
    out.send_sysex(build_dt1(base + 0x0A, encode_4nibble_offset(target_max)))    # MAX
    out.send_sysex(build_dt1(base + 0x0E, bytes([source_byte])))                 # SOURCE
    out.send_sysex(build_dt1(base + 0x0F, b"\x00" if mode_toggle else b"\x01"))  # MODE
    out.send_sysex(build_dt1(base + 0x15, encode_4nibble_direct(0)))             # ACT RANGE LO
    out.send_sysex(build_dt1(base + 0x19, encode_4nibble_direct(16383)))         # ACT RANGE HI
    out.send_sysex(build_dt1(base + 0x1D, b"\x00"))                              # MIDI CH = SYS
    out.send_sysex(build_dt1(base + 0x1E, b"\x00"))                              # MIDI CC# out
    out.send_sysex(build_dt1(base + 0x1F, encode_4nibble_direct(0)))             # CC VAL MIN
    out.send_sysex(build_dt1(base + 0x23, encode_4nibble_direct(16383)))         # CC VAL MAX
    out.send_sysex(build_dt1(base + 0x27, b"\x00"))                              # N/A fixed
    out.send_sysex(build_dt1(base + 0x28, b"\x00"))                              # MIDI PC#
    out.send_sysex(build_dt1(base + 0x29, b"\x00\x00"))                          # BANK MSB
    out.send_sysex(build_dt1(base + 0x2B, b"\x00\x00"))                          # BANK LSB (FINAL — commits)


# ---- main flow -------------------------------------------------------

def main():
    # GX10Session gives us a built-in sniffer + MidiOut, and lets us
    # run the strict identity check before sending any DT1.
    sess = GX10Session()
    require_alive(sess)
    out = sess.out
    time.sleep(0.3)

    # ---- PHASE 1: chain edit transaction ----
    print("\nPhase 1: Chain edit (BOOST CLEAN + PEQ + REV PLATE)")
    out.send_sysex(build_dt1(0x00200003, b"\x01"))
    time.sleep(0.1)
    print("  ChainEditTrigger = 1 (BEGIN)")

    # FxItem #0 = BOOSTER, ON, sub-TYPE=CLEAN BOOST
    out.send_sysex(build_dt1(fx_item_addr(SLOT_BOOST, 0x00),
                              bytes([BOOSTER_FX_TYPE])))
    out.send_sysex(build_dt1(fx_item_addr(SLOT_BOOST, 0x01), b"\x01"))
    out.send_sysex(build_dt1(fx_item_addr(SLOT_BOOST, 0x03),
                              encode_4nibble_offset(BOOSTER_CLEAN_BOOST)))
    print(f"  FxItem #0 = BOOSTER (TYPE=0x{BOOSTER_FX_TYPE:02X}), "
          f"ON, sub-TYPE=CLEAN BOOST (1)")

    # FxItem #1 = PEQ, ON
    out.send_sysex(build_dt1(fx_item_addr(SLOT_PEQ, 0x00),
                              bytes([PARAMETRIC_EQ_TYPE])))
    out.send_sysex(build_dt1(fx_item_addr(SLOT_PEQ, 0x01), b"\x01"))
    print(f"  FxItem #1 = PARAMETRIC EQ (TYPE=0x{PARAMETRIC_EQ_TYPE:02X}), ON")

    # FxItem #2 = REVERB, ON, sub-TYPE=PLATE
    out.send_sysex(build_dt1(fx_item_addr(SLOT_REV, 0x00),
                              bytes([REVERB_FX_TYPE])))
    out.send_sysex(build_dt1(fx_item_addr(SLOT_REV, 0x01), b"\x01"))
    out.send_sysex(build_dt1(fx_item_addr(SLOT_REV, 0x03),
                              encode_4nibble_offset(REVERB_PLATE)))
    print(f"  FxItem #2 = REVERB (TYPE=0x{REVERB_FX_TYPE:02X}), "
          f"ON, sub-TYPE=PLATE (2)")

    # Bulk chain linked-list: TOP=#0 -> #1 -> #2 -> end
    chain_payload = build_chain_payload(SLOT_BOOST, SLOT_PEQ, SLOT_REV)
    out.send_sysex(build_dt1(0x10000F0C, chain_payload))
    print(f"  Chain linked-list (50 bytes) at 0x10000F0C: "
          f"TOP=#0 -> #1 -> #2 -> end")

    out.send_sysex(build_dt1(0x00200003, b"\x00"))
    time.sleep(0.1)
    print("  ChainEditTrigger = 0 (END)")

    # ---- PHASE 2: knob settings ----
    print("\nPhase 2: Main-display knob settings")
    # KnobN SettingFxItem: 4 bytes at 0x69..0x6C
    knob_fx_items = bytes([SLOT_BOOST, SLOT_PEQ, SLOT_REV, 0])
    out.send_sysex(build_dt1(0x10000069, knob_fx_items))
    print(f"  KnobN SettingFxItem (0x69..0x6C) = "
          f"{knob_fx_items.hex().upper()} (slots 0,1,2,0)")

    # KnobN SETTING: 16 bytes at 0x6D..0x7C, 4 nibbles per knob
    knob_targets = (
        encode_4nibble_direct(TARGET_BOOSTER_TYPE) +      # Knob 1 (param 1 of #0)
        encode_4nibble_direct(TARGET_PEQ_HIGH_GAIN) +     # Knob 2 (param 2 of #1)
        encode_4nibble_direct(TARGET_REVERB_PRE_DELAY) +  # Knob 3 (param 3 of #2)
        encode_4nibble_direct(TARGET_NONE)                # Knob 4 (no #3 in chain)
    )
    out.send_sysex(build_dt1(0x1000006D, knob_targets))
    print(f"  KnobN SETTING (0x6D..0x7C, 16 bytes) targets:")
    print(f"    Knob 1 -> TARGET={TARGET_BOOSTER_TYPE}  (BOOSTER TYPE)")
    print(f"    Knob 2 -> TARGET={TARGET_PEQ_HIGH_GAIN}  (PARAMETRIC EQ HIGH GAIN)")
    print(f"    Knob 3 -> TARGET={TARGET_REVERB_PRE_DELAY}  (REVERB PRE-DELAY)")
    print(f"    Knob 4 -> TARGET={TARGET_NONE}    (---- unmapped)")

    # ---- PHASE 3: Assign #1 (CC#64 toggles REV ON/OFF) ----
    print("\nPhase 3: Assign #1 = CC#64 toggles REV ON/OFF (field-by-field)")
    write_assign_fields(out, 0x10000200,
                         target_fx_item=SLOT_REV,
                         target_idx=TARGET_EFFECT_ONOFF,
                         source_byte=SOURCE_CC64,
                         mode_toggle=True,
                         target_min=0, target_max=1)
    print(f"  17 DT1s at 0x10000200..0x1000022C, "
          f"final write to 0x2B commits the group")
    print(f"    SW=ON, TARGET_FX_ITEM=#{SLOT_REV} (REV), "
          f"TARGET=1 (EFFECT ON/OFF), MIN=0, MAX=1")
    print(f"    SOURCE={SOURCE_CC64} (CC#64), MODE=TOGGLE")
    print(f"    NOTE: CC#32 is excluded by Roland (Bank-Select LSB); "
          f"CC#64 is the substitute")

    print("\n" + "="*60)
    print("DONE. Look at the device:")
    print("  - Chain should show: BOOST(CLEAN) -> PEQ -> REV(PLATE)")
    print("  - Main display knobs: Knob1=BOOST TYPE, Knob2=PEQ HIGH-GAIN,")
    print("                        Knob3=REV PRE-DELAY, Knob4=unmapped")
    print("  - Send CC#64 from any MIDI source -> REV toggles ON/OFF")
    print("Revert: press any patch button on the device.")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
