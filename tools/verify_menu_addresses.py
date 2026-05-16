"""Quick live verification that menu addresses from the MIDI
Implementation chart are readable via RQ1 on the GX-10.

Reads a curated list of well-known SystemCommon / SystemControl /
SystemMidi / SystemInOut addresses and prints the device's response.
If the chart is correct, every read returns 1 byte (or N bytes for
multi-byte fields) within the documented range.
"""
from __future__ import annotations
import json
import os
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff
from device_id import require_alive_raw


# (address, size, label, expected_range_or_enum)
TARGETS = [
    # SystemCommon (region base 0x00000000)
    (0x00000003, 4, "MEMORY NUMBER", "0..299, 4 nibbles"),
    (0x00000004, 1, "PLAYPAGE MODE", "0..3 (LARGE NUMBER/NAME/CONTROL/CHAIN)"),
    (0x00000006, 1, "TUNER MODE", "0..1 (NORMAL/STREAM)"),
    (0x00000008, 1, "BANK CHANGE MODE", "0..2 (WAIT1/WAIT2/IMMEDIATE)"),
    (0x0000000D, 1, "EXP1 HOLD", "0..1 (OFF/ON)"),
    (0x0000000E, 1, "EXP2 HOLD", "0..1 (OFF/ON)"),
    (0x0000000F, 1, "AUTO OFF", "0..4 (OFF/10H/5H/1H/20MIN)"),
    (0x00000011, 1, "LOCK STATUS", "0..1 (OFF/ON)"),
    (0x00000012, 1, "LOCK: KNOB", "0..1 (OFF/ON)"),
    (0x00000013, 1, "LOCK: TOUCH SCREEN", "0..1 (OFF/ON)"),
    (0x00000014, 1, "LOCK: BUTTON", "0..1 (OFF/ON)"),
    (0x00000015, 1, "LOCK: OUTPUT LEVEL", "0..1 (OFF/ON)"),
    (0x00000016, 1, "DELETE WARNING", "0..1 (OFF/ON)"),
    (0x00000017, 1, "OVERWRITE WARNING", "0..1 (OFF/ON)"),
    (0x00000018, 1, "FX ORDER", "0..1 (BY TYPE/BY NAME)"),
    (0x00000019, 1, "BANK EXTENT MIN (GX-10)", "0..98"),
    (0x0000001A, 1, "BANK EXTENT MAX (GX-10)", "0..98"),
    (0x0000001B, 1, "COLOR MODE", "0..1 (TYPE 1/TYPE 2)"),
    (0x0000001C, 1, "SHOW AUTO OFF WARNING", "0..1 (ON/OFF)"),
    # SystemControl (0x00001000)
    (0x00001034, 1, "CONTROL MODE", "0..3 (MEMORY/MANUAL/BANK_NUM/MANUAL2)"),
    (0x00001063, 1, "GLOBAL EQ SW", "0..1 (OFF/ON)"),
    (0x00001064, 1, "Down&Up Function", "0..3 (OFF/TUNER/DOWN/UP)"),
    (0x00001065, 1, "Up&Ctl1 Function", "0..3 (OFF/MANUAL/DOWN/UP)"),
    # SystemMidi (0x00003000)
    (0x00003000, 1, "MIDI RX CHANNEL", "0..16 (1-16, OMNI)"),
    (0x00003002, 1, "MIDI TX CHANNEL", "0..16 (1-16, RX CH)"),
    (0x00003004, 1, "MIDI IN THRU", "0..3 (OFF/MIDI OUT/USB OUT/USB&MIDI)"),
    (0x00003005, 1, "USB IN THRU (GX-100)", "GX-100 only"),
    (0x00003006, 1, "CLOCK OUT", "0..1 (OFF/ON)"),
    (0x00003007, 1, "MAP SELECT", "0..1 (FIX/PROG)"),
    # SystemInOut (0x00004000) — USB SETTINGS
    (0x00004000, 1, "USB MAIN: LEVEL SELECT", ""),
    (0x0000400B, 1, "SYNC CLOCK", ""),
    # SystemEfct (0x00005000)
    (0x00005000, 1, "PHRASE LOOP MODE", "0..1 (MONO/STEREO)"),
    (0x00005001, 1, "PHRASE LOOP REC ACTION", "0..1 (REC>PLAY>DUB / REC>DUB>PLAY)"),
    # SystemPitch (0x00006000)
    (0x00006000, 1, "TUNER OUTPUT", ""),
    (0x00006005, 1, "REF PITCH", ""),
    # MemoryCommon - first MEMORY MIDI 1:CH
    (0x10000035, 1, "MEMORY MIDI 1: CH (temp)", "0..16 (OFF, 1-16)"),
    # SystemControl Ctl1 Function (per MIDI chart 0x1B)
    (0x0000101B, 1, "Ctl1 Function", "0..18 (chart §3.2)"),
    (0x0000101C, 1, "Ctl2 Function", "0..18"),
    # Bank/PcMap
    (0x00100000, 4, "PCMAP BANK1 PC#1 [0]", ""),
    (0x00100004, 4, "PCMAP BANK1 PC#1 [1]", ""),
]


def parse_dt1(msg: bytes):
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7 or msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    return addr, bytes(msg[13:-2])


def main():
    out_idx, _ = midi_send.find_output_port("GX-10")
    in_idx, _ = midi_sniff.find_port("GX-10")
    out = midi_send.MidiOut(out_idx)
    Path("captures/menu_verify").mkdir(parents=True, exist_ok=True)
    sn = midi_sniff.Sniffer(in_idx, Path("captures/menu_verify/sniff.jsonl"), "GX-10")
    sn.open()
    q: "queue.Queue[bytes]" = queue.Queue()
    events = []   # parallel list for require_alive_raw
    def silent(o):
        if o.get("kind") == "sysex":
            try:
                raw = bytes.fromhex(o["hex"])
                q.put(raw)
                events.append(raw)
            except: pass
    sn._emit = silent
    time.sleep(0.3)
    require_alive_raw(out, events)
    events.clear()  # don't leak handshake bytes into the per-target reads

    def get(addr, timeout=0.4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: msg = q.get_nowait()
            except queue.Empty: time.sleep(0.005); continue
            p = parse_dt1(msg)
            if p and p[0] == addr: return p[1]
        return None

    results = []
    try:
        for addr, size, label, doc in TARGETS:
            out.send_sysex(midi_send.build_rq1(addr, size))
            r = get(addr, 0.4)
            if r is None:
                status = "no response"
                value = None
            elif size == 1:
                status = "ok"
                value = r[0]
            elif size == 4:
                # 4-nibble field: signed_decoded = ((((((n0<<4)|n1)<<4)|n2)<<4)|n3) - 0x8000
                if all(b <= 0x0F for b in r):
                    raw = (r[0] << 12) | (r[1] << 8) | (r[2] << 4) | r[3]
                    value = raw - 0x8000
                    status = "ok"
                else:
                    value = r.hex()
                    status = "raw"
            else:
                value = r.hex()
                status = "raw"
            print(f"  0x{addr:08X} {label:<32} = {value!r:<30} [{status}]  {doc}")
            results.append({
                "address": f"0x{addr:08X}",
                "label": label,
                "size": size,
                "value": value,
                "status": status,
                "doc": doc,
            })
        Path("captures/menu_verify/results.json").write_text(
            json.dumps(results, indent=2)
        )
        print(f"\nresults: captures/menu_verify/results.json")
        ok = sum(1 for r in results if r["status"] == "ok")
        nr = sum(1 for r in results if r["status"] == "no response")
        print(f"  ok: {ok}/{len(results)}, no_response: {nr}")
    finally:
        try: out.close()
        except: pass
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
