# gxnarly upstream issues — drafts ready to file

**Date:** 2026-05-09 (updated 2026-05-10)
**Source repo:** `/home/kaltan/src2/gxnarly` (this repo's downstream
consumer, per `Plan-Phase-4.md:237`).
**This repo's evidence base:** all references below cite committed
files in `gx10-re/` (the `firmware-versions` branch) or live device
probe transcripts in `reports/linux_probe_results.md`.

These are six distinct issues against gxnarly. Copy-paste each one
into a separate GitHub Issue (or whatever tracker gxnarly uses) when
you have repo access. Each one has a self-contained reproduction.

> **2026-05-10 update — Issue 6 added.** A complete BTS-driven
> effect catalog is now available at
> `gx10-re/captures/bts_effect_catalog.json` (83 effects × 632
> knobs × addresses verified live). This makes gxnarly's
> `devices/gx10.json` / `devices/gx100.json` regenerable from a
> single source of truth, and supersedes the typebar-derived
> `docs/effect_catalog.md` that some of the issues below
> referenced as the bug source. See **Issue 6** for the
> regeneration recommendation.

---

## Issue 1 — `knob_cell` encoder writes wrong wire bytes for FX Parameters > 15 (CRITICAL)

**Severity:** P0 — silent bug, produces incorrect device state.

**File:** `Sources/GxnarlyCore/Dictionary/ParameterEntry.swift:193-197`

```swift
case .knobCell:
    var cell = Data([0x08, 0x00, 0x00, 0x00])
    cell[valueByteOffset] = UInt8(clamped & 0x7F)
    return cell
```

This places the entire raw value (0..127) in `cell[3]`, but the
Roland device interprets each FX Parameter cell byte as **a single
nibble** (low 4 bits only). For values > 15 the upper nibble of
`cell[3]` is silently dropped.

### Reproduction (verified live on GX-10 firmware 1.04, 2026-05-09)

```python
# write [0x08, 0x00, 0x00, 0x64] (gxnarly encoder for raw=100) at 0x10001107
# read back -> [0x08, 0x00, 0x00, 0x04]
# device's stored value is 0x8004 - 0x8000 = 4 (NOT 100)

# write canonical 4-nibble [0x08, 0x00, 0x06, 0x04] at 0x10001107
# read back -> [0x08, 0x00, 0x06, 0x04]   (unchanged)
# device's stored value is 0x8064 - 0x8000 = 100  (CORRECT)

# write [0x08, 0x00, 0x00, 0x32] (gxnarly encoder for raw=50)
# read back -> [0x08, 0x00, 0x00, 0x02]
# device sees 2 instead of 50.
```

Full transcript: `gx10-re/reports/linux_probe_results.md` §P0-1.

### Independent confirmation: BTS sends the canonical form

A Windows USBPcap session running BOSS Tone Studio captured BTS
dragging a slider through values 1, 50, 100. **Every DT1 BTS sent
matches the canonical 4-nibble offset-binary form**:

| Display | BTS DT1 payload | Decoded raw |
|--------:|:----------------|------------:|
|   0     | `08 00 00 00`   | 0x8000      |
|   1     | `08 00 00 01`   | 0x8001      |
|  50     | `08 00 03 02`   | 0x8032      |
| 100     | `08 00 06 04`   | 0x8064      |

None of the 39 captured drag DT1s used the gxnarly single-byte
form (`[08 00 00 64]` etc.). BTS — Roland's own editor — uses the
same encoding `tools/encoding.py` produces. Source:
`gx10-re/reports/bts_capture_findings.md` §3.

### Why `verify-dict` doesn't catch it

`Sources/GxnarlyCLI/VerifyDict.swift:101-105` does read-only RQ1
round-trips and counts replies. It never writes a value and reads
back to compare. Even if it did, the gxnarly decoder reads only
`cell[valueByteOffset]`, so it would happily report raw=4 as
"matching" the original raw=4, missing the underlying truncation.

### Fix

Use one nibble per byte (matches `raw_4nib_be` already in the
encoder and the offset-binary convention from
`docs/protocol.md:304-309`):

```swift
case .knobCell:
    let v = clamped + 0x8000              // offset binary
    return Data([
        UInt8((v >> 12) & 0x0F),          // 0x08 for unipolar 0..32767
        UInt8((v >>  8) & 0x0F),
        UInt8((v >>  4) & 0x0F),
        UInt8(v         & 0x0F),
    ])
```

The decoder needs the matching change in `ParameterEntry.swift:245-247`:

```swift
case .knobCell:
    guard cell.count >= 4 else { return nil }
    return ((Int(cell[start]    ) & 0x0F) << 12)
         | ((Int(cell[start + 1]) & 0x0F) <<  8)
         | ((Int(cell[start + 2]) & 0x0F) <<  4)
         |  (Int(cell[start + 3]) & 0x0F)
         - 0x8000
```

### Add a verify step that catches this class of bug

Extend `verify-dict` with an opt-in **write-restore-write-readback**
mode for one knob per category:

1. Read original value.
2. Write a known-test value (e.g. half of `rawMax`, must be > 15).
3. Read back; assert decoded value matches the test value.
4. Restore original.

If gxnarly's encoder is wrong, step 3 fails on any unipolar knob
with `rawMax > 15`. (Bipolar knobs already use the offset-binary
form correctly because their values cross byte 2's nibble.)

---

## Issue 2 — `address_roots` mislabel `0x20000000` and claim `0x60400000` is `user_patch_slots`

**Severity:** P1 — metadata only; doesn't break wire-level operation
(gxnarly's writes go to the temp/edit buffer at `0x10000000`), but
mislabels regions in shipped JSON.

**Files:**
- `devices/gx10.json` and `devices/gx100.json` — both contain:

```json
"address_roots": {
  "temp_patch":         "0x10000000",
  "live_patch_mirror":  "0x20000000",   // wrong: this IS user-patch storage
  "preset_name_table":  "0x50000000",
  "user_patch_slots":   "0x60400000",   // wrong: this is the bank-label region
  "system_status":      "0x7F000000"
}
```

### Evidence (verified live on GX-10 firmware 1.04)

```
RQ1 0x20000000 size=4 -> "NATU"   (start of user patch 1's name "NATURAL...")
RQ1 0x29290000 size=4 -> no reply
RQ1 0x30000000 size=4 -> no reply  (gxnarly's "live_patch_mirror" doesn't exist)
RQ1 0x60400000 size=16 -> "USER 1          " (bank-label data, 0x10000 stride)
RQ1 0x60410000 size=16 -> "USER 2          "
```

The Roland v2 MIDI Implementation manual address map
(`docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md`) confirms:

- `0x20000000` = `Memory 1..200 (user)` × `0x60000` stride.
- `0x60400000` is not in the documented address map.

### Fix

```json
"address_roots": {
  "temp_patch":         "0x10000000",
  "user_patch_slots":   "0x20000000",
  "preset_name_table":  "0x50000000",
  "user_bank_labels":   "0x60400000",
  "system_status":      "0x7F000000"
}
```

(Drop `live_patch_mirror`; investigate `0x60400000` further before
relying on it.)

Full transcript: `gx10-re/reports/linux_probe_results.md` §P0-2.

---

## Issue 3 — `gx10.json` missing GX-10 footswitch params at offsets 0x64, 0x65

**Severity:** P0 — block-size mismatch on writeback can zero these
two registers.

**File:** `devices/gx10.json`

The v2 MIDI Implementation manual adds two GX-10-only fields at the
end of the `[SystemControl]` block (size grows from 0x64 to 0x66):

| Address    | Name                       | Bits        | Range  | Enum                    |
|------------|----------------------------|-------------|--------|-------------------------|
| `0x00001064` | `Down & Up Function(GX-10)`  | `0000 00aa` | `0..3` | `OFF, TUNER, DOWN, UP`  |
| `0x00001065` | `Up & Ctl1 Function(GX-10)`  | `0000 00aa` | `0..3` | `OFF, MANUAL, DOWN, UP` |

### Verified live on GX-10 firmware 1.04

`RQ1 0x00001000 size=0x66` returns 102 payload bytes:

```
byte 0x64 = 0x00  (Down & Up Function = OFF default)
byte 0x65 = 0x01  (Up & Ctl1 Function = MANUAL default)
```

Full transcript: `gx10-re/reports/linux_probe_results.md` §P0-3.

### Fix

Add two `parameters` entries:

```json
{
  "id": "system.down_up_function_gx10",
  "name": "DOWN+UP FUNCTION",
  "category": "SYSTEM",
  "role": "system",
  "address_hex": "00001064",
  "cell_size": 1,
  "value_byte_offset": 0,
  "encoding": "raw_byte",
  "type": "enum",
  "raw_min": 0, "raw_max": 3,
  "raw_payloads_hex": ["00", "01", "02", "03"],
  "enum_labels": ["OFF", "TUNER", "DOWN", "UP"]
},
{
  "id": "system.up_ctl1_function_gx10",
  "name": "UP+CTL1 FUNCTION",
  "category": "SYSTEM",
  "role": "system",
  "address_hex": "00001065",
  "cell_size": 1,
  "value_byte_offset": 0,
  "encoding": "raw_byte",
  "type": "enum",
  "raw_min": 0, "raw_max": 3,
  "raw_payloads_hex": ["00", "01", "02", "03"],
  "enum_labels": ["OFF", "MANUAL", "DOWN", "UP"]
}
```

Do NOT add to `gx100.json` — these fields are GX-10-specific.

---

## Issue 4 — `FirmwareVersion` parses Identity Reply bytes that don't encode firmware version

**Severity:** P1 — misderives "firmware 1.0" on a GX-10 actually
running 1.04. Affects every dictionary-filtering decision.

**File:** `Sources/GxnarlyCore/Device/FirmwareVersion.swift:19-23`

```swift
public init(softwareVersion: [UInt8]) {
    self.major = softwareVersion.first.map(Int.init) ?? 0
    self.minor = softwareVersion.count >= 2 ? Int(softwareVersion[1]) : 0
}
```

This treats `softwareVersion[0]` as major and `[1]` as minor. **Both
assumptions are wrong for the GX-10/GX-100 family.**

### Evidence (verified live on GX-10 firmware 1.04, 2026-05-09)

```
host:   F0 7E 7F 06 01 F7
device: F0 7E 10 06 02 41 0B 04 00 00 01 00 00 00 F7
                                       ^^ ^^ ^^ ^^
                                       sw_rev = 01 00 00 00
```

The bytes `01 00 00 00` are reported by **both** firmware 1.0 (per
`gx10-re/docs/firmware_versions.md:45`'s historical claim) **and**
firmware 1.04 (this device's actual firmware, confirmed via the
device's MENU → SYSTEM → VERSION screen).

The v2 MIDI Implementation manual confirms `softwareVersion[0]` is a
**product flag**, not a version:

> `nnH: Software revision level # 1 (GX-100:0 / GX-10:1)`
> *(GX-100_GX-10_MIDI_Imple_eng02_W.md, line 222)*

`softwareVersion[1..3]` are reserved zeros.

### Consequence

`Plan-Phase-4.md:26-27` reports gxnarly's verify-dict ran against
"GX-10 firmware 1.0" — but the device was actually 1.04. The
675/675 round-trip count is correct; the inferred firmware is wrong.

The dictionary-visibility filter is unreliable: any v2-only field
gated on `min_firmware: "M.m"` will be incorrectly hidden from a
GX-10 with firmware 1.04 (the filter sees 1.0).

### Fix — replace `FirmwareVersion` with `FeatureFlags` from a probe

```swift
public struct FeatureFlags: Sendable, Equatable, Codable {
    public let product: Product           // .gx10, .gx100
    public let hasV2Effects: Bool         // TYPE 78..82 accepted
    public let hasV2SystemCommonExt: Bool // 0x1B, 0x1C populated
    public let hasGx10Footswitches: Bool  // 0x64, 0x65 readable
}

public extension RolandSysEx.IdentityReply {
    var product: Product {
        switch softwareVersion.first ?? 0 {
        case 0x00: return .gx100
        case 0x01: return .gx10
        default:   return .unknown
        }
    }
}
```

The probe sequence:

1. `RQ1 0x0000001B size=1` — if non-zero, v2 SystemCommon extension
   is present.
2. `DT1 0x10001100 = [78]` then `RQ1 0x10001100 size=1` — if reply
   echoes 78, the device exposes v2 effects.
3. (GX-10 only) `RQ1 0x00001065 size=1` — if reply, the GX-10
   footswitch fields are exposed.

Map dictionary entries' `min_firmware: "2.0"` predicate to
`FeatureFlags.hasV2Effects` instead of "version >= 2.0".

See `gx10-re/docs/firmware_versions.md` (rewritten 2026-05-09) for
the full updated detection spec.

---

## Issue 5 — `model_id` metadata in `devices/*.json` is the wrong width

**Severity:** P3 — cosmetic / metadata only.

**Files:** `devices/gx10.json`, `devices/gx100.json`

Both declare:

```json
"device": {
  "model_id":      "0x0000",   // 2-byte representation
  "family_code":   "0x040B",
  ...
}
```

The **5-byte** Roland Model ID is `00 00 00 00 0B`. The framing
constant in `Sources/GxnarlyCore/SysEx/RolandSysEx.swift:18` already
embeds it correctly inside the SysEx header
(`F0 41 10 00 00 00 00 0B`), so wire framing is fine. The JSON
metadata is misleading — readers may think the model ID is 16 bits.

### Fix

Either:

```json
"device": {
  "family_code":  "0x040B",
  "model_id_5b":  "00 00 00 00 0B",
  ...
}
```

or drop `model_id` entirely (the family_code is what
distinguishes this product family).

---

## Issue 6 — Regenerate `devices/{gx10,gx100}.json` from the new BTS-driven effect catalog

**Severity:** P1 — supersedes part of Issue 1 with a more complete fix.

**Background:** A Windows-side BTS USBPcap session (2026-05-10)
produced `gx10-re/captures/bts_effect_catalog.json` — a complete,
live-device-verified catalog covering all 83 GX-10 effect TYPE
bytes (`0x00`..`0x52`), 632 knobs total. Each entry has:

- `address` (verified live, plus 78 stride-inferred entries flagged
  with `_address_inferred`)
- `label` (BTS UI text)
- `kind` (`numeric` / `enum` / `dropdown`)
- `raw_min` / `raw_max` (probe-sampled — see caveats below)
- `value_min` / `value_max` (display range, merged from the
  Parameter Guide)
- `unit`, `step`, `offset` (for the `display = raw*step + offset`
  linear formula)
- `raw_to_display` (sample mapping, raw 0..15 only)
- `value_min_documented` / `value_max_documented` (Parameter Guide
  full ranges)

**Caveats** (from
`captures/bts_typebar_resweep_v2/catalog_diff.md` and the catalog
metadata):

1. The catalog records **sub-type 0** for each TYPE byte. Effects
   with sub-type-dependent knob layouts (WAH, AMP, …) need
   per-`(TYPE, sub-type)` capture for full coverage. Tracked
   upstream as task #33.
2. 412/632 knobs have `raw_max=15` because the bulk-enum probe only
   sampled raw 0..15. Documented full ranges live in
   `value_*_documented`.
3. 78 addresses are stride-inferred (`_address_inferred`) — derived
   from the FxItem's known stride-4 layout. Verify before relying
   on them for write paths.

**Why this supersedes Issue 1's catalog claims:** Issue 1 cites the
old `gx10-re/docs/effect_catalog.md` as the wire-format reference,
which itself had bugs (WAH names permuted, COMP missing TONE +
DIRECT MIX, LOOP LEVEL at the wrong address). The encoder bug in
Issue 1 is real and unchanged, but the catalog source it was
diagnosed against is no longer canonical.

**Recommended fix:**

- Replace `gxnarly/tools/dict/generate.py`'s consumption of
  `gx10-re/docs/effect_catalog.md` and
  `gx10-re/docs/effects/all_effects.json` with consumption of
  `gx10-re/captures/bts_effect_catalog.json` directly.
- For each effect, emit `parameters` entries from the catalog's
  `knobs` array. Use `address` directly. Encoding is `knob_cell`
  (after Issue 1 fix) for numeric knobs, `raw_byte` for enum/
  dropdown knobs whose raw range is small.
- Tag effects whose layout might differ from sub-type 0 with a
  `sub_type_dependent: true` flag — block writes until per-sub-type
  layouts are captured (or accept the sub-type-0-only limitation
  with a warning).

**Verification:**

- Re-run `gxnarly-cli verify-dict` after regeneration. Should still
  hit 100% round-trip on a live device.
- Compare regenerated `devices/gx10.json` against the old one.
  Expected diffs:
  - WAH knob names corrected (per Issue 1 + the catalog diff)
  - COMP gains TONE and DIRECT MIX entries
  - LOOP LEVEL moves from `0x10001107` to `0x10001103`
  - Five new effects already present at TYPE 0x4E..0x52 (SLICER,
    HUMANIZER, FEEDBACKER, SITAR SIM, AUTO WAH) — verify gxnarly
    already has these
  - Two GX-10 SystemControl footswitch params at 0x64/0x65 (per
    Issue 3)
- Cross-check stride-inferred addresses (78 entries) by spot-probing
  on the live device.

**Source files in `gx10-re`:**

- `captures/bts_effect_catalog.json` — the catalog
- `captures/bts_typebar_resweep_v2/catalog_diff.md` — what changed
  vs the old catalog
- `captures/bts_typebar_resweep_v2/catalog_corrected.json` —
  per-effect "permuted/correct/missing" classification
- `captures/bts_wah_validation.summary.md` — sub-type-blindness
  diagnosis
- `reports/bts_capture_findings.md` — Windows session synthesis
- `docs/effects/README.md` — status of the old catalog

---

## Cross-link

Each issue cites this repo's `linux_probe_results.md` for live
device evidence. Pull the report, the manuals, and this issue list
on the gxnarly side and the issues should be self-contained.

The new effect catalog (`captures/bts_effect_catalog.json`) is the
canonical reference for parameter address layouts; everything else
in `docs/effect_catalog.md` and `docs/effects/all_effects.json` is
superseded as of 2026-05-10 — see `docs/effects/README.md`.
