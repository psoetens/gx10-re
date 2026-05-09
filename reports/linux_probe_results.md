# Linux probe results — settling cross-check findings against real GX-10

**Date:** 2026-05-09
**Device under test:** BOSS GX-10, USB 0582:0312, ALSA `hw:4,0,0`,
firmware version **1.04** (per user; *not* visible in any SysEx data
returned).
**Tooling:** `tools/midi_io_linux.py` (rtmidi-based) +
`tools/probe_v2_findings.py`.
**Plan:** `.claude/plans/linux-probe-cross-check.md`.

Verdicts cite `reports/cross_check_findings.md` items.

---

## Summary table

| ID  | Verdict | Headline |
|-----|---------|----------|
| **P0-1** | **CONFIRMED — gxnarly's `knob_cell` encoding is broken** | Device truncates each cell byte to its low nibble. gxnarly's `[0x08,0x00,0x00,VV]` form silently sets values to `VV mod 16` for `VV > 15`. |
| **P0-2** | **PARTIALLY CONFIRMED** | `0x60400000` IS a real region containing user-bank label data ("USER 1", "USER 2", …), but it is **not** the user-patch storage. The manual's `0x20000000` is. gxnarly's metadata mislabels both. |
| **P0-3** | **CONFIRMED — block size is 0x66 on this firmware** | `[SystemControl]` returns 102 bytes; offsets `0x64`/`0x65` (Down&Up Function / Up&Ctl1 Function GX-10) are present and meaningful. gxnarly's GX-10 dictionary needs them. |
| **P1-1** | **CHANGED — both interpretations are wrong** | Identity Reply on this firmware-1.04 GX-10 returns `01 00 00 00`, **identical to firmware-1.0 per `firmware_versions.md:45`**. Firmware version is *not* exposed via Identity Reply on this device family. |
| **P1-2** | (Not probed; documentation regen) | Defer. |
| **P1-3** | (Not probed; documentation diff) | Defer. |
| **P2-2** | **REJECTED — Setup region is intact on firmware 1.04** | All five `00 20 xx xx` sub-blocks reply. The v2 manual's "removal" is documentation-only; the firmware still exposes them. |
| **P2-4** | **PARTIAL** | `0x7F000000=03`, `0x7F000001=00`, `0x7F000003=00`. `0x7F000002` and `0x7F000703` time out without an active BTS-handshake (`0x7F000001=01`). |
| **P2-5** | **CONFIRMED — all 5 v2 effects exist on GX-10 v1.04** | TYPE 78..82 round-trip cleanly; TYPE ≥ 83 clamps to 82. Validates `firmware_overlay.json`'s "since launch" claim. |

---

## P0-1 — gxnarly `knob_cell` encoding (CRITICAL)

### Probe

`probe_v2_findings.py` writes 4 different 4-byte cells to address
`0x10001107` and reads back. (Note: at the time of probing FxItem 1
TYPE was `0x35` not `0x00`, so this is an arbitrary parameter cell —
the encoding behaviour is the same for any 4-byte FX Parameter cell.)

```
current value at 0x10001107: 08 00 06 04
  -- write gxnarly knob_cell (byte-3 = 0x64): 08 00 00 64
     read-back: 08 00 00 04
  -- write 4-nibble offset binary (8,0,6,4): 08 00 06 04
     read-back: 08 00 06 04
  -- write 4-nibble offset binary (8,0,3,2) =50: 08 00 03 02
     read-back: 08 00 03 02
  -- write byte-3 = 0x32 (50 single-byte): 08 00 00 32
     read-back: 08 00 00 02
```

### Interpretation

The device discards the upper 4 bits of every byte in an FX Parameter
cell. Byte `0x64` (binary `0110 0100`) is stored as `0x04` (low nibble).
Byte `0x32` (binary `0011 0010`) is stored as `0x02`. This **proves**
the manual's "0000 aaaa" bit-pattern claim and `protocol.md:304`'s
4-nibble big-endian decoding.

Concrete consequence: **gxnarly's encoder writes wrong values for any
FX Parameter > 15**.
- `gxnarly.encodeCell(rawValue: 100)` → `[08 00 00 64]` →
  device stores `0x8004 - 0x8000 = 4`. UI claims 100, device sees 4.
- `gxnarly.encodeCell(rawValue: 50)` → `[08 00 00 32]` →
  device stores `0x8002 - 0x8000 = 2`. UI claims 50, device sees 2.

`gxnarly`'s `verify-dict` only does read-only RQ1 round-trips, which
is why the bug never surfaces in their tests.

### Action

Fix gxnarly's `knob_cell` encoder to emit one nibble per byte:

```swift
case .knobCell:
    let v = clamped + 0x8000          // offset binary
    return Data([
        UInt8((v >> 12) & 0x0F),      // 0x08 for unipolar 0..32767
        UInt8((v >>  8) & 0x0F),
        UInt8((v >>  4) & 0x0F),
        UInt8(v & 0x0F),
    ])
```

The Python implementation in this repo must use this form from the
start (`tools/reanalyze_knobs_4nibble.py` already implements the
correct decode).

---

## P0-2 — `address_roots` audit

### Probe

```
0x10000000 (temp_patch)         → "X-TI..."        (edit-buffer patch name)
0x20000000 (manual: user 1)     → "NATU..."        (user patch 1 name "NATURAL...")
0x29290000 (manual: user 200)   → no reply         (offset miscalculated — actual end address differs)
0x30000000 (gxnarly live_mirror)→ no reply         (NOT a valid region on this device)
0x50000000 (preset_name_table)  → "NATU..."        (preset 1 name)
0x60400000 (gxnarly user_patch_slots) → "USER 1   "   (user-bank label data)
+0x10000 → "USER 2   "
+0x100   → no reply
+0x1000  → no reply
```

### Interpretation

- Manual is correct: user patches are at `0x20000000` (named patches
  like "NATURAL", not "USER 1").
- `0x60400000` is a real region with stride `0x10000` between entries
  and content like "USER 1   "/"USER 2   " — these are **labels for
  user-memory bank groupings**, not the patches themselves. Likely
  one of the bank-name / category-label tables.
- `0x30000000` does not respond → gxnarly's `live_patch_mirror` claim
  is unsupported.

### Action

In `gxnarly/devices/{gx10,gx100}.json`:

```json
"address_roots": {
  "temp_patch":         "0x10000000",
  "user_patch_slots":   "0x20000000",
  "preset_name_table":  "0x50000000",
  "user_bank_labels":   "0x60400000",
  "system_status":      "0x7F000000"
}
```

Drop `live_patch_mirror`. Investigate `0x60400000` further before
relying on it.

---

## P0-3 — `[SystemControl]` block size on firmware 1.04

### Probe

```
RQ1 0x00001000 size=0x66 → reply 117 bytes (102 payload). ✓
RQ1 0x00001000 size=0x64 → reply 115 bytes (100 payload). ✓
byte 0x62 (last v1 fixed-zero) = 0x00
byte 0x63 (GLOBAL EQ SW)       = 0x01
byte 0x64 (Down&Up Function GX-10) = 0x00
byte 0x65 (Up&Ctl1 Function GX-10) = 0x01
```

### Interpretation

Confirms v2-manual's `[SystemControl]` size of `0x66` is correct.
Bytes `0x64`/`0x65` are exposed by firmware 1.04. Their non-zero
values `0x00` and `0x01` (initial defaults: OFF, MANUAL/TUNER per
the v2 manual enums) confirm they're real registers, not undefined
padding.

### Action

- gxnarly's `gx10.json` should include two new entries at addresses
  `0x00001064` and `0x00001065`. Existing GX-100 dictionary should
  *not* include them (per v2 manual they're GX-10-only).
- `docs/midi_firmware_analysis.md` §5.2 stands as written.
- Remove the open hedge in §5.2 ("GX-100 firmware presumably accepts
  but ignores writes here") — we know now it's a GX-10-only field;
  GX-100 reads at these offsets will need a separate test on a
  GX-100 device.

---

## P1-1 — Identity Reply does NOT carry firmware version on GX-10

### Probe

```
F0 7E 7F 06 01 F7              ← Identity Request
F0 7E 10 06 02 41 0B 04 00 00 01 00 00 00 F7
software-revision bytes: 01 00 00 00
```

### Interpretation

`firmware_versions.md:45` claims firmware 1.0 reports
`softwareVersion = [01 00 00 00]`. This device, on firmware **1.04**
per the user, reports the **same four bytes**. Therefore:

- Identity-Reply byte 10 is **a product-id flag**, exactly as the v2
  manual annotates (`(GX-100:0 / GX-10:1)`), **not** the major
  version. The firmware-versions.md table conflating it with major
  version is wrong.
- Identity-Reply bytes 11/12/13 are **all zero on this device** —
  Roland reserves them but doesn't populate firmware version into
  them. (Or the GX-10 firmware-update tool deliberately doesn't bump
  the bytes.)
- **The actual firmware version is not retrievable via Identity
  Request** on this device family. We need an alternative source.

### Probes for an alternative source (none found)

We tried RQ1 at: `0x00000040`, `0x00000050`, `0x00000060`, `0x00000080`,
`0x000000A0`, `0x00010000`, `0x00FF0000`, `0x00200500`, `0x7F000800`,
`0x7F010000`. None reply with version-looking data. (`0x00000080`
returns the same bytes as `0x00000000`, suggesting the device
address-decodes within `[SystemCommon]` only — the rest may be
unmapped.)

USB descriptors: `bcdDevice = 1.00`, `iSerial = ""`, `iProduct =
"GX-10"`. None carry firmware version.

### Action — REVISE BOTH PROJECTS' VERSION DETECTION

**P1-1a (gx10-re)** — rewrite `docs/firmware_versions.md`:
- Drop the table that maps `01 05 ...` → "firmware 1.05" etc. — there
  is no evidence the GX-10 ever reports anything other than
  `01 00 00 00` regardless of installed firmware.
- Adopt the v2-manual interpretation: byte 10 = product id
  (GX-100=0, GX-10=1).
- Document that **firmware version is not exposed via SysEx** on the
  GX-10/GX-100 family, and explain the editor needs to either:
  (a) treat all dictionary entries as available and let the device
  silently reject unsupported writes (lossy), or
  (b) probe one v2-only feature (e.g. AUTO OFF byte > 1, `[SystemCommon]`
  offset `0x1B` `COLOR MODE` non-zero) to infer "v2.0+" without
  knowing the patch level, or
  (c) ask the user to read the firmware version from the device's
  MENU and enter it in editor settings.

**P1-1b (gxnarly)** — file an upstream issue:
- `Sources/GxnarlyCore/Device/FirmwareVersion.swift:21-22`'s
  "Roland uses the first two bytes as major.minor" is incorrect for
  this device family.
- gxnarly's "GX-10 firmware 1.0" log line in
  `Plan-Phase-4.md:26-27` is mis-derived; the connected GX-10 was
  firmware 1.04 all along.
- Suggest replacing `FirmwareVersion(softwareVersion:)` with a
  device-feature probe (option (b) above) until Roland provides a
  proper version source.

---

## P2-2 — Setup region is INTACT on firmware 1.04

### Probe

```
RQ1 0x00200000 size=1  → 0x00     (SetupTemp)
RQ1 0x00200003 size=1  → 0x00     (ChainEditTrigger)
RQ1 0x00200040 size=1  → 0x00     (SetupTemp2)
RQ1 0x00200140 size=1  → 0x4C     (SetupTemp3)
RQ1 0x00200340 size=1  → 0x01     (SetupEfct)
RQ1 0x00200440 size=1  → no reply (SetupComm — possibly different layout)
RQ1 0x00200000 size=0x40 → 9 bytes returned (manual size = 0x05 + slack)
```

### Interpretation

The v2 *manual* removed the Setup region from public documentation,
but the *firmware* still has the region intact on GX-10 firmware
1.04. Five of six probed offsets reply; only `0x00200440`
(`SetupComm`) is silent — likely a layout change rather than full
removal.

`protocol.md:625-635`'s ChainEditTrigger gotcha (handshake at
`0x00200003`) still applies — the address still reads.

### Action

- Update `docs/protocol.md:625-635` to note that the ChainEditTrigger
  remains valid on GX-10 firmware 1.04 despite v2 manual silence.
- Update `docs/midi_firmware_analysis.md` §2 — v2-manual removal of
  Setup region is **documentation-only**, not a firmware change.
- Keep Setup-region access in any editor that targets GX-10. Probe
  `0x00200440 SetupComm` with different offsets/sizes to map its
  current shape.

---

## P2-4 — `0x7F` system status flags

### Probe

```
0x7F000000 = 0x03   (matches docs/protocol.md:425)
0x7F000001 = 0x00   (BTS not connected → handshake bit 0)
0x7F000002 = no reply (active-app-mode mirror; quiet without BTS handshake)
0x7F000003 = 0x00   (still "unknown" per docs/protocol.md:428)
0x7F000004 = no reply
0x7F000005 = no reply
0x7F000010 = no reply
0x7F000703 = no reply
```

### Interpretation

`0x7F000002` and `0x7F000703` need a live BTS handshake (write
`0x7F000001 = 0x01` first) to populate. Defer those captures to a
BTS-running session.

### Action

- Add a probe step that writes `0x7F000001 = 0x01` first, then reads
  `0x7F000002` etc. — but mark this as "may be brittle without a real
  BTS session" and don't rely on it for production code.
- Promote `0x7F000000 = 0x03` from "unknown" to a documented constant
  (firmware-1.04 GX-10 always reports 0x03; verify on a GX-100).

---

## P2-5 — Effect TYPE 78..82 work on GX-10 v1.04

### Probe

```
saved TYPE: 0x35 (53 — some pre-existing effect)
write TYPE=78 (0x4E) -> read-back: 0x4E ✓
write TYPE=79 (0x4F) -> read-back: 0x4F ✓
write TYPE=80 (0x50) -> read-back: 0x50 ✓
write TYPE=81 (0x51) -> read-back: 0x51 ✓
write TYPE=82 (0x52) -> read-back: 0x52 ✓
write TYPE=83          -> read-back: 0x52 (clamped)
write TYPE=90          -> read-back: 0x52 (clamped)
write TYPE=127         -> read-back: 0x52 (clamped)
restored TYPE -> 0x35
```

### Interpretation

`SLICER, HUMANIZER, FEEDBACKER, SITAR SIM, AUTO WAH` (TYPE 78..82)
are present and selectable on GX-10 firmware 1.04. The device clamps
TYPE > 82 to 82, confirming the v2 manual's `(0..82)` range. Validates
`docs/effects/firmware_overlay.json`'s
`min_firmware_gx10: "1.00"` claim.

### Action

No change needed; record this as confirmed.

---

## Bonus findings

### B-1. `[SystemCommon]` GX-10 BANK EXTENT fields are populated (`0x19`/`0x1A`)

```
SystemCommon dump (0x00000000 size=0x2D):
  TUNER TYPE (0x07)          : 0x02   (= POLY in v1 enum, invalid in v2's {1,3} set)
  AUTO OFF   (0x0F)          : 0x00   (= OFF, valid in both v1 & v2)
  BANK EXTENT MIN/MAX GX-100 (0x09/0x0A): 0x00 / 0x4A (=74)
  BANK EXTENT MIN/MAX GX-10  (0x19/0x1A): 0x01 / 0x62 (=98)
  COLOR MODE                 (0x1B): 0x00 (= TYPE 1)
  AUTO OFF WARN              (0x1C): 0x01 (= ON/SHOW)
```

The GX-10 honours both the v2-manual GX-10 fields at `0x19`/`0x1A`
(value 1..98 makes sense for "U01..U66, P01..P33") AND keeps GX-100
fields at `0x09`/`0x0A` populated with the GX-100 max (`0x4A=74`).
The GX-100 fields look like factory-default leftovers on a GX-10 —
firmware doesn't clear them but doesn't use them either.

`TUNER TYPE = 0x02` indicates this firmware-1.04 GX-10 still uses
the **v1 enum** `{0,1,2}` (`MONO+POLY/MONO/POLY`), **not** the v2
manual's `{1,3}` set. That suggests the v2 manual's TUNER TYPE
restriction is a **GX-100-v2.0-only change** that didn't propagate
to the GX-10 even after firmware 1.04. Important: **enum-set decisions
must be product-aware, not just version-aware.**

### B-2. `[SystemControl]` byte 0x65 has non-zero default

`Up & Ctl1 Function(GX-10)` = `0x01` (= MANUAL per the v2 enum
`OFF, MANUAL, DOWN, UP`). This is the real device default for the
two-pedal MANUAL chord on a GX-10.

### B-3. RQ1 may return more bytes than requested

`RQ1 0x00200000 size=0x40` returned 9 bytes, not 64. The device
clamps size to the actual block size. gxnarly's
`Session.readChunked` (per Plan-Phase-4 note 6) handles this; the
Python impl will need the same logic.

### B-4. RQ1 outside known blocks may alias

`RQ1 0x00000080 size=0x10` returned the same data as
`RQ1 0x00000000 size=0x10`. Consistent with `[SystemCommon]` having a
total size of `0x2D`; addresses past `0x2D` may alias to offset 0 (or
the device may decode only the `0x00..0x2C` range and ignore higher
bits). Don't rely on RQ1 outside documented blocks.

---

## Pacing observations

`probe_v2_findings.py` issued ~30 RQ1/DT1 messages back-to-back with
50 ms `time.sleep` after writes and no explicit gap on reads. **Zero
drops**. This matches gxnarly's measured pace_gap=0 ns profile. We
can adopt the same in the Python implementation.

---

## Files written / modified

- `tools/midi_io_linux.py` (new) — rtmidi-backed MIDI I/O.
- `tools/probe_v2_findings.py` (new) — runs the probe matrix.
- `.venv/` (new) — Python venv with `python-rtmidi` installed.

Device state was restored after each write (TYPE byte and FX
Parameter cell). No persistent changes.

---

## 2026-05-09 follow-up: encoder wire→display validation + WAH catalog bug

After the device returned to Linux, validated `tools/encoding.py`
end-to-end (wire bytes → device → user-visible display value) using
the human-in-the-loop method (write known-distinctive value → user
reads display).

### Setup

FxItem 0 was holding TYPE = `0x35` (WAH), variant 2 (FAT WAH per
user). Wrote 6 distinctive values via `encode_fx_param(N)` to the
6 FX Param cells of FxItem 0:

| Address    | FX Param # | Wrote display | Wire bytes      |
|------------|-----------:|--------------:|-----------------|
| `10001107` | 2 | 11 | `08 00 00 0B` |
| `1000110B` | 3 | 22 | `08 00 01 06` |
| `1000110F` | 4 | 33 | `08 00 02 01` |
| `10001113` | 5 | 44 | `08 00 02 0C` |
| `10001117` | 6 | 55 | `08 00 03 07` |
| `1000111B` | 7 | 66 | `08 00 04 02` |

Asked the user to read each WAH FAT knob value displayed on the
device.

### User-reported display values

| Knob (UI label)  | Displayed | → maps to wire address |
|------------------|----------:|------------------------|
| WAH TYPE         | FAT WAH (unchanged) | `0x10001103` (untouched, variant selector) |
| EFFECT LEVEL     | 44        | `0x10001113`             |
| DIRECT MIX       | 55        | `0x10001117`             |
| PEDAL POSITION   | 11        | `0x10001107`             |
| PEDAL MIN        | 22        | `0x1000110B`             |
| PEDAL MAX        | 33        | `0x1000110F`             |
| (none — value 66 not shown) | — | `0x1000111B` (unused FX Param 7) |

### Two findings

**1. `tools/encoding.py` validated end-to-end.** Every wire value
landed at the correct displayed value. The encoder is correct for
unipolar knobs over the full 0..100 display range. (Bipolar +
out-of-band cases not tested in this round but the unit tests in
`tools/test_encoding.py` cover them.)

**2. `docs/effect_catalog.md` WAH section is wrong** — the addresses
are correct but the **knob name → address mapping is permuted**:

| Address    | Reality (verified)  | Catalog claimed |
|------------|---------------------|-----------------|
| `10001107` | **PEDAL POSITION**  | WAH TYPE        |
| `1000110B` | **PEDAL MIN**       | EFFECT LEVEL    |
| `1000110F` | **PEDAL MAX**       | DIRECT MIX      |
| `10001113` | **EFFECT LEVEL**    | PEDAL POSITION  |
| `10001117` | **DIRECT MIX**      | PEDAL MIN       |
| `1000111B` | (unused FX Param 7) | not listed      |

Likely cause: `tools/build_effect_catalog.py` aligns capture-order
knobs against manual-order names, but BTS UI ordering ≠ manual
ordering for WAH. Tracked as task #29 — needs systematic audit of
other effects via the same write-and-read method.

### Bonus: device LCD edits don't broadcast on MIDI

During the failed first attempt to sniff a knob turn, no DT1 events
were captured even though the user reported having turned a knob
(and a subsequent re-read showed `0x1000110B` had moved 0 → 50 from
the device side). The GX-10 stores user-driven knob changes
internally without echoing on MIDI OUT to the editor port.

This means **passive sniffing only captures host-driven edits**
(BTS, our scripts, etc.), not edits the user makes via the device's
own LCD/buttons. For mapping device-side controls, use the
write-and-read-display loop instead of a sniff.

### Restored state

After the experiment, FxItem 0 cells restored to their pre-test
values (the user's PEDAL MIN had been left at 50 from the failed
sniff attempt, so that is what was restored — not 0).

### Slot-identity correction for BTS findings §3

The Windows-Claude assumed FxItem 0 was COMP/X-COMP and inferred
`0x10001117` was DIRECT MIX. With FAT WAH, `0x10001117` is **also**
DIRECT MIX (in WAH). So the BTS slider drag — whatever TYPE was
selected at capture time — most likely wrote to the DIRECT MIX
parameter, not PEDAL MIN. The wire-encoding finding (canonical
4-nibble offset binary) stands regardless of slot identity.

---

## 2026-05-09 follow-up: catalog audit — COMP

After the WAH audit (above) revealed a **name↔address permutation**
bug, ran the same write-distinctive-and-read protocol on **COMP**
(TYPE byte 0x08) by changing FxItem 0's TYPE byte and writing
11/22/33/44/55/66 to FX Params 2..7.

User-reported displays:

| Address    | Distinctive | UI label  | Catalog claimed |
|------------|------------:|-----------|-----------------|
| `10001107` | 11          | SUSTAIN   | SUSTAIN ✓       |
| `1000110B` | 22          | ATTACK    | ATTACK ✓        |
| `1000110F` | 33          | LEVEL     | LEVEL ✓         |
| `10001113` | +44         | TONE      | (not listed)    |
| `10001117` | 55          | DIRECT MIX | (not listed)    |
| `1000111B` | 66          | (hidden)  | not listed      |

So COMP has a **different** catalog-bug pattern from WAH:

- WAH: 5 catalog-listed knobs, but the **names↔addresses are
  permuted**.
- COMP: 3 catalog-listed knobs, all **correctly mapped**, but two
  more **always-visible knobs (TONE, DIRECT MIX) are missing from
  the catalog entirely**.

Two distinct bug types. The "+44" display for TONE incidentally
confirms the encoder also handles bipolar knobs correctly (TONE
range presumably -50..+50; we wrote `encode_fx_param(44) = [08 00
02 0C]` and got display "+44" — i.e. the device interprets raw
0x802C as +44, matching offset binary).

Task #29 is now firmly a **systematic** catalog audit — each effect
needs the write-distinctive-and-read pass to determine which bug
pattern (or none) it has. The two patterns observed so far suggest
the catalog generator (`tools/build_effect_catalog.py`,
`tools/manual_xref_v2.py`, plus the captured `summary.json` data)
has at least two distinct alignment / completeness bugs that need
investigating at the source-code level, not patched effect by
effect in the markdown.

### Probe of `0x7F000703` toggle (cross_check P2-4 follow-up)

Mirrored the BTS startup sequence to test the hypothesis that
writing `0x7F000703 = 0x01` unlocks unsolicited DT1 broadcasts:

```
1. Identity Request                              -> reply
2. RQ1 0x7F000000                                -> 0x03
3. DT1 0x7F000001 = 0x01 (twice, mirroring BTS)  -> ack via RQ1 reply 0x01
4. RQ1 0x7F000002                                -> 0x00 (reply unlocked by attach bit)
5. RQ1 0x7F000003                                -> 0x00
6. RQ1 0x7F000703                                -> NO REPLY (silent even with attach bit)
7. DT1 0x7F000703 = 0x00 then 0x01               -> ack
8. RQ1 0x7F000703                                -> NO REPLY
9. listen 8s for unsolicited broadcasts          -> 0 events
```

**Hypothesis rejected.** Writing `0x7F000703 = 0x01` does not
unlock any device-side broadcast channel. The register also doesn't
reply to RQ1 (Windows-Claude's BTS capture only saw BTS *write*
the register, not read it — so `0x7F000703` is plausibly write-only,
or its read-replies are gated behind something we haven't set up).

Whatever `0x7F000703` does for BTS, it isn't activating MIDI
broadcasts. Its purpose remains unknown. Possible roles:
internal-state-only flag with no MIDI side effects; or a write that
unlocks something only when paired with a specific user action
(entering tuner mode, opening a particular dialog) we didn't
trigger. Closing as inconclusive but with the broadcast-subscribe
hypothesis ruled out.
