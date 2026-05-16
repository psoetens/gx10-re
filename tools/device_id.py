"""Identity-request helper — confirm device is alive + report product.

Centralised in one place so every device-talking tool can do the
"is the GX-10/GX-100 actually there" check the same way before
proceeding. Stops the "bogus / empty output" failure mode that
happens when the MIDI port is reachable but the device isn't
responding (USB stuck, another client holding it, power-cycle
needed, etc.).

Usage:

    from device_id import require_alive
    sess = GX10Session()
    info = require_alive(sess)        # prints + sys.exit on failure
    # info.product is "GX-10" / "GX-100" / "unknown(0xNN)"
    # tools needing a specific product:
    info = require_alive(sess, allow=["GX-10"])

Lower-level API:

    info = identify(sess, timeout=1.0)   # raises DeviceUnreachable on no reply

Background: `docs/firmware_versions.md` documents the Universal
Identity Reply layout. We inspect `sw_revision[0]` (byte 10 of the
SysEx body) to distinguish GX-10 (0x01) from GX-100 (0x00). The
other fields are returned in `ProductInfo` for tools that need them.
"""
from __future__ import annotations
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import build_identity_request


# Product flag carried in sw_revision[0] of the Universal Identity Reply.
# See `docs/firmware_versions.md` §"Reading the Identity Reply".
PRODUCT_FLAGS = {
    0x00: "GX-100",
    0x01: "GX-10",
}


@dataclass(frozen=True)
class ProductInfo:
    product: str           # "GX-10", "GX-100", or "unknown(0xNN)"
    device_id: int         # SysEx byte 2  (Roland device ID, usually 0x10)
    manufacturer: int      # SysEx byte 5  (0x41 = Roland)
    family: int            # SysEx bytes 6..7 → little-endian (0x040B = GX family)
    model: int             # SysEx bytes 8..9 → little-endian
    sw_revision: bytes     # SysEx bytes 10..13
    raw_reply: bytes       # full F0..F7

    @property
    def is_roland_gx(self) -> bool:
        return self.manufacturer == 0x41 and self.family == 0x040B


class DeviceUnreachable(RuntimeError):
    """Raised when the device fails to reply to an Identity Request."""


def _parse_identity_reply(raw: bytes) -> ProductInfo | None:
    """Decode a Universal Identity Reply (F0 7E <dev> 06 02 ... F7).

    Returns None if `raw` isn't a valid identity reply; otherwise a
    `ProductInfo`.
    """
    if len(raw) < 15 or raw[0] != 0xF0 or raw[-1] != 0xF7:
        return None
    if raw[1] != 0x7E or raw[3] != 0x06 or raw[4] != 0x02:
        return None
    sw_rev = bytes(raw[10:14])
    product = PRODUCT_FLAGS.get(sw_rev[0], f"unknown(0x{sw_rev[0]:02X})")
    return ProductInfo(
        product=product,
        device_id=raw[2],
        manufacturer=raw[5],
        family=(raw[7] << 8) | raw[6],
        model=(raw[9] << 8) | raw[8],
        sw_revision=sw_rev,
        raw_reply=bytes(raw),
    )


def identify(sess, timeout: float = 1.0) -> ProductInfo:
    """Send an Identity Request and return the parsed reply.

    `sess` is a GX10Session-like object with:
      - `sess.send(sysex_bytes)`
      - `sess.events`  — list of incoming SysEx bytes (populated by
                         the underlying sniffer callback)
      - `sess.lock`    — threading.Lock guarding `events`

    Raises DeviceUnreachable if no identity reply arrives within
    `timeout` seconds.
    """
    with sess.lock:
        sess.events.clear()
    sess.send(build_identity_request())
    deadline = time.time() + timeout
    while time.time() < deadline:
        with sess.lock:
            for e in list(sess.events):
                info = _parse_identity_reply(e)
                if info is not None:
                    return info
        time.sleep(0.02)
    raise DeviceUnreachable(_unreachable_msg(timeout))


def _coerce_to_bytes(e) -> bytes | None:
    """Tolerant extractor for various events-buffer shapes used
    across tools: raw bytes, bytearray, (timestamp, bytes), or a
    dict with 'hex' / 'bytes' / 'raw'."""
    if isinstance(e, (bytes, bytearray)):
        return bytes(e)
    if isinstance(e, tuple) and len(e) >= 2 and isinstance(e[1], (bytes, bytearray)):
        return bytes(e[1])
    if isinstance(e, dict):
        for k in ("bytes", "raw"):
            v = e.get(k)
            if isinstance(v, (bytes, bytearray)):
                return bytes(v)
        hex_str = e.get("hex")
        if isinstance(hex_str, str):
            try:
                return bytes.fromhex(hex_str)
            except ValueError:
                return None
    return None


def identify_raw(out, events: list, lock=None,
                 timeout: float = 1.0) -> ProductInfo:
    """Identity-check using a raw MidiOut + an events buffer (the
    pattern used by many tools that don't go through GX10Session).

      `out`    — a midi_send.MidiOut (or equivalent with .send_sysex)
      `events` — a list of incoming events the caller's sniffer
                 callback appends to. Each entry may be raw `bytes`,
                 a `(timestamp, bytes)` tuple, or a sniffer dict with
                 a 'hex'/'bytes'/'raw' field — `_coerce_to_bytes`
                 normalises.
      `lock`   — optional threading.Lock guarding `events`

    The caller must already have a sniffer running that populates
    `events`. This function just sends the Identity Request and
    polls the buffer for the matching reply.
    """
    import contextlib
    if lock is None:
        @contextlib.contextmanager
        def _no_lock():
            yield
        lock_ctx = _no_lock
    else:
        lock_ctx = lambda: lock  # noqa: E731 — keep it tight

    with lock_ctx():
        events.clear()
    out.send_sysex(build_identity_request())
    deadline = time.time() + timeout
    while time.time() < deadline:
        with lock_ctx():
            snap = list(events)
        for e in snap:
            raw = _coerce_to_bytes(e)
            if raw is None:
                continue
            info = _parse_identity_reply(raw)
            if info is not None:
                return info
        time.sleep(0.02)
    raise DeviceUnreachable(_unreachable_msg(timeout))


def identify_gxmidi(g, timeout: float = 1.0) -> ProductInfo:
    """Identity-check via a midi_io.GxMidi instance.

    GxMidi has a built-in `.identity(timeout)` that returns the
    full Identity Reply (or None on timeout). We just parse it.
    """
    raw = g.identity(timeout=timeout)
    if raw is None:
        raise DeviceUnreachable(_unreachable_msg(timeout))
    info = _parse_identity_reply(bytes(raw))
    if info is None:
        raise DeviceUnreachable(
            f"received a message but it wasn't a valid identity reply: "
            f"{bytes(raw).hex(' ').upper()}"
        )
    return info


def _unreachable_msg(timeout: float) -> str:
    return (
        f"No identity reply within {timeout:.1f}s. The GX-10/GX-100 may be "
        f"unplugged, powered off, or in a stuck CoreMIDI/USB state from a "
        f"previous client. Fix: unplug+replug the USB cable, quit any other "
        f"MIDI app (BTS, DAW), and retry."
    )


def _abort_with_diagnostics(info: ProductInfo, problems: list[str]) -> None:
    """Print a detailed diagnostic dump of an unexpected identity reply
    and sys.exit. Use when a reply was received but doesn't pass the
    sanity check — better than silently assuming a product family."""
    print("\nERROR: identity reply received but the device is not a "
          "recognized Roland GX-10 / GX-100.\n", file=sys.stderr)
    print("Decoded identity reply:", file=sys.stderr)
    print(f"  raw           {info.raw_reply.hex(' ').upper()}", file=sys.stderr)
    print(f"  device_id     0x{info.device_id:02X}", file=sys.stderr)
    print(f"  manufacturer  0x{info.manufacturer:02X}  "
          f"(expected 0x41 Roland)", file=sys.stderr)
    print(f"  family        0x{info.family:04X}        "
          f"(expected 0x040B GX family)", file=sys.stderr)
    print(f"  model         0x{info.model:04X}", file=sys.stderr)
    print(f"  sw_revision   {info.sw_revision.hex(' ').upper()}      "
          f"(byte 0 = product flag: 0x00=GX-100, 0x01=GX-10)", file=sys.stderr)
    print(f"  product       {info.product}", file=sys.stderr)
    print("\nProblems:", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    print("\nThis tool will not proceed against an unrecognized device.",
          file=sys.stderr)
    sys.exit(3)


def _validate_or_die(info: ProductInfo, allow: list[str] | None,
                     verbose: bool) -> ProductInfo:
    """Shared sanity-check pass used by all three require_alive_*
    flavors after a successful identify_*()."""
    problems: list[str] = []
    if not info.is_roland_gx:
        problems.append(
            f"manufacturer/family mismatch: got mfr=0x{info.manufacturer:02X} "
            f"family=0x{info.family:04X}, expected Roland (0x41) GX family (0x040B)"
        )
    if info.product.startswith("unknown"):
        problems.append(
            f"product flag {info.product}; expected 0x00 (GX-100) or 0x01 (GX-10) "
            f"in sw_revision[0]"
        )
    if allow is not None and info.product not in allow:
        problems.append(
            f"detected {info.product}; this tool requires one of: {', '.join(allow)}"
        )
    if problems:
        _abort_with_diagnostics(info, problems)
    if verbose:
        print(f"Device: {info.product}  "
              f"(family 0x{info.family:04X}, sw_rev "
              f"{info.sw_revision.hex(' ').upper()})", file=sys.stderr)
    return info


def require_alive(sess, allow: list[str] | None = None,
                  verbose: bool = True, timeout: float = 1.0) -> ProductInfo:
    """Strict device sanity check via a GX10Session — call at the top
    of every device-talking tool, before any RQ1 / DT1, to fail fast
    with diagnostics rather than producing bogus / empty output.

    Exits with sys.exit code:
      2  no identity reply within `timeout` seconds (device
         unreachable / unplugged / port held by another client)
      3  reply received but device is not a recognized
         Roland GX-10 / GX-100 (or, if `allow` is set, not in
         the allowed list)

    Returns ProductInfo on success.

    `allow`: optional list of acceptable product labels (e.g.
    `allow=["GX-10"]`). When unset, both "GX-10" and "GX-100" are
    accepted; any other product flag aborts. The check is strict
    by design — we'd rather refuse to run than print false data
    against an unknown device.
    """
    try:
        info = identify(sess, timeout=timeout)
    except DeviceUnreachable as e:
        print(f"\nERROR: {e}\n", file=sys.stderr)
        sys.exit(2)
    return _validate_or_die(info, allow, verbose)


def require_alive_raw(out, events: list, lock=None,
                      allow: list[str] | None = None,
                      verbose: bool = True,
                      timeout: float = 1.0) -> ProductInfo:
    """Same strict check as `require_alive`, but for tools that don't
    use GX10Session — instead they have a raw `midi_send.MidiOut`
    plus their own `events` buffer fed by a `midi_sniff.Sniffer`
    callback. Call after both the sniffer and the MidiOut are open.
    """
    try:
        info = identify_raw(out, events, lock=lock, timeout=timeout)
    except DeviceUnreachable as e:
        print(f"\nERROR: {e}\n", file=sys.stderr)
        sys.exit(2)
    return _validate_or_die(info, allow, verbose)


def require_alive_gxmidi(g, allow: list[str] | None = None,
                         verbose: bool = True,
                         timeout: float = 1.0) -> ProductInfo:
    """Same strict check as `require_alive`, but for tools that use
    `midi_io.GxMidi`."""
    try:
        info = identify_gxmidi(g, timeout=timeout)
    except DeviceUnreachable as e:
        print(f"\nERROR: {e}\n", file=sys.stderr)
        sys.exit(2)
    return _validate_or_die(info, allow, verbose)


# CLI for quick standalone use:
#   python tools/device_id.py
#   python tools/device_id.py --quiet   # exit code only; 0=alive, 2=unreachable
if __name__ == "__main__":
    import argparse
    sys.path.insert(0, str(Path(__file__).parent))
    from example_lib import GX10Session

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true",
                    help="suppress output (use exit code only)")
    ap.add_argument("--timeout", type=float, default=1.0)
    args = ap.parse_args()

    sess = GX10Session()
    info = require_alive(sess, verbose=not args.quiet, timeout=args.timeout)
    if not args.quiet:
        print(f"  device_id     0x{info.device_id:02X}")
        print(f"  manufacturer  0x{info.manufacturer:02X}  "
              f"({'Roland' if info.manufacturer == 0x41 else '?'})")
        print(f"  family        0x{info.family:04X}  "
              f"({'GX family' if info.family == 0x040B else '?'})")
        print(f"  model         0x{info.model:04X}")
        print(f"  sw_revision   {info.sw_revision.hex(' ').upper()}")
        print(f"  product       {info.product}")
    sys.stdout.flush()
    import os; os._exit(0)
