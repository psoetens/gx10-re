"""Merge captures/bts_typebar_resweep_v2/catalog_visual_extraction.json
(address -> knob-label per TYPE) with captures/bts_bulk_enum/*_TYPE*.json
(per-knob raw -> BTS display value) into a single consolidated catalog at
captures/bts_effect_catalog.json.

The result is the canonical static knob/enum/range mapping for the GX-10's
83 effect types (TYPE 0x00..0x52). Client code reads this instead of
re-probing BTS at runtime.

Schema (per type):
  {
    "0x00": {
      "title": "AC GUITAR SIMULATOR",
      "category": "AC_SIM",
      "knobs": [
        {
          "address": "0x10001107",
          "label": "BODY",
          "kind": "numeric",
          "raw_min": 0, "raw_max": 15,
          "value_min": 0, "value_max": 15,
          "step": 1, "offset": 0, "unit": "",
          "raw_to_display": {"0": "0", "1": "1", ...}
        }, ...
      ],
      "dropdowns": [
        {"address": "0x10001103", "label": "TYPE",
         "kind": "enum", "values": ["BOSS COMP", "D-COMP", "ORANGE"], ...}
      ]
    }, ...
  }
"""
from __future__ import annotations
import json
import re
from pathlib import Path


REPO = Path(__file__).parent.parent
CATALOG = REPO / "captures/bts_typebar_resweep_v2/catalog_visual_extraction.json"
BULK_DIR = REPO / "captures/bts_bulk_enum"
OUT = REPO / "captures/bts_effect_catalog.json"


def normalize_label(label: str) -> str:
    """Strip trailing parenthetical hints like '(bipolar)' or '(enum: ...)'
    and trailing words used as type qualifiers (e.g. 'band' on GEQ rows)."""
    s = re.sub(r"\s*\(.*?\)\s*$", "", label).strip()
    s = re.sub(r"\s+band$", "", s, flags=re.IGNORECASE)
    return s


def classify_knob(raw_to_display: dict[str, str]) -> dict:
    """Return knob kind + numeric formula or enum value list."""
    pairs = [(int(r), v) for r, v in raw_to_display.items()]
    pairs.sort()
    raws = [r for r, _ in pairs]
    vals = [v for _, v in pairs]
    raw_min, raw_max = raws[0], raws[-1]

    def is_numeric_token(s: str) -> bool:
        s = s.strip()
        if not s:
            return False
        return bool(re.match(r"^[+-]?\d+(\.\d+)?\s*[a-zA-Z%]*$", s))

    if all(is_numeric_token(v) for v in vals):
        nums = []
        unit = ""
        for v in vals:
            m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%]*)$", v.strip())
            if m:
                nums.append(float(m.group(1)) if "." in m.group(1) else int(m.group(1)))
                if m.group(2) and not unit:
                    unit = m.group(2)
        if len(nums) >= 2 and len(set(raws)) >= 2:
            step_f = (nums[-1] - nums[0]) / (raws[-1] - raws[0]) if (raws[-1] - raws[0]) else 1
            offset_f = nums[0] - step_f * raws[0]
            ok = all(abs((step_f * r + offset_f) - n) < 0.01 for r, n in zip(raws, nums))
            if ok:
                step = int(step_f) if step_f == int(step_f) else step_f
                offset = int(offset_f) if offset_f == int(offset_f) else offset_f
                return {
                    "kind": "numeric",
                    "raw_min": raw_min,
                    "raw_max": raw_max,
                    "value_min": nums[0],
                    "value_max": nums[-1],
                    "unit": unit,
                    "step": step,
                    "offset": offset,
                    "raw_to_display": raw_to_display,
                }
        return {
            "kind": "numeric_irregular",
            "raw_min": raw_min,
            "raw_max": raw_max,
            "unit": unit,
            "raw_to_display": raw_to_display,
        }

    return {
        "kind": "enum",
        "raw_min": raw_min,
        "raw_max": raw_max,
        "values": vals,
        "raw_to_display": raw_to_display,
    }


# Distortion-family bytes whose addresses come from shared pattern A/B in
# the visual catalog (no per-byte address_to_label).
DIST_PATTERN_A_BYTES = {0x24, 0x25, 0x27, 0x28, 0x29, 0x2E}
DIST_PATTERN_B_BYTES = {0x26, 0x2A, 0x2B, 0x2C, 0x2D, 0x2F}


_PREFIX_PENALTY_PATTERNS = (
    "TAP ", "1: ", "2: ", "OCT ", "VIB ",
)


def _label_phantom_score(label: str) -> int:
    """Heuristic: lower score = "more likely to be the real label".
    Used by `_dedup_phantoms` to pick the keeper from a duplicate
    group. Penalises sub-section prefixes the BTS UI panel sometimes
    leaks into adjacent cells, and prefers shorter labels."""
    s = label.upper().strip()
    score = len(s)
    for pat in _PREFIX_PENALTY_PATTERNS:
        if s.startswith(pat):
            score += 100
            break
    return score


def _dedup_phantoms(knobs: list[dict]) -> list[dict]:
    """Group knobs by address; if a group has more than one entry, keep
    only the entry with the lowest phantom score (shortest, no
    sub-section prefix). Drop the rest. Returns a new list preserving
    original order of the kept entries."""
    keep_label_per_addr: dict[str, str] = {}
    addr_groups: dict[str, list[dict]] = {}
    for k in knobs:
        a = k.get("address")
        if not a:
            continue
        addr_groups.setdefault(a, []).append(k)
    for addr, group in addr_groups.items():
        if len(group) <= 1:
            keep_label_per_addr[addr] = group[0]["label"]
            continue
        winner = min(group, key=lambda k: _label_phantom_score(k["label"]))
        keep_label_per_addr[addr] = winner["label"]
    out = []
    seen_addrs: set[str] = set()
    for k in knobs:
        a = k.get("address")
        if a is None:
            out.append(k)
            continue
        if a in seen_addrs:
            continue
        if k["label"] == keep_label_per_addr.get(a):
            out.append(k)
            seen_addrs.add(a)
    return out


def label_to_address_map(catalog_entry: dict, type_byte: int,
                         catalog: dict) -> dict[str, str]:
    """Return {NORMALIZED_LABEL: address_hex}."""
    addrs = catalog_entry.get("address_to_label", {}) if catalog_entry else {}
    if not addrs:
        if type_byte in DIST_PATTERN_A_BYTES:
            addrs = {k: v for k, v in catalog["_distortion_family_pattern_A"].items()
                     if k.startswith("0x")}
        elif type_byte in DIST_PATTERN_B_BYTES:
            addrs = {k: v for k, v in catalog["_distortion_family_pattern_B"].items()
                     if k.startswith("0x")}
    out = {}
    for addr, raw_label in addrs.items():
        norm = normalize_label(raw_label).upper()
        if norm.startswith("<"):
            continue
        out[norm] = addr
    return out


def build():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}

    for t in range(0x00, 0x53):
        tkey = f"0x{t:02X}"
        entry = catalog.get(tkey, {})
        title = entry.get("title", "?")
        category = entry.get("category", "")

        bulk_files = list(BULK_DIR.glob(f"{t:02X}_*_TYPE{t:02X}.json"))
        if not bulk_files:
            print(f"  {tkey}: NO bulk enum file")
            continue
        bulk = json.loads(bulk_files[0].read_text(encoding="utf-8"))

        addr_map = label_to_address_map(entry, t, catalog)

        # Distortion gain knobs are catalogued as "<gain>" placeholders, so
        # fall back to the byte's known position in pattern A or B.
        dist_gain_addr = None
        if t in DIST_PATTERN_A_BYTES:
            dist_gain_addr = "0x10001107"
        elif t in DIST_PATTERN_B_BYTES:
            dist_gain_addr = "0x10001103"
        DIST_GAIN_LABELS = {"DRIVE", "BOOST", "FUZZ", "DIST"}

        knobs_out = []
        unmatched = []
        for label, kdata in bulk["knobs"].items():
            cls = classify_knob(kdata["raw_to_display"])
            norm = normalize_label(label).upper()
            address = addr_map.get(norm)
            if not address and dist_gain_addr and norm in DIST_GAIN_LABELS:
                address = dist_gain_addr
            if not address:
                unmatched.append(label)
            knobs_out.append({"address": address, "label": label, **cls})

        dropdowns_out = []
        for label, ddata in bulk["dropdowns"].items():
            cls = classify_knob(ddata["raw_to_display"])
            # Param 1 / sub-type byte at offset 0x03 from FxItem base
            dropdowns_out.append({
                "address": "0x10001103",
                "label": label,
                **cls,
            })

        # Stride-infer missing addresses from neighboring knobs. Every effect
        # uses the standard FxItem layout — params at offsets 0x03, 0x07, 0x0B,
        # 0x0F, ... (stride 4). Two passes: forward from most recent known
        # address, then backward to anchor leading-unaddressed knobs.
        last_known_offset = None
        for knob in knobs_out:
            if knob.get("address"):
                addr_int = int(knob["address"], 16)
                last_known_offset = addr_int - 0x10001100
            elif last_known_offset is not None:
                last_known_offset += 4
                inferred = 0x10001100 + last_known_offset
                knob["address"] = f"0x{inferred:08X}"
                knob["_address_inferred"] = True
        next_known_offset = None
        for knob in reversed(knobs_out):
            if knob.get("address") and not knob.get("_address_inferred"):
                addr_int = int(knob["address"], 16)
                next_known_offset = addr_int - 0x10001100
            elif knob.get("address"):
                # already-inferred forward: keep, also update anchor
                addr_int = int(knob["address"], 16)
                next_known_offset = addr_int - 0x10001100
            elif next_known_offset is not None:
                next_known_offset -= 4
                inferred = 0x10001100 + next_known_offset
                knob["address"] = f"0x{inferred:08X}"
                knob["_address_inferred"] = True

        # De-dup phantoms: if two knob entries claim the same address,
        # keep the one with the shortest label without sub-section
        # prefixes (TAP, 1:, 2:, OCT, etc.). The BTS bulk-enum sweep
        # sometimes reads neighboring panel labels into the same cell
        # when a multi-row layout is in play; this collapses them.
        knobs_out = _dedup_phantoms(knobs_out)

        out[tkey] = {
            "title": title,
            "category": category,
            "knobs": knobs_out,
            "dropdowns": dropdowns_out,
        }
        if unmatched:
            out[tkey]["_unmatched_label_addresses"] = unmatched

    OUT.write_text(json.dumps(out, indent=2))

    n_total = len(out)
    n_with_unmatched = sum(1 for v in out.values() if "_unmatched_label_addresses" in v)
    n_knobs_total = sum(len(v["knobs"]) for v in out.values())
    n_knobs_addressed = sum(
        1 for v in out.values() for k in v["knobs"] if k.get("address")
    )
    print(f"\n  wrote {OUT}")
    print(f"  effects: {n_total}")
    print(f"  knobs total: {n_knobs_total}")
    print(f"  knobs with address: {n_knobs_addressed}")
    print(f"  effects with at least one unmatched knob: {n_with_unmatched}")


if __name__ == "__main__":
    build()
