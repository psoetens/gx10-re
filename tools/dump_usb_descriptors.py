"""Dump GX-10 vendor-mode USB descriptors via libusb-1.0.

Works without disturbing Roland's driver — pyusb only reads cached
descriptors via the Windows USB hub. Control transfers and I/O are
not available unless WinUSB is bound (see docs/usb_vendor_mode.md).

Requires: pip install pyusb libusb-package
"""
import sys

try:
    import libusb_package
    import usb.core
    import usb.util
except ImportError:
    print("Need pyusb + libusb-package: pip install pyusb libusb-package")
    sys.exit(1)


def main():
    backend = libusb_package.get_libusb1_backend()
    dev = usb.core.find(idVendor=0x0582, idProduct=0x0311, backend=backend)
    if dev is None:
        print("ERROR: GX-10 (VID 0582 / PID 0311) not found.")
        sys.exit(2)
    print(dev)


if __name__ == "__main__":
    main()
