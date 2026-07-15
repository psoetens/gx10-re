"""Self-driving LOOPER_CONTROL (0x7F000705) transition mapper.

probe_looper_control.py established that 0x7F000705 write-edges drive
the looper transport, but one-shot manual tests gave inconsistent verb
semantics across sessions (02 = stop in one run, inert in another;
00 = end-rec->play in one run, stop-from-play in another). This script
maps the transition table systematically:

  For every start state we can navigate to, and every candidate verb,
  apply the verb (with a guaranteed value-change edge) and record 3.5 s
  of evidence: register reads (attach-gated recording flag) + every
  0x10000154 MemoryLed.ON_OFF_STATE broadcast (LED blink timeline).

Nothing is classified live — the raw evidence log is written to
reports/looper_matrix_<n>.jsonl for offline analysis. LED signatures
(observed on GX-10, C1 = LOOP CTL = bit 7):
  RECORD / OVERDUB : register reads 01; LED solid on
  PLAY             : register 00; LED pulses at the loop period (~2 s)
  STOPPED+content  : register 00; LED blinks
  EMPTY            : register 00; LED dark, no broadcasts

Operator protocol:
  1. Close/pause all other MIDI clients (BTS, gxnarly).
  2. Load the looper memory (PHRASE LOOP in chain, LOOP CTL on C1).
  3. CLEAR the looper manually (LED dark).
  4. python tools/probe_looper_matrix.py
     The script records ~2 s of silence as loop content and walks the
     matrix on its own (~4 min). Don't touch the pedals while it runs.
  5. If a verb under test clears the loop, the script detects the
     content loss at the next play-check and re-records silence before
     continuing — the verb that preceded the loss is the CLEAR
     candidate, flagged in the log and the final summary.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from midi_send import find_output_port, MidiOut, build_rq1, build_dt1
import midi_sniff
from device_id import require_alive_raw

LOOPER_CONTROL = 0x7F000705
EDITOR_SUBSCRIBE = 0x7F000001
LED_STATE = 0x10000154          # MemoryLed.ON_OFF_STATE, 8 nibbles
C1_BIT = 7                      # LOOP CTL LED on GX-10

RECORD_SILENCE_S = 2.0
OBSERVE_S = 3.5
# Values worth testing as verbs. 00/01 double as navigation primitives.
CANDIDATE_VERBS = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
                   0x08, 0x10, 0x7F]


class Rig:
    """MIDI I/O + raw evidence log."""

    def __init__(self, port_substr: str, log_path: Path):
        self.events: list[tuple[float, bytes]] = []
        self.raw_events: list[bytes] = []   # plain view for device_id
        self.lock = threading.Lock()
        in_idx, in_name = midi_sniff.find_port(port_substr)
        if in_idx is None:
            print(f"ERROR: no MIDI input matching '{port_substr}'")
            sys.exit(2)
        self.sniffer = midi_sniff.Sniffer(in_idx, Path("__nul__.jsonl"),
                                          in_name)
        self.t0 = time.time()

        def emit(o):
            if o.get("kind") == "sysex":
                try:
                    raw = bytes.fromhex(o["hex"])
                except Exception:
                    return
                with self.lock:
                    self.events.append((time.time() - self.t0, raw))
                    self.raw_events.append(raw)
        self.sniffer._emit = emit
        self.sniffer.open()
        out_idx, _ = find_output_port(port_substr)
        if out_idx is None:
            print("ERROR: no output port")
            sys.exit(2)
        self.out = MidiOut(out_idx)
        time.sleep(0.4)
        self.log = log_path.open("w", encoding="utf-8")
        require_alive_raw(self.out, self.raw_events, self.lock)

    def note(self, **kv):
        kv["t"] = round(time.time() - self.t0, 3)
        self.log.write(json.dumps(kv) + "\n")
        self.log.flush()

    def write_reg(self, value: int):
        self.out.send_sysex(build_dt1(LOOPER_CONTROL, bytes([value])))
        self.note(kind="write", addr=f"{LOOPER_CONTROL:08X}", value=value)

    def attach(self):
        self.out.send_sysex(build_dt1(EDITOR_SUBSCRIBE, b"\x01"))
        self.note(kind="attach")
        time.sleep(0.3)

    def read_reg(self, timeout: float = 0.8):
        """RQ1 LOOPER_CONTROL, return first reply byte or None."""
        start = time.time() - self.t0
        self.out.send_sysex(build_rq1(LOOPER_CONTROL, 1))
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for t, raw in reversed(self.events):
                    if t < start:
                        break
                    p = self._parse_dt1(raw)
                    if p and p[0] == LOOPER_CONTROL and p[1]:
                        self.note(kind="read", value=p[1][0])
                        return p[1][0]
            time.sleep(0.05)
        self.note(kind="read", value=None)
        return None

    @staticmethod
    def _parse_dt1(raw: bytes):
        if not raw or raw[0] != 0xF0 or raw[-1] != 0xF7:
            return None
        if len(raw) < 14 or raw[8] != 0x12:
            return None
        return int.from_bytes(raw[9:13], "big"), bytes(raw[13:-2])

    def led_timeline(self, since: float):
        """(t, c1_on) for every LED broadcast after `since`."""
        out = []
        with self.lock:
            for t, raw in self.events:
                if t < since:
                    continue
                p = self._parse_dt1(raw)
                if not p or p[0] != LED_STATE or len(p[1]) < 8:
                    continue
                led32 = 0
                for i in range(8):
                    led32 = (led32 << 4) | (p[1][i] & 0x0F)
                out.append((round(t, 3), (led32 >> C1_BIT) & 1))
        return out


def observe(rig: Rig, label: str) -> dict:
    """Watch OBSERVE_S seconds; summarize register + LED evidence."""
    since = time.time() - rig.t0
    time.sleep(OBSERVE_S)
    reg = rig.read_reg()
    leds = rig.led_timeline(since)
    edges = len(leds)
    summary = {"label": label, "reg": reg, "led_edges": edges,
               "led_timeline": leds}
    rig.note(kind="observe", **summary)
    return summary


def classify(obs: dict) -> str:
    """Best-effort live classification (final analysis is offline)."""
    if obs["reg"] == 1:
        return "REC/DUB"
    if obs["led_edges"] == 0:
        return "quiet (stopped-solid or empty)"
    return f"LED active ({obs['led_edges']} edges: play-pulse or blink)"


def content_check(rig: Rig) -> bool:
    """True if loop content still exists.

    Strategy: fire a 0->1 edge (00 then 01). With content, LOOP CTL
    semantics give play or dub; from empty it starts RECORDING
    (register reads 01 AND stays 01 after we immediately end with 00 —
    actually ending rec creates content, so instead: read the register
    0.6 s after the 01. reg==01 with a dark LED beforehand => it was
    empty and is now recording; we then end the recording to restore
    silence content and report empty."""
    before = rig.led_timeline(time.time() - rig.t0 - OBSERVE_S)
    rig.write_reg(0x00)
    time.sleep(0.4)
    rig.write_reg(0x01)
    time.sleep(0.6)
    reg = rig.read_reg()
    was_dark = len(before) == 0
    if reg == 1 and was_dark:
        # started recording from empty -> content was CLEARED
        time.sleep(RECORD_SILENCE_S)
        rig.write_reg(0x00)          # end rec -> play (content restored)
        time.sleep(0.5)
        rig.note(kind="content_check", result="was_empty")
        return False
    rig.note(kind="content_check", result="content_present",
             reg=reg, was_dark=was_dark)
    return True


def main():
    reports = Path(__file__).resolve().parent.parent / "reports"
    reports.mkdir(exist_ok=True)
    n = 1
    while (reports / f"looper_matrix_{n}.jsonl").exists():
        n += 1
    log_path = reports / f"looper_matrix_{n}.jsonl"
    rig = Rig("GX-10", log_path)
    print(f"evidence -> {log_path}")

    rig.attach()

    # Seed content: record RECORD_SILENCE_S of silence.
    print("seeding: recording ~2 s of silence as loop content …")
    rig.write_reg(0x00)
    time.sleep(0.3)
    rig.write_reg(0x01)              # rec (expects EMPTY looper!)
    time.sleep(RECORD_SILENCE_S)
    rig.write_reg(0x00)              # end rec -> play
    time.sleep(0.5)
    seed = observe(rig, "seed/play")
    print(f"  seed state: {classify(seed)}")

    clear_candidates = []
    for verb in CANDIDATE_VERBS:
        # Navigate to a defined-ish state before each test: force a
        # fresh play via 00->01 edge chain (play or dub), then end any
        # rec with 00. Cheap and uses only the two reliable primitives.
        rig.write_reg(0x00); time.sleep(0.3)
        rig.write_reg(0x01); time.sleep(0.6)
        rig.write_reg(0x00); time.sleep(0.6)
        pre = observe(rig, f"pre[{verb:02X}]")

        # Guaranteed edge: register now holds 00 (just written).
        if verb == 0x00:
            rig.write_reg(0x01); time.sleep(0.3)   # make 00 a change
        rig.write_reg(verb)
        post = observe(rig, f"post[{verb:02X}]")
        print(f"verb {verb:02X}: pre={classify(pre):<40s} "
              f"post={classify(post)}")

        if not content_check(rig):
            print(f"  !! verb {verb:02X} CLEARED the loop "
                  f"(content gone at check) — CLEAR candidate")
            clear_candidates.append(verb)

    print("\n=== DONE ===")
    print(f"clear candidates: "
          f"{[f'{v:02X}' for v in clear_candidates] or 'none found'}")
    print(f"raw evidence: {log_path}")
    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == "__main__":
    main()
