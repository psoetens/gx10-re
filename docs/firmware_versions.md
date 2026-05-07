# GX-10 / GX-100 firmware versions

How an editor (or any host program) can identify which firmware the
connected device is running, and which features depend on which version.

## Reading the firmware version from the device

Send a Universal Identity Request and parse the `softwareVersion` field:

```
host:   F0 7E 7F 06 01 F7
device: F0 7E 10 06 02 41 0B 04 00 00 01 00 00 00 F7
                                       ^^ ^^ ^^ ^^
                                       SW version (4 bytes)
```

By Roland convention the first two bytes are **major** and **minor**:

| Bytes         | Meaning              |
|---------------|----------------------|
| `01 00 ...`   | firmware **1.0**     |
| `01 05 ...`   | firmware **1.05**    |
| `02 00 ...`   | firmware **2.0**     |
| `02 04 ...`   | firmware **2.04**    |

(See `docs/protocol.md` §2.1 — the format is shared with the GX-100,
GT-1000, SY-1000, ME-90, and other modern Roland Family `0x040B` devices.)

## Why this matters

Recent firmware updates have **added entire effect categories** to the
GX-100 — categories the GX-10 had at launch. An editor that ships a
single dictionary for both devices needs a way to hide effects that the
connected device's firmware doesn't support, otherwise the user sees UI
controls that send writes the device silently ignores.

We tag each parameter that depends on a post-launch firmware with a
`min_firmware: "M.m"` field. The host filters the dictionary at runtime
based on the Identity Reply.

## GX-10 firmware history

| Version | Released | What's known |
|---------|----------|--------------|
| **1.00** | release-day (2024) | Launch firmware. Reports `softwareVersion = [01 00 00 00]`. |
| **1.05** | (after launch — date TBD; sole public update on Boss's downloads page as of 2026-05) | Bug fixes; no new effects publicly documented. |

Tools/captures in this repository were taken against firmware 1.00 (see
`docs/protocol.md` "Captured at the wire level …" section). Re-running
the captures after a firmware update is the way to detect any address
shifts or new registers.

## GX-100 firmware history

| Version | Released | What's known |
|---------|----------|--------------|
| **1.00** | 2022 (launch) | Initial release. |
| **1.10+** | minor updates | Bug fixes. |
| **2.00** | September 2024 | **Major content update — closes the gap with the GX-10's launch effect list.** |
| **2.04** | (sub-2.x revisions documented in BTS update articles) | Bug fixes. |

### What v2.00 added — confirmed effects

These were added to the GX-100 in v2.00 and were already present on the
GX-10 v1.00. In our parameter dictionary they should be tagged
`min_firmware: "2.0"` for the GX-100 device JSON only:

**New effects (7):**
- **SD-1** Super Overdrive (in OD/DS chain)
- **DS-1** Distortion (in OD/DS chain)
- **Sitar Sim** (sitar simulator)
- **Auto Wah** (envelope-driven wah)
- **Feedbacker** (natural-harmonic feedback)
- **Slicer** (rhythmic gating, several patterns)
- **Humanizer** (vocal-vowel formant)

**New amps (10):**
- **3 high-gain guitar amps**: X-Ultra, X-Optima, X-Titan
- **6 bass amps** (mix of vintage classics and modern favourites)
- **1 additional guitar amp** (TBD; press coverage cites 10 amps total
  with three explicitly named for guitar metal-style use)

**Tooling-side changes** (BOSS Tone Studio for desktop):
- Liveset download
- Patch sharing between users

Sources cataloged below.

## Implications for the editor

1. **Always identify before showing UI.** Send Identity Request first,
   read `softwareVersion`, store as a `(major, minor)` pair, drive the
   parameter-visibility filter from it.
2. **Tag the device JSON, not the protocol.** The wire framing
   (RQ1/DT1/checksum/address tree) does not change between firmware
   versions; only the *content* (which addresses correspond to which
   effects) does.
3. **The GX-10 dictionary needs no `min_firmware` tags today** — every
   effect was present at launch.
4. **The GX-100 dictionary needs ~13 categories tagged `min_firmware: "2.0"`**
   (the 7 new effects + ~6 amp categories) for hosts that target users
   on firmware 1.x.

## Sources

- [BOSS GX-100 Version 2.0 firmware update — official announcement (Facebook)](https://www.facebook.com/BOSSInfoGlobal/posts/gx-100-version-20-firmware-update-out-nowincluding-three-new-aird-guitar-amps-po/1060849952077569/)
- ["Boss adds new amps, effects, and enhanced features to its … GX-100"](https://www.guitarplayer.com/news/boss-gx-100-firmware-update-2024) — Guitar Player
- ["A bevy of enhancements for endless tonal possibilities"](https://www.guitarworld.com/news/boss-gx-100-update-2024) — Guitar World
- [BOSS GX-100 and GX-10 Firmware Update](https://www.sweetwater.com/sweetcare/articles/boss-gx-100-firmware-update/) — Sweetwater
- [Boss GX-100 Firmware and Tone Studio 2.0 Update thread](https://www.vguitarforums.com/smf/index.php?topic=37747.0) — vguitarforums
- [r/BossGX100 — "Hell yes — version 2 update out!"](https://www.reddit.com/r/BossGX100/comments/1fkjbtr/hell_yes_version_2_update_out/) — community discussion
- [GX-10 Updates & Drivers (BOSS support)](https://www.boss.info/global/support/by_product/gx-10/updates_drivers/) — only v1.05 listed as of 2026-05
- [GX-100 Updates & Drivers (BOSS support)](https://www.boss.info/global/support/by_product/gx-100/updates_drivers/) — current GX-100 firmware downloads
