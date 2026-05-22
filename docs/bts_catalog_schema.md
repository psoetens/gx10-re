# `catalogs/bts_effect_catalog_complete.json` — schema reference

This catalog is the merged authoritative source-of-truth for the GX-10
/ GX-100 effect parameters. It is built by `tools/merge_bts_into_catalog.py`
from:

- **BOSS Tone Studio's `effect_parameter.js`** (parsed via
  `tools/parse_bts_effect_parameter.js`) — Roland's own parameter
  database. Source of truth for everything except the supplementary
  fields below.
- **`resource.js`** — BTS's enum-string table; resolves every
  `resourceId` to its display value list.
- **`captures/bts_effect_catalog.json`** — our older probe-based
  catalog. Contributes the `*_documented` / `*_probe_sample` fields
  that BTS doesn't have.

The raw BTS extracts (`captures/bts_effect_parameter*.json`) are
gitignored; the merged file is what downstream code consumes.

## Top-level shape

```jsonc
{
  "0x00": { ... AC GUITAR SIMULATOR ... },
  "0x01": { ... AC RESONANCE ... },
  ...
  "0x52": { ... AUTO WAH ... }
}
```

Keys are the **FX TYPE byte** at SysEx offset 0 of each `MemoryFxItem`
(`0x10001100` for slot 0). Range `0x00..0x52` covers the 83 effect
types BTS knows about; see `tools/fx_type_enum.py` for the canonical
name table.

## Per-effect section

```jsonc
{
  "title": "CHORUS",                 // human title (our naming)
  "category": "CHO",                 // internal short code used by our tooling
  "bts_section": "CHORUS",           // BTS's section key in effect_parameter.js
  "bts": { ...section metadata... }, // see below
  "knobs": [ ...knob entries... ],   // numeric parameters
  "dropdowns": [ ...dropdown entries... ], // sub-type discriminator parameters
  "orphans_from_old_catalog": [...]  // optional; entries from our old catalog
                                     // at addresses BTS doesn't claim — flagged
                                     // for review, not authoritative
}
```

### Section-level `bts` block

All fields are **passed through verbatim from BTS** when present;
fields are omitted when null/absent.

| Field | BTS source | Meaning |
|---|---|---|
| `color` | `color` | BTS chain-block tint (`light_blue`, `red`, `blue`, etc.) |
| `dial_color` | `dialColor` | Optional alternate color for dials when it differs from `color` |
| `label_main` | `labelMain` | 3-letter chain-block abbreviation (`CHO`, `AMP`, `DLY`) |
| `label_sub` | `labelSub` | Subtitle/qualifier under the main label |
| `label_palette_main` | `labelPaletteMain` | Label used in BTS's "palette" (drawer) view if different |
| `label_palette_sub` | `labelPaletteSub` | Same, sub form |
| `small_label_sub` | `smallLabelSub` | Compact variant of `label_sub` for narrow UI |
| `select_boxes` | `selectBoxes` | List of `uniqueName`s that act as the section's **sub-type discriminators** — these are what we classify as `dropdowns`. Every other param is rendered as a knob even if its values come from an enum. |
| `has_switch` | `hasSwitch` | Whether this effect type has an OFF/ON switch on the chain block |
| `is_bass_type` | `isBassType` | True for bass-specific variants (`BASS CHORUS`, `BASS HARMONIST`, …) |
| `do_not_show_sub_type` | `doNotShowSubType` | Special-case effects whose sub-type is hidden from the UI |

### `knobs[]` and `dropdowns[]` entries

Same shape for both arrays. The difference is purely whether the
parameter is a sub-type discriminator (`uniqueName ∈ select_boxes`)
or an ordinary parameter. Even enum-typed knobs (e.g. `WAVEFORM:
TRI/SINE`) are in `knobs`, not `dropdowns`.

#### Authoritative numeric range (BTS-sourced)

| Field | BTS source | Meaning |
|---|---|---|
| `address` | `0x10001100 + p.address` | **Absolute** SysEx address as a hex string (`"0x1000110B"`). Adding `0x200 × slot_index` gives the address in any other FxItem slot. |
| `label` | `name` | Human-readable knob label as BTS uses it |
| `kind` | (derived) | `"numeric"` or `"enum"`. `enum` only when the param is a sub-type discriminator. |
| `raw_min` | `min` | Minimum raw value the parameter accepts on the wire |
| `raw_max` | `max` | Maximum raw value on the wire |
| `values` | resource lookup | Present when `bts.resource_id` is set; the list of display strings indexed by `(raw - bts.ofs)` (or just `raw` when `ofs` is 0). For numeric knobs this is informational; for dropdowns it is the canonical enum. |

#### Nested `bts` block — BTS-only fields

Pass-throughs from `effect_parameter.js`. Anything absent in BTS is
omitted here.

| Field | BTS source | Meaning |
|---|---|---|
| `address` | `address` | **Relative** byte offset within the slot (0–0x132). Equivalent to `int(absolute_address, 16) - 0x10001100`. |
| `unique_name` | `uniqueName` | Slug identifier — stable across firmware versions, used inside `show_when` expressions and `select_boxes`. |
| `init` | `init` | Factory-default raw value. Sometimes a string (`"100"`) when BTS authored it that way; treat as numeric. |
| `ofs` | `ofs` | Offset-binary encoding base added to the value when packing the SysEx 4-nibble field. Almost always either `0` (small-int) or `32768` (signed offset-binary). The raw `min`/`max` already reflect the post-encoding codomain — **don't subtract `ofs` to convert to a display value**; use `format_js` instead. |
| `size` | `size` | Symbolic size encoding from `utilities/constant.js`. The character pattern in the comment column tells the field's nibble layout: `INTEGER1x7` = 1 byte/7 bits, `INTEGER2x4` = 2 bytes / 4 nibbles, `INTEGER4x4` = 4 bytes / 4 nibbles (one nibble per byte — the common 4-nibble 16-bit value), etc. |
| `template` | `templateValue` | Human-readable range/enum description (e.g. `"0-100"`, `"0-100, BPM"`, `"FLAT, 20.0Hz～12.5kHz"`). Useful as a fallback when `format_js` is absent. |
| `format_js` | `format` | **JavaScript expression** for raw→display conversion, preserved verbatim. The full set of expressions BTS uses is enumerable (18 shapes); `tools/bts_formula.py:format_value()` handles all of them. Examples: `"value + '%'"`, `"Math.floor(value / 10)"`, `"((value - 50) > 0 ? '+' : '') + (value - 50)"`, `"formatHarmonistUserShift('A', value)"`. |
| `factor` | `factor` | Companion to `format_js` for scaled values. Currently always `10` (used for BPM, where raw `400..2500` displays as `40..250`). |
| `show_when` | `showConditions` | **Array of JavaScript boolean expressions** preserved verbatim. The parameter is visible iff ALL expressions evaluate true. Patterns reference other parameters by `{uniqueName}` (e.g. `"{type} === 3"`, `"{voice} === 1 || {voice} === 2"`). `tools/bts_formula.py:evaluate_condition()` parses the small DSL. Special call: `getSyncClock()` returns the current internal-clock-vs-MIDI-clock setting (consult `ctx['getSyncClock']` in the evaluator). |
| `resource_id` | `resourceId` | Index into BTS's `resource.js` text-array table. Already resolved into the `values` field at the entry top level; included here for cross-referencing only. |
| `ui` | (composite) | UI placement; see below. |
| `center` | `center` | Center value for dials drawn as centred-on-zero (signed knobs). |
| `pid` | `pid` | Internal parameter ID BTS uses for SysEx tracking — e.g. `"Setup_efct%14"`. Mainly useful when correlating live-capture sniffs against the catalog. |
| `dial_class` | `dialClass` | CSS class hint for the dial widget. Common values include `"param-dial bpm"` (BPM-format display) and `"param-dial bpm midi"` (MIDI-clock variant). |
| `is_not_editable` | `isNotEditable` | True for knobs BTS displays read-only (mostly the MIDI-clock-shadowed BPM variants). |
| `related_params` | `relatedParams` | List of other `uniqueName`s whose visibility/value depends on this one. Special value `"ALL"` means changing this resets/reflows every other param in the section. |
| `sort_index` | `sortIndex` | Tie-breaker for ordering when multiple knobs share a UI cell. |

#### `bts.ui` — UI placement

Two parallel UIs render the same parameter list with different
constraints. Both are optional per-knob; if a parameter doesn't render
on a given side, its sub-block is omitted.

```jsonc
"ui": {
  "pc": { "row": 1, "col": 9 },             // desktop "Patch Control" editor
  "sp": { "page": 3, "row": 2, "col": 2 }   // device on-screen Setting Page
}
```

| Sub-block | BTS source | Meaning |
|---|---|---|
| `ui.pc.row` | `rowPC` | Row 1..4 in BTS's desktop editor pane |
| `ui.pc.col` | `colPC` | Column 1..12 in BTS's desktop editor pane |
| `ui.sp.page` | `pageSP` | Page 1..6 on the device's on-screen edit display (paged with the device's panel buttons) |
| `ui.sp.row` | `rowSP` | Row 1..2 within an SP page |
| `ui.sp.col` | `colSP` | Column 1..3 within an SP page (rarely 4) |

Notes:
- BTS uses the **string `'-'`** as a sentinel meaning "this param is
  hidden from this UI variant". The merger converts it to JSON `null`.
  A `null` in any coordinate means "unconstrained on that axis" or
  "hidden", depending on context — check whether the rest of the
  block is also null.
- BTS's desktop layout fits everything on a single canvas (no
  multi-page concept on the PC side). The device's SP layout is paged
  because the hardware screen is small. Each SP page holds up to
  `2 rows × 3 cols = 6` parameters.
- `pageSP` distribution across the 911 BTS parameters:
  `1×453, 2×230, 3×86, 4×24, 5×12, 6×12, '-'×7` — most parameters live
  on the first 1-2 SP pages; only the densest effects (DELAY+,
  HARMONIST, PRIME PHASER) push into pages 5-6.
- `PC` = **Patch Control** (BTS's main editor pane). `SP` = **Setting
  Page** / on-device parameter screen. Don't confuse the latter with
  the AMP block's `sp-type` parameter, which stands for **Speaker
  TYPE** (cab simulator) and is unrelated.

#### Supplementary fields (from our older catalog)

These come from `captures/bts_effect_catalog.json` (probe-based) and
are preserved when an entry can be matched by `(relative_address,
label)` to a BTS row. They are **not authoritative** — BTS wins — but
they are useful cross-references.

| Field | Origin | Meaning |
|---|---|---|
| `value_min`, `value_max` | Derived from our probe sweep + Parameter Guide | Display-value range (post-`format_js`). Numeric, not always exact for non-trivial format expressions. |
| `unit` | Parameter Guide parse | Display-value unit string (`"ms"`, `"Hz"`, `""`). |
| `step` | Parameter Guide parse | Granularity of display value (almost always `1`). |
| `offset` | Parameter Guide parse | Offset between raw and display value when the relationship is a simple linear shift. Independent of `bts.ofs` (which is the SysEx encoding base). |
| `raw_min_documented`, `raw_max_documented` | Roland's published Parameter Guide PDF | The raw range as documented by Roland. Should match `raw_min`/`raw_max`; divergence indicates either a Parameter Guide error or a BTS data change. |
| `value_min_documented`, `value_max_documented` | Parameter Guide | Same, but for the display value. |
| `raw_min_probe_sample`, `raw_max_probe_sample` | Live device sweep | Actual values the device returned during probing. Often a strict sub-range of `raw_min..raw_max` because the probe only sampled discrete points. |
| `value_min_probe_sample`, `value_max_probe_sample` | Live device sweep | Same for display values. |
| `raw_to_display` | Live device sweep | Partial map of raw integer → display string captured by reading the device's BTS-side display during the sweep. Useful for sanity-checking `format_js` evaluation. |

#### `orphans_from_old_catalog`

Optional per-effect array. Lists entries from our older probe-based
catalog (`captures/bts_effect_catalog.json`) whose addresses don't
appear in BTS's parameter list. These usually reflect mis-attributed
labels in the older capture (e.g. a "BPM" label at the wrong address
because the probe sweep mis-aligned with the parameter that displayed
the BPM unit). They are kept in the merged catalog so we don't
silently drop the older data; downstream consumers should treat them
as suspicious until reviewed.

```jsonc
"orphans_from_old_catalog": [
  {
    "address": "0x1000111F",
    "label": "BPM",
    "_orphan": "no BTS parameter at this address",
    ...original fields from the old catalog...
  }
]
```

## Field-naming conventions used in the merged JSON

- Top-level keys mirror our existing catalog (`title`, `category`,
  `knobs`, `dropdowns`) so existing consumers don't break.
- BTS-specific fields live under a `bts` sub-object on both sections
  and per-knob entries.
- Field names inside `bts.*` are `snake_case` translations of BTS's
  `camelCase` (`uniqueName` → `unique_name`, `showConditions` → `show_when`).
- BTS's JavaScript-expression strings are preserved **verbatim** —
  evaluation lives in `tools/bts_formula.py`, not in the JSON.
- The `'-'` sentinel from BTS's data file is converted to `null`.
- Absent/empty/null values are stripped from the output (no
  `"factor": null` clutter).

## Related tools

- `tools/parse_bts_effect_parameter.js` — extracts BTS's
  `effect_parameter.js` (+ optional `resource.js`) to JSON. Run on a
  Mac with BTS installed.
- `tools/bts_formula.py` — evaluates the BTS `format_js` and
  `show_when` mini-DSLs.
- `tools/merge_bts_into_catalog.py` — produces this catalog.
- `tools/diff_bts_param_db.py` — generates `reports/bts_param_db_diff.md`,
  the per-effect divergence report between our older catalog and BTS.
