# `raw_to_display` cross-contamination in `bts_effect_catalog_complete.json`

**Date:** 2026-05-27
**Trigger:** Downstream consumer (gxnarly) rendered DELAY's CARRYOVER
toggle as `["20.0Hz", "25.0Hz"]` instead of `["OFF", "ON"]`. Tracing
the codegen revealed the labels came from BTS's own
`raw_to_display` map on that knob — which carries 16 frequency
strings unrelated to the boolean field.
**Scope:** 36 knobs across 19 effect types in
`catalogs/bts_effect_catalog_complete.json`.
**Severity:** Low for the device (wire encoding unaffected — the
device's actual raw byte semantics are untouched). High for any
downstream tool that surfaces the `raw_to_display` field as user-
visible labels (gxnarly did; BTS itself presumably ignores it for
these rows in favour of `values[]`).

---

## Root cause

For every knob the BTS catalog ships two label sources:

- `values: [...]` — the BTS UI display list, indexed 0..len(values)-1.
- `raw_to_display: { "<rawByte>": "<label>", ... }` — a per-wire-byte
  label override, intended for knobs where the wire ordering and
  the UI display ordering diverge (e.g. **AIRD PREAMP MIC TYPE**:
  `values[]` in UI order has FLAT at index 8, but the wire-byte
  ordering puts FLAT at byte 4 — `raw_to_display` carries that
  reordering).

For 36 knobs the `raw_to_display` map contains data that is
demonstrably **not for the knob it lives on**:

```json
// catalogs/bts_effect_catalog_complete.json, effect 0x0D ("DELAY")
{
  "address": "0x10001117",
  "label": "CARRYOVER",
  "raw_min": 0,
  "raw_max": 1,
  "values": ["OFF", "ON"],            // ← correct
  "raw_to_display": {
    "0": "20.0Hz", "1": "25.0Hz", "2": "31.5Hz", "3": "40.0Hz",
    "4": "50.0Hz", "5": "63.0Hz", "6": "80.0Hz", "7": "100Hz",
    "8": "125Hz", "9": "160Hz", "10": "200Hz", "11": "250Hz",
    "12": "315Hz", "13": "400Hz", "14": "500Hz", "15": "630Hz"
  }                                   // ← labels from HIGH CUT, range 0..15
}
```

The HIGH CUT-style frequency list appears verbatim in many boolean
fields' `raw_to_display`, suggesting a copy/template step in the
catalog generator that didn't reset the field before populating
the next knob. Similar leakage patterns are visible with waveform
labels (`["TRI","SINE"]`) appearing in `HIGH CUT` and `LOW CUT`
fields, and with `ms` labels appearing in `WAVEFORM` fields.

## Detection heuristic

Two cheap structural checks separate genuine `raw_to_display`
re-orderings (the AIRD PREAMP MIC TYPE pattern) from contamination:

1. **Key range** — every `raw_to_display` key must fall inside
   `[raw_min..raw_max]`. A wider key set is impossible for the
   knob (the device can't address those raw bytes here) and
   indicates the rtd was copied from a sibling knob with a larger
   raw range.
2. **Label set** — every `raw_to_display` label must also appear
   somewhere in `values[]`. A genuine wire-vs-UI divergence is a
   *permutation* of the same label set (MIC TYPE's rtd labels are
   all also in `values[]` — only the indices differ).
   Contamination introduces labels that are not in `values[]` at
   all (frequencies in an OFF/ON knob, waveform names in an Hz
   knob).

A row failing either check should be treated as contaminated.

## Affected knobs — full inventory (36)

Format: `[effect 0x__] EFFECT / KNOB    raw N..M  [contamination kind]`

### Boolean knobs (raw 0..1) carrying foreign-domain labels

| Effect | Knob | Address | `values[]` | `raw_to_display` flavour |
|---|---|---|---|---|
| `0x0D` DELAY | CARRYOVER | `0x10001117` | `["OFF","ON"]` | 16 HIGH-CUT frequency labels |
| `0x0E` DELAY+ | AUTO TRIGGER | `0x10001137` | `["OFF","ON"]` | single `{"5":"63.0Hz"}` |
| `0x12` TWIST DELAY | CARRYOVER | `0x1000111B` | `["OFF","ON"]` | single `{"1":"1"}` |
| `0x18` PRIME FLANGER | TURBO | `0x10001113` | `["OFF","ON"]` | `{"0":"TRI","1":"SINE"}` |
| `0x19` PRIME BASS FLANGER | TURBO | `0x10001113` | `["OFF","ON"]` | `{"0":"TRI","1":"SINE"}` |
| `0x39` PRIME PHASER | BI-PHASE | `0x1000111F` | `["OFF","ON"]` | 16 entries `{"0":"OFF","1":"0",...}` (raw-index labels) |
| `0x3A` PRIME BASS PHASER | BI-PHASE | `0x1000111F` | `["OFF","ON"]` | same 16-entry pattern |
| `0x41` TERA ECHO | TRIGGER | `0x1000111B` | `["OFF","ON"]` | `{"0":"MONO","1":"DIR/EFX","2":"STEREO"}` |
| `0x04` CHORUS | WAVEFORM | `0x10001123` | `["TRI","SINE"]` | 3-entry frequency strings, keys 0..2 |
| `0x04` CHORUS | 1: WAVEFORM | `0x10001137` | `["TRI","SINE"]` | `{"3":"1.5ms"}` |
| `0x04` CHORUS | 2: WAVEFORM | `0x10001153` | `["TRI","SINE"]` | `{"3":"1.5ms"}` |
| `0x04` CHORUS | OUTPUT MODE | `0x1000115F` | `["MONO","STEREO"]` | `{"3":"6.30kHz"}` |

### Frequency / step / ms fields with cross-contaminated rtd

| Effect | Knob | `values[]` summary | `raw_to_display` flavour |
|---|---|---|---|
| `0x04` CHORUS | HIGH CUT | 30 Hz/kHz labels | `{"0":"TRI","1":"SINE"}` |
| `0x04` CHORUS | PRE-DELAY | 81 ms labels | `{"0":"FLAT","1":"20.0Hz","2":"25.0Hz"}` |
| `0x04` CHORUS | 1: PRE-DELAY | 81 ms labels | `{"3":"3"}` |
| `0x04` CHORUS | 2: RATE | 119 numeric labels | `{"3":"MONO"}` |
| `0x04` CHORUS | 2: PRE-DELAY | 81 ms labels | `{"3":"3"}` |
| `0x04` CHORUS | 2: LOW CUT | 31 freq labels | `{"3":"TRI"}` |
| `0x06` PRIME CHORUS | LOW CUT | 31 freq labels | `{"0":"TRI","1":"SINE"}` |
| `0x0E` DELAY+ | TAP TIME | unit-hint `["[%]"]` | `{"5":"5"}` |
| `0x0E` DELAY+ | 1: TIME | 2018 ms labels | `{"5":"60"}` |
| `0x16` FLANGER | STEP RATE | 120 numeric labels | 16 freq labels (HIGH-CUT-style) |
| `0x16` FLANGER | LOW CUT | 31 freq labels | 16 raw-index labels |
| `0x17` BASS FLANGER | STEP RATE | 120 numeric labels | 16 freq labels |
| `0x17` BASS FLANGER | LOW CUT | 31 freq labels | 16 raw-index labels |
| `0x18` PRIME FLANGER | SEPARATION | 13 numeric labels | `{"0":"OFF","1":"ON"}` |
| `0x19` PRIME BASS FLANGER | SEPARATION | 13 numeric labels | `{"0":"OFF","1":"ON"}` |
| `0x1A` HARMONIST | 2: HARMONY | 30 interval labels | `{"0":"C(Am)","1":"C(Am)","2":"C(Am)"}` |
| `0x1B` BASS HARMONIST | 2: HARMONY | 30 interval labels | same pattern |
| `0x39` PRIME PHASER | SEPARATION | 13 numeric labels | `{"0":"OFF","1":"ON"}` |
| `0x3A` PRIME BASS PHASER | SEPARATION | 13 numeric labels | `{"0":"OFF","1":"ON"}` |
| `0x3C` PITCH SHIFTER | 2: PRE-DELAY | 319 ms labels | `{"1":"MEDIUM","2":"SLOW","3":"MONO"}` |
| `0x3D` BASS PITCH SHIFTER | 2: PRE-DELAY | 319 ms labels | same pattern |

### HUMANIZER — rtd repeats single value 16 times (keys all out of range)

| Effect | Knob | `values[]` | `raw_to_display` |
|---|---|---|---|
| `0x4F` HUMANIZER | MODE | `["PICKING","AUTO"]` (raw 0..1) | `{"0".."15": "AUTO"}` (all `"AUTO"`) |
| `0x4F` HUMANIZER | VOWEL1 | `["a","e","i","o","u"]` (raw 0..4) | `{"0".."15": "a"}` |
| `0x4F` HUMANIZER | VOWEL2 | `["a","e","i","o","u"]` (raw 0..4) | `{"0".."15": "i"}` |

These are subtly different from the cross-domain cases above — the
labels DO appear in `values[]`, but the keys leak way past `raw_max`.
Likely a probe artifact where 16 raw bytes were swept but the knob
only uses the low N. The probe captured the device's clamped
behaviour ("everything out of range falls back to AUTO / a / i"),
which is interesting wire-level information but should NOT be
serialised as `raw_to_display` since it overstates the knob's
domain.

## Suggested upstream fix

Per contaminated row, **either**:

1. **Delete the `raw_to_display` key entirely.** Most contaminated
   rows would be fully described by `values[]` alone — that's the
   downstream-safe outcome. Cleanest, least risky.
2. **Replace the bogus labels with correct ones matching `values[]`**
   (only if the row genuinely needs wire-vs-UI reordering — none
   of the 36 listed here appear to).

If the contamination originates in a step in the catalog generator
that templates `raw_to_display` from a sibling field without
resetting, **fixing that generator step** would prevent the
pattern from re-appearing on future captures.

The legitimate `raw_to_display` overrides (AIRD PREAMP MIC TYPE,
BASS AIRD PREAMP MIC TYPE, and ~75 other knobs that pass both
heuristic checks) must be preserved — those rows do real work and
removing them would mislabel the affected knobs.

## Repro / verification script

```python
#!/usr/bin/env python3
"""Audit raw_to_display blobs in bts_effect_catalog_complete.json.

Prints every row where raw_to_display either has keys outside
[raw_min..raw_max] OR labels not present in values[].
"""
import json
from pathlib import Path

cat = json.loads(
    Path("catalogs/bts_effect_catalog_complete.json").read_text()
)

n_total = n_contaminated = 0
for fx_key, fx in cat.items():
    if not isinstance(fx, dict):
        continue
    for knob in fx.get("knobs", []):
        rmin, rmax = knob.get("raw_min"), knob.get("raw_max")
        vals = knob.get("values")
        rtd = knob.get("raw_to_display")
        if (rmin is None or rmax is None or vals is None
                or not isinstance(rtd, dict)):
            continue
        n_total += 1
        try:
            keys_in_range = all(rmin <= int(k) <= rmax for k in rtd)
        except (TypeError, ValueError):
            keys_in_range = False
        vset = {str(v) for v in vals}
        labels_in_values = all(str(v) in vset for v in rtd.values())
        if not (keys_in_range and labels_in_values):
            n_contaminated += 1
            flags = []
            if not keys_in_range:   flags.append("keys leak")
            if not labels_in_values: flags.append("labels foreign")
            print(f"[{fx_key}] {fx.get('title'):20} / {knob.get('label'):15} "
                  f"raw {rmin}..{rmax}  → {', '.join(flags)}")

print(f"\n{n_contaminated} / {n_total} rows with raw_to_display are contaminated.")
```

Expected output on the 2026-05-22 catalog snapshot: 36 contaminated
out of 111 rows that ship a `raw_to_display`.

## Downstream impact (gxnarly)

For reference: gxnarly's codegen at
`tools/codegen/lib/catalog_loader.py` was patched 2026-05-27
to apply the two-check filter described above. With the filter:

- **Pre-fix output**: DELAY CARRYOVER ⇒ `enumValues: ["20.0Hz","25.0Hz"]`.
- **Post-fix output**: DELAY CARRYOVER ⇒ `enumValues: ["OFF","ON"]`.
- **AIRD PREAMP MIC TYPE** wire-correct ordering preserved (FLAT at
  index 4, not 8) — the filter passes both checks for that row.

The fix is purely defensive — it doesn't alter the source data.
When this upstream issue is resolved by removing the contaminated
`raw_to_display` entries or replacing them with correct labels,
gxnarly's downstream output is unchanged (the filter would simply
not trigger because the contamination wouldn't be there to filter).
**No coordinated change is needed on the downstream side after the
upstream fix.**
