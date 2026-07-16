> **Last updated 2026-05-14** — adds the
> `(EDITOR_COMMUNICATION_LEVEL, EDITOR_COMMUNICATION_REVISION)`
> capability-fingerprint finding after BTS-for-Mac source inspection;
> supersedes the earlier "no SysEx address reveals firmware version"
> claim.

# GX-10 / GX-100 firmware versions

How an editor (or any host program) can tell which **product** is
connected, which **firmware family** it's running, and how to filter
the parameter dictionary accordingly.

> ⚠️ **Updated 2026-05-09 after live device probe.** The earlier
> claim that the Identity Reply's `softwareVersion` field encodes the
> firmware version as `(major, minor)` is **wrong** for this device
> family. See `reports/linux_probe_results.md` §P1-1.
>
> 🆕 **Updated 2026-05-14 after BTS-for-Mac source inspection.** The
> prior claim that "there is no SysEx address known to expose the
> firmware version" was incomplete. There is no address that reveals
> the exact `(major, minor)` firmware version, but the two-byte pair
> `(0x7F000000, 0x7F000003)` = (`EDITOR_COMMUNICATION_LEVEL`,
> `EDITOR_COMMUNICATION_REVISION`) IS a coarse firmware capability
> fingerprint that Roland bumps with firmware updates and that BTS
> uses as its on-connect compatibility gate. See §"Firmware
> capability fingerprint" below.

## TL;DR

- The Universal Identity Reply byte `softwareVersion[0]` is a
  **product flag** (GX-100 = `0x00`, GX-10 = `0x01`), **not** a
  firmware major version. The remaining three bytes are reserved
  zeros on every firmware we've observed.
- **No SysEx address reveals the exact firmware `(major, minor)`.**
  A BOSS GX-10 running firmware 1.04 returns the same
  `softwareVersion = [01 00 00 00]` as one running firmware 1.0.
- However, the **firmware capability level** at `0x7F000000` does
  change across firmware update generations and is exposed on the
  wire. On this unit: `0x03` (the launch family, fw ≤ 1.04).
  BTS v1.0.2 — built against firmware 1.05 — hard-codes `4`, and so
  refuses to connect to this unit. See §"Firmware capability
  fingerprint" below for the full mapping.
- For dictionary filtering, replace "version sniff" with **feature
  probe**: read a small set of v2-only registers (e.g. an out-of-v1
  effect TYPE, or a v2-only `[SystemCommon]` slot) and infer the
  feature surface from what responds. The capability level alone
  is too coarse for per-feature decisions.
- Per-product gating IS reliable (Identity Reply byte 10 is stable
  across firmwares within a product). Per-firmware gating works at
  the **capability level** but does not resolve every sub-revision.

---

## Reading the Identity Reply

```
host:   F0 7E 7F 06 01 F7
device: F0 7E <dev> 06 02 41 0B 04 00 00 <p> 00 00 00 F7
                              └─┬─┘ └─┬─┘ └────────┬────────┘
                          family    number   sw_rev (4 bytes)
                          0x040B    0x0000

         <p> = 0x00 on a GX-100
         <p> = 0x01 on a GX-10
```

Per the v2 MIDI Implementation manual:

> `nnH: Software revision level # 1 (GX-100:0 / GX-10:1)`
> *(GX-100_GX-10_MIDI_Imple_eng02_W.md, line 222)*

— this is the **product discriminator**. The other three sw_rev
bytes are documented as `00H` and observed as such on all GX-10
firmwares we have access to (1.0 and 1.04).

Manufacturer ID (`0x41`) and 5-byte Model ID (`00 00 00 00 0B`) are
**identical** across GX-100 and GX-10 — they tell you nothing about
which device or which firmware.

**Corroborated against BTS source (2026-07-16).** Both BTS-for-Mac
apps (`GX-10` v1.0.0 b43, `GX-100` v2.0.3 b124,
`Contents/Resources/html/js/`) parse the Identity Reply as a hex
string in `midi_connect_controller.js` and store hex chars 20..28 —
exactly bytes 10..13, the sw_rev field — as
`ProductSetting.deviceRevisionLevel`. Both apps also ship the
constant `window.DEVICE_REVISION_LEVEL_GX_100 = '00000000'`
(`config/product_setting.js`) — Roland's own statement that the
GX-100's sw_rev is all zeros, i.e. product flag `0x00`. Notably BTS
never *compares* either value: its accept check
(`PART_OF_IDENTITY_REPLY`) matches only through the family code
(`0B 04`), so each single-product BTS app would accept the other
device and relies on the capability-level gate (§below) plus the
user having launched the right app. BTS-for-GX-1 is a different
protocol family entirely (`modelId '01060D'`) and has no
revision-level constant.

## What the device DOES NOT tell you over MIDI

- **Exact firmware `(major, minor)`** (e.g. distinguishing 1.00 from
  1.04). Not in Identity Reply, not in any RQ1 address probed so
  far (we tested `0x00000040`, `0x00000050`, `0x00000060`,
  `0x00000080`, `0x000000A0`, `0x00010000`, `0x00FF0000`,
  `0x00200500`, `0x7F000800`, `0x7F010000` — none reply with
  version-looking data).
- **USB descriptors.** `bcdDevice = 1.00` regardless of firmware;
  `iSerial` is empty.

But the device DOES tell you the **firmware capability level**
(see next section), which is what BTS actually uses to decide if a
connected unit is "old". That's a coarser signal than the
sub-version but it's the same signal Roland uses internally.

The user-visible "VERSION" screen on the GX-10's MENU does show the
running firmware (e.g. "1.04"), so the exact value is stored on the
device — just not exposed on any wire interface we can read.

**Update 2026-05-09 (Windows BTS capture, `reports/bts_capture_findings.md`
§4):** observed BTS startup at MIDI level — no SysEx reads to
addresses outside the chart-documented map, no payload resembling
`1.04` / `01 04`. The hypothesis from that session was that BTS
reads the firmware version via a **USB control transfer** or the
**`bcdDevice` USB descriptor field**, not via MIDI SysEx.

**Resolved 2026-05-14 (BTS-for-Mac v1.0.0 source inspection +
live handshake capture, `captures/bts_v100_handshake.jsonl`):**
BTS does NOT need the exact firmware version. It reads a single
**capability level** byte at `0x7F000000` (`EDITOR_COMMUNICATION_LEVEL`)
and a sub-revision at `0x7F000003` (`EDITOR_COMMUNICATION_REVISION`),
each via standard RQ1, and compares the pair to its hard-coded
`(ProductSetting.communicationLevel, ProductSetting.communicationRevision)`.
This is the gate. There is no USB control transfer involved.

This means the **firmware-version-on-the-wire claim above is
nuanced**: the exact `(major, minor)` isn't exposed, but the
capability-level pair that Roland actually cares about IS, and
it changes with firmware updates that change protocol behaviour.

## Firmware capability fingerprint

| Address | Purpose | Observed on this unit | Reserved? |
|---------|---------|-----------------------|-----------|
| `0x7F000000` | `EDITOR_COMMUNICATION_LEVEL` | `0x03` | no — bumped per firmware family |
| `0x7F000003` | `EDITOR_COMMUNICATION_REVISION` | `0x00` | unused so far; bumped within a level |

**BTS-version mapping** (extracted from each BTS bundle's
`Contents/Resources/html/js/config/product_setting.js`):

| BTS macOS version | Expected `(level, revision)` | Bundle filename |
|-------------------|-------------------------------|-----------------|
| v1.0.0 | `(3, 0)` | `bts_gx10_m100.zip` (archived; on `static.roland.com`) |
| v1.0.2 | `(4, 0)` | `bts_gx10_m102.zip` (current Roland release) |

**Inferred firmware → level mapping** (cross-referencing BOSS's
GX-10 update history with the BTS-version mapping above):

| Firmware | Inferred level | Source of inference |
|----------|----------------|---------------------|
| 1.00 (launch) | `3` | BTS v1.0.0 was current at GX-10 launch |
| 1.04 | `3` | Linux probe 2026-05-09 returned `0x03` |
| 1.05 | `4` (predicted) | BTS v1.0.2 expects `4` and was released alongside fw 1.05 |

DT1 writes to `0x7F000000` are **silently ignored** (confirmed
2026-05-14 by writing `0x04` and reading back `0x03`). The
capability level is firmware-baked, not a settable runtime flag,
so it cannot be spoofed to bypass BTS's gate.

The handshake sequence BTS runs on connect, decoded from
`captures/bts_v100_handshake.jsonl`:

```
1.  H→D    F0 7E 7F 06 01 F7                  Identity Request
2.  D→H    F0 7E 10 06 02 41 0B 04 00 00 01 00 00 00 F7
                                                Identity Reply (product=GX-10)
3.  H→D    RQ1 0x7F000000  size=1               read capability level
4.  D→H    DT1 0x7F000000  03                   level=3 (gate check vs ProductSetting.communicationLevel)
5.  H→D    DT1 0x7F000001  01                   editor-attach handshake (twice)
6.  H→D    RQ1 0x7F000003  size=1               read capability sub-revision
7.  D→H    DT1 0x7F000003  00                   revision=0 (gate check)
8.  …                                           proceed with patch-list reads (§3.5)
```

If either check fails, BTS shows `IDM_ERROR_OLD_FIRM_MESSAGE` (when
level too low) or `IDM_ERROR_OLD_BTS_MESSAGE` (when level too high)
and falls into offline mode.

---

## Per-device patch totals (canonical reference)

| Product   | User patches              | Preset patches            | Total | Address-space holes |
|-----------|---------------------------|---------------------------|-------|---------------------|
| **GX-10** | 198 (66 banks × 3/bank)   | 99 (33 banks × 3/bank)    | 297   | 3 NIU slots at raw 198, 199, 299 |
| **GX-100**| 200 (50 banks × 4/bank)   | 100 (25 banks × 4/bank)   | 300   | none                |

Both devices share the same chart-documented address space at
`0x2000_0000 + N × 0x60000` for N=0..199 (user) and the same
`0x5000_0000` 300-slot name catalogue. The GX-10 uses 3-patch banks
while the GX-100 uses 4-patch banks, which is why the GX-10 has
different bank/patch decomposition and 3 "not in use" slots in the
address space (raw 198, 199, 299 are NIU per the chart).

Decode raw memory-number → bank/patch on the GX-10:

```
if raw in (198, 199, 299): NIU
if raw < 198: ("U", raw/3 + 1, raw%3 + 1)   # U01-1 .. U66-3
else:         ("P", (raw-200)/3 + 1, (raw-200)%3 + 1)   # P01-1 .. P33-3
```

See `midi_firmware_analysis.md` §4.3 for the chart-quoted layout.

## Why this matters

Roland firmware updates can **add entire effect categories** to an
existing device. A unified GX-10 + GX-100 editor needs to either:

1. Hide UI controls for features the connected device doesn't
   support (otherwise writes are silently ignored), or
2. Show everything and let the user discover that some effects
   don't actually do anything.

(1) requires knowing the feature surface. Without a firmware
version we can probe the feature surface directly.

## Recommended detection strategy

```
1. Send Identity Request.
2. Parse Identity Reply -> read product = sw_rev[0]  (00 = GX-100, 01 = GX-10)
3. For per-product gating: use the product byte directly.
4. For per-firmware gating: probe a small set of v2-only features:
   a. RQ1 0x10001100 size=1, then DT1 TYPE=78 (SLICER) and read back.
      If TYPE clamps to a lower value, this device is on a pre-2.0
      firmware (GX-100 v1.x).  If it accepts 78, the device exposes
      the v2 effect set.
   b. RQ1 0x0000001B size=1 (COLOR MODE — v2-only SystemCommon slot).
      A v1 firmware would return zero (the slot is "fixed" in the
      v1 manual); a v2 firmware returns the real COLOR MODE value
      0/1.
   c. RQ1 0x00001065 size=1 (Up & Ctl1 Function — GX-10-only v2
      field). Only meaningful on GX-10; on GX-100 the byte is
      either absent or returns a fixed value.
5. Set a "feature flags" struct from the probe results, NOT a
   `(major, minor)` pair. Drive dictionary visibility from feature
   flags.
6. Restore any DT1-mutated state (TYPE byte) before exiting probe
   mode.
```

This sidesteps the "no firmware version on the wire" problem and
gives us per-feature precision (some firmwares may add features
without a major-version bump).

### What about gxnarly's `min_firmware: "M.m"` field?

The dictionary tagging is still useful — but the version it gates
against should come from a feature probe, not Identity Reply.
Concretely:

- Replace `gxnarly/Sources/GxnarlyCore/Device/FirmwareVersion.swift`
  with a `FeatureFlags` struct.
- Map each `min_firmware: "2.0"` entry to a feature flag (e.g.
  `has_v2_effects`).
- The host runs the probe sequence above on connect and populates
  `FeatureFlags`.

See `reports/cross_check_findings.md` P1-1b for the cross-link.

---

## GX-10 firmware history

| Version | Released | What's known |
|---------|----------|--------------|
| **1.00** | release-day (2024) | Launch firmware. Identity Reply: `softwareVersion = [01 00 00 00]`. Inferred capability `(level=3, revision=0)` — BTS v1.0.0 was released alongside this firmware and expects `(3, 0)`. |
| **1.04** | (current at 2026-05-09) | Live tested: Identity Reply `[01 00 00 00]` — **same bytes as 1.00**. Capability `(3, 0)`. Setup region (00 20 xx xx) intact. SystemControl block is 0x66 bytes (GX-10 footswitch fields at offsets 0x64/0x65 populated). All 5 v2-effects (TYPE 78..82) present and selectable. |
| **1.05** | (per BOSS support page, 2026-05-09) | Not directly tested. Predicted capability `(level=4, revision=0)` from BTS v1.0.2's `ProductSetting.communicationLevel: 4`. Identity Reply almost certainly still `[01 00 00 00]` (product flag is firmware-stable). The level bump from 3→4 gates **four bug-fix workarounds in BTS v1.0.2** rather than any new wire protocol — see [`bts_version_diff_v100_vs_v102.md`](bts_version_diff_v100_vs_v102.md). Notable: BTS v1.0.2's `TOTAL_USER_PATCH - 2` adjustment (200 → 198) is a GX-100-specific correction (50 banks × 4 = 200 user slots, with 2 reserved → 198 usable). The GX-10's user-patch count is also 198 by coincidence of arithmetic (66 banks × 3), but the bank decomposition is different — see the totals table above. |

The repository's protocol captures were taken against firmware 1.00
(see `docs/protocol.md` "Captured at the wire level …" section).
The probe results in `reports/linux_probe_results.md` were taken
against firmware 1.04.

## GX-100 firmware history

| Version | Released | What's known |
|---------|----------|--------------|
| **1.00** | 2022 (launch) | Initial release. |
| **1.10** | minor updates | Bug fixes; pre-v2.0 effect set. |
| **2.00** | September 2024 | **Major content update — closes the gap with the GX-10's launch effect list.** Adds 5 new effects (TYPE 78..82) + amp/dist/od subtypes. |
| **2.04** | (sub-2.x revisions documented in BTS update articles) | Bug fixes. |

We have not yet probed a live GX-100. The Identity Reply
discriminator (sw_rev[0] = `0x00`) is per the v2 manual annotation;
unverified by us against hardware.

### What v2.00 added — confirmed effects

These were added to the GX-100 in v2.00 and were already present on
the GX-10 v1.00. Our parameter dictionary tags them
`min_firmware_gx100: "2.00"` in
`catalogs/firmware_overlay.json`:

**New effects (5)** — confirmed via live device probe (Linux side,
Task #11), all selectable on GX-10 v1.04:

| TYPE | Effect       | Source                    |
|-----:|--------------|---------------------------|
|  78  | `SLICER`     | v2 manual + live probe    |
|  79  | `HUMANIZER`  | v2 manual + live probe    |
|  80  | `FEEDBACKER` | v2 manual + live probe    |
|  81  | `SITAR SIM`  | v2 manual + live probe    |
|  82  | `AUTO WAH`   | v2 manual + live probe    |

**New amps (~10):** Press release cites 10 new amp models in v2.00.
Three high-gain guitar amps named (X-Ultra, X-Optima, X-Titan); six
bass amps (un-named in press). Per-subtype tagging is being closed
out via the v1↔v2 GX-100 Parameter Guide diff —
see `reports/v2_subtype_additions.md` (in flight).

**Tooling-side changes (BTS desktop):**
- Liveset download
- Patch sharing between users

---

## What's tagged in `catalogs/firmware_overlay.json`

Whole categories present in the effect catalog whose names match the
v2.0 announcement byte-for-byte:

| Catalog name | Press / announcement name | min_firmware_gx100 |
|---|---|---|
| `SLICER`     | Slicer       | 2.00 |
| `SITAR_SIM`  | Sitar Sim    | 2.00 |
| `HMN`        | Humanizer    | 2.00 |
| `A_WAH`      | Auto Wah     | 2.00 |
| `FB`         | Feedbacker   | 2.00 |

(Per `firmware_overlay.json`'s actual content as of 2026-05-09.)

### Sub-type additions (per-type schema)

Sub-types added inside existing categories. The schema gxnarly uses
(`type_min_firmware: { "<idx>": "M.m" }` per
`Sources/GxnarlyCore/Dictionary/ParameterEntry.swift:7-61`) supports
this; this repo's `firmware_overlay.json` has a
`subtype_additions_pending_schema` block that lists them and is
being resolved by the v1↔v2 GX-100 manual diff:

- **OVERDRIVE.SD-1** (Boss SD-1 Super Overdrive model)
- **DISTORTION.DS-1** (Boss DS-1 Distortion model)
- **AMP.X-Ultra**, **AMP.X-Optima**, **AMP.X-Titan** — three
  high-gain guitar amps
- 1 additional guitar amp + 6 bass amps (BOSS announced 10 amps
  total; only 3 named in press)

Final list will be in `reports/v2_subtype_additions.md`.

---

## Sources

- [BOSS GX-100 Version 2.0 firmware update — official announcement (Facebook)](https://www.facebook.com/BOSSInfoGlobal/posts/gx-100-version-20-firmware-update-out-nowincluding-three-new-aird-guitar-amps-po/1060849952077569/)
- ["Boss adds new amps, effects, and enhanced features to its … GX-100"](https://www.guitarplayer.com/news/boss-gx-100-firmware-update-2024) — Guitar Player
- ["A bevy of enhancements for endless tonal possibilities"](https://www.guitarworld.com/news/boss-gx-100-update-2024) — Guitar World
- [BOSS GX-100 and GX-10 Firmware Update](https://www.sweetwater.com/sweetcare/articles/boss-gx-100-firmware-update/) — Sweetwater
- [Boss GX-100 Firmware and Tone Studio 2.0 Update thread](https://www.vguitarforums.com/smf/index.php?topic=37747.0) — vguitarforums
- [r/BossGX100 — "Hell yes — version 2 update out!"](https://www.reddit.com/r/BossGX100/comments/1fkjbtr/hell_yes_version_2_update_out/) — community discussion
- [GX-10 Updates & Drivers (BOSS support)](https://www.boss.info/global/support/by_product/gx-10/updates_drivers/) — only v1.05 listed as of 2026-05
- [GX-100 Updates & Drivers (BOSS support)](https://www.boss.info/global/support/by_product/gx-100/updates_drivers/) — current GX-100 firmware downloads
- `docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md` line 222 (product discriminator)
- `reports/linux_probe_results.md` §P1-1 (live GX-10 1.04 confirms sw_rev = `[01 00 00 00]`)
