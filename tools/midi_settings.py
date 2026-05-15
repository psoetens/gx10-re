"""Read and write the GX-10's MIDI SETTINGS block at 0x0000_3000.

Covers every field in `docs/gaps.md` §6.3 — RX/TX CHANNEL, MIDI IN THRU,
CLOCK OUT, MAP SELECT, and the 13 per-controller CC# assignments.

Usage:
    python tools/midi_settings.py                       # list all settings
    python tools/midi_settings.py --json                # list as JSON
    python tools/midi_settings.py --set rx_channel 1    # write a setting
    python tools/midi_settings.py --set midi_in_thru OFF
    python tools/midi_settings.py --set 0x00003004 0    # write by raw addr

Caveat (2026-05-15): writes to `MIDI IN THRU` (0x0000_3004) via DT1
sometimes do not take effect on the device without a power cycle or
specific commit sequence we haven't fully characterized. If your write
doesn't stick, toggle the setting on the device's hardware menu
(MENU → MIDI SETTINGS → USB IN THRU) instead. This caveat is specific
to this single byte so far; other SystemMidi fields take writes
normally.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import GX10Session
from device_id import require_alive


# (address, name, kind, decoder_in, decoder_out)
# kind is informational; decoder_in turns the raw byte into a string,
# decoder_out turns a user-supplied string (or int) into a raw byte.

def _enum(names):
    def _in(b): return f"{b}={names[b]}" if 0 <= b < len(names) else f"{b}=?"
    def _out(s):
        if isinstance(s, int) or (isinstance(s, str) and s.isdigit()):
            return int(s)
        up = str(s).upper().strip()
        for i, n in enumerate(names):
            if n.upper() == up: return i
        raise ValueError(f"unknown value {s!r}; valid: {names}")
    return _in, _out

def _channel(b):
    # 0..15 → channel 1..16
    return f"{b}=ch{b+1}" if 0 <= b <= 15 else f"{b}=?"

def _channel_out(s):
    s = str(s).strip().lower()
    if s.startswith("ch"): s = s[2:]
    n = int(s)
    if 1 <= n <= 16: return n - 1
    if 0 <= n <= 15: return n
    raise ValueError(f"channel must be 1..16 (or raw 0..15), got {s!r}")

def _tx_channel(b):
    if 0 <= b <= 15: return f"{b}=ch{b+1}"
    if b == 16:     return "16=RX (mirror RX_CHANNEL)"
    return f"{b}=?"

def _tx_channel_out(s):
    s = str(s).strip().lower()
    if s in ("rx", "rx_channel"): return 16
    if s.startswith("ch"): s = s[2:]
    n = int(s)
    if 1 <= n <= 16: return n - 1
    if n == 16:      return 16  # raw RX-mirror sentinel
    if 0 <= n <= 15: return n
    raise ValueError(f"tx channel: 1..16 or 'RX', got {s!r}")

def _cc(b):
    # Per chart: each per-controller CC# field accepts OFF, CC#1..31,
    # CC#64..95 — 64 valid values stored compactly as raw 0..63.
    #   raw 0       -> OFF
    #   raw 1..31   -> CC#1..31
    #   raw 32..63  -> CC#64..95   (raw + 32 = CC#)
    if b == 0: return "0=OFF"
    if 1 <= b <= 31: return f"{b}=CC#{b}"
    if 32 <= b <= 63: return f"{b}=CC#{b + 32}"
    return f"{b}=? (out of valid 0..63 range)"

def _cc_out(s):
    s = str(s).strip().upper()
    if s in ("OFF", "NONE", "-"): return 0
    if s.startswith("CC#"): s = s[3:]
    elif s.startswith("CC"): s = s[2:]
    n = int(s)
    # Accept either raw 0..63 or literal CC# 1..31 / 64..95
    if n == 0: return 0
    if 1 <= n <= 31: return n
    if 64 <= n <= 95: return n - 32
    # Treat 32..63 as raw indices into the second half (silently
    # mapping to CC#64..95) — for power users who know the encoding.
    if 32 <= n <= 63: return n
    raise ValueError(f"CC# must be OFF / 1..31 / 64..95 (or raw 0..63), got {s!r}")


# MIDI IN THRU enum: the chart documents 4 values but the order is
# inferred from the BTS v1.0.2 source comment ("USB OUT or USB & MIDI"
# trigger the loopback). The order below is best-effort; if you read
# back a value whose name doesn't match the device menu, swap them.
MIDI_IN_THRU_IN, MIDI_IN_THRU_OUT = _enum(["OFF", "MIDI", "USB OUT", "USB & MIDI"])
CLOCK_OUT_IN,    CLOCK_OUT_OUT    = _enum(["OFF", "ON", "AUTO"])
MAP_SELECT_IN,   MAP_SELECT_OUT   = _enum(["FIX", "PROG"])


# Field map: short_name -> (address, label, decoder_in, decoder_out)
FIELDS = {
    "rx_channel":     (0x00003000, "RX CHANNEL",                  _channel,        _channel_out),
    "tx_channel":     (0x00003002, "TX CHANNEL",                  _tx_channel,     _tx_channel_out),
    "midi_in_thru":   (0x00003004, "MIDI IN THRU",                MIDI_IN_THRU_IN, MIDI_IN_THRU_OUT),
    "clock_out":      (0x00003006, "CLOCK OUT",                   CLOCK_OUT_IN,    CLOCK_OUT_OUT),
    "map_select":     (0x00003007, "MAP SELECT",                  MAP_SELECT_IN,   MAP_SELECT_OUT),
    "cc_num1":        (0x00003008, "CC# NUM 1",                   _cc,             _cc_out),
    "cc_num2":        (0x00003009, "CC# NUM 2",                   _cc,             _cc_out),
    "cc_num3":        (0x0000300A, "CC# NUM 3",                   _cc,             _cc_out),
    "cc_num4":        (0x0000300B, "CC# NUM 4",                   _cc,             _cc_out),
    "cc_bank_down":   (0x0000300C, "CC# BANK DOWN",               _cc,             _cc_out),
    "cc_bank_up":     (0x0000300D, "CC# BANK UP",                 _cc,             _cc_out),
    "cc_ctl1":        (0x0000300E, "CC# CTL1",                    _cc,             _cc_out),
    "cc_ctl2":        (0x0000300F, "CC# CTL2",                    _cc,             _cc_out),
    "cc_ctl3":        (0x00003010, "CC# CTL3",                    _cc,             _cc_out),
    "cc_ctl4":        (0x00003011, "CC# CTL4",                    _cc,             _cc_out),
    "cc_exp1_sw":     (0x00003012, "CC# EXP1 SW",                 _cc,             _cc_out),
    "cc_exp1":        (0x00003013, "CC# EXP1",                    _cc,             _cc_out),
    "cc_exp2":        (0x00003014, "CC# EXP2",                    _cc,             _cc_out),
}


def read_all(sess):
    """Return {short_name: {address, label, raw, decoded}} for every field."""
    out = {}
    for name, (addr, label, dec_in, _) in FIELDS.items():
        b = sess.request(addr, 1, timeout=1.0)
        if b is None:
            out[name] = {"address": f"0x{addr:08X}", "label": label,
                         "raw": None, "decoded": "(no reply)"}
        else:
            out[name] = {"address": f"0x{addr:08X}", "label": label,
                         "raw": f"{b[0]:02X}", "decoded": dec_in(b[0])}
    return out


def format_table(rows):
    out = []
    out.append(f"{'short_name':<14s} {'address':<10s} {'label':<24s} {'raw':<4s} decoded")
    out.append("-" * 78)
    for name, r in rows.items():
        out.append(f"{name:<14s} {r['address']:<10s} {r['label']:<24s} "
                   f"{r['raw'] or '--':<4s} {r['decoded']}")
    return "\n".join(out)


def write_field(sess, field, value):
    """Write a value to a field. `field` can be a short_name or a raw
    address like '0x00003004'. `value` is a string or int the field's
    decoder_out can parse. Returns (address, raw_byte, readback)."""
    if field in FIELDS:
        addr, label, _, dec_out = FIELDS[field]
    else:
        # Raw address path
        try:
            addr = int(field, 16) if str(field).lower().startswith("0x") else int(field)
        except ValueError:
            raise SystemExit(f"unknown field: {field!r}. valid names: {list(FIELDS)} or 0xADDR")
        label = "(raw address)"
        dec_out = lambda s: int(str(s), 0)

    raw = dec_out(value)
    if not (0 <= raw <= 0x7F):
        raise SystemExit(f"value {raw} out of range 0..0x7F for a single-byte SysEx field")
    sess.write(addr, bytes([raw]))
    import time
    time.sleep(0.1)
    rb = sess.request(addr, 1, timeout=1.0)
    return addr, raw, (rb[0] if rb else None), label


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", nargs=2, metavar=("FIELD", "VALUE"),
                    help="write a value to a field (short_name or 0xADDR)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    sess = GX10Session()
    require_alive(sess)

    if args.set:
        field, value = args.set
        addr, sent, readback, label = write_field(sess, field, value)
        if readback is None:
            print(f"wrote 0x{sent:02X} to 0x{addr:08X} ({label}); read-back FAILED", file=sys.stderr)
            ok = False
        else:
            ok = readback == sent
            verdict = "VERIFIED" if ok else f"WARN: readback 0x{readback:02X} != sent 0x{sent:02X}"
            print(f"wrote 0x{sent:02X} to 0x{addr:08X} ({label}); readback 0x{readback:02X} — {verdict}")
            if field == "midi_in_thru" and not ok:
                print("  (DT1 writes to MIDI IN THRU sometimes don't stick — toggle the device's", file=sys.stderr)
                print("   MENU → MIDI SETTINGS → USB IN THRU instead. See module docstring.)", file=sys.stderr)
        sys.stdout.flush()
        import os; os._exit(0 if (readback is not None and ok) else 1)

    rows = read_all(sess)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(format_table(rows))
    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
