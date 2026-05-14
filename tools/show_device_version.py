"""Print everything we can read about the connected GX-10 / GX-100 over MIDI.

Reads the Universal Identity Reply plus the two firmware-capability bytes
at 0x7F000000 and 0x7F000003. Does NOT distinguish the exact firmware
(major, minor) — that's not on the wire — but identifies the capability
level Roland uses internally to gate BTS compatibility.

Backed by docs/firmware_versions.md §"Firmware capability fingerprint".

Usage:
    python tools/show_device_version.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_identity_request
import midi_sniff
from example_lib import GX10Session


# BTS macOS version → (communicationLevel, communicationRevision) it expects.
# Extracted from each bundle's Resources/html/js/config/product_setting.js.
BTS_VERSION_REQUIREMENTS = {
    "v1.0.0": (3, 0),
    "v1.0.2": (4, 0),
}


def parse_identity_reply(raw: bytes):
    """Decode a Universal Identity Reply (F0 7E <dev> 06 02 ... F7).

    Returns a dict, or None if `raw` isn't an identity reply.
    """
    if len(raw) < 15 or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if raw[1] != 0x7E or raw[3] != 0x06 or raw[4] != 0x02:
        return None
    return {
        "device_id":    raw[2],
        "manufacturer": raw[5],
        "family":       (raw[7] << 8) | raw[6],
        "model":        (raw[9] << 8) | raw[8],
        "sw_revision":  bytes(raw[10:14]),
    }


def collect_identity_reply(timeout=1.0):
    """Send identity request, wait for the reply on the sniffer.

    The reply comes back on a different code path than DT1 (RQ1 has an
    address match; identity replies don't), so GX10Session.request can't
    be used directly. We do it by hand with the same backend.
    """
    sess = GX10Session()
    try:
        with sess.lock:
            sess.events.clear()
        sess.send(build_identity_request())
        deadline = time.time() + timeout
        while time.time() < deadline:
            with sess.lock:
                for e in list(sess.events):
                    p = parse_identity_reply(e)
                    if p is not None:
                        return p, sess
            time.sleep(0.02)
        return None, sess
    except Exception:
        try: sess.out.close()
        except Exception: pass
        try: sess.sniffer.close()
        except Exception: pass
        raise


def main():
    print("Probing GX-10 / GX-100…\n")

    reply, sess = collect_identity_reply()
    if reply is None:
        print("ERROR: no identity reply received within 1 s", file=sys.stderr)
        sys.exit(2)

    # Decode product flag (sw_revision[0])
    sw_rev = reply["sw_revision"]
    product_byte = sw_rev[0]
    product_name = {0x00: "GX-100", 0x01: "GX-10"}.get(product_byte, f"unknown (0x{product_byte:02X})")

    print(f"Identity Reply")
    print(f"  manufacturer       0x{reply['manufacturer']:02X}  ({'Roland' if reply['manufacturer'] == 0x41 else '?'})")
    print(f"  family             0x{reply['family']:04X}  ({'GX-10/100 family' if reply['family'] == 0x040B else '?'})")
    print(f"  model              0x{reply['model']:04X}")
    print(f"  sw_revision[0..3]  {sw_rev.hex(' ').upper()}")
    print(f"    → product flag   {product_name}")
    if any(sw_rev[1:]):
        print(f"  ⚠ sw_revision[1..3] non-zero (unexpected; reserved on all firmware observed so far)")
    print()

    # Read the firmware capability fingerprint.
    level_b = sess.request(0x7F000000, 1, timeout=1.0)
    rev_b   = sess.request(0x7F000003, 1, timeout=1.0)

    print(f"Firmware capability fingerprint")
    if level_b is None:
        print(f"  0x7F000000  EDITOR_COMMUNICATION_LEVEL     (no reply)")
        level = None
    else:
        level = level_b[0]
        print(f"  0x7F000000  EDITOR_COMMUNICATION_LEVEL     0x{level:02X} ({level})")
    if rev_b is None:
        print(f"  0x7F000003  EDITOR_COMMUNICATION_REVISION  (no reply)")
        rev = None
    else:
        rev = rev_b[0]
        print(f"  0x7F000003  EDITOR_COMMUNICATION_REVISION  0x{rev:02X} ({rev})")
    print()

    # Map to compatible BTS versions
    if level is not None and rev is not None:
        compat = [v for v, req in BTS_VERSION_REQUIREMENTS.items() if req == (level, rev)]
        higher = [v for v, req in BTS_VERSION_REQUIREMENTS.items() if req > (level, rev)]
        lower  = [v for v, req in BTS_VERSION_REQUIREMENTS.items() if req < (level, rev)]
        print(f"BTS compatibility (Mac)")
        if compat:
            print(f"  will connect:    {', '.join(compat)}")
        if higher:
            print(f"  too new (refuses, 'older firmware'): {', '.join(higher)}")
        if lower:
            print(f"  too old (refuses, 'older BTS'):      {', '.join(lower)}")
        print()

    # Inferred firmware family
    print(f"Inferred firmware family")
    if level == 3:
        print(f"  GX-10 firmware ≤ 1.04 (launch family). Exact sub-version (1.00 vs 1.04)")
        print(f"  is NOT exposed on MIDI — read the on-device VERSION menu for that.")
    elif level == 4:
        print(f"  GX-10 firmware ≥ 1.05.")
    else:
        print(f"  Unknown capability level {level}; mapping in docs/firmware_versions.md")
        print(f"  may be out of date.")

    # Be a good citizen — release the input port quickly.
    try: sess.out.close()
    except Exception: pass
    try: sess.sniffer.close()
    except Exception: pass

    # Flush before os._exit — otherwise buffered stdout is lost on some
    # tty configurations.
    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == "__main__":
    main()
