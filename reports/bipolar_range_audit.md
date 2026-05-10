# Bipolar knob range audit — probe/guide disagreement

**Date:** 2026-05-10
**Trigger:** GEQ 31.5Hz showed `raw_min=-20` after `merge_param_guide.py`,
which is structurally impossible on the wire (4-nibble offset-binary,
unsigned 0..0xFFFF).

## Root cause

For ~82 knobs the BTS sweep probed only raws 0..15 and recorded
displays `0..+15` of the knob's unit (dB / semitones / etc.) →
implied `offset=0, step=1`. The Parameter Guide, however, lists a
bipolar range like `-20..+20`. Plugging the guide bounds into the
probe-derived formula gives `raw_min = (-20 - 0) / 1 = -20` — which
the wire cannot represent.

The probe data and guide data thus disagree on the knob's actual
encoding. Both cannot be true simultaneously. The probe says
"raw 5 → display +5dB". The guide says "the knob ranges
-20..+20 dB". These are reconcilable only via one of:

1. The device uses a separate sign bit / sub-byte (no evidence so
   far in the protocol)
2. The device's effective wire range for these knobs is e.g. raw
   0..40 with `offset=-20`, and the BTS probe started near
   center=0dB rather than at the documented minimum
3. The probe only swept the upper half of the dial

Without a live re-probe across the full physical knob travel, we
can't pick between (2) and (3). The safest catalog action is to
**flag the knob and preserve the probe sample**; do not silently
fabricate an offset.

## What `merge_param_guide.py` now does

When the documented formula yields `rmin_doc < 0`, the knob:

- gets `_range_inconsistent` set to a short diagnostic string
- keeps probe-derived `raw_min`, `raw_max`, `value_min`, `value_max`,
  `step`, `offset`
- records `value_min_documented` and `value_max_documented` so the
  guide-derived bounds aren't lost
- does **not** get `raw_min_documented` / `raw_max_documented`
  written (would be negative — meaningless)

## Scope (post-fix)

| Effect | Knobs flagged | Knobs (examples)                                |
|--------|---------------|-------------------------------------------------|
| 0x15 GRAPHIC EQUALIZER | 10 | 31.5Hz … 16kHz, LEVEL                |
| 0x14 (PARAMETRIC EQ)   | 5  | LOW GAIN, HIGH GAIN, LEVEL, *-MID GAIN       |
| 0x40                    | 5  |                                              |
| 0x3C, 0x3D              | 4  each |                                          |
| 0x3F                    | 3  |                                              |
| 21 other effects        | 2  each | (most with TONE / SAG / RESONANCE-style) |
| 9 effects               | 1  each |                                          |

Total: **82 knobs across 36 effects**. Every flagged knob has the
same pattern — probe sample `raw 0..15 → display 0..+15<unit>`,
guide spec spans negative.

After this run, zero knobs in the catalog have `raw_*` or
`raw_*_documented` < 0.

## Resolution path

The proper fix is a live broadcast-capture audit (per the AMP /
DELAY+ / WAH methodology — see `reports/amp_address_audit.md`):

1. Set the FxItem to the effect type
2. Editor-attach handshake on
3. Listen for DT1 broadcasts while the user turns each flagged knob
   from one physical extreme to the other
4. Record the actual raw value at min and max → real `offset`/`step`

Until done, downstream consumers (gxnarly) MUST treat
`_range_inconsistent` knobs as "probe-only, full range unverified"
and clamp writes to `[raw_min, raw_max]` (the probe-observed range,
not the guide range).
