"""Programmatic sweep of every effect TYPE on FxItem #0 — no BTS UI needed.

For each TYPE byte 0x00..0x7F:
  1. DT1 0x10001100 = TYPE (set effect category on slot 0)
  2. RQ1 0x10001100 size=0x140 (read back the full FxItem block)
  3. Record the read-back so we can compare layouts across TYPEs

Snapshots FxItem #0 before, restores after, so the user's patch survives.

Usage:
    python tools/sweep_all_types.py --out captures/bts_full_sweep
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
import midi_send
import midi_sniff


FXITEM0_BASE = 0x10001100
FXITEM_SIZE = 0x140  # 320 bytes — covers TYPE + on/off + dup + 44 FX Params (4 nibbles each = 4 bytes)


def parse_dt1(msg: bytes):
    """Parse a Roland DT1 SysEx into (addr, payload). Returns None if not DT1."""
    if len(msg) < 14 or msg[0] != 0xF0 or msg[-1] != 0xF7:
        return None
    if msg[1:8] != bytes([0x41, 0x10, 0x00, 0x00, 0x00, 0x00, 0x0B]):
        return None
    if msg[8] != 0x12:
        return None
    addr = (msg[9] << 24) | (msg[10] << 16) | (msg[11] << 8) | msg[12]
    payload = bytes(msg[13:-2])  # exclude checksum + F7
    return addr, payload


class Probe:
    def __init__(self, out_port: str, in_port: str):
        out_idx, _ = midi_send.find_output_port(out_port)
        if out_idx is None:
            raise RuntimeError(f"no output port {out_port!r}")
        self.out = midi_send.MidiOut(out_idx)

        in_idx, in_name = midi_sniff.find_port(in_port)
        if in_idx is None:
            raise RuntimeError(f"no input port {in_port!r}")
        # Use a dedicated callback to capture DT1 replies into a queue.
        import queue
        self._q: "queue.Queue[bytes]" = queue.Queue()
        self._sniffer = _Listener(in_idx, in_name, self._q)
        self._sniffer.open()

    def drain(self, secs: float = 0.05):
        """Wait `secs` and return all SysEx received so far, in order."""
        time.sleep(secs)
        out = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except Exception:
                break
        return out

    def dt1(self, addr: int, payload: bytes):
        msg = midi_send.build_dt1(addr, payload)
        self.out.send_sysex(msg)

    def rq1(self, addr: int, size: int, timeout: float = 0.5) -> bytes | None:
        """Send RQ1 and wait for the matching DT1 reply at the same address."""
        # Drain any pending events first
        self.drain(0)
        msg = midi_send.build_rq1(addr, size)
        self.out.send_sysex(msg)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for raw in self.drain(0.02):
                p = parse_dt1(raw)
                if p and p[0] == addr:
                    return p[1]
        return None

    def close(self):
        try:
            self._sniffer.close()
        except Exception:
            pass
        try:
            self.out.close()
        except Exception:
            pass


class _Listener:
    """Lightweight Sniffer that pushes raw SysEx bytes to a queue."""
    def __init__(self, port_index, port_name, q):
        import ctypes
        self._ctypes = ctypes
        self.port_index = port_index
        self.port_name = port_name
        self.q = q
        self.handle = midi_sniff.HMIDIIN()
        self.buffers = []
        self.headers = []
        self._proc = midi_sniff.MIDI_PROC(self._cb)

    def _cb(self, hMidiIn, wMsg, dwInstance, dwParam1, dwParam2):
        try:
            if wMsg == midi_sniff.MIM_LONGDATA:
                ctypes = self._ctypes
                hdr = ctypes.cast(dwParam1, ctypes.POINTER(midi_sniff.MIDIHDR)).contents
                if hdr.dwBytesRecorded > 0:
                    raw = ctypes.string_at(hdr.lpData, hdr.dwBytesRecorded)
                    if raw[:1] == b"\xF0":
                        self.q.put(raw)
                # Re-queue
                midi_sniff.winmm.midiInAddBuffer(self.handle, dwParam1,
                    ctypes.sizeof(midi_sniff.MIDIHDR))
        except Exception:
            pass

    def open(self):
        ctypes = self._ctypes
        rc = midi_sniff.winmm.midiInOpen(
            ctypes.byref(self.handle), self.port_index, self._proc, None,
            midi_sniff.CALLBACK_FUNCTION,
        )
        if rc != 0:
            raise RuntimeError(f"midiInOpen failed: rc={rc}")
        for _ in range(midi_sniff.Sniffer.NUM_BUFFERS):
            buf = ctypes.create_string_buffer(midi_sniff.Sniffer.SYSEX_BUF_SIZE)
            hdr = midi_sniff.MIDIHDR()
            hdr.lpData = ctypes.addressof(buf)
            hdr.dwBufferLength = midi_sniff.Sniffer.SYSEX_BUF_SIZE
            hdr.dwBytesRecorded = 0
            hdr.dwFlags = 0
            self.buffers.append(buf)
            self.headers.append(hdr)
            midi_sniff.winmm.midiInPrepareHeader(self.handle, ctypes.byref(hdr),
                ctypes.sizeof(midi_sniff.MIDIHDR))
            midi_sniff.winmm.midiInAddBuffer(self.handle, ctypes.byref(hdr),
                ctypes.sizeof(midi_sniff.MIDIHDR))
        midi_sniff.winmm.midiInStart(self.handle)

    def close(self):
        ctypes = self._ctypes
        try:
            midi_sniff.winmm.midiInStop(self.handle)
            midi_sniff.winmm.midiInReset(self.handle)
            for hdr in self.headers:
                midi_sniff.winmm.midiInUnprepareHeader(self.handle, ctypes.byref(hdr),
                    ctypes.sizeof(midi_sniff.MIDIHDR))
            midi_sniff.winmm.midiInClose(self.handle)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="captures/bts_full_sweep",
                    help="output directory")
    ap.add_argument("--type-min", type=lambda x: int(x, 0), default=0x00)
    ap.add_argument("--type-max", type=lambda x: int(x, 0), default=0x7F,
                    help="inclusive (default 0x7F)")
    ap.add_argument("--settle-ms", type=int, default=80,
                    help="ms to wait between TYPE write and read-back")
    ap.add_argument("--port", default="GX-10")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    probe = Probe(args.port, args.port)
    print(f"opened ports for {args.port}", flush=True)

    # --- 1. Identity check
    probe.out.send_sysex(midi_send.build_identity_request())
    probe.drain(0.3)

    # --- 2. Snapshot FxItem #0
    print("snapshotting FxItem #0...", flush=True)
    snapshot = probe.rq1(FXITEM0_BASE, FXITEM_SIZE, timeout=1.5)
    if snapshot is None:
        print("ERROR: no reply to FxItem #0 snapshot RQ1; aborting.", flush=True)
        probe.close()
        return 2
    print(f"  snapshot len={len(snapshot)} bytes; first 16: {snapshot[:16].hex()}", flush=True)
    (out_dir / "snapshot_before.bin").write_bytes(snapshot)

    # --- 3. Editor-attach handshake (mirror BTS startup)
    probe.dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.05)
    probe.dt1(0x7F000001, bytes([0x01]))
    time.sleep(0.05)

    # --- 4. Sweep TYPE bytes
    results = {}
    distinct_blocks = {}
    print(f"sweeping TYPE 0x{args.type_min:02X}..0x{args.type_max:02X} "
          f"({args.type_max - args.type_min + 1} types)...", flush=True)
    # Open sweep.jsonl for incremental writes — survives any later hang.
    raw_log = (out_dir / "sweep.jsonl").open("w", encoding="utf-8", buffering=1)
    raw_log.write(json.dumps({"event": "snapshot", "hex": snapshot.hex()}) + "\n")
    for t in range(args.type_min, args.type_max + 1):
        probe.dt1(FXITEM0_BASE, bytes([t]))
        time.sleep(args.settle_ms / 1000.0)
        block = probe.rq1(FXITEM0_BASE, FXITEM_SIZE, timeout=0.8)
        if block is None:
            print(f"  TYPE 0x{t:02X}: NO REPLY", flush=True)
            results[t] = None
            raw_log.write(json.dumps({"type": t, "block": None}) + "\n")
            continue
        actual_type = block[0] if len(block) > 0 else None
        results[t] = block.hex()
        if block.hex() not in distinct_blocks:
            distinct_blocks[block.hex()] = []
        distinct_blocks[block.hex()].append(t)
        head = block[:16].hex()
        print(f"  TYPE 0x{t:02X}: actual=0x{actual_type:02X} "
              f"head={head}", flush=True)
        raw_log.write(json.dumps({
            "type": t, "actual": actual_type, "block": block.hex()
        }) + "\n")
    raw_log.close()

    # --- 5. Restore snapshot — bulk DT1 is silently rejected past first byte;
    # write header (3 bytes) + each FX Param slot (4 bytes, stride 4) individually.
    # Cap at offset 0x7C so address byte stays ≤ 0x7F.
    print("restoring FxItem #0...", flush=True)
    for off in range(min(3, len(snapshot))):
        probe.dt1(FXITEM0_BASE + off, bytes([snapshot[off]]))
        time.sleep(0.01)
    n_params = 0
    for offset in range(0x03, min(len(snapshot) - 3, 0x7C), 0x04):
        payload = snapshot[offset:offset + 4]
        if len(payload) != 4 or any(b > 0x7F for b in payload):
            continue
        probe.dt1(FXITEM0_BASE + offset, payload)
        time.sleep(0.005)
        n_params += 1
    print(f"  wrote header + {n_params} FX-Param slots", flush=True)
    time.sleep(0.1)

    # --- 6. Verify restore
    after = probe.rq1(FXITEM0_BASE, FXITEM_SIZE, timeout=1.5)
    if after is not None and after == snapshot:
        print("restore VERIFIED — block matches snapshot byte-for-byte", flush=True)
    else:
        print(f"WARNING: restore mismatch. snapshot[:16]={snapshot[:16].hex()} "
              f"after[:16]={(after or b'')[:16].hex()}", flush=True)
        (out_dir / "snapshot_after_restore.bin").write_bytes(after or b"")

    # --- 7. Clear editor-attach
    probe.dt1(0x7F000001, bytes([0x00]))
    time.sleep(0.05)

    probe.close()

    # --- 8. Save results
    summary = {
        "type_min": args.type_min,
        "type_max": args.type_max,
        "snapshot_hex": snapshot.hex(),
        "n_types": len(results),
        "n_distinct_layouts": len(distinct_blocks),
        "results": {f"0x{t:02X}": v for t, v in results.items()},
        "distinct_layouts": [
            {
                "block_hex": k[:64] + ("…" if len(k) > 64 else ""),
                "block_full": k,
                "types": [f"0x{t:02X}" for t in v],
                "n_types": len(v),
            }
            for k, v in distinct_blocks.items()
        ],
    }
    (out_dir / "sweep.json").write_text(json.dumps(summary, indent=2))

    print(f"\n=== Summary ===")
    print(f"  TYPEs probed: {len(results)}")
    print(f"  TYPEs that replied: {sum(1 for v in results.values() if v)}")
    print(f"  distinct FxItem layouts: {len(distinct_blocks)}")
    for i, (block_hex, types) in enumerate(distinct_blocks.items()):
        head = block_hex[:32]
        print(f"  layout #{i:02d} (n={len(types):>2d}): "
              f"head={head}  types={[f'0x{t:02X}' for t in types[:6]]}"
              f"{'…' if len(types) > 6 else ''}")
    print(f"\nWrote: {out_dir / 'sweep.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
