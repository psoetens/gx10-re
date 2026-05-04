# GX-10 across Linux, macOS, and iOS — what's known and what's needed

Reframing of the "we need to write a Linux driver" goal. The picture
turns out to be much smaller than expected: the Linux kernel already
has generic Roland-vendor-class support upstream.

## What each OS does today

| OS | Vendor mode supported? | Generic mode supported? | Multi-channel (DRY+MAIN)? |
|----|------------------------|-------------------------|---------------------------|
| **Windows** | yes — Roland's `RDID1261` driver (the one we want to avoid) | yes — Microsoft's built-in USB-Audio class driver | Vendor: yes (4ch). Generic: stereo only. |
| **macOS** | yes — Roland provides a signed vendor driver | yes — built-in USB-Audio class driver | Vendor: yes. Generic: stereo only. |
| **iOS / iPadOS** | **NOT supported** — Roland tells iOS users to switch to GENERIC | yes — built-in | Stereo only. Roland's iOS support article explicitly says: *"change the USB DRIVER setting to GENERIC."* |
| **Linux** | **No Roland driver, ever** | yes — kernel `snd-usb-audio` with already-existing Roland quirks | **Should be yes** — see below |

## Why the GX-10 likely works on Linux out-of-the-box

The mainline Linux kernel (`sound/usb/quirks-table.h` + `sound/usb/implicit.c`) already has:

1. **Catch-all device quirk** for every Roland VID 0x0582 vendor-class device:
   ```c
   /* this catches most recent vendor-specific Roland devices */
   {
       .match_flags = USB_DEVICE_ID_MATCH_VENDOR |
                      USB_DEVICE_ID_MATCH_INT_CLASS,
       .idVendor = 0x0582,
       .bInterfaceClass = USB_CLASS_VENDOR_SPEC,
       QUIRK_DRIVER_INFO {
           .ifnum = QUIRK_ANY_INTERFACE,
           .type = QUIRK_AUTODETECT
       }
   },
   ```
   This tells `snd-usb-audio` to parse the GX-10's vendor-framed
   interfaces as if they were USB-Audio-Class.

2. **Generic Roland implicit-feedback handling** in `sound/usb/implicit.c`:
   ```c
   /* Roland/BOSS implicit feedback with vendor spec class */
   if (USB_ID_VENDOR(chip->usb_id) == 0x0582) {
       ...
   }
   /* Roland/BOSS need full-duplex streams */
   if (USB_ID_VENDOR(chip->usb_id) == 0x0582) {
       ...
   }
   ```
   This fixes sample-rate sync and the "playback must be open for
   capture to work" quirk that BOSS multi-effects have.

The GX-10 is PID 0x0311. It has no PID-specific entry but doesn't need
one — the catch-all + generic implicit-feedback covers it.

A separate user thread on vguitarforums titled *"gx-100 and linux: works!"*
(Dec 2023) confirms the sister device GX-100 (PID 0x0310) operates on
Linux with full DRY+MAIN routing. The GX-10 has the same vendor-mode
USB descriptor structure (4 interfaces, iso 132B/frame on EP 0x8E IN +
EP 0x0D OUT, vendor MIDI on EP 0x03 OUT / 0x84 IN bulk) and should
behave identically.

## The minimal Linux test plan

No reverse engineering needed unless the catch-all path actually fails.
Steps:

```bash
# 1. Confirm the device enumerates
$ lsusb | grep 0582:0311
Bus 002 Device 006: ID 0582:0311 Roland Corp.

# 2. Confirm snd-usb-audio binds it
$ dmesg | tail -20
# Expect lines like:
# usb 2-X: New USB device found, idVendor=0582, idProduct=0311
# usb 2-X: Manufacturer: Roland
# usbcore: registered new interface driver snd-usb-audio
# snd-usb-audio: Found 0582:0311 GX-10

# 3. List ALSA devices
$ arecord -l
$ aplay -l
# Expect: a card "GX-10" with multiple subdevices, 4 capture / 4 playback
# channels (DRY left, DRY right, MAIN left, MAIN right) at 44.1 / 48 kHz.

# 4. Test capture on the DRY channels
$ arecord -D plughw:GX-10 -f S24_3LE -c 4 -r 48000 -d 5 test.wav

# 5. Test MIDI
$ aseqdump -p "GX-10"
# Then poke knobs / press footswitches on the device — events should show.
```

## If it doesn't work — the actual RE workflow

The kernel auto-detect can fall down on devices whose audio class
descriptors aren't standard-compliant. If steps 3-5 above fail, the
RE process is **not "write a driver"**, it's **"add a per-device entry
to `quirks-table.h`"** — typically 10-20 lines.

### Workflow

1. **Capture what the Windows Roland driver does**, since BTS and any
   Windows DAW already exercise the full vendor-mode flow:

   - Install **USBPcap** on Windows (one-time admin install, MS-signed
     kernel driver). It bus-taps the USB host controller and writes a
     `.pcap` file.
   - Open Wireshark, select the USBPcap interface, filter for
     `usb.idVendor == 0x0582`.
   - Trigger an event:
     - Plug the device in (enumeration)
     - Open BTS (descriptor reads, MIDI handshake)
     - Start a DAW capture (set-interface, format-set, isoc streaming)
     - Pluck the guitar (audio frames flow)
   - Save the capture.

2. **Decode the relevant non-standard bits**. Most of the traffic is
   plain USB-Audio Class — only the vendor-specific deviations matter:

   - Any control transfers on Interface 0 with vendor `bRequest` codes —
     these are the bits Linux's auto-detect doesn't know about. Note
     them but skip implementation; if BTS works without them on Windows
     in generic mode, they're not needed.
   - The format-set on Interface 1 / 2: bit-depth, sample rate,
     channel count. Compare to what `snd-usb-audio` would derive from
     the standard descriptors — if they match, the catch-all is enough.
   - Implicit feedback endpoint usage: confirm Interface 1 OUT and
     Interface 2 IN are full-duplex (already handled by the generic
     Roland code in `implicit.c`).

3. **Test on Linux** with that knowledge. If the kernel still refuses
   the multi-channel format, write a small `quirks-table.h` patch:

   ```c
   {
       USB_DEVICE_VENDOR_SPEC(0x0582, 0x0311),
       QUIRK_DRIVER_INFO {
           .vendor_name = "Roland",
           .product_name = "GX-10",
           .ifnum = QUIRK_ANY_INTERFACE,
           .type = QUIRK_COMPOSITE,
           QUIRK_DATA_COMPOSITE {
               { QUIRK_DATA_STANDARD_AUDIO(1) },   /* iface 1 = playback */
               { QUIRK_DATA_STANDARD_AUDIO(2) },   /* iface 2 = capture */
               { QUIRK_DATA_STANDARD_MIDI(3) },    /* iface 3 = MIDI */
               QUIRK_COMPOSITE_END
           }
       }
   },
   ```

   Build the kernel (or just `snd-usb-audio.ko`), `modprobe -r snd-usb-audio &&
   modprobe snd-usb-audio`, retest. Iterate. Submit upstream.

## Why we can ignore Interface 0 (vendor control)

User's observation: BTS works fully in generic mode. So whatever lives
behind Interface 0's vendor commands isn't required for normal editor
or audio operation. It's almost certainly Roland's **firmware-update
channel** — exactly what you'd expect a vendor-specific endpoint to be
on otherwise standard-USB-Audio hardware. Roland's GX-10 firmware
update tool is a separate Windows application (`BOSSGX10Update.exe`
or similar); that's the user of Interface 0.

## Bottom line

- **The driver-RE project is much smaller than the original framing
  suggested.** Most of the "Roland driver" is just standard USB-Audio
  with vendor framing, which Linux already handles.
- **First action is "plug it into Linux and see what happens"**, not
  "capture USB traffic and write a driver".
- USBPcap RE is the fallback if the catch-all path fails, and even
  then the deliverable is a small `quirks-table.h` patch, not a
  kernel module.
- iOS and Linux both effectively run the device in "generic mode" —
  iOS by user setting, Linux by virtue of having no vendor driver.
  The difference: the Linux kernel's existing Roland quirks treat
  vendor-mode descriptors AS IF they were USB-Audio Class, which on
  the GX-100 has been verified to expose DRY+MAIN as separate
  channels. iOS doesn't do this; it requires actual generic mode on
  the device.
