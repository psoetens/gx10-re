"""
Decode the JSONL captures produced by midi_sniff.py into structured Roland
SysEx records.

The GX-10 protocol observed so far:

    F0 41 <dev> 00 00 00 0B <cmd> <a3 a2 a1 a0> <data...> <sum> F7

  - 41           Roland manufacturer ID
  - dev          device ID (always 0x10 in our captures)
  - 00 00 00 0B  4-byte model ID for GX-10
  - cmd          0x11 = RQ1 (data request, host -> device)
                 0x12 = DT1 (data set, both directions)
  - addr (4B)    big-endian, 7-bit-clean (no byte > 0x7F)
  - data         payload, all 7-bit-clean
  - sum          Roland checksum: (sum(addr+data) + sum) & 0x7F == 0

Usage:
    python sysex_decode.py captures/handshake.jsonl [--ascii] [--summary]
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROLAND_MFR = 0x41
# Observed GX-10 model ID: 5 bytes immediately after dev_id, ending in 0x0B
# (matches family LSB from Identity Reply where family = 0x040B). Newer Roland
# products use an extended model ID with a leading 0x00 prefix.
GX10_MODEL = bytes([0x00, 0x00, 0x00, 0x00, 0x0B])
GX10_MODEL_LEN = len(GX10_MODEL)

CMDS = {0x11: "RQ1", 0x12: "DT1"}


def roland_checksum_ok(addr_data: bytes, sum_byte: int) -> bool:
    return (sum(addr_data) + sum_byte) & 0x7F == 0


def parse_sysex(raw: bytes):
    """Return a dict describing the SysEx, or None if it doesn't look Roland."""
    if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return {"kind": "non-sysex", "len": len(raw), "raw": raw.hex().upper()}

    body = raw[1:-1]
    # Universal SysEx: F0 7E ... F7 (Non-Realtime) or F0 7F ... F7 (Realtime)
    if body[:1] == b"\x7E" or body[:1] == b"\x7F":
        return parse_universal(body, "non-realtime" if body[0] == 0x7E else "realtime")

    if body[0] != ROLAND_MFR:
        return {"kind": "vendor", "vendor": f"{body[0]:02X}", "body": body.hex().upper()}

    if len(body) < 1 + 1 + GX10_MODEL_LEN + 1:
        return {"kind": "roland-short", "body": body.hex().upper()}

    dev = body[1]
    model = bytes(body[2:2 + GX10_MODEL_LEN])
    cmd = body[2 + GX10_MODEL_LEN]
    rest = body[3 + GX10_MODEL_LEN:]

    if model != GX10_MODEL:
        return {
            "kind": "roland",
            "dev": f"{dev:02X}",
            "model": model.hex().upper(),
            "cmd": f"{cmd:02X}",
            "rest": rest.hex().upper(),
        }

    if len(rest) < 4 + 1:
        return {"kind": "gx10-short", "body": body.hex().upper()}

    addr = rest[:4]
    payload = rest[4:-1]
    sum_byte = rest[-1]
    addr_int = int.from_bytes(addr, "big")
    chk_ok = roland_checksum_ok(addr + payload, sum_byte)
    return {
        "kind": "gx10",
        "dev": f"{dev:02X}",
        "cmd_byte": cmd,
        "cmd": CMDS.get(cmd, f"?{cmd:02X}"),
        "addr": f"{addr_int:08X}",
        "addr_int": addr_int,
        "len": len(payload),
        "data": payload.hex().upper(),
        "sum": f"{sum_byte:02X}",
        "sum_ok": chk_ok,
    }


def parse_universal(body: bytes, kind: str):
    # body[0] = 7E or 7F (already consumed); we got the rest
    if len(body) < 4:
        return {"kind": f"univ-{kind}", "body": body.hex().upper()}
    chan = body[1]
    sub1 = body[2]
    sub2 = body[3]
    rest = body[4:]
    label = None
    if kind == "non-realtime" and sub1 == 0x06 and sub2 == 0x02:
        # Identity Reply
        if len(rest) >= 6:
            mfr = rest[0]
            family = int.from_bytes(rest[1:3], "little")  # Roland uses little-endian here
            model_no = int.from_bytes(rest[3:5], "little")
            sw = rest[5:].hex().upper()
            label = f"IdentityReply mfr={mfr:02X} family={family:#06x} model={model_no:#06x} sw={sw}"
    return {
        "kind": f"univ-{kind}",
        "chan": f"{chan:02X}",
        "sub1": f"{sub1:02X}",
        "sub2": f"{sub2:02X}",
        "rest": rest.hex().upper(),
        "note": label,
    }


def ascii_safe(b: bytes) -> str:
    return "".join(chr(c) if 0x20 <= c < 0x7F else "." for c in b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="capture jsonl from midi_sniff.py")
    ap.add_argument("--ascii", action="store_true", help="show ASCII rendering of payload")
    ap.add_argument("--summary", action="store_true", help="print per-address summary at end")
    ap.add_argument("--addr-prefix", default=None, help="filter to addresses starting with this hex prefix")
    args = ap.parse_args()

    addr_counter = Counter()
    addr_lengths = defaultdict(set)
    addr_first_seen = {}
    bad_chk = 0
    label = None
    by_label = defaultdict(int)

    with open(args.path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "label":
                label = ev.get("label")
                continue
            if ev.get("kind") != "sysex":
                continue
            label = ev.get("label", label)
            raw = bytes.fromhex(ev["hex"])
            parsed = parse_sysex(raw)
            if parsed.get("kind") != "gx10":
                # still useful (e.g. universal identity)
                if parsed.get("kind", "").startswith("univ"):
                    print(f"[{ev['t']:8.3f}] UNIV {parsed}")
                continue
            if args.addr_prefix and not parsed["addr"].startswith(args.addr_prefix.upper()):
                continue
            ok = "OK" if parsed["sum_ok"] else "BADSUM"
            if not parsed["sum_ok"]:
                bad_chk += 1
            data_hex = parsed["data"]
            ascii_part = ""
            if args.ascii:
                ascii_part = "  | " + ascii_safe(bytes.fromhex(data_hex))
            print(f"[{ev['t']:8.3f}] {parsed['cmd']} addr={parsed['addr']} len={parsed['len']:3d} {ok}  {data_hex}{ascii_part}")
            addr_counter[parsed["addr"]] += 1
            addr_lengths[parsed["addr"]].add(parsed["len"])
            addr_first_seen.setdefault(parsed["addr"], ev["t"])
            by_label[label or "(none)"] += 1

    if args.summary:
        print("\n=== SUMMARY ===")
        print(f"Bad checksums: {bad_chk}")
        print(f"\nUnique addresses ({len(addr_counter)}):")
        for addr, count in sorted(addr_counter.items()):
            lens = sorted(addr_lengths[addr])
            print(f"  {addr}  count={count:3d}  payload_lens={lens}  first_t={addr_first_seen[addr]:.3f}")
        print(f"\nMessage counts by label:")
        for lbl, c in sorted(by_label.items()):
            print(f"  {lbl!r}: {c}")


if __name__ == "__main__":
    main()
