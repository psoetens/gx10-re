"""Audit per-effect per-knob min/max/step from captured all-up + all-down
sweep pcaps. Reports anomalies (very few values, missing min, BPM-style
14-bit encoding) so we can prioritize follow-up sweeps."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TYPEBAR = ROOT / "captures" / "typebar_full"


def load_events(jsonl: Path):
    """Yield (addr_hex, full_payload_hex) for every host->dev DT1."""
    if not jsonl.exists():
        return
    with jsonl.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") != "sysex" or ev.get("dir") != "host->dev":
                continue
            raw = bytes.fromhex(ev["hex"])
            if len(raw) < 16 or raw[8] != 0x12:
                continue
            addr = int.from_bytes(raw[9:13], "big")
            payload = raw[13:-2]
            yield f"{addr:08X}", payload.hex().upper()


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for page_dir in sorted(TYPEBAR.glob("page*")):
        for eff_dir in sorted(page_dir.iterdir()):
            if not eff_dir.is_dir():
                continue
            if only and only not in eff_dir.name:
                continue
            up_jsonl = eff_dir / "knobs_all_up.jsonl"
            down_jsonl = eff_dir / "knobs_all_down.jsonl"
            if not up_jsonl.exists() or not down_jsonl.exists():
                continue
            print(f"=== {eff_dir.relative_to(TYPEBAR)} ===")
            # Combine values per address
            by_addr = {}
            for addr, payload in load_events(up_jsonl):
                by_addr.setdefault(addr, set()).add(payload)
            for addr, payload in load_events(down_jsonl):
                by_addr.setdefault(addr, set()).add(payload)

            for addr in sorted(by_addr):
                payloads = sorted(by_addr[addr])
                n = len(payloads)
                # Last byte of payload = simple value byte
                last_bytes = sorted({int(p[-2:], 16) for p in payloads if p})
                # Min/max as byte
                lo = last_bytes[0] if last_bytes else None
                hi = last_bytes[-1] if last_bytes else None
                # Try step as the modal diff
                if len(last_bytes) >= 2:
                    diffs = [last_bytes[i+1]-last_bytes[i]
                             for i in range(len(last_bytes)-1)]
                    from collections import Counter
                    step = Counter(diffs).most_common(1)[0][0]
                else:
                    step = None
                # 14-bit detection: payload prefix changes (3rd byte > 0)
                third_byte_set = sorted({int(p[4:6], 16) for p in payloads if len(p) >= 6})
                multi_byte = len(third_byte_set) > 1 or any(b > 0 for b in third_byte_set)
                anomaly = []
                if n <= 4:
                    anomaly.append(f"FEW_VALUES({n})")
                if lo is not None and lo > 0 and step == 1:
                    anomaly.append(f"MISSING_MIN(min={lo})")
                if multi_byte:
                    anomaly.append(f"14BIT(prefix={third_byte_set[:5]})")
                marker = " ".join(anomaly) if anomaly else "OK"
                print(f"  {addr}: n={n:3d} byte_range={lo}-{hi} step={step}  {marker}")


if __name__ == "__main__":
    main()
