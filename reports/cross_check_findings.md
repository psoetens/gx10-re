# Cross-check findings: gx10-re docs vs gxnarly code vs Roland manuals

**Date:** 2026-05-09
**Scope:** Full pass over `gx10-re/docs/`, the freshly-added Roland manuals
(`docs/manuals/`), and `/home/kaltan/src2/gxnarly/` (Swift implementation
that talks to the device over ALSA / CoreMIDI). Goal: identify
inconsistencies, stale claims, and open questions — proposing an action
for each.

**Authority order** for resolving conflicts:
1. Roland manuals (`docs/manuals/GX-100_*MIDI_Imple*.md` and
   `docs/manuals/GX-{100,10}_*Parameter_Guide_*.md`).
2. Live device probe.
3. `gx10-re/docs/protocol.md`, `effect_catalog.md`, etc. (RE captures).
4. `gxnarly/devices/*.json` (downstream-derived).

---

## Severity legend

- **P0** — silent semantic bug; will produce wrong values on the wire.
- **P1** — wrong/stale fact in a published file; misleads anyone who
  reads it but doesn't break wire-level operation.
- **P2** — gap or open question; behaviour unverified.
- **P3** — naming / cosmetic / cleanup.

---

## P0 findings (likely silent bugs)

### P0-1. gxnarly `knob_cell` encoding may be incorrect for FX Parameters

**Evidence:**
- `gxnarly/Sources/GxnarlyCore/Dictionary/ParameterEntry.swift:193-197`:
  ```swift
  case .knobCell:
      var cell = Data([0x08, 0x00, 0x00, 0x00])
      cell[valueByteOffset] = UInt8(clamped & 0x7F)
      return cell
  ```
  Wire: `[0x08, 0x00, 0x00, VV]` with `VV` ∈ 0..127. Decoder
  (line 245-247) reads `Int(cell[valueByteOffset])` — i.e. the raw byte.
- `gx10-re/docs/protocol.md:304-306`:
  > `0x03–0x132 | **FX Parameter 1..44** | each 4 nibbles big-endian,
  > range 12768–52768 = -20000..+20000 in offset binary`
  >
  > ⚠️ **CRITICAL** — every FX Parameter is **4 nibbles**, not 1 byte.
- gx10-re's `tools/reanalyze_knobs_4nibble.py` (per `effect_catalog.md`)
  re-decodes captured ranges using the 4-nibble formula. Concrete
  example: COMP SUSTAIN max → bytes `08 00 06 04` →
  `0x8064 - 0x8000 = 100`. Under gxnarly's encoder, raw_max=100 produces
  `[0x08 0x00 0x00 0x64]`, which decoded as 4-nibble big-endian (one
  nibble per byte) yields `0x8004 - 0x8000 = 4`.

**Why gxnarly's verify-dict didn't catch it:**
`Sources/GxnarlyCLI/VerifyDict.swift:101-105` reads via RQ1 with a
0.3 s timeout and counts replies; it doesn't write a known value and
read it back, and it doesn't compare against an expected display value.
For unipolar knobs whose `raw_max` ≤ 0x0F (15), the two encodings
coincide. Most effect knobs go higher, so most FX Parameter writes
likely set the wrong value silently — but unless someone sets
gxnarly's slider to >15 and watches the BTS UI / hardware display, no
test in either project would catch it.

**Action (P0-1):**
1. Plug the device in and verify on real hardware: write
   `[0x08, 0x00, 0x00, 0x64]` to a known knob (e.g. COMP SUSTAIN at
   `0x10001107`) and read back; observe whether the device reports
   display value 4 or 100.
2. Compare against writing the canonical 4-nibble form
   `[0x08, 0x00, 0x06, 0x04]`.
3. If protocol.md is right, fix gxnarly's `knob_cell` encoder to use
   one-nibble-per-byte (same as `raw_4nib_be`) plus the +0x8000 offset.
   Notify gxnarly upstream.
4. If gxnarly's encoder happens to work because the device is lenient
   about nibble vs byte interpretation, document that the device
   accepts both forms — and fix protocol.md's overly strict claim.

---

### P0-2. gxnarly's `address_roots` for GX-100/GX-10 disagree with the manual

**Evidence:**
- `gxnarly/devices/gx100.json` (and `gx10.json`):
  ```json
  "address_roots": {
    "temp_patch":         "0x10000000",
    "live_patch_mirror":  "0x20000000",
    "preset_name_table":  "0x50000000",
    "user_patch_slots":   "0x60400000",
    "system_status":      "0x7F000000"
  }
  ```
- Manual (v1 and v2): user memory bank starts at `0x20000000`.
  `Memory 1..200 (user)` × `0x60000` stride.
- `gx10-re/docs/protocol.md:153-156`:
  > `0x2000_0000 | Memory 1..200 (user) | ✔` ...
  > `0x6040_0000 | — | (mirror?)` ...
  > "Earlier RE notes claimed user patches here; per official chart,
  > user patches are at `0x2000_0000`. The `0x6040_0000` region may be
  > a mirror or unrelated."

So gxnarly:
- Mis-labels `0x20000000` as `live_patch_mirror`. Per the manual it's
  the user-patch bank.
- Calls `0x60400000` `user_patch_slots`. Per the manual it isn't.

gxnarly's verified 675/675 round-trips are all on the temp-patch /
edit buffer at `0x10000000`. The roots field is metadata; nothing
in the dictionary actually uses `0x60400000`. So the labels mislead
without breaking anything (yet).

**Action (P0-2):**
- Update `gxnarly/devices/{gx10,gx100}.json` `address_roots` to:
  `temp_patch: 0x10000000`, `user_patch_slots: 0x20000000`,
  `preset_name_table: 0x50000000` (verify), `system_status:
  0x7F000000`. Drop `live_patch_mirror` until verified — it might be
  the mirror at `0x30000000` mentioned in the manual.
- File an issue on gxnarly. We can't push from here; the gxnarly repo
  has its own owner (per `gx10-re/docs/firmware_versions.md` it consumes
  ours).

---

### P0-3. gxnarly's GX-10-specific firmware features absent from `gx10.json`

**Evidence:** v2 manual adds two GX-10-only `[SystemControl]` params
at offsets `0x64` (`Down & Up Function`) and `0x65`
(`Up & Ctl1 Function`) — both listed in
`docs/midi_firmware_analysis.md` §5.2. Neither appears in
`gxnarly/devices/gx10.json` (search confirms no `0x64`/`0x65` at base
`0x10000000`).

**Why this is P0 not P1:** if a user changes either footswitch
function in BTS while gxnarly is connected, gxnarly's edit-buffer
view will be stale and any compare/write-back will overwrite real
values with unspecified zeros for those bytes — gxnarly's
`SystemControl` block size is 0x64 not 0x66.

**Action (P0-3):**
- Add the two entries to gxnarly's GX-10 dictionary (gated to v1.05+
  if the user has a v1.00 device that doesn't expose them — needs
  device probe).
- Verify size of any block-read RQ1 against base `0x10001000` matches
  v2's `0x66` total size on a v1.05 GX-10.

---

## P1 findings (wrong/stale facts in published files)

### P1-1. `firmware_versions.md` "first byte = major version" conflicts with v2 manual annotation

Already documented in `docs/midi_firmware_analysis.md` §1.2. Quoting
both sides:
- `docs/firmware_versions.md:21-26` (table):
  `01 00 ...` = firmware 1.0 ; `02 04 ...` = firmware 2.04.
- `docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md:222`:
  `nnH: Software revision level # 1 (GX-100:0 / GX-10:1)`.

The manual's annotation reads byte 10 as a product flag. The
firmware_versions.md interpretation reads it as the major version.
They only happen to agree on the two currently-shipping firmwares
because the major versions coincide with Roland's chosen product flag.

**Action (P1-1):**
- The device is attached. Run an Identity Request and capture the raw
  4-byte sw_rev sequence. If the GX-10 reports `01 05 00 00`, the
  major-version reading is right (and the manual is misleading). If
  it reports `01 00 vv 00` (with `vv` ≠ 0), the manual's reading is
  right.
- Update `firmware_versions.md` and `midi_firmware_analysis.md` §1
  with the resolved reading.
- Add a probe to `tools/detect_device.py` that pretty-prints the
  Identity Reply per the resolved interpretation.

---

### P1-2. `effect_catalog.md` and `all_effects.json` knob ranges are stale (single-byte)

**Evidence:** `docs/effect_catalog.md` and `docs/effects/all_effects.json`
were generated before the FX Parameter 4-nibble decoding fix described
in `docs/protocol.md:304-309`. `effect_catalog.md` lines 22-41 list 22
knob-count mismatches whose underlying byte-range data is single-byte
extracted. `official_xref.md` flags this as a "critical bug" pending
regeneration.

**Action (P1-2):**
- Run `tools/reanalyze_knobs_4nibble.py` over the captured data and
  regenerate `all_effects.json` and `effect_catalog.md`.
- Re-run the 22-effect mismatch audit on the regenerated data — most
  should resolve, the remainder should be reclassified.

**Status (2026-05-09): VERIFIED RESOLVED.**
`reanalyze_knobs_4nibble.py` was re-run and updated 0 records — the
fix has already been applied to all `summary.json` files. The
committed `all_effects.json` already has `min_raw`/`max_raw`/
`min_display`/`max_display` fields with correct 4-nibble offset-binary
decoded ranges (e.g. COMP SUSTAIN: legacy `min/max = 0/15`,
correct `min_display/max_display = 0/100`; BOOST TONE:
`-50/+50`).
The 22-effect mismatch audit reports all 22 entries with explanations
(categories A–E), zero unresolved (category F): the count
discrepancies are about manual-vs-capture knob structure (BPM unit
toggles, TYPE/MODE conditionals, USER-scale conditionals,
captured-extras), NOT about value ranges. So 4-nibble decoding
correctly didn't change them.

**Tangential bug spotted:** `tools/build_effects_doc.py` aggregation
is non-deterministic — re-running it produces 61 lines of swapped
`name_manual_v2` attributions per run. Likely a dict iteration
order issue in `manual_xref_v2.py`. Filed as a follow-up; doesn't
affect the decoded value ranges, only manual-name attribution.

---

### P1-3. `firmware_overlay.json` flags subtype additions as "pending schema"; gxnarly already has the schema

**Evidence:**
- `docs/effects/firmware_overlay.json` `subtype_additions_pending_schema`
  block lists SD-1 (OD subtype 4), DS-1 (DIST subtype 4), three
  high-gain amps and six bass amps as untagged because `firmware_overlay`
  is keyed by category not by subtype.
- `gxnarly/Sources/GxnarlyCore/Dictionary/ParameterEntry.swift:7-61`
  defines a `type_min_firmware: { "<index>": "M.m" }` field that
  already does per-subtype gating.
- `gxnarly/devices/gx100.json` already has 4 entries with
  `type_min_firmware` set (OD index 4 → "2.0"; DIST index 4 → "2.0";
  AMP/AMP_BASS variants).

**Action (P1-3):**
- Adopt gxnarly's `type_min_firmware` schema in
  `firmware_overlay.json`, or add a parallel `type_overrides` block.
- Cross-walk against the v1 GX-100 manual chunks
  (`docs/manuals/GX-100_v1_Parameter_Guide_*.md`) to identify exactly
  which TYPE indices were added in v2.0 vs which were present in v1.x —
  this is now a doable diff thanks to the just-added v1 manual.

---

### P1-4. `menus.md` chart-correction notes still refer to address `0x0000_000D` as "EXP1 HOLD"

**Evidence:** `docs/menus.md:8-21` lists corrections including:
- `0x0000_000D` was "AUTO OFF" (wrong) → **EXP1 HOLD** (correct).
- `0x0000_000F` (correct) = AUTO OFF.
- User patches at `0x2000_0000` (not `0x6040_0000` as earlier notes).

These match the v2 manual `[SystemCommon]` block. Fine. But
`docs/firmware_versions.md` should reference the same authoritative
addresses for AUTO OFF when describing how min_firmware tags get
applied — currently it doesn't cite a specific offset.

**Action (P1-4):** Cross-link `menus.md` corrections from
`firmware_versions.md` and `midi_firmware_analysis.md` so the
authoritative offset map lives in one place.

---

### P1-5. Knob/Assign target-table inconsistency persists; canonical form not declared

**Evidence:** `docs/midi_firmware_analysis.md` §8.4 documents the
v1+v2 inconsistency between knob and assign tables (RING MOD vs RING
MODULATOR; RET vs RETURN LEVEL; PRIME VIBARTO typo). gxnarly's
dictionary uses categorical names, not numeric target-table indices, so
the disagreement doesn't propagate — but `docs/assign_target_table.json`
in this repo has 741 entries (0..740, matches v2 ✓) and presumably uses
one of the two label sets without saying which.

**Action (P1-5):** Pick a canonical label set (recommend the assign
table — `RING MODULATOR`, `SEND/RETURN RETURN LEVEL`, fix `VIBARTO`→
`VIBRATO`) in `assign_target_table.json`. Document the choice in
`midi_firmware_analysis.md` §8.4.

---

## P2 findings (open questions / unverified)

### P2-1. Memory Number / BANK EXTENT product-aware decoding not in gxnarly

**Evidence:** Manual v2 `[SystemCommon]` 0x00..0x03 holds Memory
Number with **product-specific decode** (GX-100: 50×4; GX-10: 66×3
with NIU holes). gxnarly's gx10.json and gx100.json both expose
patch-name and patch slots, but the per-product translation
(raw → "U03-2") is not in either dictionary or the helper code we
inspected.

**Action (P2-1):**
- Add product-aware Memory Number decode in this repo's Python (will be
  needed for any patch browser). Cross-reference the lookup tables
  in `midi_firmware_analysis.md` §4.3.
- File an issue against gxnarly to add per-product decode.

---

### P2-2. Setup region (`00 20 xx xx`) on v1 GX-100 firmware — never modeled in either project

**Evidence:**
- v1 manual lists 5 sub-blocks at `00 20 00 00`..`00 20 04 40`
  (`[SetupTemp]`, `[SetupTemp2]`, `[SetupTemp3]`, `[SetupEfct]`,
  `[SetupComm]`).
- v2 manual: removed entirely.
- `gx10-re/docs/protocol.md:625-635` mentions `0x00200003`
  (`Setup_temp ChainEditTrigger`) as a handshake bit BTS uses for chain
  edits — so this region IS used by Tone Studio.
- gxnarly: no entries at `0x00200000`.

**Open question:** If we want compatibility with GX-100 v1.x devices,
the Setup region must be modeled (or at least the ChainEditTrigger).
On v2 firmware it's gone — is the ChainEditTrigger relocated, or no
longer needed?

**Action (P2-2):**
- Probe the attached device (presumably v2 firmware): RQ1 at
  `0x00200003` size 1. If silent / out-of-range, ChainEditTrigger is
  v2-removed. Look for a replacement handshake (could be inferred from
  BTS traffic on a v2 device).
- Document in `protocol.md:625` whether the gotcha applies to v2.

---

### P2-3. Identity-Reply byte 11 ("`00H` Software revision level # 2") — observed value?

**Evidence:** Manual says always `00H` for byte 11. Other modern
Roland devices (e.g. GT-1000) use byte 11 to encode minor version.
We don't have a captured Identity Reply on file.

**Action (P2-3):** Capture and pretty-print the Identity Reply on
the attached device. If byte 11 is non-zero we have new information.

---

### P2-4. `0x7F000000`, `0x7F000003`, `0x7F000703` — still listed as "unknown system flag" in protocol.md

**Evidence:** `docs/protocol.md:425-430`. Manual is silent on the
`0x7F` region (it's runtime-only, not in the address tree). gxnarly
has `system_status: 0x7F000000` as a root but no specific entries
under it.

**Action (P2-4):** Sniff-and-document while BTS is running on the
attached device — at minimum the editor-attached handshake at
`0x7F000001` and the active-app-mode mirror at `0x7F000002`. Promote
out of "unknown" if found-stable.

---

### P2-5. Effect TYPE 78..82 (`SLICER, HUMANIZER, FEEDBACKER, SITAR SIM, AUTO WAH`) — does the GX-10 expose them today?

**Evidence:** `firmware_overlay.json` claims GX-10 has them since
v1.00 (launch). gxnarly's `gx10.json` includes the 5 effects as
ungated entries. Manual v2 lists them in the unified TYPE enum 0..82
without per-product gating.

**Action (P2-5):** On the attached GX-10, write each TYPE byte 78..82
to FxItem 1 TYPE (`0x10001100`) via DT1 and read back. If any returns
out-of-range or no reply, the per-product list needs updating.

---

### P2-6. v1 GX-100 manual just landed — diff against v2 GX-100 to enumerate firmware-2.0 additions per subtype

**Evidence:** `docs/manuals/GX-100_v1_Parameter_Guide_*.md` (just
added by `cc62cf0`) and the existing
`docs/manuals/GX-100_Parameter_Guide_*.md` (v2.0). The diff between
these enumerates exactly which TYPE indices were added in v2.0.

**Action (P2-6):**
- Run a structural diff (comparable to `manual_xref_v2.py` over both
  chunk sets) to produce a definitive list of v2.0-added subtypes.
- Resolve `firmware_overlay.json:113-137`
  `subtype_additions_pending_schema` against this list.
- Sync the result to gxnarly's `type_min_firmware` map.

---

## P3 findings (cosmetic / cleanup)

### P3-1. gxnarly `model_id: "0x0000"` is a 2-byte representation of a 5-byte field

`devices/{gx10,gx100}.json` declares `"model_id": "0x0000"`. The actual
Roland 5-byte Model ID is `00 00 00 00 0B`. The framing constant in
`Sources/GxnarlyCore/SysEx/RolandSysEx.swift:18` is correct
(`F0 41 10 00 00 00 00 0B`). The JSON metadata is misleading.

**Action (P3-1):** Change to `"model_id": "0x000000000B"` or split
into `family_code: "0x040B"` (already there) plus
`model_id_5b: "00 00 00 00 0B"`.

---

### P3-2. Pacing values: gx10-re's Python tools vs gxnarly's measured profile

gxnarly: `pace_gap_nanos: 0`, `rq1_timeout_nanos: 1_000_000_000`,
settle = 50 ms (per `bench/profile.json` and
`Sources/GxnarlyCore/SysEx/GxnarlySession.swift:343`). Validated at
0% drops over 30 s sustained, 60 ms p50, 61 ms p99, 17 msg/s ceiling.

`gx10-re/tools/*` use scattered `time.sleep(...)` calls (not audited
yet). For consistency and performance the Python side should adopt
the same profile.

**Action (P3-2):** Add a `tools/midi_pacing.py` (or absorb into
`midi_send.py`) that codifies these values with citations to
gxnarly's measured profile, and migrate the most-used probe scripts
to it.

---

### P3-3. gxnarly's "675 parameters" vs gx10-re's "638 effect knobs across 81 effects"

**Evidence:** `gxnarly` Plan-Phase-4.md:23-33 reports 675 entries (638
effect-knob, 37 system/master/assigns/tuner). `gx10-re` doesn't
report a comparable single number. Both projects could be miscounting
the same way (see P0-1: stale single-byte ranges) — verify after
P1-2 regeneration.

**Action (P3-3):** After P1-2 fix, generate a unified
"parameter inventory" report, comparing entry counts per category
across the manuals + gx10-re + gxnarly. Any disagreement is a missing
parameter on one side.

---

### P3-4. `gaps.md` §1.1 (effect-chain INSERT/DELETE/OVERWRITE marked BROKEN) — manual is silent

`docs/gaps.md` reports the chain-edit buttons no-op, possibly because
of the `0x00200003` ChainEditTrigger gotcha noted in
`protocol.md:625-635`. With the v2 manual deleting the Setup region,
the gotcha may no longer apply on v2 firmware — or BTS itself may have
been updated.

**Action (P3-4):** Re-test in current BTS on the attached device
(presumably v2 firmware). Update or close `gaps.md §1.1` accordingly.
Connects to P2-2.

---

## Priority-ordered work plan

1. **Verify P0-1 on hardware** — biggest risk, single test.
2. **Verify P1-1 on hardware** — single Identity Request, settles
   version detection across both projects.
3. **Probe device for P2-2, P2-4, P2-5** in one capture session.
4. **Run P1-2** (regen `all_effects.json` + `effect_catalog.md`) —
   unblocks P3-3 and P1-3 / P2-6 cross-checks.
5. **Run P2-6** (v1↔v2 GX-100 manual diff) — resolves
   `firmware_overlay.json` "pending" tags.
6. **Fix P0-2, P0-3, P3-1** in the gxnarly JSONs (file an upstream
   issue; we can't push from here).
7. **Documentation polish**: P1-4, P1-5, P3-2, P3-3, P3-4.

## Recommendation for the Python implementation in this repo

Keep Python — agreed. Three concrete recommendations from the
gxnarly cross-check:

- **Adopt gxnarly's parameter schema concepts** (per-entry
  `min_firmware` and per-type `type_min_firmware`) into a Python
  dataclass model. The gxnarly schema is well-thought-through; we
  shouldn't reinvent it.
- **Adopt gxnarly's measured pacing profile** for our SysEx tools
  (P3-2). They've benchmarked it; we shouldn't re-derive.
- **Don't adopt gxnarly's `knob_cell` encoding** until P0-1 is
  verified. If the encoding is wrong, our Python implementation has
  a chance to do it right from the start. Our 4-nibble decoder in
  `tools/reanalyze_knobs_4nibble.py` is the right starting point.

---

## Source files

- `docs/manuals/GX-100_*MIDI_Imple_eng0{1,2}_W.md`
- `docs/manuals/GX-{100,10}_Parameter_Guide_*.md`
- `docs/manuals/GX-100_v1_Parameter_Guide_*.md` (just added)
- `docs/midi_firmware_analysis.md`
- `docs/protocol.md`, `effect_catalog.md`, `firmware_versions.md`,
  `menus.md`, `official_xref.md`, `gaps.md`, `bpm_encoding.md`
- `docs/effects/all_effects.json`, `firmware_overlay.json`
- `docs/assign_target_table.json`, `per_effect_types.json`
- `/home/kaltan/src2/gxnarly/Sources/GxnarlyCore/SysEx/RolandSysEx.swift`
- `/home/kaltan/src2/gxnarly/Sources/GxnarlyCore/SysEx/GxnarlySession.swift`
- `/home/kaltan/src2/gxnarly/Sources/GxnarlyCore/Device/FirmwareVersion.swift`
- `/home/kaltan/src2/gxnarly/Sources/GxnarlyCore/Dictionary/ParameterEntry.swift`
- `/home/kaltan/src2/gxnarly/Sources/GxnarlyCLI/VerifyDict.swift`
- `/home/kaltan/src2/gxnarly/Sources/GxnarlyTransportALSA/ALSATransport.swift`
- `/home/kaltan/src2/gxnarly/devices/{gx10,gx100,_schema}.json`
- `/home/kaltan/src2/gxnarly/Plan.md`, `Plan-Phase-4.md`,
  `bench/profile.json`
