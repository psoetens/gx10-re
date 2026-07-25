#!/usr/bin/env python3
"""Can a user memory's NAME be rewritten in place, without rewriting the
whole patch?

An editor wants "rename this memory" to persist to the slot itself, not
just to the edit buffer at 0x10000000 — but it must not drag any other
in-flight edit along with it. `docs/protocol.md` §5.6 shows BTS writing
into memory space (its RESTORE issues DT1 sequences at
`0x20000000 + memory_n * 0x60000`), so writes there are supported; what
was never probed is whether a SINGLE 16-byte DT1 at a memory's name
offset lands cleanly and leaves the other ~16 KB untouched.

The probe, against one slot:

  1. read every documented block of the memory           (before)
  2. read the name catalogue entry at 0x50000000         (before)
  3. DT1 16 ASCII bytes at the memory's offset 0x0000
  4. re-read body + catalogue                            (after)
  5. diff every sampled block, reporting any byte outside the name
  6. write the original name back, and verify the restore

Non-destructive by design: the original name is captured first and put
back at the end (`--no-restore` opts out). Nothing else is ever written.

Usage:
    python3 tools/probe_memory_name_write.py --slot 184
    python3 tools/probe_memory_name_write.py --slot 184 --name "PROBE TEST"

The device is a single-client MIDI port — quit any editor (gxnarly, BTS)
before running, or the reads will interleave.
"""
import argparse
import sys
import time

from midi_io import GxMidi, parse_dt1_payload

MEMORY_BASE = 0x20000000
MEMORY_STRIDE_LINEAR = 6 << 14      # 0x60000 in chart hex
CATALOGUE_BASE = 0x50000000
BODY_SIZE = 0x4000
CHUNK = 0x100                        # 7-bit-clean catalogue request size
BODY_CHUNK = 0x40                    # granularity the device answers at
NAME_LEN = 0x10


def to_linear(addr: int) -> int:
    return (((addr >> 24) & 0x7F) << 21 | ((addr >> 16) & 0x7F) << 14
            | ((addr >> 8) & 0x7F) << 7 | (addr & 0x7F))


def to_wire(lin: int) -> int:
    return (((lin >> 21) & 0x7F) << 24 | ((lin >> 14) & 0x7F) << 16
            | ((lin >> 7) & 0x7F) << 8 | (lin & 0x7F))


def memory_addr(n: int) -> int:
    """Chart-hex address of memory N. Stride is added in 7-bit-per-byte
    arithmetic, not raw int math — see `probe_user_memory_names_burst.py`."""
    return to_wire(to_linear(MEMORY_BASE) + n * MEMORY_STRIDE_LINEAR)


def offset_addr(base: int, chart_offset: int) -> int:
    """`base` advanced by a CHART offset, in 7-bit-per-byte arithmetic.

    Both operands are chart hex (each byte 0..0x7F), so the offset is
    converted to linear before adding — `0x000140` means 192 bytes in,
    not 320. Mixing the two conventions is what made an earlier version
    of this probe request unreachable addresses."""
    return to_wire(to_linear(base) + to_linear(chart_offset))


def encode_name(name: str) -> bytes:
    """16 printable-ASCII bytes, space-padded — the device's name field."""
    clean = "".join(c if 0x20 <= ord(c) <= 0x7E else " " for c in name)
    return clean[:NAME_LEN].ljust(NAME_LEN).encode("ascii")


# The documented per-memory block starts (protocol.md §5.6). These are
# addresses the device actually answers at; arbitrary offsets between
# them are unreachable (only 7-bit-safe addresses emit DT1s, §3.1.1),
# which is why this probe samples blocks rather than walking the body.
SAMPLE_BLOCKS = [
    ("common",   0x000000),
    ("led",      0x000140),
    ("assign1",  0x000200),
    ("assign2",  0x000240),
    ("assign20", 0x000B40),
    ("efct",     0x000F00),
    ("fxItem1",  0x001100),
    ("fxItem2",  0x001300),
    ("fxItem20", 0x003700),
]


def read_blocks(gx: GxMidi, base: int, label: str) -> dict:
    """Sample every documented block of one memory.

    Not a full 16 KB dump: the device replies only at its own record
    boundaries (a `size=0x40` request returns a 63-byte record, per §3.4),
    and most offsets in between are unreachable padding — walking the body
    dies within the first few hundred bytes. Sampling the §5.6 block list
    covers the name's own block plus one of every other kind, across the
    whole memory, which is what "did the write disturb anything else?"
    actually needs. Returns {} on any missing reply."""
    out = {}
    for name, off in SAMPLE_BLOCKS:
        msg = gx.rq1(offset_addr(base, off), BODY_CHUNK, timeout=1.5)
        payload = parse_dt1_payload(msg)
        if not payload:
            print(f"  ! {label}: no reply for {name} (chart offset 0x{off:06X})")
            return {}
        out[name] = payload
        time.sleep(0.004)
    return out


def read_catalogue_name(gx: GxMidi, n: int) -> str:
    """The slot's entry in the read-only name catalogue — this is what a
    sidebar's catalogue sweep sees, which may or may not track a memory
    write."""
    # 8 names per chunk, NOT 16: a `size=0x100` catalogue request returns
    # a 128-byte DT1 = 8 × 16-byte names (§3.5 — the request size is a
    # ceiling, the device picks the record). Dividing by 16 addressed the
    # wrong chunk and got silence.
    chunk_index, within = divmod(n, 8)
    msg = gx.rq1(CATALOGUE_BASE + chunk_index * CHUNK, CHUNK, timeout=1.5)
    payload = parse_dt1_payload(msg)
    if len(payload) < (within + 1) * NAME_LEN:
        return "(no reply)"
    raw = payload[within * NAME_LEN:(within + 1) * NAME_LEN]
    return raw.decode("ascii", errors="replace").rstrip()


def diff_offsets(before: bytes, after: bytes) -> list:
    return [i for i in range(min(len(before), len(after))) if before[i] != after[i]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, required=True,
                    help="user memory index V (0-based; U62-2 on a GX-10 = 184)")
    ap.add_argument("--name", default="ZZPROBE",
                    help="temporary name to write (restored afterwards)")
    ap.add_argument("--no-restore", action="store_true",
                    help="leave the probe name in place")
    args = ap.parse_args()

    gx = GxMidi()
    print(f"port: {gx.port_name}")
    if gx.identity() is None:
        print("! no identity reply — is the device in class-compliant USB mode?")
        return 1

    base = memory_addr(args.slot)
    print(f"memory {args.slot} base = 0x{base:08X}\n")

    before = read_blocks(gx, base, "before")
    if not before:
        return 1
    original = before["common"][:NAME_LEN].decode("ascii", errors="replace")
    cat_before = read_catalogue_name(gx, args.slot)
    print(f"  memory name    : {original!r}")
    print(f"  catalogue name : {cat_before!r}\n")

    print(f"writing {args.name!r} to 0x{base:08X} (16 bytes, name field only)")
    gx.dt1(base, encode_name(args.name))
    time.sleep(0.35)

    after = read_blocks(gx, base, "after")
    if not after:
        return 1
    cat_after = read_catalogue_name(gx, args.slot)

    outside = []
    for name, _off in SAMPLE_BLOCKS:
        b, a = before[name], after[name]
        start = NAME_LEN if name == "common" else 0
        for i in range(min(len(b), len(a))):
            if i >= start and b[i] != a[i]:
                outside.append(f"{name}+0x{i:02X}")

    print(f"\n  memory name    : {after['common'][:NAME_LEN].decode('ascii', 'replace')!r}")
    print(f"  catalogue name : {cat_after!r}")
    print(f"  blocks sampled : {len(SAMPLE_BLOCKS)}")
    print(f"  changed outside the name field : {len(outside)}"
          + (f" -> {outside[:12]}" if outside else ""))

    persisted = after["common"][:NAME_LEN].decode("ascii", "replace").rstrip() == args.name.strip()
    print("\nVERDICT")
    print(f"  name write persisted to memory : {'YES' if persisted else 'NO'}")
    print(f"  only the name changed          : {'YES' if not outside else 'NO'}")
    print(f"  catalogue tracks the write     : "
          f"{'YES' if cat_after.strip() == args.name.strip() else 'NO'}")

    if not args.no_restore:
        print(f"\nrestoring {original.rstrip()!r}")
        gx.dt1(base, encode_name(original))
        time.sleep(0.35)
        back = parse_dt1_payload(gx.rq1(base, CHUNK, timeout=1.5))[:NAME_LEN]
        ok = back.decode("ascii", "replace") == original
        print(f"  restored: {'YES' if ok else 'NO'} "
              f"({back.decode('ascii', 'replace')!r})")

    gx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
