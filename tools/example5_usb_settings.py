"""Example 5: read and display the GX-10's USB settings.

Reads the chart-documented [SystemInOut] block at 0x00004000 (13 bytes)
and decodes all 7 fields. The 4 USB level fields are 2-nibble 0..200%
encodings; the on/off fields are single bytes; AIRD OUTPUT SELECT is
a 1-byte enum.

Note: same values are present regardless of USB driver mode (GENERIC or
VENDOR). BTS hides some of these in GENERIC mode because the dry-channel
routing has no audible effect when only stereo is exposed over USB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import GX10Session


SYSTEM_INOUT_ADDR = 0x00004000
SYSTEM_INOUT_LEN = 0x0D


MAIN_LEVEL_SELECT = ["-10 dBu", "+4 dBu"]

AIRD_OUTPUT_SELECT = [
    "LINE/PHONES (RECORDING)",
    "JC-120 RETURN",
    "JC-120 INPUT",
    "KATANA-100/212 RETURN",
    "KATANA-100/212 INPUT",
    "KATANA-100 RETURN",
    "KATANA-100 INPUT",
    "TUBE COMBO 212 RETURN",
    "TUBE COMBO 212 INPUT",
    "TUBE COMBO 112 RETURN",
    "TUBE COMBO 112 INPUT",
    "TUBE STACK 412 RETURN",
    "TUBE STACK 412 INPUT",
    "BASS AMP WITH TWEETER",
    "BASS AMP NO TWEETER",
]


def decode_2nib(b_hi, b_lo):
    """The chart's '0000 aaaa | 0000 bbbb' encoding: low nibble of each
    byte combine into an 8-bit value."""
    return ((b_hi & 0xF) << 4) | (b_lo & 0xF)


def percent_bar(value, maximum=200, width=24):
    """Simple text bar showing 0..max as filled blocks."""
    filled = int(round(width * value / maximum))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def main():
    sess = GX10Session()
    payload = sess.request(SYSTEM_INOUT_ADDR, SYSTEM_INOUT_LEN)
    if not payload or len(payload) < SYSTEM_INOUT_LEN:
        print("ERROR: device did not return the full SystemInOut block")
        sys.exit(2)

    print("=" * 70)
    print("GX-10 USB SETTINGS  (chart [SystemInOut] @ 0x00004000)")
    print("=" * 70)

    # 0x00 MAIN:LEVEL SELECT
    main_level = payload[0x00]
    name = (MAIN_LEVEL_SELECT[main_level] if main_level < len(MAIN_LEVEL_SELECT)
            else f"?({main_level})")
    print(f"  MAIN:LEVEL SELECT      {name}")

    # 0x03/04, 0x05/06, 0x07/08, 0x09/0A — USB level percentages
    levels = [
        ("USB MAIN:EFX OUT      ", 0x03, 0x04),
        ("USB MAIN:MIX LEVEL    ", 0x05, 0x06),
        ("USB DRY:OUT           ", 0x07, 0x08),
        ("USB DRY:TO EFX        ", 0x09, 0x0A),
    ]
    for label, hi_off, lo_off in levels:
        v = decode_2nib(payload[hi_off], payload[lo_off])
        print(f"  {label} {v:>3d} %  {percent_bar(v)}")

    # 0x0B USB LOOPBACK
    lb = payload[0x0B]
    print(f"  USB LOOPBACK           {'ON' if lb else 'OFF'}")

    # 0x0C AIRD OUTPUT SELECT
    aird = payload[0x0C]
    aird_name = (AIRD_OUTPUT_SELECT[aird] if aird < len(AIRD_OUTPUT_SELECT)
                  else f"?({aird})")
    print(f"  AIRD OUTPUT SELECT     {aird_name}")

    print("=" * 70)
    print(f"  raw block bytes:  {payload[:SYSTEM_INOUT_LEN].hex().upper()}")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
