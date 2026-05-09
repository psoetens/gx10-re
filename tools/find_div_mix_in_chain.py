"""Read all FxItem TYPE bytes in the chain and find any DIVIDER (0x1D),
SPLITTER (0x1E), MIXER (0x1F) entries. If found, dumps their full FxItem
payload so we can identify LOOP LEVEL's address by inspecting the bytes.
"""
from __future__ import annotations
import os
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() /
    "AppData/Local/Packages/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/LocalCache/local-packages/Python313/site-packages"))

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


CHAIN_LIST_BASE = 0x10000F0C
FXITEM_BASE = 0x10001100
FXITEM_STRIDE = 0x200
N_SLOTS = 15  # GX-10 chain max


def parse_dt1(msg):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def main():
    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    sn = midi_sniff.Sniffer(in_idx, Path("captures/bts_loop_level_probe/find.jsonl"), "GX-10")
    sn.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    def silent(o):
        if o.get("kind") == "sysex":
            try: q.put(bytes.fromhex(o["hex"]))
            except: pass
    sn._emit = silent

    def get(addr, timeout=0.6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: msg = q.get_nowait()
            except queue.Empty: time.sleep(0.005); continue
            p = parse_dt1(msg)
            if p and p[0] == addr: return p[1]
        return None

    try:
        # Read each FxItem's TYPE byte
        types = {}
        for slot in range(N_SLOTS):
            base = FXITEM_BASE + slot * FXITEM_STRIDE
            out.send_sysex(midi_send.build_rq1(base, 0x01))
            r = get(base, 0.4)
            if r is None:
                print(f"  slot {slot:2d}: no response")
                types[slot] = None
            else:
                types[slot] = r[0]
                print(f"  slot {slot:2d}: TYPE 0x{r[0]:02X}")

        # Find DIV_MIX trio + LOOPER
        for slot, t in types.items():
            if t in (0x1C, 0x1D, 0x1E, 0x1F):
                base = FXITEM_BASE + slot * FXITEM_STRIDE
                out.send_sysex(midi_send.build_rq1(base, 0x140))
                payload = get(base, 0.6)
                if payload:
                    name = {0x1C: "PHRASE LOOP", 0x1D: "DIVIDER", 0x1E: "SPLITTER", 0x1F: "MIXER"}[t]
                    print(f"\n=== slot {slot} {name} (TYPE 0x{t:02X}) ===")
                    # Print 4-byte param values starting at offset 0x03
                    for off in range(0x03, 0x80, 0x04):
                        if off + 4 > len(payload): break
                        nib = payload[off:off+4]
                        if any(b > 0x0F for b in nib):
                            continue
                        raw = (nib[0] << 12) | (nib[1] << 8) | (nib[2] << 4) | nib[3]
                        # 4-nibble offset binary: signed value = raw - 0x8000
                        signed = raw - 0x8000
                        print(f"  offset 0x{off:02X} (addr 0x{FXITEM_BASE+off:08X}): nibbles={nib.hex()} raw=0x{raw:04X} signed={signed}")
    finally:
        try: out.close()
        except: pass
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
