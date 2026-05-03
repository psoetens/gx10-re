"""Read live device status of every footswitch / pedal — works on
both GX-10 and GX-100. Auto-detects the connected model via Identity
Reply and uses the right LED-bit mapping for that model.

  - Function assigned to each pedal in the currently-loaded memory
    (MemoryCommon offsets 0x10..0x21, per-patch).
  - Mode (TOGGLE / MOMENT) for each pedal (MemoryCommon 0x22..0x31).
  - LED ON/OFF state (MemoryLed offset 0x14..0x1B — 32-bit bitmap
    where each bit corresponds to one pedal/switch).
  - AMP CTL1/2 current state from MemoryEfct.
  - Global COLOR MODE (SystemCommon 0x1B = TYPE 1 / TYPE 2).

LED *colors* are NOT a direct device readback — they're derived by the
firmware from the assigned Function plus the current ON/OFF state.
Common patterns:
  - "MEMORY -1 / +1 / 1..4" → display colour = patch's primary effect
  - "BPM TAP" → flashes white at tempo
  - "TUNER" → green when active
  - "AMP CTL 1/2" → red/orange when on
  - "OFF" → unlit
  - Effect-bypass-style functions → match the controlled effect's hex
The chart only stores the Function and ON/OFF state; the colour is
inferred by the firmware/display.

Usage:
  Close BTS first (it holds the MIDI port). Then:
  python tools/read_pedal_status.py
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1
import midi_sniff
from device_profile import detect_and_profile, GX10_LED_BITS, GX100_LED_BITS
from effect_colors import (EFFECT_COLOR, FUNCTION_COLOR, friendly,
                            NAVIGATION_FUNCTIONS, PEDAL_FX_EFFECTS)
try:
    from assign_target_table import ASSIGN_TARGET
except Exception:
    ASSIGN_TARGET = {}
try:
    from fx_type_enum import FX_TYPE_NAME
except Exception:
    FX_TYPE_NAME = {}

# SystemControl ControlMode — verified 2026-05-03 against user's GX-10:
#   0 = UP/DOWN
#   1 = MANUAL
#   2 = BANK/NUM
#   3 = MANUAL (alternate — the user normally only sees 0/1/2 but the
#               script captured 3 once; treat identically to 1)
# Earlier I had the BTS resource.js list "UP/DOWN, BANK/NUM, MANUAL"
# misindexed onto 0/1/2 — the actual device enum is in a different
# order. The chart's max=3 spans 4 values (0..3) but only 0/1/2 are
# user-reachable on GX-10.
# In MANUAL mode (1 or 3) GX-10 maps its 3 hardware footswitches
# (BANK DOWN, BANK UP, CTL 1) onto the GX-100's MAN NUM 1/2/3 sources
# for the assign block — same Assign-source enum covers both models.
CONTROL_MODE_NAMES = {0: "UP/DOWN", 1: "MANUAL",
                       2: "BANK/NUM", 3: "MANUAL (alt)"}
MANUAL_MODES = (1, 3)
BANK_NUM_MODES = (2,)
UP_DOWN_MODES = (0,)
SYSTEM_CONTROL_BASE = 0x00001000
ADDR_CONTROL_MODE = SYSTEM_CONTROL_BASE + 0x34

# Assign block: 20 entries × 0x40 bytes each, starting at 0x000200 within
# the patch. Per chart's [Assign] block:
#   off 0x00  SW (0..1)
#   off 0x01  TARGET_FX_ITEM (0..19)
#   off 0x02..0x05  TARGET (4-nibble, 0..740 ASSIGN_TARGET_TABLE index)
#   off 0x0E  SOURCE (0..83) — which pedal/CC controls this assign
#   off 0x0F  MODE (TOGGLE / MOMENT)
ASSIGN_BLOCK_OFS = 0x000200
ASSIGN_ENTRY_SIZE = 0x40
ASSIGN_NUM = 20


def chart_addr_add(base: int, linear_offset: int) -> int:
    """Add a LINEAR (7-bit-per-byte) offset to a chart-hex base address.
    Roland addresses are 4 bytes, each 0..127 — adding 0x40 to byte d
    makes d=0x40, but adding another 0x40 carries to byte c (not byte
    d=0x80). Convert base to linear, add, unpack back to chart hex."""
    a = (base >> 24) & 0xFF
    b = (base >> 16) & 0xFF
    c = (base >> 8) & 0xFF
    d = base & 0xFF
    base_lin = ((a & 0x7F) << 21) | ((b & 0x7F) << 14) | \
               ((c & 0x7F) << 7) | (d & 0x7F)
    new_lin = base_lin + linear_offset
    return ((new_lin >> 21) & 0x7F) << 24 \
         | ((new_lin >> 14) & 0x7F) << 16 \
         | ((new_lin >> 7) & 0x7F) << 8 \
         | (new_lin & 0x7F)

# SOURCE byte values (chart Assign offset 0x0E enum)
ASSIGN_SOURCE_NAMES = [
    "NUM 1", "NUM 2", "NUM 3", "NUM 4",
    "MAN 1", "MAN 2", "MAN 3", "MAN 4",
    "CUR NUM", "BANK DOWN", "BANK UP",
    "CTL 1", "CTL 2", "CTL 3", "CTL 4",
    "EXP 1 SW", "EXP 1", "EXP 2",
    "INT PDL", "WAVE PDL", "INPUT",
    # values 21..83 are CC#1..CC#31 + CC#64..CC#95 — not pedal sources
]


def parse_assign(raw: bytes):
    """Parse one 0x40-byte Assign entry. Returns dict with the fields we
    care about (SW, SOURCE, TARGET)."""
    if len(raw) < 0x10:
        return None
    sw = raw[0x00] & 0x01
    target_fx_item = raw[0x01] & 0x1F
    # TARGET is 4-nibble (offsets 0x02..0x05)
    target = ((raw[0x02] & 0xF) << 12 | (raw[0x03] & 0xF) << 8 |
              (raw[0x04] & 0xF) << 4 | (raw[0x05] & 0xF))
    source = raw[0x0E] & 0x7F
    mode = raw[0x0F] & 0x01
    return {"sw": sw, "target_fx_item": target_fx_item, "target": target,
            "source": source, "mode": mode}


def parse_all_assigns(blob: bytes):
    """Parse the full 20 × 0x40 Assign block. Returns list of dicts."""
    out = []
    for i in range(ASSIGN_NUM):
        ofs = i * ASSIGN_ENTRY_SIZE
        a = parse_assign(blob[ofs:ofs + ASSIGN_ENTRY_SIZE])
        if a is None:
            continue
        a["index"] = i + 1
        out.append(a)
    return out


def assign_color_for_pedal(pedal_label: str, assigns: list,
                              fxitem_types: dict,
                              source_aliases: dict = None):
    """Return (effect_category, target_param, color_name) for the first
    active (SW=1) assign whose SOURCE matches the given pedal label OR
    one of its aliases. On GX-10 the 3 hardware pedals (BANK DOWN/UP,
    CTL 1) double as MAN NUM 1/2/3 in MANUAL mode, so we check both
    direct and aliased sources.

    Returns (None, None, None) if no active assign targets this pedal."""
    if not assigns or not ASSIGN_TARGET:
        return (None, None, None)
    candidate_labels = (source_aliases or {}).get(pedal_label) or [pedal_label]
    valid_indices = []
    for label in candidate_labels:
        try:
            valid_indices.append(ASSIGN_SOURCE_NAMES.index(label))
        except ValueError:
            pass
    if not valid_indices:
        return (None, None, None)
    for a in assigns:
        if a["sw"] and a["source"] in valid_indices:
            cat, tgt = ASSIGN_TARGET.get(a["target"], ("", ""))
            if "EFFECT(RENAMED" in cat or cat == "EFFECT":
                fxi = a.get("target_fx_item")
                if fxi is not None and fxi in fxitem_types:
                    type_byte = fxitem_types[fxi]
                    eff_name = FX_TYPE_NAME.get(type_byte, f"TYPE#{type_byte}")
                    color = (EFFECT_COLOR.get(eff_name)
                             or EFFECT_COLOR.get(eff_name.upper()))
                    return (eff_name, tgt or "ON/OFF", color)
                # FxItem TYPE not yet read — note that we know the slot
                return (f"EFFECT(FxItem#{fxi+1 if fxi is not None else '?'})",
                        tgt or "ON/OFF", None)
            color = EFFECT_COLOR.get(cat) or EFFECT_COLOR.get(cat.upper())
            return (cat, tgt, color)
    return (None, None, None)


def is_divider_category(cat: str) -> bool:
    """True if the assign-target category names a DIVIDER (green=A / red=B)."""
    return bool(cat) and "DIVIDER" in cat.upper()


def render_color(cat: str, color_name: str, state: int) -> str:
    """Format a colour for output. DIVIDER targets always render as
    green (path A, state=0) / red (path B, state=1) — never 'off' and
    never the raw 'white' that effect_parameter.js gives them."""
    if is_divider_category(cat):
        return (f"{friendly('red')} (path B)" if state
                else f"{friendly('green')} (path A)")
    if not color_name:
        return "(unknown)"
    return friendly(color_name)


# ----- chart constants ---------------------------------------------------
TEMP_BASE = 0x10000000
MEMORY_COMMON_OFS = 0x000000
MEMORY_LED_OFS = 0x000140
MEMORY_EFCT_OFS = 0x000F00
SYSTEM_COMMON_BASE = 0x00000000

# Function value names (0..18) per chart's Num1 Function field. Ctl1-4 /
# Exp1Sw extend the list to include BANK DOWN / BANK UP at indices 1-2.
FUNCTION_NAMES_NUM = [
    "OFF", "1", "MEMORY -1", "MEMORY +1", "BPM TAP", "TUNER",
    "MEMORY/MAN", "TUNER/MAN", "MAN/TUNER", "AMP CTL 1", "AMP CTL 2",
    "PFX", "DIV CH.SEL", "SEND/RETURN", "LOOP CTL", "LOOP STOP",
    "LOOP CLEAR", "MIDI START",
]
# Bank Down/Up Function uses index 1 = "BANK DOWN" / "BANK UP" instead of "1"
FUNCTION_NAMES_BANK_DOWN = list(FUNCTION_NAMES_NUM)
FUNCTION_NAMES_BANK_DOWN[1] = "BANK DOWN"
FUNCTION_NAMES_BANK_UP = list(FUNCTION_NAMES_NUM)
FUNCTION_NAMES_BANK_UP[1] = "BANK UP"
# Manual NumX Function: only 0..14, no MEMORY -1/+1
FUNCTION_NAMES_MAN_NUM = [
    "OFF", "BPM TAP", "TUNER", "MEMORY/MAN", "TUNER/MAN", "MAN/TUNER",
    "AMP CTL 1", "AMP CTL 2", "PFX", "DIV CH.SEL", "SEND/RETURN",
    "LOOP CTL", "LOOP STOP", "LOOP CLEAR", "MIDI START",
]
# CNum Function: 0..14 same as Manual NumX
FUNCTION_NAMES_CNUM = list(FUNCTION_NAMES_MAN_NUM)
# Ctl1-4 / Exp1Sw Function: 0..18 — adds BANK DOWN, BANK UP, MEMORY-1, MEMORY+1
FUNCTION_NAMES_CTL = [
    "OFF", "BANK DOWN", "BANK UP", "MEMORY -1", "MEMORY +1",
    "BPM TAP", "TUNER", "MEMORY/MAN", "TUNER/MAN", "MAN/TUNER",
    "AMP CTL 1", "AMP CTL 2", "PFX", "DIV CH.SEL", "SEND/RETURN",
    "LOOP CTL", "LOOP STOP", "LOOP CLEAR", "MIDI START",
]
EXP_FUNCTION_NAMES = [
    "OFF", "FOOT VOL", "PEDAL FX", "FV/PEDAL FX", "FV+TUNER", "FV+TUNE/PFX",
]
MODE_NAMES = ["TOGGLE", "MOMENT"]

# Pedal table — labels + chart MemoryCommon offsets, model-agnostic.
# led_bit per device differs; populated from device_profile at runtime.
#   tuple = (label, function_offset, mode_offset, key, function_table)
# `key` is what we look up in the profile's led_bits dict.
PEDAL_DEFS = [
    ("NUM 1     ", 0x10, 0x22, "NUM 1",     FUNCTION_NAMES_NUM),
    ("NUM 2     ", 0x11, 0x23, "NUM 2",     FUNCTION_NAMES_NUM),
    ("NUM 3     ", 0x12, 0x24, "NUM 3",     FUNCTION_NAMES_NUM),
    ("NUM 4     ", 0x13, 0x25, "NUM 4",     FUNCTION_NAMES_NUM),
    ("BANK DOWN ", 0x14, 0x26, "BANK DOWN", FUNCTION_NAMES_BANK_DOWN),
    ("BANK UP   ", 0x15, 0x27, "BANK UP",   FUNCTION_NAMES_BANK_UP),
    ("CUR NUM   ", 0x16, 0x28, "CUR NUM",   FUNCTION_NAMES_CNUM),
    # MAN NUM 1..4 are alternative assignments active in MAN mode
    # (no LED bit on either model — Manual mode reuses NUM 1-4 LEDs)
    ("MAN NUM 1 ", 0x17, 0x29, None,        FUNCTION_NAMES_MAN_NUM),
    ("MAN NUM 2 ", 0x18, 0x2A, None,        FUNCTION_NAMES_MAN_NUM),
    ("MAN NUM 3 ", 0x19, 0x2B, None,        FUNCTION_NAMES_MAN_NUM),
    ("MAN NUM 4 ", 0x1A, 0x2C, None,        FUNCTION_NAMES_MAN_NUM),
    # External jacks (CTL 2-4 not present on GX-10)
    ("CTL 1     ", 0x1B, 0x2D, "CTL 1",     FUNCTION_NAMES_CTL),
    ("CTL 2     ", 0x1C, 0x2E, "CTL 2",     FUNCTION_NAMES_CTL),
    ("CTL 3     ", 0x1D, 0x2F, "CTL 3",     FUNCTION_NAMES_CTL),
    ("CTL 4     ", 0x1E, 0x30, "CTL 4",     FUNCTION_NAMES_CTL),
    ("EXP 1 SW  ", 0x1F, 0x31, "EXP 1 SW",  FUNCTION_NAMES_CTL),
]


def build_pedals_for_profile(profile):
    """Resolve LED bits for the given profile. Returns the same shape as
    the previous PEDALS table: (label, foff, moff, led_bit, fnames)."""
    name_to_bit = {name: bit for bit, name in profile["led_bits"].items()}
    out = []
    for label, foff, moff, key, fnames in PEDAL_DEFS:
        led_bit = name_to_bit.get(key, -1) if key else -1
        out.append((label, foff, moff, led_bit, fnames))
    return out
EXP_PEDALS = [
    ("EXP 1     ", 0x20, EXP_FUNCTION_NAMES),
    ("EXP 2     ", 0x21, EXP_FUNCTION_NAMES),
]


def find_pfx_target_in_chain(fxitem_types: dict):
    """When a pedal's Function is PFX and no Assign block entry matches,
    the device routes to whichever pedal-controllable effect (WAH /
    PEDAL BEND / etc.) is currently in the chain. Scan the FxItem TYPE
    bytes and return (effect_name, color_name) for the first match, or
    (None, None)."""
    if not fxitem_types:
        return (None, None)
    for slot in sorted(fxitem_types):
        type_byte = fxitem_types[slot]
        eff = FX_TYPE_NAME.get(type_byte)
        if eff and eff in PEDAL_FX_EFFECTS:
            return (eff, EFFECT_COLOR.get(eff))
    return (None, None)


def derive_led_color(pedal_label: str, function_name: str, manual_state: int,
                       control_mode: int, cur_patch: int,
                       assigns: list, fxitem_types_arg: dict = None,
                       patches_per_bank: int = 3,
                       bank_num_slot_pedals: list = None,
                       source_aliases: dict = None) -> str:
    """Best-effort derivation of the displayed LED colour given the
    current pedal mode + the pedal's assigned function + the manual-mode
    toggle state + the patch's Assign block + the chain's FxItem types.

    Order of precedence (most specific wins):
      1. Mode-specific overrides (UP/DOWN BANK pedals = blue;
         BANK/NUM NUM-pedal-for-current-slot = blue)
      2. DIV CH.SEL function = always dual green/red
      3. Active Assign for this pedal = its target's colour
         (DIVIDER targets render dual green/red regardless of state)
      4. PFX function with no Assign = derived from the chain's
         pedal-controllable effect (WAH / PEDAL BEND / TOUCH WAH / …)
      5. Function colour from FUNCTION_COLOR (TUNER, AMP CTL, etc.)
      6. Otherwise off
    """
    fxt = fxitem_types_arg or {}

    # --- 1. mode-specific overrides --------------------------------------
    # UP/DOWN mode: BANK DOWN/UP are always blue. CTL 1 falls through.
    if control_mode in UP_DOWN_MODES and pedal_label in ("BANK DOWN", "BANK UP"):
        return friendly("blue")

    # BANK/NUM mode: the 3 (GX-10) or 4 (GX-100) "slot" footswitches act
    # as patch-position indicators within the current bank. Only the one
    # matching (cur_patch % patches_per_bank) lights up. If a CUR NUM
    # assign is active, that assign's target colour overrides the blue.
    if control_mode in BANK_NUM_MODES and bank_num_slot_pedals:
        if pedal_label in bank_num_slot_pedals and cur_patch is not None:
            cur_slot = cur_patch % len(bank_num_slot_pedals)
            is_current = (bank_num_slot_pedals[cur_slot] == pedal_label)
            if not is_current:
                return "(off)"
            # Current-slot pedal — check for an active CUR NUM assign that
            # would re-colour it. CUR NUM source index = 8 in the chart's
            # Assign source enum.
            try:
                cur_num_src = ASSIGN_SOURCE_NAMES.index("CUR NUM")
            except ValueError:
                cur_num_src = -1
            cur_num_assign = next(
                (a for a in assigns
                 if a["sw"] and a["source"] == cur_num_src),
                None,
            )
            if cur_num_assign is not None:
                cat, tgt = ASSIGN_TARGET.get(cur_num_assign["target"],
                                              ("?", "?"))
                if ("EFFECT(RENAMED" in cat or cat == "EFFECT") \
                        and cur_num_assign["target_fx_item"] in (fxitem_types_arg or {}):
                    actual = FX_TYPE_NAME.get(
                        (fxitem_types_arg or {})[cur_num_assign["target_fx_item"]])
                    if actual:
                        cat = actual
                # DIVIDER keeps its normal green (path A) / red (path B)
                # rendering even when CUR NUM is the source.
                if is_divider_category(cat):
                    return (render_color(cat, "white", manual_state)
                            + f" [CUR NUM->{cat}:{tgt}]")
                # Other CUR NUM assigns: off=blue (slot indicator),
                # on=effect color
                color = (EFFECT_COLOR.get(cat)
                         or EFFECT_COLOR.get(cat.upper()))
                if manual_state:
                    return (f"{friendly(color) if color else '(unknown)'} "
                            f"(on) [CUR NUM->{cat}:{tgt}]")
                return f"{friendly('blue')} (off) [CUR NUM->{cat}:{tgt}]"
            return friendly("blue")
        # Non-slot pedals in BANK/NUM are dark (unless they're EXP/etc
        # which fall through to assign-derived colours in MANUAL only —
        # in BANK/NUM they're typically inert)
        if pedal_label in ("BANK DOWN", "BANK UP") or pedal_label.startswith("NUM "):
            return "(off)"

    # --- 2. DIV CH.SEL function is always dual-state ---------------------
    if function_name == "DIV CH.SEL":
        return render_color("DIVIDER", "white", manual_state) + " [DIV CH.SEL]"

    # --- 3. active Assign for this pedal trumps Function -----------------
    asn_cat, asn_tgt, asn_color = assign_color_for_pedal(
        pedal_label, assigns, fxt, source_aliases)
    if asn_cat:
        rendered = render_color(asn_cat, asn_color, manual_state)
        if is_divider_category(asn_cat):
            return f"{rendered} [{asn_cat}:{asn_tgt}]"
        if manual_state:
            return f"{rendered} [{asn_cat}]"
        return f"(off:{rendered}) [{asn_cat}]"

    # --- 4. PFX function without an explicit Assign ----------------------
    if function_name == "PFX":
        eff, c = find_pfx_target_in_chain(fxt)
        if eff:
            tag = f"[PFX -> {eff} (chain)]"
            rendered = friendly(c) if c else "(unknown)"
            return f"{rendered} {tag}" if manual_state else f"(off:{rendered}) {tag}"
        return "(PFX, no chain target)"

    # --- 5. Function colour for stateful functions -----------------------
    if function_name in NAVIGATION_FUNCTIONS:
        return "(off)"   # nav actions don't paint a manual-mode LED
    c = FUNCTION_COLOR.get(function_name)
    if c is None:
        return "(off)"
    if not manual_state:
        return f"(off:{friendly(c)})"
    return friendly(c)


def parse_dt1(raw):
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if len(raw) < 14 or raw[8] != 0x12:
        return None
    addr = int.from_bytes(raw[9:13], "big")
    payload = bytes(raw[13:-2])
    return addr, payload


def main():
    # Detect connected device first so we use the right LED-bit map
    model, profile = detect_and_profile(port_substr="GX-10")
    pedals = build_pedals_for_profile(profile)

    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port("GX-10")
    if in_idx is None:
        print("ERROR: no MIDI input port matching 'GX-10'")
        sys.exit(2)
    s = midi_sniff.Sniffer(in_idx, Path("__nul__.jsonl"), in_name)

    def emit(o):
        if o.get("kind") == "sysex":
            try:
                with lock:
                    events.append(bytes.fromhex(o["hex"]))
            except Exception:
                pass
    s._emit = emit
    s.open()
    out_idx, _ = find_output_port("GX-10")
    if out_idx is None:
        print("ERROR: no output port"); sys.exit(2)
    out = MidiOut(out_idx)
    time.sleep(0.4)

    # Read MemoryCommon Function+Mode (0x10..0x32, 35 bytes)
    fmaddr = TEMP_BASE + MEMORY_COMMON_OFS + 0x10
    out.send_sysex(build_rq1(fmaddr, 0x23))
    # Read MemoryLed ON OFF STATE (0x14..0x1B, 8 bytes)
    ledaddr = TEMP_BASE + MEMORY_LED_OFS + 0x14
    out.send_sysex(build_rq1(ledaddr, 0x08))
    # Read MemoryEfct AMP CTL1/CTL2 (0x07..0x08, 2 bytes)
    ampctladdr = TEMP_BASE + MEMORY_EFCT_OFS + 0x07
    out.send_sysex(build_rq1(ampctladdr, 0x02))
    # Read SystemCommon COLOR MODE (0x1B)
    cmaddr = SYSTEM_COMMON_BASE + 0x1B
    out.send_sysex(build_rq1(cmaddr, 0x01))
    # Read SystemCommon AMP CTL1/2 mode (LATCH/PULSE/INVERT, 0x0B..0x0C)
    sysampaddr = SYSTEM_COMMON_BASE + 0x0B
    out.send_sysex(build_rq1(sysampaddr, 0x02))
    # Read Memory Name (0..0x0F, 16 bytes)
    nameaddr = TEMP_BASE + MEMORY_COMMON_OFS + 0x00
    out.send_sysex(build_rq1(nameaddr, 0x10))
    # Read SystemControl ControlMode (foot-pedal operating mode)
    out.send_sysex(build_rq1(ADDR_CONTROL_MODE, 0x01))
    # Read SystemCommon Memory Number (current loaded patch index, 4 nibbles)
    memnumaddr = SYSTEM_COMMON_BASE + 0x00
    out.send_sysex(build_rq1(memnumaddr, 0x04))
    # Read each Assign individually — a single 0x800-byte RQ1 gets
    # split into many DT1s by the device, and reassembly is fragile.
    # 20 separate 0x40-byte reads each get a single matching DT1.
    # Use 7-bit-per-byte arithmetic for the per-Assign stride.
    # NOTE: small inter-RQ1 delay — sending 40+ requests back-to-back
    # causes the device to drop replies (observed empirically: bursts
    # of >30 requests result in some FxItem reads getting no reply).
    INTER_RQ1_S = 0.015
    assign_addrs = []
    base_assign = TEMP_BASE + ASSIGN_BLOCK_OFS
    for i in range(ASSIGN_NUM):
        addr = chart_addr_add(base_assign, i * ASSIGN_ENTRY_SIZE)
        assign_addrs.append(addr)
        out.send_sysex(build_rq1(addr, ASSIGN_ENTRY_SIZE))
        time.sleep(INTER_RQ1_S)
    # Read all 20 FxItem TYPE bytes (so we can resolve "EFFECT(RENAMED WITH
    # TYPE)" assigns to their actual current effect colour). Each FxItem
    # is at offset 0x001100 + i * 0x200; TYPE byte at offset +0x00.
    fxtype_addrs = []
    for i in range(20):
        addr = TEMP_BASE + 0x001100 + i * 0x200
        fxtype_addrs.append(addr)
        out.send_sysex(build_rq1(addr, 1))
        time.sleep(INTER_RQ1_S)

    time.sleep(2.0)

    # Snapshot replies, identify any missed FxItem TYPE reads, retry once
    by_addr = {}
    with lock:
        for e in events:
            p = parse_dt1(e)
            if p:
                by_addr[p[0]] = p[1]
    missed_fxitems = [a for a in fxtype_addrs if a not in by_addr]
    if missed_fxitems:
        for addr in missed_fxitems:
            out.send_sysex(build_rq1(addr, 1))
            time.sleep(0.025)
        time.sleep(1.0)

    by_addr = {}
    with lock:
        for e in events:
            p = parse_dt1(e)
            if p:
                by_addr[p[0]] = p[1]

    # Decode
    name_payload = by_addr.get(nameaddr, b"\x20" * 16)
    patch_name = "".join(chr(b) if 32 <= b <= 126 else "?"
                          for b in name_payload[:16])

    fm_payload = by_addr.get(fmaddr, b"")
    led_payload = by_addr.get(ledaddr, b"")
    amp_payload = by_addr.get(ampctladdr, b"")
    cm_payload = by_addr.get(cmaddr, b"")
    sysamp_payload = by_addr.get(sysampaddr, b"")
    ctrl_mode_payload = by_addr.get(ADDR_CONTROL_MODE, b"")
    memnum_payload = by_addr.get(memnumaddr, b"")
    # Reassemble the 20 individually-read Assign entries into a list
    assigns = []
    for i, addr in enumerate(assign_addrs):
        p = by_addr.get(addr, b"")
        if len(p) < 0x10:
            continue
        a = parse_assign(p)
        if a is None:
            continue
        a["index"] = i + 1
        assigns.append(a)
    active_assigns = [a for a in assigns if a["sw"]]
    # Per-FxItem TYPE bytes (slot index 0..19 → effect name)
    fxitem_types = {}
    for i, addr in enumerate(fxtype_addrs):
        p = by_addr.get(addr)
        if p:
            fxitem_types[i] = p[0] & 0x7F
    ctrl_mode_byte = ctrl_mode_payload[0] if ctrl_mode_payload else None
    ctrl_mode_name = CONTROL_MODE_NAMES.get(ctrl_mode_byte, f"?({ctrl_mode_byte})")
    # Decode 4-nibble Memory Number (chart: 0..299)
    cur_patch = None
    if len(memnum_payload) >= 4:
        cur_patch = ((memnum_payload[0] & 0xF) << 12 |
                     (memnum_payload[1] & 0xF) << 8 |
                     (memnum_payload[2] & 0xF) << 4 |
                     (memnum_payload[3] & 0xF))

    if not fm_payload:
        print("ERROR: no reply for MemoryCommon Function/Mode read")
        import os; os._exit(2)

    # Decode LED bitmap from 4-nibble encoding (8 bytes -> 32-bit value)
    if len(led_payload) >= 8:
        led32 = 0
        for i in range(8):
            led32 = (led32 << 4) | (led_payload[i] & 0x0F)
    else:
        led32 = 0

    color_mode = cm_payload[0] if cm_payload else None
    amp_modes = ["LATCH", "PULSE", "INVERT"]

    print(f"\n=== {model} LIVE PEDAL/SWITCH STATUS ===")
    print(f"Loaded patch:   '{patch_name.strip()}'  (memory #{cur_patch})")
    print(f"PEDAL MODE:     {ctrl_mode_name}  (ControlMode={ctrl_mode_byte})")
    if color_mode is not None:
        print(f"COLOR MODE:     {'TYPE 1' if color_mode == 0 else 'TYPE 2'}  (system-wide LED palette)")
    if len(sysamp_payload) >= 2:
        print(f"AMP CTL1 mode:  {amp_modes[sysamp_payload[0]]}")
        print(f"AMP CTL2 mode:  {amp_modes[sysamp_payload[1]]}")
    if len(amp_payload) >= 2:
        print(f"AMP CTL1 state: {'ON' if amp_payload[0] else 'OFF'}")
        print(f"AMP CTL2 state: {'ON' if amp_payload[1] else 'OFF'}")

    print(f"\nLED bitmap raw: 0x{led32:08X}  (manual-mode toggle state — frozen in other modes)")
    physical = profile["physical_pedals"]
    print()
    print(f"  {'PEDAL':10s}  {'FUNCTION':14s}  {'MODE':7s}  LED   {'COLOR':40s}  present?")
    print(f"  {'-' * 10}  {'-' * 14}  {'-' * 7}  ----  {'-' * 40}  --------")
    for label, foff, moff, ledbit, fnames in pedals:
        fbyte = fm_payload[foff - 0x10] if foff - 0x10 < len(fm_payload) else None
        mbyte = fm_payload[moff - 0x10] if moff - 0x10 < len(fm_payload) else None
        fname = fnames[fbyte] if fbyte is not None and fbyte < len(fnames) else f"?{fbyte}"
        mname = MODE_NAMES[mbyte] if mbyte is not None and mbyte < len(MODE_NAMES) else f"?{mbyte}"
        if ledbit >= 0:
            manual_state = (led32 >> ledbit) & 1
            led_str = "[*] " if manual_state else "[ ] "
        else:
            manual_state = 0
            led_str = "----"
        present = "yes" if label.strip() in physical else "no"
        color = derive_led_color(label.strip(), fname, manual_state,
                                  ctrl_mode_byte, cur_patch, active_assigns,
                                  fxitem_types,
                                  profile.get("patches_per_bank", 3),
                                  profile.get("bank_num_slot_pedals", []),
                                  profile.get("manual_mode_source_aliases", {}))
        print(f"  {label}  {fname:14s}  {mname:7s}  {led_str}  {color:40s}  {present}")

    print()
    print(f"  {'PEDAL':10s}  {'FUNCTION':14s}")
    print(f"  {'-' * 10}  {'-' * 14}")
    for label, foff, fnames in EXP_PEDALS:
        fbyte = fm_payload[foff - 0x10] if foff - 0x10 < len(fm_payload) else None
        fname = fnames[fbyte] if fbyte is not None and fbyte < len(fnames) else f"?{fbyte}"
        print(f"  {label}  {fname:14s}")

    if active_assigns:
        print(f"\nActive assigns ({len(active_assigns)} of {ASSIGN_NUM}):")
        for a in active_assigns:
            src_name = (ASSIGN_SOURCE_NAMES[a["source"]]
                        if a["source"] < len(ASSIGN_SOURCE_NAMES)
                        else f"src#{a['source']}")
            cat, tgt = ASSIGN_TARGET.get(a["target"], ("?", "?"))
            # Resolve the effect-category name for colour lookup. The
            # "EFFECT(RENAMED WITH TYPE)" meta-target points at whichever
            # effect is in the assign's TARGET_FX_ITEM slot — we
            # dereference via the FxItem TYPE byte.
            if ("EFFECT(RENAMED" in cat or cat == "EFFECT") and a["target_fx_item"] in fxitem_types:
                actual_type = FX_TYPE_NAME.get(fxitem_types[a["target_fx_item"]],
                                                f"TYPE#{fxitem_types[a['target_fx_item']]}")
                cat_disp = f"{actual_type} (FxItem#{a['target_fx_item']+1})"
                color_cat = actual_type
            else:
                cat_disp = cat
                color_cat = cat
            color_name = (EFFECT_COLOR.get(color_cat)
                          or EFFECT_COLOR.get(color_cat.upper()))
            mode_n = "TOG" if a["mode"] == 0 else "MOM"
            # render_color handles DIVIDER (green/red) and everything else
            # via friendly(). For DIVIDER the per-state colour depends on
            # the current bitmap bit for that source; we don't have a
            # universal mapping from assign source → LED bit yet, so for
            # the summary we just say "green/red (dual)" when DIVIDER.
            if is_divider_category(color_cat):
                colour_disp = (f"{friendly('green')}/{friendly('red')} "
                                f"(path A / path B)")
            else:
                colour_disp = friendly(color_name) if color_name else "(unknown)"
            print(f"  Assign #{a['index']:2d}  source={src_name:10s}  "
                  f"target=#{a['target']:3d} {cat_disp}:{tgt}  "
                  f"colour={colour_disp}  mode={mode_n}")
    print("\nNote: LED *color* derived from Function + Assign block. The")
    print("chart does not store the LED colour directly — firmware does.")
    print("ControlMode mapping (verified on GX-10): 0=UP/DOWN, 1=MANUAL,")
    print("2=BANK/NUM, 3=MANUAL (alt).")

    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
