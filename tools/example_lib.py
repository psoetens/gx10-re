"""Shared utilities for the example_*.py demo scripts.

Pulls together:
  - chain walker: turn the 50-byte CHAIN TOP/NEXT block into an ordered list
    of FxItem storage slot indices.
  - target resolver: given an ASSIGN TARGET TABLE index (0..740) and the
    FX TYPE byte of the FxItem the assign points at, return the offset
    inside that FxItem of the parameter being controlled.

The target resolver derives its data from two sources:
  - catalogs/assign_target_table.json  (chart's 741-entry table)
  - captures/typebar_full/page*/*/summary.json  (per-effect captured
    knob addresses, populated by manual_xref_v2.py)

It builds, lazily on first use, a dict
    {fx_type_byte: {param_name_uppercased: relative_offset_in_FxItem}}
where the param name comes from the assign table's `target` field and
the offset is read from the captured summary.json's `address` for the
matching knob (or `type_address` if the assign table's row is the per-
effect TYPE selector).

Why we need both sources: the assign table tells us what name a TARGET
index corresponds to, but doesn't give a byte offset. The captured
summary tells us which byte each named knob lives at. The two have to be
joined by name, with category aliasing for the few mismatches between
fx_type_enum names and assign-table category names.
"""
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_dt1, build_rq1
import midi_sniff
import fx_type_enum


ROOT = Path(__file__).parent.parent
ASSIGN_TARGET_TABLE = json.loads((ROOT / "catalogs" / "assign_target_table.json").read_text())
TYPEBAR = ROOT / "captures" / "typebar_full"


# ---- chart constants ------------------------------------------------

FX_ITEM_BASE = 0x10001100        # FxItem #0 base
FX_ITEM_STRIDE = 0x200           # bytes between successive FxItems (chart-hex)

FX_TYPE_BYTE_OFFSET = 0x00       # MemoryFxItem global TYPE byte
ON_OFF_OFFSET = 0x01             # MemoryFxItem ON/OFF byte
DUP_NUMBER_OFFSET = 0x02         # MemoryFxItem DuplicationNumber

FX_PARAM_BASE_OFFSET = 0x03      # FX Parameter 1 starts here
FX_PARAM_STRIDE = 0x04           # 4 nibbles per param

CHAIN_BLOCK_ADDR = 0x10000F0C    # MemoryEfct: 50 bytes (TOP + NEXT[0..48])
CHAIN_BLOCK_LEN = 50

KNOB_FX_ITEM_ADDR = 0x10000069   # MemoryCommon: 4 bytes, KnobN SettingFxItem
KNOB_TARGET_ADDR  = 0x1000006D   # MemoryCommon: 16 bytes, KnobN SETTING (4-nibble each)


def fx_item_addr(slot, offset=0):
    """Address of `offset` within FxItem storage slot #slot."""
    return FX_ITEM_BASE + slot * FX_ITEM_STRIDE + offset


# ---- value encoding -------------------------------------------------

def encode_4nib_direct(v):
    """4 nibbles big-endian (no offset), e.g. for TARGET enum or ACT RANGE."""
    return bytes([(v >> 12) & 0xF, (v >> 8) & 0xF,
                  (v >> 4) & 0xF, v & 0xF])


def decode_4nib_direct(b):
    return ((b[0] & 0xF) << 12) | ((b[1] & 0xF) << 8) \
           | ((b[2] & 0xF) << 4) | (b[3] & 0xF)


def encode_4nib_offset(display_value):
    """4 nibbles of (display_value + 0x8000), i.e. offset binary.
    Use for FX Parameters and TARGET MIN/MAX."""
    return encode_4nib_direct(display_value + 0x8000)


def decode_4nib_offset(b):
    return decode_4nib_direct(b) - 0x8000


# ---- low-level MIDI helpers ----------------------------------------

def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])


class GX10Session:
    """One MIDI in+out session with a sniffer queue. Supports request/reply."""

    def __init__(self, port_substr="GX-10"):
        self.events = []
        self.lock = threading.Lock()
        in_idx, in_name = midi_sniff.find_port(port_substr)
        if in_idx is None:
            raise RuntimeError(f"no MIDI input matching {port_substr!r}")
        self.sniffer = midi_sniff.Sniffer(in_idx, Path("__nul__.jsonl"), in_name)
        self.sniffer._emit = self._emit
        self.sniffer.open()
        out_idx, _ = find_output_port(port_substr)
        if out_idx is None:
            raise RuntimeError(f"no MIDI output matching {port_substr!r}")
        self.out = MidiOut(out_idx)
        time.sleep(0.4)

    def _emit(self, o):
        if o.get("kind") == "sysex":
            try:
                with self.lock:
                    self.events.append(bytes.fromhex(o["hex"]))
            except Exception:
                pass

    def send(self, sysex_bytes):
        self.out.send_sysex(sysex_bytes)

    def write(self, addr, payload):
        """DT1 write."""
        self.out.send_sysex(build_dt1(addr, payload))

    def request(self, addr, size, timeout=0.7):
        """RQ1 + wait for matching DT1 reply, return payload or None."""
        with self.lock:
            self.events.clear()
        self.out.send_sysex(build_rq1(addr, size))
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for e in list(self.events):
                    p = parse_dt1(e)
                    if p and p[0] == addr:
                        return p[1]
            time.sleep(0.02)
        return None


# ---- chain walker --------------------------------------------------

def walk_chain(chain_block):
    """chain_block is the 50-byte payload at 0x10000F0C.
    Returns the ordered list of FxItem storage slot indices in the chain,
    head first. byte = slot_index + 1; 0 = end / unused."""
    if len(chain_block) < CHAIN_BLOCK_LEN:
        return []
    top_byte = chain_block[0]
    if top_byte == 0:
        return []
    order = []
    cur = top_byte - 1
    seen = set()
    while 0 <= cur < 49 and cur not in seen and len(order) < 50:
        seen.add(cur)
        order.append(cur)
        nxt_byte = chain_block[1 + cur]
        if nxt_byte == 0:
            break
        cur = nxt_byte - 1
    return order


# ---- target → offset lookup ----------------------------------------

# Map from assign-table category -> fx_type_enum name (the FX_TYPE_NAME
# value for the corresponding fx_type_byte). Most categories match
# directly; these are the ones that don't.
CATEGORY_TO_FX_TYPE_NAME = {
    "AC GUITAR SIM":           "AC GUITAR SIMULATOR",
    "PARAMETRIC EQ":           "PARAMETRIC EQUALIZER",
    "GRAPHIC EQ":              "GRAPHIC EQUALIZER",
    "PREAMP":                  "AIRD PREAMP",
    "BASS PREAMP":             "AIRD BASS PREAMP",
    "X COMPRESSOR":            "X-COMP",
    "BASS X COMP":             "X-BASS COMP",
    "X OVERDRIVE":             "X-OD",
    "X BASS OVERDRIVE":        "X-BASS OD",
    "X DISTORTION":            "X-DS",
    "BASS METAL DIST":         "BASS METAL",
    "PRIME FLANGER":           "FLANGER PRIME",
    "BASS PRIME FLANGER":      "BASS FLANGER PRIME",
    "PRIME VIBARTO":           "VIBRATO PRIME",     # chart typo
    "CLASSIC VIBE":            "CLASSIC-VIBE",
    "POLY OCTAVE":             "OCTAVE POLY",
    "BASS OCTAVE":             "OCTAVE BASS",
    # "EFFECT(RENAMED WITH TYPE)" is the generic ON/OFF row — handled
    # separately by callers (it points at offset 0x01 of whatever
    # FxItem TARGET_FX_ITEM resolves to).
    # "TUNER" / "MIDI" / "MASTER" categories aren't FX TYPE-mapped (they
    # live in the master block / system regions).
}


def _fx_type_name_to_byte():
    return {v: k for k, v in fx_type_enum.FX_TYPE_NAME.items()}


def fx_type_byte_for_category(category):
    """Return the fx_type_byte that holds a given assign-target category,
    or None for non-effect categories (TUNER/MIDI/MASTER/----)."""
    name_to_byte = _fx_type_name_to_byte()
    aliased = CATEGORY_TO_FX_TYPE_NAME.get(category, category)
    return name_to_byte.get(aliased)


_OFFSET_LOOKUP_CACHE = None


def _build_offset_lookup():
    """Walk every captures/typebar_full/page*/*/summary.json and build
        {fx_type_byte: {UPPER_PARAM_NAME: relative_offset_in_FxItem}}
    Includes the per-effect TYPE selector at 0x03 when the summary
    reports has_type=True (i.e., the effect has a sub-type dropdown).
    """
    out = {}
    for sp in TYPEBAR.glob("page*/*/summary.json"):
        try:
            s = json.loads(sp.read_text())
        except Exception:
            continue
        fxb = s.get("fx_type_byte")
        if fxb is None:
            continue
        out.setdefault(fxb, {})
        # TYPE selector — has_type=True means the FX Param 1 is a
        # discrete enum dropdown rather than a continuous knob.
        if s.get("has_type") and s.get("type_address"):
            try:
                addr = int(s["type_address"], 16)
                out[fxb]["TYPE"] = addr - FX_ITEM_BASE
            except (ValueError, TypeError):
                pass
        for k in s.get("knobs", []):
            name = (k.get("name_manual_v2") or k.get("name_manual") or "").strip()
            addr = k.get("address")
            if not name or not addr or name == "?":
                continue
            try:
                rel = int(addr, 16) - FX_ITEM_BASE
            except (ValueError, TypeError):
                continue
            # Use uppercase, normalized name as the key
            out[fxb][name.upper()] = rel
    return out


def offset_lookup():
    """Cache + return the fx_type_byte → param_name → offset table."""
    global _OFFSET_LOOKUP_CACHE
    if _OFFSET_LOOKUP_CACHE is None:
        _OFFSET_LOOKUP_CACHE = _build_offset_lookup()
    return _OFFSET_LOOKUP_CACHE


def _fuzzy_name_match(table, name):
    """Try increasingly relaxed matches for a knob name against a table.

    The assign-target table sometimes prefixes the parameter name with
    a redundant disambiguator (e.g. "EFFECT LEVEL" vs the captured
    knob's plain "LEVEL", or METAL's "DISTORTION TYPE" vs "TYPE").
    Captures sometimes do the inverse (e.g. PREAMP's "MIC LEVEL" vs
    just "LEVEL").
    """
    n = name.upper().strip()
    if n in table:
        return table[n]
    # Last-word match: "EFFECT LEVEL" -> "LEVEL", "DISTORTION TYPE" -> "TYPE"
    parts = n.split()
    for k in range(1, len(parts)):
        suffix = " ".join(parts[k:])
        if suffix in table:
            return table[suffix]
    # Captured-name-as-suffix-of-target: target says "MIC LEVEL", capture
    # is "LEVEL" — covered above.  Also handle the inverse: target says
    # "LEVEL" but captured knob is "MIC LEVEL".
    matches = [v for k, v in table.items() if k.endswith(" " + n)]
    if len(matches) == 1:
        return matches[0]
    return None


def target_to_offset(target_idx, fx_type_byte):
    """Return the relative offset (within MemoryFxItem) of the parameter
    that ASSIGN TARGET TABLE index `target_idx` points at, when the
    enclosing FxItem has FX TYPE byte = fx_type_byte.

    Returns None if the target/category doesn't apply to that FX TYPE
    (e.g., target is for a different effect, or it's the generic
    EFFECT ON/OFF row, or it's a master/system target).
    """
    entry = ASSIGN_TARGET_TABLE.get(str(target_idx))
    if not entry:
        return None
    cat = entry.get("category", "")
    name = (entry.get("target") or "").strip().upper()
    if not name or cat == "----":
        return None
    # Generic EFFECT ON/OFF row — caller handles it specially.
    if cat == "EFFECT(RENAMED WITH TYPE)" and name == "ON/OFF":
        return ON_OFF_OFFSET
    expected_byte = fx_type_byte_for_category(cat)
    if expected_byte != fx_type_byte:
        return None
    table = offset_lookup().get(fx_type_byte, {})
    return _fuzzy_name_match(table, name)


# ---- knob-settings reader ------------------------------------------

def read_knob_settings(sess):
    """Return a list of 4 dicts, one per main-display knob:
        [{slot, target_idx, target_category, target_name, offset, abs_addr}, ...]
    `offset` and `abs_addr` will be None for unmapped knobs (target=0)
    or when the target can't be resolved against the current FxItem TYPE.
    """
    fx_items = sess.request(KNOB_FX_ITEM_ADDR, 4)
    targets_blob = sess.request(KNOB_TARGET_ADDR, 16)
    if not fx_items or not targets_blob:
        return []
    out = []
    for k in range(4):
        slot = fx_items[k]
        target_idx = decode_4nib_direct(targets_blob[k*4:(k+1)*4])
        entry = ASSIGN_TARGET_TABLE.get(str(target_idx)) or {}
        cat = entry.get("category", "----")
        name = entry.get("target", "----")
        # Determine actual offset via the FxItem's TYPE byte
        type_byte_raw = sess.request(fx_item_addr(slot, FX_TYPE_BYTE_OFFSET), 1)
        fx_type = type_byte_raw[0] if type_byte_raw else None
        offset = target_to_offset(target_idx, fx_type) if fx_type is not None else None
        abs_addr = (fx_item_addr(slot, offset)
                    if offset is not None else None)
        out.append({
            "knob": k + 1,
            "slot": slot,
            "target_idx": target_idx,
            "target_category": cat,
            "target_name": name,
            "fx_type_byte": fx_type,
            "fx_type_name": fx_type_enum.FX_TYPE_NAME.get(fx_type, "?"),
            "offset": offset,
            "abs_addr": abs_addr,
        })
    return out


# ---- chain reader --------------------------------------------------

def read_chain(sess):
    """Return list of {slot, fx_type_byte, fx_type_name, on_off} for each
    FxItem in chain order."""
    chain_block = sess.request(CHAIN_BLOCK_ADDR, CHAIN_BLOCK_LEN)
    if not chain_block:
        return []
    slots = walk_chain(chain_block)
    out = []
    for slot in slots:
        type_b = sess.request(fx_item_addr(slot, FX_TYPE_BYTE_OFFSET), 1)
        on_off = sess.request(fx_item_addr(slot, ON_OFF_OFFSET), 1)
        out.append({
            "slot": slot,
            "fx_type_byte": type_b[0] if type_b else None,
            "fx_type_name": fx_type_enum.FX_TYPE_NAME.get(
                type_b[0] if type_b else -1, "?"),
            "on_off": on_off[0] if on_off else None,
        })
    return out
