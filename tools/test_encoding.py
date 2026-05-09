"""Round-trip tests for tools/encoding.py.

These are pure unit tests — no device required. They verify the
encoder/decoder pair against the canonical examples from
`docs/bpm_encoding.md`, `reports/linux_probe_results.md` §P0-1,
and the v2 manual's "0000 aaaa" bit-pattern requirement.

Run:  python tools/test_encoding.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from encoding import (
    encode_4nib_be, decode_4nib_be,
    encode_fx_param, decode_fx_param,
    encode_bpm, decode_bpm,
    encode_2nib_be, decode_2nib_be,
    encode_byte, decode_byte,
    encode_ascii_string, decode_ascii_string,
)


passed = 0
failed = 0


def check(label, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {label}: expected {expected!r}, got {actual!r}")


# ---- 4-nibble ----------------------------------------------------

# 0 -> all zeros
check("4nib encode 0",        encode_4nib_be(0),        b"\x00\x00\x00\x00")
check("4nib decode 0",        decode_4nib_be(b"\x00\x00\x00\x00"), 0)
# 0xFFFF -> max
check("4nib encode 0xFFFF",   encode_4nib_be(0xFFFF),   b"\x0F\x0F\x0F\x0F")
check("4nib decode 0xFFFF",   decode_4nib_be(b"\x0F\x0F\x0F\x0F"), 0xFFFF)
# 0x8064 -> 08 00 06 04 (the SUSTAIN=100 canonical wire form)
check("4nib encode 0x8064",   encode_4nib_be(0x8064),   b"\x08\x00\x06\x04")
check("4nib decode 0x8064",   decode_4nib_be(b"\x08\x00\x06\x04"), 0x8064)

# Decoder is tolerant of upper-nibble noise (real device truncates)
check("4nib decode tolerant", decode_4nib_be(b"\x08\x00\x00\x64"), 0x8004)

# Round-trip every value in [0, 0xFFFF]
for v in range(0, 0x10000, 137):
    check(f"4nib roundtrip {v}", decode_4nib_be(encode_4nib_be(v)), v)

# ---- offset-binary FX Parameter ---------------------------------

# Display 0 -> 08 00 00 00 (wire 0x8000)
check("fx_param encode 0",    encode_fx_param(0),    b"\x08\x00\x00\x00")
check("fx_param decode 0",    decode_fx_param(b"\x08\x00\x00\x00"), 0)
# Display 100 -> 08 00 06 04 (wire 0x8064)
check("fx_param encode 100",  encode_fx_param(100),  b"\x08\x00\x06\x04")
check("fx_param decode 100",  decode_fx_param(b"\x08\x00\x06\x04"), 100)
# Display 50 -> 08 00 03 02 (wire 0x8032)
check("fx_param encode 50",   encode_fx_param(50),   b"\x08\x00\x03\x02")
check("fx_param decode 50",   decode_fx_param(b"\x08\x00\x03\x02"), 50)
# Display -100 -> wire 0x7F9C = 07 0F 09 0C
check("fx_param encode -100", encode_fx_param(-100), b"\x07\x0F\x09\x0C")
check("fx_param decode -100", decode_fx_param(b"\x07\x0F\x09\x0C"), -100)
# Display range bounds
check("fx_param encode -20000", encode_fx_param(-20000), encode_4nib_be(0x8000 - 20000))
check("fx_param encode +20000", encode_fx_param(+20000), encode_4nib_be(0x8000 + 20000))

# ---- BPM ---------------------------------------------------------

# canonical examples from docs/bpm_encoding.md
check("bpm encode 40",   encode_bpm(40),   b"\x00\x01\x09\x00")  # V=400 = 0x190
check("bpm decode 40",   decode_bpm(b"\x00\x01\x09\x00"), 40.0)
check("bpm encode 50",   encode_bpm(50),   b"\x00\x01\x0F\x04")  # V=500 = 0x1F4
check("bpm decode 50",   decode_bpm(b"\x00\x01\x0F\x04"), 50.0)
check("bpm encode 100",  encode_bpm(100),  b"\x00\x03\x0E\x08")  # V=1000 = 0x3E8
check("bpm encode 250",  encode_bpm(250),  b"\x00\x09\x0C\x04")  # V=2500 = 0x9C4
check("bpm round-trip 121", decode_bpm(encode_bpm(121.0)), 121.0)
check("bpm round-trip 121.5", decode_bpm(encode_bpm(121.5)), 121.5)

# ---- 2-nibble ----------------------------------------------------

# MEMORY LEVEL = 200 (0xC8) -> 0C 08
check("2nib encode 200",  encode_2nib_be(200), b"\x0C\x08")
check("2nib decode 200",  decode_2nib_be(b"\x0C\x08"), 200)
check("2nib encode 0",    encode_2nib_be(0),   b"\x00\x00")
check("2nib encode 0xFF", encode_2nib_be(0xFF), b"\x0F\x0F")

# ---- byte / ascii -----------------------------------------------

check("byte encode 0",    encode_byte(0),    b"\x00")
check("byte encode 0x7F", encode_byte(0x7F), b"\x7F")
check("byte decode top-bit-clean", decode_byte(b"\x82"), 0x02)

check("ascii encode 'NATURAL'",
      encode_ascii_string("NATURAL", 16),
      b"NATURAL         ")
check("ascii decode 'NATURAL  '",
      decode_ascii_string(b"NATURAL         "),
      "NATURAL")
# Non-printable replaced with space
check("ascii encode tab",
      encode_ascii_string("AB\tC", 8),
      b"AB C    ")

# ---- error checking ---------------------------------------------

ok = False
try:
    encode_4nib_be(0x10000)
except ValueError:
    ok = True
check("4nib reject overflow", ok, True)

ok = False
try:
    encode_bpm(30)
except ValueError:
    ok = True
check("bpm reject too-low", ok, True)

ok = False
try:
    encode_byte(0x80)
except ValueError:
    ok = True
check("byte reject 8-bit", ok, True)

# ---- end ---------------------------------------------------------

print(f"\n{passed} passed, {failed} failed")
if failed:
    sys.exit(1)
