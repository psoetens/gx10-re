# GX-100 v2.0 — what was added vs v1.x (per Parameter Guide diff)

**Date:** 2026-05-09
**Sources:**
- `docs/manuals/GX-100_v1_Parameter_Guide_*.md` (pre-v2.0 firmware)
- `docs/manuals/GX-100_Parameter_Guide_*.md` (v2.0 firmware)
**Tool:** `tools/diff_v1_v2_param_guide.py`
**Closes:** `docs/effects/firmware_overlay.json` →
`subtype_additions_pending_schema` block.

---

## TL;DR

GX-100 v2.0 adds **5 new effects**, **9 named new amps**
(3 guitar + 6 bass), **2 new OD/DIST subtypes**, and **4 new mic
types**, plus chain-routing primitives (`DUAL`, `DIVIDER`, `MIXER`),
several new menu sections (`COLOR MODE`, `HARDWARE SETTINGS`,
`IN/OUT SETTINGS`), and the v2-only `[SystemCommon]` slots
(`COLOR MODE`, `SHOW AUTO OFF WARNING AT STARTUP`).

Per `reports/linux_probe_results.md` §P2-5, all 5 new effects exist
on the GX-10 since v1.00 launch — confirming the v2.0 update was
GX-100 catching up with the GX-10.

---

## New effect categories (5)

These are new top-level effects with TYPE bytes 78..82 in the
manual's effect TYPE enum (`docs/midi_firmware_analysis.md` §7).
Confirmed live on GX-10 fw1.04 in `reports/linux_probe_results.md`
§P2-5.

| TYPE | Manual name           | `firmware_overlay.json` short |
|-----:|-----------------------|-------------------------------|
|  78  | `SLICER`              | `SLICER`                      |
|  79  | `HUMANIZER`           | `HMN`                         |
|  80  | `FEEDBACKER`          | `FB`                          |
|  81  | `SITAR SIMULATOR`     | `SITAR_SIM`                   |
|  82  | `AUTO WAH`            | `A_WAH`                       |

---

## New AIRD PREAMP guitar amps (3)

**Previously "pending schema"** in `firmware_overlay.json` —
resolved here.

Inserted at the end of the X-series block in the AIRD PREAMP TYPE
list:

| Index in v2 list | Name      | Description (from manual)                                                                  |
|-----------------:|-----------|--------------------------------------------------------------------------------------------|
| 9 (after X-MODDED) | `X-ULTRA`  | A high-gain sound that uses MDP for a dense midrange tone with dynamics.                   |
| 10               | `X-OPTIMA` | A high-gain sound that uses MDP to emphasize sonic balance for phrases and ensemble play.  |
| 11               | `X-TITAN`  | A tight high-gain sound with an edge, which uses MDP.                                      |

The remaining 20 AIRD PREAMP TYPE entries are byte-identical between
v1 and v2.

**Combined count:** v1 had 20 amps; v2 has 23 → exactly 3 added.
(The press citing "10 amps total" was inflated; the actual additions
are 3 guitar + 6 bass = 9.)

---

## New AIRD BASS PREAMP amps (6)

Inside the `AIRD BASS PREAMP` parameter table in
`Parameter_Guide_04_effects_bass_master`. v1 referenced an external
"SP TYPE List" without listing names; v2 spells them out:

| Index | Name           |
|------:|----------------|
| 1     | `STUDIO BASS`  |
| 2     | `SILVER TUBE`  |
| 3     | `CLASSIC BLUE` |
| 4     | `SOLID STACK`  |
| 5     | `FAT TUBE`     |
| 6     | `DARK DRV`     |

Plus the v1 reference text `Refer to "SP TYPE list (p. 11)"` was
replaced by an explicit list. Total: 6 new bass amps in v2.0 (matches
press release "6 bass amps").

---

## New OD / DIST subtypes (2)

| Effect       | Index | Subtype | Description                              |
|--------------|------:|---------|------------------------------------------|
| `OVERDRIVE`  | 4     | `SD-1`  | Models BOSS SD-1 Super Overdrive.        |
| `DISTORTION` | 1     | `DS-1`  | Models BOSS DS-1 Distortion.             |

(Indices match `gxnarly/devices/gx100.json` `type_min_firmware`
schema; gxnarly already gates these correctly.)

---

## New MIC TYPE entries (4)

`MIC TYPE list` in `Parameter_Guide_01_effects_distortion`:

| Name        | Description                                         |
|-------------|-----------------------------------------------------|
| `RBN121`    | Models the ROYER R-121 ribbon mic.                  |
| `BLEND A`   | SM57 + R-121 mix; SM57 louder.                       |
| `BLEND B`   | SM57 + R-121 mix; equal volumes.                     |
| `BLEND C`   | SM57 + R-121 mix; R-121 louder.                      |

v1 had 5 mic types (DYN57, DYN421, CND451, CND87, FLAT). v2 has 9
→ exactly these 4 added.

---

## Chain-routing primitives (3 — possibly always present)

Detected by the diff as v2-only top-level sections. **These may not
be new effects** — they could be chain-routing primitives that were
present at v1 launch but documented separately in older guides:

- `DUAL`
- `DIVIDER`
- `MIXER`

Action: cross-check against `docs/manuals/GX-10_Parameter_Guide_*.md`
(GX-10 has all v2.0 features since launch — if DUAL/DIVIDER/MIXER
appear there, they are NOT v2.0-specific). Then update
`firmware_overlay.json` accordingly.

---

## Menu / UX additions (4 — not effect-related, no firmware filtering)

Detected by the diff as v2-only top-level sections in chunk 5
(menu):

- `COLOR MODE` — **confirmed live** at `[SystemCommon]` `0x1B`
  (Linux probe). Uses TYPE 1 / TYPE 2 enum.
- `HARDWARE SETTINGS` — new menu sub-section.
- `IN/OUT SETTINGS` — new menu sub-section.
- `CTL/EXP` — new menu sub-section (or restructured from v1).

These don't gate effects but DO add new readable/writable system
parameters. They're orthogonal to the parameter-dictionary
`min_firmware` tagging — the editor can show them all on v2 firmware
and hide them on v1 (where the addresses return 0).

---

## Items that AREN'T v2.0 additions (false positives caught)

The first parser pass flagged several "DIFF" entries that turned out
to be:

- `OVERDRIVE` types `NATURAL OD`, `WARM OD`, ..., `CENTA OD` — false
  positive: v2's table was split across a page break and the parser
  attributed the second half to a chapter heading. Fixed by merging
  same-name commits.
- `CHORUS`, `DELAY PLUS`, `ANALOG DELAY`, `BASS CHORUS`,
  `REVERB`, `AC RESONANCE` — apparent diffs on enum values like
  `MONO`, `STEREO`, `HALL S`, etc. were caused by `[img]` placeholder
  formatting differences between v1 and v2. Fixed by stripping
  `[img]` and `**` markers in `normalise_enum_value`.

---

## Schema migration in `firmware_overlay.json`

Replace the `subtype_additions_pending_schema` block with a
`type_overrides` block keyed by `(category, type_index)` and
`min_firmware_gx100`. Concrete entries:

```json
"type_overrides": {
  "OVERDRIVE":   { "4": { "name": "SD-1",        "min_firmware_gx100": "2.00" } },
  "DISTORTION":  { "1": { "name": "DS-1",        "min_firmware_gx100": "2.00" } },
  "AIRD_PREAMP": {
    "9":  { "name": "X-ULTRA",   "min_firmware_gx100": "2.00" },
    "10": { "name": "X-OPTIMA",  "min_firmware_gx100": "2.00" },
    "11": { "name": "X-TITAN",   "min_firmware_gx100": "2.00" }
  },
  "AIRD_BASS_PREAMP": {
    "1": { "name": "STUDIO BASS",  "min_firmware_gx100": "2.00" },
    "2": { "name": "SILVER TUBE",  "min_firmware_gx100": "2.00" },
    "3": { "name": "CLASSIC BLUE", "min_firmware_gx100": "2.00" },
    "4": { "name": "SOLID STACK",  "min_firmware_gx100": "2.00" },
    "5": { "name": "FAT TUBE",     "min_firmware_gx100": "2.00" },
    "6": { "name": "DARK DRV",     "min_firmware_gx100": "2.00" }
  },
  "MIC_TYPE": {
    "5": { "name": "RBN121",  "min_firmware_gx100": "2.00" },
    "6": { "name": "BLEND A", "min_firmware_gx100": "2.00" },
    "7": { "name": "BLEND B", "min_firmware_gx100": "2.00" },
    "8": { "name": "BLEND C", "min_firmware_gx100": "2.00" }
  }
}
```

(Indices need to be cross-checked against the actual TYPE byte
values once we have a live GX-100 — for now they're inferred from
the v2 manual's list ordering.)

---

## Cross-check artifact

Raw diff output is reproducible by running:

```
python tools/diff_v1_v2_param_guide.py
```

Any future GX-100 firmware update can be vetted by re-running the
tool against the new chunks and a current Parameter Guide.
