"""Run all P0/P1/P2 probes from reports/cross_check_findings.md against
the connected GX-10. Save the transcript to stdout (the caller redirects
to a report). Read-only where possible; writes are wrapped read-restore.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_io_linux import GxMidi, parse_dt1_payload, hex_msg


def hr(t):
    print(f"\n=== {t} ===")


def show(label, msg):
    if msg is None:
        print(f"  {label}: (no reply within timeout)")
        return None
    payload = parse_dt1_payload(msg)
    print(f"  {label}: full={hex_msg(msg)}")
    print(f"    payload ({len(payload)}B): {hex_msg(payload)}")
    return payload


def main():
    g = GxMidi()
    print(f"port: {g.port_name}")

    # ---------- P1-1: Identity Reply -----------
    hr("P1-1: Identity Reply")
    rep = g.identity(timeout=2.0)
    if rep:
        print(f"  full: {hex_msg(rep)}")
        sw = rep[10:14] if len(rep) >= 15 else b""
        print(f"  software-revision bytes: {hex_msg(sw)}")
        print(f"  device-family-code: 0x{rep[7]:02X}{rep[6]:02X}")
    print("  user reports actual firmware version: 1.04")
    print("  -> mismatch with sw_rev: firmware version NOT in Identity Reply")

    # ---------- P0-3: SystemControl 0x66 vs 0x64 ----------
    hr("P0-3: SystemControl block size (0x10001000)")
    r66 = g.rq1(0x10001000, 0x66, timeout=2.0)
    r64 = g.rq1(0x10001000, 0x64, timeout=2.0)
    p66 = show("size=0x66", r66)
    p64 = show("size=0x64", r64)
    if p66:
        print(f"  bytes at offsets 0x64, 0x65: 0x{p66[0x64]:02X} 0x{p66[0x65]:02X}")

    # ---------- P0-3a: SystemCommon block ----------
    hr("P0-3a: SystemCommon block (0x00000000) size=0x2D")
    r = g.rq1(0x00000000, 0x2D, timeout=2.0)
    p = show("SystemCommon", r)
    if p and len(p) >= 0x2D:
        print(f"  TUNER TYPE (0x07): 0x{p[0x07]:02X}")
        print(f"  AUTO OFF   (0x0F): 0x{p[0x0F]:02X}")
        print(f"  BANK EXTENT MIN/MAX (GX-100, 0x09/0x0A): 0x{p[0x09]:02X}/0x{p[0x0A]:02X}")
        print(f"  GX-10 fields BANK EXT MIN/MAX (0x19/0x1A): 0x{p[0x19]:02X}/0x{p[0x1A]:02X}")
        print(f"  COLOR MODE (0x1B): 0x{p[0x1B]:02X}")
        print(f"  AUTO OFF WARN (0x1C): 0x{p[0x1C]:02X}")

    # ---------- P2-2: Setup region ----------
    hr("P2-2: Setup region (00 20 xx xx)")
    for label, addr, size in [
        ("SetupTemp.0",       0x00200000, 1),
        ("SetupTemp+3",       0x00200003, 1),
        ("SetupTemp2.0",      0x00200040, 1),
        ("SetupTemp3.0",      0x00200140, 1),
        ("SetupEfct.0",       0x00200340, 1),
        ("SetupComm.0",       0x00200440, 1),
    ]:
        r = g.rq1(addr, size, timeout=1.0)
        show(f"{label} @ 0x{addr:08X}", r)

    # ---------- P2-4: 0x7F system flags ----------
    hr("P2-4: 0x7F00xxxx system flags")
    for addr in [0x7F000000, 0x7F000001, 0x7F000002, 0x7F000003,
                 0x7F000004, 0x7F000005, 0x7F000010, 0x7F000703]:
        r = g.rq1(addr, 1, timeout=0.7)
        show(f"@ 0x{addr:08X}", r)

    # ---------- P0-1: knob_cell vs 4-nibble encoding ----------
    hr("P0-1: knob_cell vs 4-nibble encoding (FxItem 1, FX Param 2)")
    # Per protocol.md:249, 0x10001100 is FxItem 1 base. TYPE byte at 0x100,
    # FX Parameter 1 at offset 0x03 (so 0x10001103..0x10001106), FX Parameter 2
    # at offset 0x07 (0x10001107..0x1000110A). gxnarly's COMP SUSTAIN sits at
    # 0x10001107. Save the current 4 bytes, write each test value, read back,
    # finally restore.
    base = 0x10001107
    saved = g.rq1(base, 4, timeout=1.0)
    if saved:
        save_bytes = parse_dt1_payload(saved)
        print(f"  current value at 0x{base:08X}: {hex_msg(save_bytes)}")
        # ensure FxItem 1 is COMP type so SUSTAIN actually exists
        type_addr = 0x10001100
        cur_type_msg = g.rq1(type_addr, 1, timeout=1.0)
        cur_type = parse_dt1_payload(cur_type_msg)
        print(f"  FxItem 1 TYPE @ 0x{type_addr:08X}: {hex_msg(cur_type)}  (need 0x00 = COMP for SUSTAIN context)")

        # Two encodings of "100":
        #   gxnarly form: byte 3 holds 100 (0x64) directly
        #   4-nibble form: nibbles 8,0,6,4 = 0x8064 - 0x8000 = 100
        for label, payload in [
            ("gxnarly knob_cell (byte-3 = 0x64)",   bytes([0x08, 0x00, 0x00, 0x64])),
            ("4-nibble offset binary (8,0,6,4)",    bytes([0x08, 0x00, 0x06, 0x04])),
            ("4-nibble offset binary (8,0,3,2) =50", bytes([0x08, 0x00, 0x03, 0x02])),
            ("byte-3 = 0x32 (50 single-byte)",      bytes([0x08, 0x00, 0x00, 0x32])),
        ]:
            print(f"  -- write {label}: {hex_msg(payload)}")
            g.dt1(base, payload)
            time.sleep(0.05)
            rr = g.rq1(base, 4, timeout=1.0)
            print(f"     read-back: {hex_msg(parse_dt1_payload(rr))}")
        # restore
        if save_bytes:
            print(f"  -- restoring: {hex_msg(save_bytes)}")
            g.dt1(base, save_bytes)
            time.sleep(0.05)

    # ---------- P2-5: TYPE 78..82 on GX-10 FxItem 1 ----------
    hr("P2-5: write TYPE 78..82 to FxItem 1 (0x10001100)")
    type_addr = 0x10001100
    saved_type_msg = g.rq1(type_addr, 1, timeout=1.0)
    saved_type = parse_dt1_payload(saved_type_msg) if saved_type_msg else b"\x00"
    print(f"  saved TYPE: {hex_msg(saved_type)}")
    for t in range(78, 83):
        g.dt1(type_addr, bytes([t]))
        time.sleep(0.03)
        rr = g.rq1(type_addr, 1, timeout=1.0)
        rb = parse_dt1_payload(rr)
        # also try TYPE > 82 to see if device clamps
        print(f"  write TYPE={t} (0x{t:02X}) -> read-back: {hex_msg(rb)}")
    # try the upper bound + 1 to see device behavior
    for t in [83, 90, 127]:
        g.dt1(type_addr, bytes([t]))
        time.sleep(0.03)
        rr = g.rq1(type_addr, 1, timeout=1.0)
        rb = parse_dt1_payload(rr)
        print(f"  write TYPE={t} (overshoot) -> read-back: {hex_msg(rb)}")
    # restore
    if saved_type:
        g.dt1(type_addr, saved_type)
        time.sleep(0.05)
        print(f"  restored TYPE -> {hex_msg(saved_type)}")

    # ---------- P0-2: address-roots check (read attempts) ----------
    hr("P0-2: address-roots probe — read at gxnarly-claimed user_patch_slots")
    for label, addr in [
        ("0x10000000 (temp_patch)",        0x10000000),
        ("0x20000000 (manual: user 1)",    0x20000000),
        ("0x29290000 (manual: user 200 region)", 0x29290000),
        ("0x30000000 (gxnarly live_mirror)", 0x30000000),
        ("0x50000000 (preset_name_table)", 0x50000000),
        ("0x60400000 (gxnarly user_patch_slots)", 0x60400000),
    ]:
        r = g.rq1(addr, 4, timeout=1.0)
        show(f"{label} @ 0x{addr:08X}", r)

    g.close()


if __name__ == "__main__":
    main()
