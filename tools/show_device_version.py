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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import GX10Session
from device_id import require_alive


# BTS macOS version → (communicationLevel, communicationRevision) it expects.
# Extracted from each bundle's Resources/html/js/config/product_setting.js.
BTS_VERSION_REQUIREMENTS = {
    "v1.0.0": (3, 0),
    "v1.0.2": (4, 0),
}


def main():
    sess = GX10Session()
    # Strict sanity check: aborts with diagnostics if the device is
    # unreachable or replies with an unrecognized product flag.
    info = require_alive(sess, verbose=False)

    print(f"Identity Reply")
    print(f"  device_id          0x{info.device_id:02X}")
    print(f"  manufacturer       0x{info.manufacturer:02X}  "
          f"({'Roland' if info.manufacturer == 0x41 else '?'})")
    print(f"  family             0x{info.family:04X}  "
          f"({'GX-10/100 family' if info.family == 0x040B else '?'})")
    print(f"  model              0x{info.model:04X}")
    print(f"  sw_revision[0..3]  {info.sw_revision.hex(' ').upper()}")
    print(f"    → product flag   {info.product}")
    if any(info.sw_revision[1:]):
        print(f"  ⚠ sw_revision[1..3] non-zero (unexpected; reserved on "
              f"all firmware observed so far)")
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
        print(f"  GX-10 firmware ≤ 1.04 (launch family). Exact sub-version "
              f"(1.00 vs 1.04) is NOT exposed on MIDI — read the on-device "
              f"VERSION menu for that.")
    elif level == 4:
        print(f"  GX-10 firmware ≥ 1.05.")
    else:
        print(f"  Unknown capability level {level}; mapping in "
              f"docs/firmware_versions.md may be out of date.")

    # Be a good citizen — release the input port quickly.
    try: sess.out.close()
    except Exception: pass
    try: sess.sniffer.close()
    except Exception: pass

    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == "__main__":
    main()
