# GX-10 / GX-100 firmware versions

How an editor (or any host program) can tell which **product** is
connected, which **firmware family** it's running, and how to filter
the parameter dictionary accordingly.

> ⚠️ **Updated 2026-05-09 after live device probe.** The earlier
> claim that the Identity Reply's `softwareVersion` field encodes the
> firmware version as `(major, minor)` is **wrong** for this device
> family. See `reports/linux_probe_results.md` §P1-1. This file has
> been rewritten accordingly.

## TL;DR

- The Universal Identity Reply byte `softwareVersion[0]` is a
  **product flag** (GX-100 = `0x00`, GX-10 = `0x01`), **not** a
  firmware major version. The remaining three bytes are reserved
  zeros on every firmware we've observed.
- **There is no SysEx address known to expose the firmware
  version.** A BOSS GX-10 running firmware 1.04 returns the same
  `softwareVersion = [01 00 00 00]` as one running firmware 1.0.
- For dictionary filtering, replace "version sniff" with **feature
  probe**: read a small set of v2-only registers (e.g. an out-of-v1
  effect TYPE, or a v2-only `[SystemCommon]` slot) and infer the
  feature surface from what responds.
- Per-product gating IS reliable (Identity Reply byte 10 is stable
  across firmwares within a product). Per-firmware gating is not.

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

## What the device DOES NOT tell you over MIDI

- **Firmware version.** Not in Identity Reply, not in any RQ1
  address probed so far (we tested `0x00000040`, `0x00000050`,
  `0x00000060`, `0x00000080`, `0x000000A0`, `0x00010000`,
  `0x00FF0000`, `0x00200500`, `0x7F000800`, `0x7F010000` — none
  reply with version-looking data).
- **USB descriptors.** `bcdDevice = 1.00` regardless of firmware;
  `iSerial` is empty.

The user-visible "VERSION" screen on the GX-10's MENU does show the
running firmware, so it's stored on the device — just not exposed
on any wire interface we can read.

A Windows-side BTS USBPcap session is queued (see
`reports/windows-session-task-plan.md` Task 4) to discover whether
BTS reads the version from a yet-undiscovered SysEx address or
whether it simply doesn't.

---

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
| **1.00** | release-day (2024) | Launch firmware. Identity Reply: `softwareVersion = [01 00 00 00]`. |
| **1.04** | (current at 2026-05-09) | Live tested: `[01 00 00 00]` — **same bytes as 1.00**. Setup region (00 20 xx xx) intact. SystemControl block is 0x66 bytes (GX-10 footswitch fields at offsets 0x64/0x65 populated). All 5 v2-effects (TYPE 78..82) present and selectable. |
| **1.05** | (per BOSS support page, 2026-05-09) | Listed but not yet tested. Likely the same Identity Reply pattern. |

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
`docs/effects/firmware_overlay.json`:

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

## What's tagged in `docs/effects/firmware_overlay.json`

Whole categories present in `all_effects.json` whose names match the
v2.0 announcement byte-for-byte:

| `all_effects.json` name | Press / announcement name | min_firmware_gx100 |
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
