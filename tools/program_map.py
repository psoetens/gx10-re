"""Read and modify the GX-10's MIDI Program Map (PcmapPc).

When MAP SELECT (`0x0000_3007`) is set to PROG, the device routes
incoming Program Change messages through a user-defined map of 3
banks × 128 entries. Each entry is a 4-nibble memory # (0..299).

  Bank 1 at `0x0010_0000`   (Bank Select MSB = 0)
  Bank 2 at `0x0010_0400`   (Bank Select MSB = 1)
  Bank 3 at `0x0010_0800`   (Bank Select MSB = 2)

Each bank addresses 0x400 bytes of Roland address space — but only
the bytes with low-byte ≤ 0x7F are valid (the 7-bit address rule
documented in `docs/protocol.md` §3.1.1). 128 entries × 4 bytes per
entry = 512 bytes of data; the four 0x80-byte gaps between the
0x100-aligned blocks are how Roland fits the data into 7-bit-clean
addresses.

Decoding: each 4-byte entry holds memory # 0..299 as 4 nibbles,
big-endian. value = (b0<<12) | (b1<<8) | (b2<<4) | b3, with each
byte's high nibble being zero.

Per-device totals (see `docs/firmware_versions.md`):

  * GX-10:  297 usable = 198 user (66 banks × 3) + 99 preset
            (33 banks × 3) with NIU at raw 198, 199, 299.
  * GX-100: 300 usable = 200 user (50 banks × 4) + 100 preset
            (25 banks × 4).

Usage:
    python tools/program_map.py                # show MAP SELECT + all 3 banks
    python tools/program_map.py --bank 1       # just bank 1
    python tools/program_map.py --json         # JSON output
    python tools/program_map.py --set 1 5 17   # bank 1, PC#5 → memory 17
    python tools/program_map.py --reset        # write identity defaults to all 3 banks

The --reset action writes the identity mapping bank 1 PC#1..128 →
memory 0..127, bank 2 PC#1..128 → memory 128..255, bank 3 PC#1..128
→ memory 256..299 (with the tail clamped at 299). This is a
practical "reset to a known monotone layout" — it is NOT necessarily
identical to Roland's factory-init pattern, which we have not
captured. Use at your own risk; verify against BTS before relying.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import GX10Session


BANK_BASE = {1: 0x00100000, 2: 0x00100400, 3: 0x00100800}
ENTRIES_PER_BANK = 128
BYTES_PER_ENTRY = 4
MAP_SELECT_ADDR = 0x00003007
MEMORY_MIN, MEMORY_MAX = 0, 299


def encode_memory(n: int) -> bytes:
    """4-nibble big-endian encoding of a memory # in [0, 0xFFFF]."""
    if not (0 <= n <= 0xFFFF):
        raise ValueError(f"memory # {n} out of range 0..0xFFFF")
    return bytes([(n >> 12) & 0xF, (n >> 8) & 0xF,
                  (n >> 4) & 0xF, n & 0xF])


def decode_memory(b: bytes) -> int:
    return ((b[0] & 0xF) << 12) | ((b[1] & 0xF) << 8) \
         | ((b[2] & 0xF) << 4) | (b[3] & 0xF)


def memory_label(n: int) -> str:
    """Annotate a memory # with the GX-10 bank/patch label per chart.

    GX-10: raw 0..197 → U01-1..U66-3 (3 patches/bank);
           raw 198, 199, 299 → NIU;
           raw 200..298 → P01-1..P33-3.
    (GX-100 uses 4 patches/bank — not labelled here.)"""
    if n in (198, 199, 299):
        return "NIU"
    if 0 <= n <= 197:
        bank, slot = divmod(n, 3)
        return f"U{bank+1:02d}-{slot+1}"
    if 200 <= n <= 298:
        bank, slot = divmod(n - 200, 3)
        return f"P{bank+1:02d}-{slot+1}"
    return "?"


def entry_addr(bank: int, pc: int) -> int:
    """Convert a (bank, PC#) into a 7-bit-clean RQ1/DT1 address.

    Logical offset L = (pc-1) * 4 (bytes from bank base). The address
    space wraps the upper-nibble of the low byte through the next
    0x100 boundary, so:

        addr = base + (L // 0x80) * 0x100 + (L % 0x80)

    For pc=33 (L=128), this gives base + 0x100 instead of base + 0x80
    (which would have low-byte > 0x7F)."""
    L = (pc - 1) * BYTES_PER_ENTRY
    return BANK_BASE[bank] + (L // 0x80) * 0x100 + (L % 0x80)


def read_bank(sess, bank: int) -> list[int]:
    """Read 128 entries from one bank.

    Each entry is 4 bytes. We read 16 entries (= 64 bytes = 0x40,
    7-bit-clean) at a time. 8 chunks cover the whole bank, with
    each chunk's start address routed through the 7-bit gaps
    (offsets 0x00, 0x40, 0x100, 0x140, 0x200, 0x240, 0x300, 0x340).

    Larger RQ1 chunks would work on the wire but the device splits
    its reply into multiple DT1s, and example_lib.GX10Session.request
    only returns the first one — so we keep chunks small enough that
    each RQ1 yields exactly one DT1."""
    base = BANK_BASE[bank]
    payload = bytearray()
    for chunk_off in (0x000, 0x040, 0x100, 0x140, 0x200, 0x240, 0x300, 0x340):
        b = sess.request(base + chunk_off, 0x40, timeout=1.0)
        if b is None or len(b) != 0x40:
            raise RuntimeError(
                f"failed to read bank {bank} chunk at 0x{base + chunk_off:08X} "
                f"(got {len(b) if b else 0} bytes, expected 64)")
        payload.extend(b)
    return [decode_memory(payload[i * 4:(i + 1) * 4])
            for i in range(ENTRIES_PER_BANK)]


def write_entry(sess, bank: int, pc: int, memory: int):
    """Write one PC# → memory mapping. pc is 1..128, memory is 0..299."""
    if bank not in BANK_BASE:
        raise ValueError(f"bank must be 1, 2, or 3 (got {bank})")
    if not (1 <= pc <= ENTRIES_PER_BANK):
        raise ValueError(f"PC# must be 1..{ENTRIES_PER_BANK} (got {pc})")
    if not (MEMORY_MIN <= memory <= MEMORY_MAX):
        raise ValueError(f"memory # must be {MEMORY_MIN}..{MEMORY_MAX} (got {memory})")
    sess.write(entry_addr(bank, pc), encode_memory(memory))


def reset_defaults(sess):
    """Write the GX-10 factory-default program map to all 3 banks.

    Each bank covers one third of the GX-10's 297 patches (99 patches
    per bank, matching the device's 3-patches-per-bank layout):

      Bank 1: PC#1..99  → memory 0..98   (U01-1 .. U33-3)
              PC#100..128 → memory 98 (clamped at U33-3)
      Bank 2: PC#1..99  → memory 99..197 (U34-1 .. U66-3)
              PC#100..128 → memory 197 (clamped at U66-3)
      Bank 3: PC#1..99  → memory 200..298 (P01-1 .. P33-3)
              PC#100..128 → memory 298 (clamped at P33-3)

    NIU slots (raw 198, 199, 299) are deliberately skipped — bank 2's
    user range ends at 197, bank 3 starts at 200, and bank 3's tail
    clamps at 298. This matches what the device returns out-of-the-
    box. On a GX-100 the layout would differ (4 patches/bank); this
    reset is GX-10-specific."""
    print("Resetting program map to GX-10 factory layout "
          "(3 × 99 patches + tail-clamp at each bank's last valid memory) …",
          file=sys.stderr)
    bank_ranges = {
        1: (0, 98),     # user U01-1 .. U33-3
        2: (99, 197),   # user U34-1 .. U66-3
        3: (200, 298),  # preset P01-1 .. P33-3
    }
    for bank in (1, 2, 3):
        lo, hi = bank_ranges[bank]
        for pc in range(1, ENTRIES_PER_BANK + 1):
            # PCs 1..99 map linearly; PCs 100..128 saturate at hi.
            target = min(lo + (pc - 1), hi)
            write_entry(sess, bank, pc, target)
            time.sleep(0.005)
        print(f"  bank {bank} done (PC#1..99 → {lo}..{hi}, "
              f"PC#100..128 clamped to {hi})", file=sys.stderr)


def read_map_select(sess):
    b = sess.request(MAP_SELECT_ADDR, 1, timeout=1.0)
    return b[0] if b else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bank", type=int, choices=(1, 2, 3),
                    help="show only this bank")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--set", nargs=3, metavar=("BANK", "PC", "MEMORY"),
                    type=int, help="write one entry: --set <bank> <pc#> <memory#>")
    ap.add_argument("--reset", action="store_true",
                    help="overwrite all 3 banks with the identity mapping")
    args = ap.parse_args()

    sess = GX10Session()

    if args.set:
        bank, pc, memory = args.set
        write_entry(sess, bank, pc, memory)
        time.sleep(0.1)
        rb = sess.request(entry_addr(bank, pc), 4, timeout=1.0)
        if rb is None:
            print(f"WARN: write to bank {bank} PC#{pc} sent, but readback failed",
                  file=sys.stderr)
            import os; sys.stdout.flush(); os._exit(2)
        rb_val = decode_memory(rb)
        ok = rb_val == memory
        verdict = "VERIFIED" if ok else f"WARN: readback {rb_val} != sent {memory}"
        print(f"bank {bank} PC#{pc} → memory {memory} ({memory_label(memory)}) — {verdict}")
        import os; sys.stdout.flush(); os._exit(0 if ok else 1)

    if args.reset:
        reset_defaults(sess)
        print("Done. Re-run without --reset to verify.")
        import os; sys.stdout.flush(); os._exit(0)

    # Default: list MAP SELECT + bank tables
    ms = read_map_select(sess)
    ms_label = {0: "FIX", 1: "PROG"}.get(ms, f"raw {ms}")
    print(f"MAP SELECT (0x{MAP_SELECT_ADDR:08X}): {ms_label}")
    print()

    output = {"map_select": {"raw": ms, "label": ms_label}, "banks": {}}
    banks = (args.bank,) if args.bank else (1, 2, 3)
    for bank in banks:
        entries = read_bank(sess, bank)
        output["banks"][str(bank)] = entries
        if args.json:
            continue
        print(f"=== Bank {bank}  (base 0x{BANK_BASE[bank]:08X}) ===")
        # 4 columns of 32 rows
        rows_per_col = 32
        for row in range(rows_per_col):
            cells = []
            for col in range(4):
                idx = col * rows_per_col + row
                if idx >= ENTRIES_PER_BANK:
                    continue
                pc = idx + 1
                m = entries[idx]
                cells.append(f"PC{pc:>3d}→{m:>3d} ({memory_label(m):<6s})")
            print("   ".join(cells))
        print()

    if args.json:
        print(json.dumps(output, indent=2))

    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == "__main__":
    main()
