"""Spot-check that our captured evidence agrees with the official MIDI
Implementation chart for a curated set of chart-documented addresses.

For each (address, label, expected_min, expected_max), we:
  1. Search every captured knob/control summary for the address
  2. Check that the captured raw byte range overlaps the chart's range
  3. Report PASS / FAIL / NO-EVIDENCE

Cases:
  - PASS: chart range agrees with captured range
  - FAIL: chart range and captured range differ in a way that suggests
    misattribution
  - NO-EVIDENCE: address never appeared in any capture (we never moved
    that control during exploration)

A NO-EVIDENCE result isn't a defect — most chart entries weren't
exercised. The point is to flag actual mismatches.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"


# (address_hex, description, chart_min, chart_max)
# Mostly drawn from the official chart's MemoryEfct, SystemEfct,
# SystemPitch, and a sample of MemoryFxItem TYPE/parameter slots.
CHECKS = [
    # MemoryEfct: address = 0x10000F00 + offset (memory #0 temporary buffer)
    ("10000F02", "MASTER BPM (raw 4-nibble, 400-2500 = 40.0-250.0)", 400, 2500),
    ("10000F06", "MASTER KEY (0..11 = C..B)", 0, 11),
    ("10000F07", "AMP CTL1 (0=OFF, 1=ON)", 0, 1),
    ("10000F08", "AMP CTL2 (0=OFF, 1=ON)", 0, 1),
    ("10000F09", "CARRYOVER (0..1)", 0, 1),
    ("10000F0A", "TEMPO HOLD (0..1)", 0, 1),
    # MemoryFxItem #0 (slot 0): TYPE byte
    ("10001100", "MemoryFxItem #0 TYPE (0..82)", 0, 82),
    # MemoryFxItem #0: OFF/ON
    ("10001101", "MemoryFxItem #0 OFF/ON (0..1)", 0, 1),
    # MemoryFxItem #0: DuplicationNumber
    ("10001102", "MemoryFxItem #0 DuplicationNumber (0..9)", 0, 9),
    # FX Parameter 1 of slot 0: range -20000..+20000 = 12768..52768 raw
    ("10001107", "MemoryFxItem #0 FX Parameter 1 (raw 12768..52768)", 12768, 52768),
    # SystemEfct: PHRASE LOOP MODE
    ("00005000", "PHRASE LOOP MODE (0=MONO, 1=STEREO)", 0, 1),
    ("00005001", "PHRASE LOOP REC ACTION (0..1)", 0, 1),
]


def gather_captured_ranges():
    """For each captured knob/control, record (address, raw_min, raw_max).
    Returns dict: address_hex_upper -> [(min_raw, max_raw, source_name), ...]
    """
    out = {}
    for sp in TYPEBAR.glob("page*/*/summary.json"):
        s = json.loads(sp.read_text())
        eff = s.get("name", "?")
        for k in s.get("knobs", []) + s.get("knobs_extra", []):
            addr = (k.get("address") or "").upper()
            if not addr:
                continue
            mn = k.get("min_raw")
            mx = k.get("max_raw")
            if mn is None or mx is None:
                continue
            out.setdefault(addr, []).append((mn, mx, f"{eff}/{k.get('name_manual_v2', '?')}"))
    return out


def check(addr, label, lo, hi, evidence):
    addr_u = addr.upper()
    ev = evidence.get(addr_u, [])
    if not ev:
        return "NO-EVIDENCE", f"no captured sweep at 0x{addr_u}"
    # Combine all captured ranges
    cap_min = min(e[0] for e in ev)
    cap_max = max(e[1] for e in ev)
    sources = ", ".join(sorted(set(e[2] for e in ev)))
    # We expect captured raw to fit within [lo, hi]
    if cap_min < lo or cap_max > hi:
        return "FAIL", (f"captured {cap_min}..{cap_max}, chart says {lo}..{hi} "
                        f"(sources: {sources})")
    return "PASS", f"captured {cap_min}..{cap_max} within chart {lo}..{hi} ({sources})"


def main():
    evidence = gather_captured_ranges()
    print(f"Captured-address evidence: {len(evidence)} unique addresses\n")

    counts = {"PASS": 0, "FAIL": 0, "NO-EVIDENCE": 0}
    for addr, label, lo, hi in CHECKS:
        verdict, detail = check(addr, label, lo, hi, evidence)
        counts[verdict] += 1
        print(f"[{verdict:11s}]  0x{addr.upper():8s}  {label}")
        print(f"              {detail}")

    print(f"\nSummary: {counts}")


if __name__ == "__main__":
    main()
