"""Probe whether 0x7F000703 = 0x01 unlocks any device-side broadcasts.

Background:
- Windows BTS capture (reports/bts_capture_findings.md §1) saw BTS write
  0x7F000703 = 0x00 then 0x01 at startup, mirroring the 0x7F000001
  editor-attach pattern.
- Linux probe could not read 0x7F000703 without the editor-attach bit set.
- Hypothesis: 0x7F000703 = 0x01 may activate a separate broadcast
  channel — perhaps the audio-level meter the user previously
  searched for and we couldn't locate.

Test:
1. Open passive listener.
2. Read 0x7F000703 baseline (likely silent without attach bit).
3. Set 0x7F000001 = 0x01 (editor-attach), then 0x7F000703 = 0x01.
4. Listen 10 s for any unsolicited DT1.
5. Restore 0x7F000703 = 0x00, 0x7F000001 = 0x00.
6. Report.

Result (2026-05-15 macOS run, live guitar signal during listen):
**HYPOTHESIS REFUTED.** Setting 0x7F000703 = 0x01 after editor-attach
does NOT unlock an audio-meter broadcast. The only device-originated
DT1 stream that appears once editor-attach is set is at 0x10000154
(the 8-byte chain-state register, chart-documented in gaps.md §10),
which broadcasts on chain edits / footswitch toggles — independent
of input audio. If there is an SysEx-side audio meter, it lives
behind a different gate.
"""
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_io import GxMidi, parse_dt1_payload, hex_msg


def collect(g, secs, label):
    print(f"\n  [{label}] listening {secs}s ...")
    g.drain()
    by_addr = defaultdict(list)
    end = time.monotonic() + secs
    while time.monotonic() < end:
        for msg in g.drain():
            if len(msg) < 14 or msg[8] != 0x12:
                continue
            addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
            payload = bytes(msg[13:-2])
            by_addr[addr].append(payload)
        time.sleep(0.005)
    if not by_addr:
        print(f"  [{label}] (silent)")
    else:
        for addr in sorted(by_addr):
            payloads = by_addr[addr]
            print(f"  [{label}] 0x{addr:08X}  {len(payloads)} events  "
                  f"sample={hex_msg(payloads[0])}{'...' if len(payloads)>1 else ''}")
    return by_addr


def main():
    g = GxMidi()
    print(f"port: {g.port_name}")

    print("\n=== 1. baseline read of 0x7F000703 (no handshake) ===")
    r = g.rq1(0x7F000703, 1, timeout=1.0)
    print(f"  reply: {hex_msg(r)}")

    print("\n=== 2. listen quiet for 5s (baseline broadcasts) ===")
    base = collect(g, 5.0, "baseline")

    print("\n=== 3. set editor-attach bit 0x7F000001 = 0x01 ===")
    g.dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.05)
    r = g.rq1(0x7F000001, 1, timeout=1.0)
    print(f"  read-back 0x7F000001: {hex_msg(r)}")

    after_attach = collect(g, 3.0, "after-attach")

    print("\n=== 4. now read 0x7F000703 with attach bit set ===")
    r = g.rq1(0x7F000703, 1, timeout=1.0)
    print(f"  reply: {hex_msg(r)}")

    print("\n=== 5. write 0x7F000703 = 0x00 then 0x01 (mirror BTS pattern) ===")
    g.dt1(0x7F000703, bytes([0x00]))
    time.sleep(0.05)
    g.dt1(0x7F000703, bytes([0x01]))
    time.sleep(0.05)
    r = g.rq1(0x7F000703, 1, timeout=1.0)
    print(f"  read-back 0x7F000703: {hex_msg(r)}")

    print("\n=== 6. listen 10s for any unsolicited broadcasts ===")
    after_unlock = collect(g, 10.0, "post-unlock")

    print("\n=== 7. restore 0x7F000703 = 0x00 and 0x7F000001 = 0x00 ===")
    g.dt1(0x7F000703, bytes([0x00]))
    time.sleep(0.05)
    g.dt1(0x7F000001, bytes([0x00]))
    time.sleep(0.05)

    g.close()

    # Summary
    new_addrs = set(after_unlock.keys()) - set(base.keys()) - set(after_attach.keys())
    print()
    print("=== summary ===")
    print(f"  baseline (no handshake) emitted: {len(base)} address(es)")
    print(f"  after attach=1            emitted: {len(after_attach)} address(es)")
    print(f"  after attach=1 + 703=1    emitted: {len(after_unlock)} address(es)")
    if new_addrs:
        print(f"  NEW addresses unlocked by 0x7F000703=1: {sorted(f'0x{a:08X}' for a in new_addrs)}")
    else:
        print(f"  no new broadcast addresses unlocked by 0x7F000703=1")


if __name__ == "__main__":
    main()
