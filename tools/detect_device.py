"""Detect which Roland device is connected by sending a Universal
Identity Request and parsing the reply.

Returns one of:
  'GX-10'   — sw_revision[0] = 0x01
  'GX-100'  — sw_revision[0] = 0x00
  None      — couldn't identify

This is a thin wrapper around `device_id.require_alive` (which does
the strict check) — kept around because other tools / docs reference
`detect_device()` by name. New code should import from `device_id`
directly.

CLI:
    python tools/detect_device.py        # prints summary, exit 0/2/3
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from example_lib import GX10Session
from device_id import identify, DeviceUnreachable, ProductInfo


def detect_device(port_substr: str = "GX-10",
                  timeout_s: float = 1.5):
    """Return (model_string, raw_reply_bytes) or (None, None)."""
    try:
        sess = GX10Session(port_substr=port_substr)
    except Exception:
        return None, None
    try:
        info = identify(sess, timeout=timeout_s)
    except DeviceUnreachable:
        return None, None
    finally:
        try: sess.out.close()
        except Exception: pass
        try: sess.sniffer.close()
        except Exception: pass
    return info.product, info.raw_reply


def main():
    model, raw = detect_device()
    if model is None and raw is None:
        print("No Identity Reply received — device offline or another "
              "client (BTS, DAW) is holding the port", file=sys.stderr)
        sys.exit(2)
    print(f"Detected: {model or '(unknown model)'}")
    if raw is not None:
        info = ProductInfo  # for type hint only
        print(f"Raw Identity Reply:  {raw.hex().upper()}")
        if len(raw) >= 14:
            mfr = raw[5]
            print(f"  Manufacturer: 0x{mfr:02X}"
                  + (" (Roland)" if mfr == 0x41 else ""))
            print(f"  Family:       0x{raw[6]:02X} 0x{raw[7]:02X}")
            print(f"  Model:        0x{raw[8]:02X} 0x{raw[9]:02X}")
            print(f"  sw_revision:  0x{raw[10]:02X} 0x{raw[11]:02X} "
                  f"0x{raw[12]:02X} 0x{raw[13]:02X}")
    sys.stdout.flush()
    import os; os._exit(0)


if __name__ == "__main__":
    main()
