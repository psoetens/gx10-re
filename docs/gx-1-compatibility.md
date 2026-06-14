# BOSS GX-1 — compatibility assessment vs GX-10 / GX-100

**Status:** desk study from BTS source only. No GX-1 hardware probed.
**Source:** `BOSS TONE STUDIO for GX-1.app` v1.0.0 build 22
(`Copyright 2026 Roland Corporation`), installed on macOS alongside the
GX-10 (v1.0.0) and GX-100 (v2.0.3) BTS apps. All three are native
macOS shells around an HTML/JS editor in
`Contents/Resources/html/js/`.

This document answers: *what would it take to make the gxnarly editor
(and this `gx10-re` reference set) support the GX-1 too?*

Short version: **the GX-1 is the same protocol *family* but not
drop-in compatible.** It speaks the same Roland DT1/RQ1 SysEx dialect
over the same 4-byte address space with the same nibble/7-bit size
encodings, and its effect roster overlaps heavily with the GX-10/100.
But it has a **different SysEx model ID**, a **dual guitar/bass
architecture** that doubles every effect block, and several **new
top-level regions** (user IR upload, Gear Suite, global EQ, looper,
jam/session player). It is built from a **newer BTS codebase
generation** with a different parameter-table format, so the existing
GX-10/100 catalog-extraction tooling does **not** read it as-is.

---

## 1. The breaking difference: SysEx identity

`js/config/product_setting.js`:

| Field | GX-10 | GX-100 | **GX-1** |
|-------|-------|--------|----------|
| `name` | `GX-10` | `GX-100` | `GX-1` |
| `modelId` | `00 00 00 00 0B` (5 bytes) | `00 00 00 00 0B` (5 bytes) | **`01 06 0D` (3 bytes)** |
| `deviceId` | `10` | `10` | `10` |
| `lengthOfAddr` | 4 | 4 | 4 |
| `lengthOfSize` | 4 | 4 | 4 |
| `numOfUserPatch` | 99 (0–98) | up to ~300 | **99** |
| `numOfIrData` | 16 | 16 | **8** |
| `version` | 1.0.0 | 2.0.3 | 1.0.0 b22 |
| modes | guitar only | guitar only | **guitar + bass** |

**Key takeaway:** GX-10 and GX-100 share `modelId 00 00 00 00 0B` — that
is *why* one catalog and one codec serve both (the BTS build switches
GX-10 vs GX-100 behaviour at runtime, e.g. `BankExtentMinGX10` /
`BankExtentMaxGX10` fields in `SystemCommon`). The GX-1 uses Roland's
newer **3-byte model ID `01 06 0D`**. The DT1/RQ1 envelope
(`F0 41 <devId> <model…> <cmd> <addr> <data> <sum> F7`) therefore
differs in *both the value and the length* of the model-ID field. Any
codec that hardcodes the 5-byte `00 00 00 00 0B` header will not talk
to a GX-1, and a GX-1 will ignore those messages.

> The `01 06` Roland-model prefix and the leftover
> `toneCentral.dev.url … /me-90b.json` reference suggest the GX-1
> firmware/BTS lineage descends from the ME-90B generation, not the
> GX-100 generation. That matches the codebase-structure differences in
> §4.

---

## 2. What is the *same* (the good news)

- **Transport / framing.** Same class-compliant USB-MIDI path, same
  Roland Exclusive DT1 (`0x12`) / RQ1 (`0x11`) commands, same Roland
  checksum.
- **Address space shape.** 4-byte addresses, top-level regions at the
  same kind of bases:
  - `SETUP   @ 0x00000000`
  - `SYSTEM  @ 0x10000000`
  - `MEMORY  @ 0x20000000` (user patches)
  - `TEMP    @ 0x50000000` (edit buffer)
- **7-bit patch stepping.** Patch *n* lives at `0x20000000 +
  (n_hi<<24 | n_mid<<20 …)` with the high nibble stepping 7-bit-style
  (`…0x28700000, 0x29000000, 0x29100000…`) — the same high-byte-wraps-
  at-0x80 addressing gxnarly already had to special-case for the
  program map. **The 7-bit address fix gxnarly shipped for GX-10
  applies here too.**
- **Size encodings.** Same token vocabulary: `INTEGER1x7` (one 7-bit
  byte), `INTEGER2x4 / INTEGER4x4` (multi-byte nibble-packed,
  4-bits-per-byte). Same `lengthOfSize: 4` RQ1 raw-big-endian size
  field — consistent with the `gx10-re` finding that RQ1 size is raw
  4×7-bit big-endian (see `docs/protocol.md`).
- **Per-memory block layout is recognisable.** Each patch
  (`MEMORY` child) decomposes into the familiar blocks:
  `COM, CHAIN, FX1(_COM), FX2(_COM), FX3(_COM), AMP, DLY, REV, NS, FV,
  CTL, ASGN(×8)` — plus the new ones in §3.
- **Effect roster overlaps heavily.** The FX type names in
  `js/businesslogic/knob_const.js` are the GX-10/100 set: COMP,
  LIMITER, ENHANCER, TOUCH/AUTO/FIXED WAH, DEFRETTER, SLOW GEAR,
  AC.GTR SIM, AC RESO, SITAR SIM, F-BACKER, OD/DS, PARA EQ, GEQ,
  CHORUS, FLANGER, PHASER, SCRIPT PH, CLASSIC VIBE, ROTARY, VIBRATO,
  TREMOLO, SLICER, PAN, RING MOD, HUMANIZER, … Much of the per-effect
  knob semantics should transfer.

So conceptually the entire gxnarly architecture (catalog-driven
register map, `MIDIClientService` seam, diff/reconcile, virtual
device) ports. The work is re-deriving the data, not re-inventing the
design.

---

## 3. What is *new* / different in the GX-1 data model

From `js/config/address_map.js` (1705 lines; the GX-1 inlines the full
parameter DB here — see §4) and `product_setting.js`:

**Dual guitar / bass mode (the biggest modelling change).**
`guitarMode`/`bassMode` with `defaultMode: 0 (G) / 1 (B)`. The register
map carries **parallel guitar and bass variants** of effect selectors,
e.g. `MEMORY_FX1_COM_TYPE` *and* `MEMORY_FX1_COM_TYPE_BASS` (each
`max 37` → ~38 types per FX slot, two separate enums), plus system-
level `TUNER_MODE_BASS`, `OUTPUT_SELECT_BASS`, bass-specific FX
sub-blocks (`FX1_BASS_COMP_TYPE`, `FX1_BASS_SYN_TYPE`,
`*_BASS_ODDS_TYPE`). A patch belongs to one mode; the editor swaps
whole effect palettes. gxnarly's data model (one effect catalog, one
TYPE byte) would need a **mode axis**.

**New per-memory blocks** (not in GX-10/100): `FX3A`, `ODDS`
(overdrive/distortion split out), `PFX` (pedal-FX block with its own
`PFX_WAH_TYPE`), and a per-patch view of `GLOBAL_EQ`.

**New top-level / system regions:**
- `SYSTEM_GLOBAL_EQ_COM` / `SYSTEM_GLOBAL_EQ` — global EQ as a system
  feature (gxnarly already surfaces a GLOBAL EQ readout for GX-10; the
  GX-1 register addresses differ).
- `SYSTEM_INPUT_SETTING`, `SYSTEM_USB`.
- **User IR upload:** `IRDATA_NAME / IRDATA_SIZE / IRDATA_FILE /
  IRDATA_DATA` blocks and `irDataNameAddr: 0x50000000`; 8 user IR
  slots. This is a *file-transfer* feature (variable-length DT1
  streaming of cabinet impulse responses) with no GX-10/100 analogue.
- **Gear Suite:** `GSDATA_DATA` block + `gsData` librarian + a
  `bosstoneexchange.com/gear/gx-1` integration.
- **Looper:** `SYSTEM_COM_LOOP_MODE / LOOP_REC_ACTION / LOOP_LEVEL`.
- Misc system params: LED `COLOR`, `LED_BRIGHTNESS`,
  `HEADPHONE_ATTENUATOR`, `MEM_CHANGE_BOOST`, three assignable top-
  panel knobs (`KNOB1/2/3_SETTING`, `max 1024` assign-target range),
  `DOWN_UP_FUNC` / `UP_CTL1_FUNC` footswitch mapping.

**Patch count / extents.** 99 user patches (0–98), with
`MEM_EXTENT_MIN/MAX` (max 197 — note the SETUP `MEMORY_NUMBER` max 202
hints at a preset region beyond the 99 user slots).

**File formats.** Liveset `.tsl` (same extension as GX-10/100, but
`formatRev` and internal layout will differ), backup `.alb`. IR import
is its own path.

---

## 4. Why the existing extraction tooling won't just work

The GX-10/100 catalog (`catalogs/bts_effect_catalog_complete.json`) is
built by `tools/merge_bts_into_catalog.py` from BTS's
`js/config/effect_parameter.js` — a table that pairs each parameter
with its **display label, display range, unit, step, and raw→display
lookup**.

**The GX-1 BTS has no `effect_parameter.js`.** It is a newer codebase
generation with a different organisation:

- `js/config/address_map.js` holds the register map only — `addr, size,
  ofs, init, min, max, name` per parameter, where `name` is a symbolic
  `PRMID_*` token (e.g. `PRMID_MEMORY_FX1_COM_TYPE`), **not** a human
  label.
- Human labels, enum option-lists, and display formatting live
  elsewhere — `js/businesslogic/knob_const.js` (+ `knob_const_bass.js`),
  the per-item controllers, and `editor_fx.js` / `effect_controller.js`.
  The `PRMID_*` tokens are **not** used as lookup keys for the strings,
  so there is no single join column.
- Other structural moves: chain editor split into
  `js/businesslogic/chain/*` (ChainInput, ChainLevel, ChainSpeakOut,
  EffectLine); control/assign under `control_assign/*`; IR under `ir/*`;
  a whole `session/*` jam-player subsystem (YouTube + transport +
  markers); `rhythm/*`.

So a GX-1 catalog requires a **new extractor** that:
1. parses `address_map.js` for the authoritative register map
   (addr/size/min/max/init per `PRMID_*`), then
2. harvests labels + enum option-lists from `knob_const.js` and the
   controller files and joins them to the PRMIDs (likely by
   block+offset, not by name), and
3. models the guitar/bass mode axis and the new blocks.

This is meaningfully more work than the GX-10/100 merge, which had one
rich table to read.

---

## 5. What it would take — concrete checklist

### In `gx10-re` (reference + tooling) — do this first
- [ ] **Capture a live GX-1 identity reply** (Identity Request → reply)
      to confirm the `01 06 0D` model ID and device family on real
      hardware before trusting the BTS constant.
- [ ] Add a **GX-1 extractor** (`tools/extract_gx1_address_map.py` or
      similar) that parses `address_map.js` → register map, plus a
      label/enum harvester from `knob_const.js` + controllers.
- [ ] Produce GX-1 catalog JSONs alongside the GX-10/100 ones (don't
      overwrite — the model IDs and TYPE enums differ). Keep
      `bts_effect_catalog_complete.json` GX-10/100-only; add e.g.
      `gx1_effect_catalog.json`.
- [ ] Document the GX-1 SysEx envelope + address regions in
      `docs/protocol.md` (or a `protocol-gx1.md`), noting the 3-byte
      model ID and the new IR file-transfer / Gear Suite streaming.
- [ ] Decide how to represent the **guitar/bass mode axis** in the
      catalog schema (`docs/bts_catalog_schema.md`).

### In gxnarly (the editor) — once catalogs exist
- [ ] **Per-device model ID in the codec.** Replace any hardcoded
      `00 00 00 00 0B` with a device-family parameter; the codec must
      emit/parse a 3-byte header for GX-1. This is the single
      must-have for any GX-1 traffic.
- [ ] Device detection: map identity reply → {GX-10, GX-100, GX-1};
      select catalog + codec header accordingly.
- [ ] Codegen: consume the new GX-1 catalog JSONs into a parallel set
      of generated `Catalog/*` types (or a device-tagged catalog).
- [ ] Model the **guitar/bass mode** as first-class (patch carries a
      mode; effect palette + some system params switch on it).
- [ ] Adjust patch count (99) and address stepping (already 7-bit-
      aware — should reuse the existing program-map fix).
- [ ] Decide scope for the **new features**: user-IR upload (variable-
      length DT1 file transfer — non-trivial), Gear Suite, looper,
      session/jam player. These are likely *out of scope* for a first
      GX-1 release; the editor can ignore those regions and still edit
      patches.

### Likely reusable as-is
- `MIDIClientService` seam and `MockMIDIService`.
- Pacing / token-bucket machinery (re-tune against GX-1 firmware;
  `product_setting` advertises `interval: 20ms`, `timeout: 15s`).
- Diff/reconcile, virtual-device model, persistence layer.

---

## 6. Effort estimate (rough)

| Area | Effort | Risk |
|------|--------|------|
| Per-device model-ID in codec | Small | Low |
| GX-1 catalog extractor (new BTS format) | **Medium–Large** | Medium (label/PRMID join, no single table) |
| Guitar/bass mode axis in model + codegen | Medium | Medium |
| Patch editing (FX/AMP/DLY/REV/NS) parity | Medium | Low (roster overlaps GX-10/100) |
| User-IR upload / Gear Suite / looper / jam | Large each | High | (defer)

**Bottom line:** core patch editing for the GX-1 is achievable and
reuses ~all of gxnarly's architecture, gated on (a) a per-device SysEx
header and (b) a new catalog extractor for the newer BTS table format,
plus modelling the guitar/bass mode. The headline GX-1-only features
(IR upload, Gear Suite, looper, jam player) are large, independent
add-ons best deferred. **Verify the model ID and one round-trip
DT1/RQ1 against real GX-1 hardware before committing to any of it.**

---

*Method note: findings are from static reading of the three BTS app
bundles' `Resources/html/js/` only. Where this doc states register
addresses or enum maxes, they are BTS constants, not hardware-verified.
Per repo convention all device-side findings are filed here in
`gx10-re` first, then flowed into gxnarly via codegen.*
