"""4-nibble big-endian encoders/decoders for Roland GX-10 / GX-100
SysEx parameter cells.

Each byte in a multi-byte parameter cell uses only its low 4 bits
(the high 4 bits are always 0, satisfying the wire's 7-bit
constraint). The bytes concatenate big-endian as nibbles:

    V_raw = (b[0] & 0xF) << 12
          | (b[1] & 0xF) << 8
          | (b[2] & 0xF) << 4
          | (b[3] & 0xF)

The display value is then derived from V_raw via one of:

  * **offset_binary** (FX Parameters):  V_display = V_raw - 0x8000
                                        domain  V_display in [-20000, +20000]
                                        wire    V_raw     in [12768, 52768]
  * **bpm**:                            V_display (BPM) = V_raw / 10
                                        e.g. wire 0x07D0 → BPM 200
  * **raw** (target indexes, etc.):     V_display = V_raw

The device truncates each cell byte to its low nibble on write.
**This was verified live on a GX-10 fw1.04 (2026-05-09)** — see
`reports/linux_probe_results.md` §P0-1. The pre-fix gxnarly form
`[0x08, 0x00, 0x00, 0x64]` was silently stored as
`[0x08, 0x00, 0x00, 0x04]` (display value 4 instead of 100).

Two-byte (`raw_2nib_be`, e.g. MEMORY LEVEL 0..200) and one-byte
(plain enums) cells are also supported.
"""
from __future__ import annotations
from typing import Iterable


# --- 4-nibble (4 bytes, one nibble per byte) ---------------------

def encode_4nib_be(v_raw: int) -> bytes:
    """Encode a 16-bit value as 4 bytes (one nibble per byte, MSB first).

    Each output byte has 0 in its top nibble and one nibble of v_raw
    in its bottom nibble — this matches the device's `0000 aaaa`
    bit-pattern requirement.
    """
    if not 0 <= v_raw <= 0xFFFF:
        raise ValueError(f"v_raw out of 16-bit range: {v_raw}")
    return bytes([
        (v_raw >> 12) & 0x0F,
        (v_raw >>  8) & 0x0F,
        (v_raw >>  4) & 0x0F,
        (v_raw      ) & 0x0F,
    ])


def decode_4nib_be(cell: bytes) -> int:
    """Decode 4 cell bytes (one nibble per byte) into a 16-bit value."""
    if len(cell) < 4:
        raise ValueError(f"need 4 bytes, got {len(cell)}")
    return (
        ((cell[0] & 0x0F) << 12) |
        ((cell[1] & 0x0F) <<  8) |
        ((cell[2] & 0x0F) <<  4) |
         (cell[3] & 0x0F)
    )


# --- offset binary (4 nibble FX Parameters) ----------------------

OFFSET = 0x8000  # = 32768

def encode_fx_param(v_display: int) -> bytes:
    """Encode an FX Parameter display value (offset binary 4-nibble).

    For unipolar knobs (display 0..N): the wire value is 0x8000+N.
    For bipolar knobs (display -A..+B): wire = display + 0x8000.

    Examples:
      encode_fx_param(0)    -> 08 00 00 00   (wire 0x8000)
      encode_fx_param(100)  -> 08 00 06 04   (wire 0x8064)
      encode_fx_param(-100) -> 07 0F 09 0C   (wire 0x7F9C)
    """
    return encode_4nib_be(v_display + OFFSET)


def decode_fx_param(cell: bytes) -> int:
    """Inverse of `encode_fx_param`. Returns the display value."""
    return decode_4nib_be(cell) - OFFSET


# --- BPM (4 nibble, scaled-by-10) --------------------------------

def encode_bpm(bpm_display: float) -> bytes:
    """Encode a BPM (40..250 in 0.1 increments) as a 4-nibble cell.

    Wire value V = round(bpm_display * 10).

    Examples:
      encode_bpm(120)   -> 00 04 0B 00   (V = 1200 = 0x4B0)
      encode_bpm(120.5) -> 00 04 0B 05   (V = 1205 = 0x4B5)
    """
    v = round(bpm_display * 10)
    if not 400 <= v <= 2500:
        raise ValueError(f"BPM out of range [40.0, 250.0]: {bpm_display}")
    return encode_4nib_be(v)


def decode_bpm(cell: bytes) -> float:
    """Inverse of `encode_bpm`. Returns BPM as a float (one decimal)."""
    return decode_4nib_be(cell) / 10.0


# --- 2-nibble (2 bytes, e.g. MEMORY LEVEL 0..200) ----------------

def encode_2nib_be(v_raw: int) -> bytes:
    """Encode 0..255 as 2 bytes (nibble per byte)."""
    if not 0 <= v_raw <= 0xFF:
        raise ValueError(f"v_raw out of 8-bit range: {v_raw}")
    return bytes([(v_raw >> 4) & 0x0F, v_raw & 0x0F])


def decode_2nib_be(cell: bytes) -> int:
    if len(cell) < 2:
        raise ValueError(f"need 2 bytes, got {len(cell)}")
    return ((cell[0] & 0x0F) << 4) | (cell[1] & 0x0F)


# --- plain 1-byte (target enums, type bytes) ---------------------

def encode_byte(v: int) -> bytes:
    if not 0 <= v <= 0x7F:
        raise ValueError(f"7-bit value out of range: {v}")
    return bytes([v])


def decode_byte(cell: bytes) -> int:
    if len(cell) < 1:
        raise ValueError("empty cell")
    return cell[0] & 0x7F


# --- ASCII string (patch name, etc.) -----------------------------

def encode_ascii_string(s: str, cell_size: int = 16) -> bytes:
    """Encode a string into a fixed-size cell, space-padded, clamped
    to printable ASCII 0x20..0x7E."""
    raw = bytes(c if 0x20 <= c < 0x7F else 0x20 for c in s.encode("ascii", "replace"))
    if len(raw) >= cell_size:
        return raw[:cell_size]
    return raw + b" " * (cell_size - len(raw))


def decode_ascii_string(cell: bytes) -> str:
    """Decode a fixed-size cell into a stripped string."""
    return cell.decode("ascii", "replace").rstrip(" ")
