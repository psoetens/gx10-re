"""Detect which Roland device is connected by sending an Identity
Request and parsing the Identity Reply.

Returns one of:
  'GX-10'   — model byte 0x04 (per device's Identity Reply)
  'GX-100'  — model byte 0x03
  None      — couldn't identify

Identity Reply format (Universal Non-Realtime SysEx):
  F0 7E dev 06 02 41 [4 model bytes] [4 version bytes] F7
For the Roland GX series the family is reported in the model bytes.

Both models share Model ID `00 00 00 00` for DT1/RQ1 SysEx (so the
SysEx framing is identical), but the Identity Reply differs at the
family/model byte.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_identity_request
import midi_sniff


def detect_device(port_substr="GX-10", timeout_s=2.0):
    """Return model name string ('GX-10' / 'GX-100') or None."""
    events = []
    lock = threading.Lock()
    in_idx, in_name = midi_sniff.find_port(port_substr)
    if in_idx is None:
        return None
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
    out_idx, _ = find_output_port(port_substr)
    if out_idx is None:
        return None
    out = MidiOut(out_idx)
    time.sleep(0.3)
    out.send_sysex(build_identity_request())
    time.sleep(timeout_s)

    # Look for Identity Reply: F0 7E dev 06 02 41 ll mm ff dd ee mm vv ... F7
    # Both GX-100 and GX-10 share Family 0x0B04 + Model 0x0000, so the
    # only reliable distinguisher in the reply is the version byte:
    #   GX-10 reports version starting with 0x01 (firmware ver 1.x)
    #   GX-100 reports version starting with 0x02 (firmware ver 2.x)
    model = None
    raw_reply = None
    with lock:
        snap = list(events)
    for ev in snap:
        if (len(ev) >= 14 and ev[0] == 0xF0 and ev[1] == 0x7E
                and ev[3] == 0x06 and ev[4] == 0x02 and ev[5] == 0x41):
            raw_reply = ev
            family_hi, family_lo = ev[6], ev[7]
            model_hi, model_lo = ev[8], ev[9]
            ver_major = ev[10]
            if family_hi == 0x0B and family_lo == 0x04 and model_hi == 0 and model_lo == 0:
                if ver_major == 0x01:
                    model = "GX-10"
                elif ver_major == 0x02:
                    model = "GX-100"
            break

    return model, raw_reply


def main():
    model, raw = detect_device()
    if model is None and raw is None:
        print("No Identity Reply received — device offline or BTS holding port")
        sys.exit(2)
    print(f"Detected: {model or '(unknown model)'}")
    if raw is not None:
        print(f"Raw Identity Reply:  {raw.hex().upper()}")
        # Decode the standard fields
        if len(raw) >= 14:
            print(f"  Manufacturer: 0x{raw[5]:02X} (Roland)" if raw[5] == 0x41 else f"  Manufacturer: 0x{raw[5]:02X}")
            print(f"  Family:       0x{raw[6]:02X} 0x{raw[7]:02X}")
            print(f"  Model:        0x{raw[8]:02X} 0x{raw[9]:02X}")
            print(f"  Version:      0x{raw[10]:02X} 0x{raw[11]:02X} 0x{raw[12]:02X} 0x{raw[13]:02X}")
    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
