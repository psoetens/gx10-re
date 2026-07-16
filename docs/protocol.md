# BOSS GX-10 / GX-100 USB Communication Protocol

Reverse-engineered from observation of the MIDI traffic between **BOSS TONE
STUDIO for GX-10** (v1.0.0 build 43) and a connected GX-10. The official
Roland MIDI Implementation chart used to cross-reference every observation
covers both **GX-10** and **GX-100** —
the SysEx framing, address map, MemoryFxItem/MemoryEfct/MemoryCommon
layouts, FX-Parameter encoding, and ASSIGN TARGET TABLE are identical
across both models. The few model-specific differences (LED bitmap bit
assignments, user-memory count, which BANK EXTENT field is authoritative)
are documented in §5.8 below; tools auto-detect the model via Identity
Reply and adapt at runtime.

Capture is done two ways:

- **Application-level** via WinMM `midiInOpen` / `midiOutOpen` (no driver
  install, no elevation). Sees device → host directly, and host → device by
  having Python become the host and probe.
- **Wire-level** via USBPcap + Wireshark (one-time admin install + a reboot
  so USBPcap's class filter binds to the USB host controllers). Sees both
  directions including everything Tone Studio actually sends.

Both capture paths produce JSONL logs in the same shape (the
`pcap_to_jsonl.py` tool flattens a USBPcap `.pcap` into the `midi_sniff.py`
JSONL format with a `dir` field of `host->dev` / `dev->host`), so the same
`sysex_decode.py` tool processes either source.

## Quick facts

| | |
|--|--|
| USB IDs | VID `0x0582` (Roland), PID `0x0312` |
| Device class | USB-MIDI (Microsoft generic class driver, `mid=0x0001`) |
| Roland family code | `0x040B` |
| Roland model number | `0x0000` |
| Software revision (test unit) | `01 00 00 00` — byte 1 is a **product flag**, not a firmware major: GX-100 = `00`, GX-10 = `01` (see `firmware_versions.md`) |
| SysEx model ID | `00 00 00 00 0B` (5 bytes) |
| Default device ID | `0x10` |
| Address width | 4 bytes, big-endian, all 7-bit |

The GX-10 / GX-100 are in the same protocol family as the GT-1000 /
SY-1000 / ME-90 — "newer-extended" Roland SysEx with a 4-byte address
space and a 5-byte model ID. The address layout below is shared between
GX-10 and GX-100 (with the small differences noted in §5.8).

---

## 1. Transport

The GX-10 enumerates as a USB composite device. Its MIDI interface is
exposed through Microsoft's USB-MIDI class driver, **not** through Roland's
exclusive `Haute Technique` driver. As a result both the input and output
ports are *shareable* on Windows: a sniffer process and Tone Studio can both
hold the same `GX-10` MIDI port open simultaneously, and a probe process
can drive the OUTPUT port while Tone Studio is also using it.

This is the central trick that lets this entire reverse-engineering work
without USBPcap or a virtual-MIDI-port shim.

| Direction | Port name |
|-----------|-----------|
| Input  (device → host) | `GX-10` |
| Output (host → device) | `GX-10` |

### 1.1 USB modes and product IDs

The GX-10's SYSTEM → USB setting switches the device between two USB
personalities with **different product IDs** (observed live 2026-06-05
by replugging across a mode change; both repeatedly seen since):

| USB mode | PID | Linux (ALSA) | iOS / iPadOS / macOS | Windows |
|----------|-----|--------------|----------------------|---------|
| **VENDOR** | `0x0582:0311` | ✅ 2 MIDI ports (`GX-10 MIDI 1`, `GX-10 MIDI 2`) via the kernel's Roland quirk tables | ❌ invisible — needs Roland's driver, which doesn't exist for iOS | Roland driver (BTS default) |
| **GENERIC** (class-compliant) | `0x0582:0312` | ✅ 1 MIDI port (`GX-10 MIDI IN`) | ✅ CoreMIDI via Apple's class driver — **the mode gxnarly depends on** | Microsoft USB-MIDI class driver |

Notes:
- The "Quick facts" PID above (`0x0312`) is the GENERIC-mode ID; logs
  and notes citing `0x0311` were captured in VENDOR mode.
- In VENDOR mode the second ALSA port is presumably the DAW-control
  port; unprobed.
- GX-100 PIDs not yet captured — expected to follow the same
  two-personality pattern.

All non-trivial communication is carried over MIDI System Exclusive (SysEx).

---

## 2. SysEx framing

```
F0 41 <dev> 00 00 00 00 0B <cmd> <a3> <a2> <a1> <a0> <data...> <sum> F7
└── ──┘ └─┘ └──────────────┘ └───┘ └─────────────┘  └────────┘  └─┘ └──┘
SOX  Mfr Dev    Model ID      Cmd      Address       Payload    Sum  EOX
```

- `F0` / `F7` — standard SysEx delimiters.
- `41` — Roland manufacturer ID.
- `<dev>` — Device ID, observed `0x10`. Universal SysEx uses `0x7F` for "all".
- Model ID — `00 00 00 00 0B` (five bytes; leading `00` prefix, then the LSB
  of the family code `0x040B`).
- `<cmd>`:
  - `0x11` — **RQ1** (data request, host → device).
  - `0x12` — **DT1** (data set, both directions).
- Address — 4 bytes, big-endian, all `<= 0x7F`.
- Payload — for DT1: the data being written/returned. For RQ1: the size of
  the read, also 4 bytes big-endian.
- Checksum — `(sum(addr) + sum(payload) + sum) & 0x7F == 0`.

### 2.0.1 Host→device echo when device's `USB IN THRU` is enabled

When the GX-10's MENU → MIDI SETTINGS → **USB IN THRU** is set to
`USB OUT` (or `USB & MIDI`), the device routes every SysEx received
on USB MIDI IN back out on USB MIDI OUT. Any sniffer or observer on
the host sees the host's own outgoing DT1/RQ1 traffic returned as
incoming, within single-digit milliseconds.

This is **device behaviour, not driver behaviour** — it occurs
identically on macOS, Windows, and Linux when the setting is
enabled, and not at all when it's set to `OFF` (or `MIDI`, which only
routes DIN MIDI). Verified 2026-05-15 by toggling the setting on the
device's hardware menu and observing the echo appear / disappear.

The setting lives at chart-documented address `0x0000_3004`
(`SystemMidi[MIDI IN THRU]`). DT1 writes to it from the host appear
to require a power cycle or specific commit sequence to take effect —
our earlier sweep test (2026-05-14) saw echoes at all four values
because the device's persistent value wasn't actually changing despite
the writes. See `tools/midi_settings.py` for read/write access and
`docs/midi_settings.md` for the full register map.

**Implications for tooling**: host code that subscribes to incoming
SysEx must be loopback-aware when `USB IN THRU` may be on:

- `RQ1` echoes (`<cmd> = 0x11`) arrive on the device-output side
  and look superficially like RQ1s the device sent. They never are
  (the device only sends DT1 `<cmd> = 0x12`). Reply parsers must
  filter on opcode.
- DT1 echoes match the address of the original write. A handler
  that reacts to "device wrote X at this address" will fire twice
  (once for the echo of the host write, once for any real device
  reply). The fix is to track recently-sent traffic and skip echoes
  within ~200 ms.
- Tools in this repo: `example_lib.GX10Session.request()` is safe
  because it filters DT1 replies by address match and doesn't react
  to its own RQ1 echoes. `midi_sniff.py` shows the raw stream — the
  user must keep loopback in mind when reading captures.

BTS v1.0.2's `chain/chain_controller.js:4221-4223` adds a guard for
this scenario (BG777BTS-309), gated on the same `USB IN THRU` setting
the device exposes. v1.0.0 lacks the guard, which is why the chain
buttons misfire when USB IN THRU is on (`bts_mac_chain_button_bug.md`).

### 2.1 Universal Identity exchange

```
host:   F0 7E 7F 06 01 F7
device: F0 7E 10 06 02 41 0B 04 00 00 01 00 00 00 F7
```

- Manufacturer `0x41` (Roland)
- Family LSB `0x0B`, MSB `0x04` → family code `0x040B`
- Model LSB `0x00`, MSB `0x00` → model `0x0000`
- Software revision `01 00 00 00` — byte 1 is the **product flag**
  (GX-100 = `0x00`, GX-10 = `0x01`, per the MIDI implementation manual;
  see `firmware_versions.md`), the rest reserved zeros

### 2.2 RQ1 — read a region

```
F0 41 10 00 00 00 00 0B  11  <addr:4>  <size:4>  <sum>  F7
```

`size` is in bytes, big-endian, all bytes `<= 0x7F`. The device replies with
one or more DT1 messages whose payloads concatenated cover the requested
range. The device chooses where to split — typically at logical record
boundaries (e.g. it returns the 16-byte name field as one DT1 and the
parameter block immediately after as a second DT1).

Empty / unsupported addresses are simply ignored — the device sends no
reply at all.

### 2.3 DT1 — set / report

```
F0 41 10 00 00 00 00 0B  12  <addr:4>  <data: 1..n>  <sum>  F7
```

When written by host, DT1 stores `data` at `addr`. When sent by device, it
reports the value at `addr` in response to a previous RQ1 (or as part of a
notification when something changes — e.g. clicking a hex effect block in
Tone Studio's editor).

---

## 3. Address map

> **Note (2026-05-03):** This section was originally derived empirically. After
> obtaining the official Roland MIDI Implementation chart
> (`docs/manuals/GX-100_GX-10_MIDI_Imple_eng02_W.md`, March 2026), the chart's
> address tree is now the canonical reference. See `docs/official_xref.md` for
> the full cross-walk.

### 3.1 Top-level regions (per official chart)

| Region | Section name | Populated? | Purpose |
|--------|--------------|------------|---------|
| `0x0000_0000` | SystemCommon | ✔ | **Patch-select register** (4 nibbles → memory # 0–299) + global system block (KNOB / TOUCH SCREEN / BUTTON / WARNINGS / FX ORDER / BANK MODE / EXP1-2 HOLD / AUTO OFF / etc.) |
| `0x0000_1000` | SystemControl | ✔ | System-level CTL/EXP per-controller PREFERENCE / FUNCTION / MODE assignments (0x66 bytes total) |
| `0x0000_3000` | SystemMidi | ✔ | RX/TX channel, SYNC CLOCK, MIDI IN THRU, CLOCK OUT, MAP SELECT + per-controller CC# (0x15 bytes) |
| `0x0000_4000` | SystemInOut | ✔ | LEVEL SELECT, USB EFX OUT/MIX/DRY/LOOPBACK, AIRD OUTPUT SELECT (0x0D bytes) |
| `0x0000_5000` | SystemEfct | ✔ | PHRASE LOOP global: MODE (MONO/STEREO), REC ACTION |
| `0x0000_6000` | SystemPitch | ✔ | TUNER REF. PITCH, TT TUNER TYPE, TT TUNER OFFSET, TUNER OUTPUT |
| `0x0000_6100`–`0x0000_6A00` | SysteminputSetting 1-10 | ✔ | 10 named INPUT-setting memories × 0x12 bytes (NAME 16 + INST TYPE + INPUT LEVEL) |
| `0x0000_6B00` | SystemGlobalEq | ✔ | Global EQ NAME + 11 EQ knobs (LOW/HIGH GAIN, LOW-MID/HIGH-MID FREQ/Q/GAIN, LOW CUT, HIGH CUT, LEVEL) |
| `0x0010_0000`–`0x0010_0BFF` | PcmapPc bank1/2/3 | ✔ | MIDI program-map: 3 banks × 128 entries × 4 nibbles, each entry = memory # 0–299 |
| `0x0020_0000` | (editor staging) | ✔ | Tone Studio's I/O staging area — host writes here, device echoes the persisted value into `0x0000_6xxx`. NOT in the official chart; appears to be TS-internal. |
| `0x1000_0000` | Memory (temporary) | ✔ | **Live edit buffer** — current patch, ~16 KiB. See §3.4 |
| `0x2000_0000` | Memory 1..200 (user) | ✔ | **User-memory bank** — 200 memories × `0x60000` stride (= up to memory 200 at `0x292A_0000`) |
| `0x5000_0000` | (patch name catalogue) | ✔ | Patch name catalogue (read-only). Up to 300 16-byte name slots. **GX-10**: 297 usable = 198 user (66 banks × 3) + 99 preset (33 banks × 3), with 3 NIU slots at raw 198, 199, 299. **GX-100**: 300 usable = 200 user (50 banks × 4) + 100 preset (25 banks × 4). See §3.5. |
| `0x6040_0000` | (user-patch RAM mirror) | ✔ | **Working-RAM mirror of user patches** — what BTS reads to display the live patch list. 16 patch slot headers at `0x6040_0000..0x604F_0000` stride `0x10000`. Slot starts with the bank-label header (e.g. literal `"USER 1   "` at `0x6040_0000`, `"USER 2   "` at `0x6041_0000`). The persistent flash storage is at `0x2000_0000` per the chart; this region is the live RAM copy. (Source: `reports/bts_capture_findings.md` §1 — BTS startup snapshot.) |
| `0x7F00_0000` | (status / runtime) | ✔ | System status registers + tuner display stream + WRITE save-trigger. Not in the official address tree (runtime only). |

### 3.1.1 Address byte rule

All four address bytes must be `<= 0x7F`. Stepping by 0x40 is therefore valid
within a byte (0x00, 0x40), but 0x80 / 0xC0 are *invalid* — increment to the
next-higher byte instead. This restricts the effective address space to
28 bits (256 MiB), with each byte being 7-bit. The `step_7bit` helper in
`tools/rapid_probe.py` enforces this.

### 3.1.2 RQ1 size — encoding and response semantics

**Size field is raw 4-byte big-endian**, per §2.2 — every byte must be
`<= 0x7F` (the SysEx data-byte constraint), so sizes like `0x80`,
`0xFF`, or `0x8000` are illegal on the wire. Pick 7-bit-clean sizes:
`0x100` instead of `0x80`, `0x10000` instead of `0x8000`, etc.

> **Historical note.** An earlier version of `tools/midi_io.py` (before
> 2026-05-27) encoded the size with `(size >> N) & 0x7F`, which silently
> masked the high bit for any value where a big-endian byte naturally
> landed in `0x80..0xFF`. Probes built on that helper produced wire
> bytes for a smaller size than intended — the source of an earlier
> false claim that the `0x10001000`–`0x10003FFF` region had a "size ≤
> 0x40 restriction". The probes were actually issuing `size=0x40` for
> any intended size in `0x80..0xFF` and observing successful 0x40-byte
> replies. `tools/midi_send.py` (`build_rq1`) has always used
> `to_bytes(4, "big")` and is correct.

#### Size = request ceiling, NOT response length

The size field tells the device the maximum payload to consider, but
**the device returns its own "natural records" at the addresses inside
that range, regardless of how big you asked**. Empirically:

| RQ1 (request) | DT1 response | Address |
|---|---|---|
| `size=0x103` at slot-main `+0x1100` | **131 bytes** | `+0x1100` |
| `size=0x100` at header `+0x0000`   | **128 bytes** | `+0x0000` |
| `size=0x100` at catalogue row      | **128 bytes** | row addr  |
| `size=0x2D` at assign-row          | 45 bytes      | row addr  |

So when BTS issues `RQ1 0x10001100 size=0x103`, the device replies with
**one DT1 of 131 bytes** — not 259. The 0x103 is a request ceiling
that overshoots the natural record. (Direct evidence:
`captures/bts_import_export/import_export_decoded.txt:307` and
following.)

This has two consequences:

1. **Request sizes in BTS captures are not response sizes.** Anywhere
   a doc says "BTS reads N bytes at X", N is the request size; the
   response is the natural record at X, which may be smaller.
2. **You can read a much larger range in one RQ1**, and the device
   will reply with multiple DT1s — one per natural record inside the
   range. Each DT1 is tagged with its own wire address, so the host
   reassembles by address (not by sequence). See
   `reports/merge_read_findings.md`: a single `RQ1 size=0x4000`
   against a user-slot base returns ~43 DT1s covering the entire
   16-KiB body in ~1 s, byte-identical to BTS's 64-region method
   (11.9× faster than the per-region pattern).

#### Observed working request sizes

- `0x10000000`–`0x10000FFF` (live edit buffer): up to at least
  `0x10000`. Device returns many DT1s; tested in
  `tools/probe_merge_sizes.py`.
- `0x10001000`–`0x10003FFF` (live FxItem chain): up to at least
  `0x2800` (covers all 20 live slots). No special restriction
  beyond the size-encoding rule above.
- `0x20000000` user-memory: same — single `RQ1 size=0x4000` reads
  the full slot body in one round-trip.
- `0x50000000` patch-name catalogue: up to at least `0x2600` (full
  catalogue, 300 entries). BTS itself does it as 38 × `0x100`, but
  one big RQ1 works too.

#### Wire-address arithmetic across DT1s

When a multi-DT1 response crosses a 7-bit address-byte boundary, the
device increments byte 2 and resets byte 3 (per §3.1.1). So the
*linear* offset of a follow-up DT1 is **not** `wire_addr - base` —
that arithmetic skips 0x80 values. Convert each address to its linear
form (each byte masked to 7 bits, then concatenated) before computing
offsets. See `tools/probe_bts_match.py::wire_to_linear`.

Empty / unsupported addresses are simply ignored (no DT1 reply at
all); that's an address-validity behaviour, not a size-validity one.

### 3.2 `0x0000_0000` — patch-select register

The first **4 bytes** at `0x0000_0000` are the patch-select register
(originally documented as 5 bytes — that was wrong; the 5th byte is the
PLAYPAGE MODE field at offset 0x04, see §3.3). Each byte uses only its low 4
bits (`0000 aaaa` pattern), and the four nibbles combine big-endian into a
16-bit memory index:

```
V = (b[0] & 0xF) << 12 | (b[1] & 0xF) << 8 | (b[2] & 0xF) << 4 | (b[3] & 0xF)
```

V is the memory number, range 0–299. **GX-10 mapping** (per official chart):

| V range  | Bank | Patches |
|----------|------|---------|
| 0..197   | User | U01-1 .. U66-3 (66 banks × 3) |
| 198, 199 | NIU  | not in use |
| 200..298 | Preset | P01-1 .. P33-3 (33 banks × 3) |
| 299      | NIU  | not in use |

Writing a 4-byte DT1 here causes the device to load that memory into the
live edit buffer at `0x1000_0000`.

#### Verified mappings

Re-decoded with the official 4-nibble formula:

| 4-byte payload | V (memory #) | Patch (GX-10) |
|----------------|-------------:|---------------|
| `00 00 0C 0E`  | 206 | **P03-1 NEO SOUL** (captured live via `flow_preset_load`) |

Earlier 5-byte mappings in the previous version of this doc (e.g. "GX DUAL
DRIVE = `00 00 12 08 00`") need to be re-decoded as their first 4 nibbles
only — the 5th byte was likely the PLAYPAGE MODE write (a separate field).

There is no obvious linear mapping (write→preset). Each patch-select
write triggers the device to:
1. Update `0x00000000` to a normalised 4–5 byte representation.
2. Bulk-emit the new patch contents at `0x10000000+`.
3. Emit standard MIDI Bank Select MSB (`B0 00 xx`) + Bank Select LSB
   (`B0 20 xx`) + Program Change (`C0 xx`), plus two pattern CCs
   (`B0 0E 21` / `B0 2A 3A`) — these likely just convey the new patch
   identity to any downstream MIDI listener.

**Open question:** the encoding may be a Roland-internal "patch UID"
(category, sub-bank, slot, ...) rather than a flat preset number. Probing
with our `tools/probe_patch_select.py` tool can extend the table.

The remainder of the `0x00000000+` block:

```
00000000  -- -- -- -- -- 03 00 00 02 00 00 4A 00 00 01 01  bytes 5..15
00000010  00 01 00 01 01 00 00 00 00 00 00 62 00 01 00 00  
00000020  00 00 00 00 00 00 00 00 00 00 00 00 02 0B 05     
0000002D  0A 01 01                                         (record boundary)
```

The trailing `02 0B 05` looks like a version/build triplet (mirrored in the
patch header at `0x100000FA`). The gap between `0x2C` and `0x2D` is a real
record boundary — the device returns two separate DT1s for that read.

### 3.3 `0x1000_0000` — live edit buffer (canonical layout per official chart)

The `Memory` block layout (offsets from any memory base — same for the live
edit buffer at `0x1000_0000` and for user memories at `0x2000_0000+`):

| Offset | Block | Size | Description |
|--------|-------|-----:|-------------|
| `0x000000` | MemoryCommon  | 0x101 | Patch name (16 B) + per-memory CTL/EXP FUNCTION + MODE + INPUT SETTING + MEMORY MIDI 1-4 + KNOB SETTINGS |
| `0x000140` | MemoryLed     | 0x1C  | Per-memory LED state |
| `0x000200` | Assign 1      | 0x40  | Per-memory ASSIGN (stride 0x40, 20 entries) |
| `0x000240` | Assign 2      | 0x40  | |
| ... | | | |
| `0x000B40` | Assign 20     | 0x40  | |
| `0x000F00` | MemoryEfct    | 0x3E  | Master block: MEMORY LEVEL, **BPM** (4-nibble at +0x02..+0x05), KEY, AMP CTL 1/2, CARRYOVER, TEMPO HOLD, INPUT SENS, **CHAIN linked-list** (TOP + 49 NEXT pointers) |
| `0x001100` | Fx Item 1     | 0x200 | Effect slot 1: TYPE byte (0..82) + ON/OFF + DuplicationNumber + 44 FX Parameters (4 nibbles each) |
| `0x001300` | Fx Item 2     | 0x200 | (stride `0x200`) |
| ... | | | |
| `0x003700` | Fx Item 20    | 0x200 | |

**Total memory size:** ~`0x4000` bytes (0x3700 + 0x200 = 0x3900, plus tail).

#### MemoryCommon offsets of interest

| Offset | Field | Encoding |
|--------|-------|----------|
| 0x00–0x0F | Memory Name | 16 ASCII chars (range 32–126) |
| 0x10–0x13 | Num1..4 Function | 1 byte enum, range 0–17 |
| 0x14, 0x15 | BankDown / BankUp Function | 1 byte enum, range 0–17 |
| 0x16 | CNum Function | 1 byte enum, range 0–14 |
| 0x17–0x1A | Manual Num1..4 Function | 1 byte enum, range 0–14 |
| **0x1B** | **Ctl1 Function** | 1 byte enum, range 0–18 (verified) |
| **0x1C** | **Ctl2 Function** | 1 byte enum, range 0–18 |
| **0x1D** | **Ctl3 Function** | (was previously labelled CTL2 in our captures) |
| **0x1E** | **Ctl4 Function** | |
| **0x1F** | **Exp1Sw Function** | (verified) |
| 0x20 | Exp1 Function | range 0–5 (FOOT VOL / PEDAL FX / FV/PEDAL FX / FV+TUNER / FV+TUNE/PFX) |
| **0x21** | **Exp2 Function** | (verified) |
| 0x22–0x33 | Per-controller Mode (TOGGLE / MOMENT) | 1 byte each |
| 0x32 | INPUT SETTING (per-memory) | 0–10 = SYSTEM / 1–10 |
| 0x35–0x68 | MEMORY MIDI 1..4 | 4 entries × 13 bytes — see per-entry layout + PC convention below |
| 0x69–0x6C | KnobN SettingFxItem | which FX item the knob targets |
| 0x6D–0x7C | KnobN SETTING | 4 nibbles each, value 0–740 (target enum index) |

##### MEMORY MIDI per-entry layout (corrected 2026-06-16)

Each of the 4 entries is 13 bytes. **CHANNEL is a single byte** (only
needs 5 bits); BANK MSB, BANK LSB and PC# are **2-nibble big-endian**
cells (high4 @+0, low4 @+1) because their values reach 128:

| Entry offset | Field | Encoding |
|---|---|---|
| +0x00 | CHANNEL | 1 byte (0 = OFF, 1..16) |
| +0x01..02 | BANK MSB | 2-nibble BE (0 = OFF, 1..128) |
| +0x03..04 | BANK LSB | 2-nibble BE |
| +0x05..06 | PC# | 2-nibble BE (0 = OFF, 1..128) |
| +0x07..08 | CC1# | 2-nibble BE — wire value `0=OFF, 1..128`; device UI shows `wire-1` (OFF→0→1→…) |
| +0x09 | CC1 VAL | **single byte** (0..127) |
| +0x0A..0B | CC2# | 2-nibble BE — same `0=OFF` / `wire-1` display offset |
| +0x0C | CC2 VAL | **single byte** (0..127) |

Verified against U04-3 hardware (2026-06-16) with a non-consecutive
pattern: entered CC1#=10/CC1val=99/CC2#=20/CC2val=120 →
raw `… 00 0B 63 01 05 78` → wire CC1#=11, CC1val=99, CC2#=21, CC2val=120.

> **Earlier docs/codecs decoded CHANNEL as a 2-nibble cell**, which
> shifted BANK MSB/LSB/PC# one byte later and produced wrong values
> (e.g. PC read as 112 instead of 71). Corrected against hardware:
> U02-1 entry0 `01 00 01 00 01 00 04` → CH1/MSB1/LSB1/PC4, and U24-2
> `01 00 01 00 01 04 07` → CH1/MSB1/LSB1/PC71.

**Default PC convention** (device-stamped on every user memory; verified
by full 198-memory audit 2026-06-16): for user memory index `V` (0-based,
U01-1 = 0):

```
CHANNEL  = 1
BANK MSB = 1 + (V // 99)     # two MSB banks of 99 (198 = 2 × 99 user mems)
BANK LSB = 1
PC#      = (V % 99) + 1      # cycles 1..99, wraps at the MSB boundary
```

So U24-2 (V=70) → MSB1/PC71; U34-1 (V=99) → MSB2/PC1; U66-3 (V=197) →
MSB2/PC99. See `tools/memory_midi_audit.py` and `tools/memory_midi_reset.py`.

#### MemoryEfct (master block at offset 0x0F00, 62 bytes)

| Offset | Field | Range |
|--------|-------|-------|
| 0x00–0x01 | MEMORY LEVEL | 0–200 (2 nibbles) |
| **0x02–0x05** | **BPM** | 400–2500 (= 40.0–250.0; 4 nibbles big-endian, `V = BPM × 10`) |
| 0x06 | KEY | C(Am)..B(G♯m) (12 values) |
| 0x07 | AMP CTL 1 | OFF / ON |
| 0x08 | AMP CTL 2 | OFF / ON |
| 0x09 | CARRYOVER | OFF / ON |
| 0x0A | TEMPO HOLD | OFF / ON |
| 0x0B | INPUT SENS | 0–100 |
| 0x0C | CHAIN TOP ITEM | head-pointer of the chain linked-list (0 = -1 / no FX, 1–49 = FX index +1) |
| 0x0D–0x36 | CHAIN NEXT ITEM[0..41] | next-pointer chain (49 slots total at 0x0D..0x3D) |

The effect chain order is encoded as a **linked list**: `CHAIN TOP ITEM`
points to the first FX, `CHAIN NEXT ITEM[N]` is what comes after FX N.
A pointer value of 0 means "no next" (end of chain).

#### MemoryFxItem (per FX slot at offsets 0x1100, 0x1300, ..., 0x3700)

| Offset | Field | Encoding |
|--------|-------|----------|
| 0x00 | **TYPE** | 1 byte enum, range 0–82 — see `tools/fx_type_enum.py` for the 83-name table |
| 0x01 | OFF/ON | 0/1 |
| 0x02 | **DuplicationNumber** | 0–9, the "Nth instance of this effect type in the chain" counter — **NOT an A/B path marker** (an earlier revision of this row claimed `dup=1` = path A / `dup=2` = path B; live probes falsified that: 2026-05-24 — pre-SPLITTER slots render on path A regardless of dup; 2026-06-05 — direct edit-buffer read of a device-built parallel chain shows `dup=0` on every slot, incl. parallel members). **A/B membership is positional: slots between DIVIDER and SPLITTER are path A; between SPLITTER and MIXER are path B.** The SPLITTER (FX TYPE 30, 0x1E) carries `dup=0` and is internal-only — hidden on the device's chain display. NEW 2026-06-05 (`tools/probe_chain_splitter.py`, patch "METAL MR 3"): the device's own front-panel DIV insert auto-creates the SPLITTER (DIV→SPL→MIX, MIXER arrives OFF) — so BTS, the device, and current gxnarly all emit it; only pre-2026-05-27 gxnarly chains lack one. |
| 0x03–0x132 | **FX Parameter 1..44** | each 4 nibbles big-endian, range 12768–52768 = -20000..+20000 in offset binary |

> ⚠️ **CRITICAL** — every FX Parameter is **4 nibbles**, not 1 byte.
> Display value = `V_raw - 32768`. Our original RE pipeline mistakenly
> read only the last byte; see `docs/official_xref.md` and the fix in
> `tools/reanalyze_knobs_4nibble.py`. All 730 captured knob ranges have
> been re-decoded with this formula.

#### `0x10001100+`: chain control / slot type table

This is where the **per-slot effect type IDs** live. Tone Studio's
drag-and-drop of an effect type onto a chain slot triggers a 3-byte DT1
write at `0x10001100`/`0x10001101`/`0x10001102` (category, modifier, type),
plus a chain-order DT1 at `0x10000F00`. The structure within `0x10001100+`
appears to be 4-byte groups (slot 0 at `0x10001100..0x10001103`, slot 1 at
`0x10001104..0x10001107`, ...) where `+0x03` of every group is the constant
sentinel `0x08`.

Empirical type-ID values observed for slot 0 (write to `0x10001100`):

| Value | Effect (suspected) |
|-------|--------------------|
| `0x08` | COMP (BOSS COMP)   |
| `0x09` | X-COMP (X COMPRESSOR) |
| ... | (mapping table built by `tools/map_effect_types.py`) |

A direct DT1 write to `0x10001100 = T` makes the device cascade parameter
defaults for the new effect type into the rest of the patch buffer. Tone
Studio, however, caches its UI state and **does not auto-refresh** when
the device's chain changes via our DT1 — so to read the human-readable
effect name we must restart Tone Studio (which fetches device state on
startup). The `--names` flag of `map_effect_types.py` does this for each
type.

**Read-back caveat:** writing a NEW value to `0x10001101` (the modifier
byte) when no preceding category change occurred is silently ignored; the
device only honours `0x10001100` writes that map to a known effect type.
Writing to a category byte the device does NOT recognise has no effect.

**Slot identity is multi-byte.** Empirically, writing `0x08 0x01 0x00` as a
3-byte block to `0x10001100` does **not** make the slot show "BOSS COMP" in
Tone Studio's UI even though Tone Studio's drag-COMP wrote the same bytes
(among others). There are additional state bytes — likely in the per-slot
parameter region at `0x10000200 + slot*0x100` — that need to match. The
**reliable** way to assign an effect to a slot is to capture Tone Studio's
full drag-and-drop USB sequence (about a dozen DT1 writes) and replay it.
A direct `RQ1` of `0x10001100..0x100011FF` after each drag of every type
bar item gives a per-effect address+value table that the user can then
replay on demand. `tools/map_effect_types.py` is set up to drive this loop
once the drag sequence captures are added.

Empty / INIT slots have a stable "factory default" pattern:
`08 00 00 00 08 00 00 01 0B 00 14 01 0C 1E 00 00 00 00 00 03 0F 0F 0F`
— the `0F 0F 0F 0F` runs are visible "unused" markers.

Tone Studio's EMPTY/U10-1 INIT vs an active patch (e.g. GX DUAL DRIVE) differ
in **400 bytes**, distributed across the header, routing, and per-slot blocks.

When Tone Studio's user clicks a hex effect block in the editor, the device
emits a DT1 at `0x10000154` whose 4th payload byte alternates `0x02`↔`0x03`.
This is a *UI-level* "current slot" register, not the audible on/off state
(which is in the per-slot block).

> **Update (2026-07-11, GX-10 fw 1.00):** `0x10000154` is
> `MemoryLed.ON_OFF_STATE` (`0x10000140` + offset `0x14`), the 8-nibble
> 32-bit footswitch-LED bitmap of §5.7b/§5.8 — which explains the
> "4th payload byte" wobble above (it's LED bits changing). With the
> editor-attach bit set, the device **broadcasts this bitmap
> unsolicited** on footswitch presses and even on looper loop-cycle
> LED blinks (observed ~3 s period tracking a recorded loop's length,
> C1 = bit 7 toggling). An editor gets live pedal-LED state for free
> by decoding these events — no polling needed.

### 3.4 `0x20000000` — live patch mirror

```
RQ1 0x20000000 size 0x40
DT1 0x20000000 len 63  4E41545552414C20414D5020484220 ... "NATURAL AMP HB  ..."
```

Byte-identical content to `0x10000000`. We have not yet probed whether
writes to `0x20000000` have different semantics than to `0x10000000` — they
might be a write-only "audition" region vs read-only "current-state"
region, or a parallel temp buffer.

### 3.5 `0x50000000` — patch name catalogue (read-only)

Patch names, 16 ASCII bytes each, packed contiguously. BTS reads it
as **38 separate RQ1s with `size=0x100`** (16 names of request ceiling
each), incrementing the base address by 0x100 per request. Each
request returns one DT1 of 128 bytes (the natural record at that row
— per §3.1.2, the response size is determined by the device, not by
the request). The full BTS sweep covers `0x50000000..0x50002500` and
yields 38 × 128 = **4864 bytes, 304 × 16-byte name slots, up to 300
of which carry non-empty names** (NIU slots account for the
remainder). BTS's final RQ1 in the range is `0x50002500 size=0x40`,
which returns 64 bytes — a 4-name short tail.

Faster alternative: a single `RQ1 0x50000000 size=0x2600` returns the
entire catalogue as 24 DT1s (packed contiguously, ~210 bytes each)
in ~0.85 s. Empirical 3.3× speedup over BTS's 38-RQ1 pattern; see
`reports/merge_read_findings.md`.

**Per-device totals** (the 300-slot catalogue exists in both products
but the bank decomposition differs):

- **GX-10**: 297 usable = 198 user (66 banks × 3) + 99 preset
  (33 banks × 3). 3 NIU slots at raw 198, 199, 299.
- **GX-100**: 300 usable = 200 user (50 banks × 4) + 100 preset
  (25 banks × 4).

See `firmware_versions.md` "Per-device patch totals" for the
canonical reference and the GX-10 raw→bank decode formula.

```
0x50000000  "NATURAL AMP HB  HEAVY METAL     SUPREME AMP HB  MAXIMUM AMP HB  ..."
0x50000100  "JC120 AMP HB    TWIN CMB AMP HB BG COMBO AMP HB ORNG STK AMP HB ..."
...
0x50002500  "FUZZ BASS       LOOPER CLEAN    LOOPER CRUNCH   LOOPER DRIVE    LOOPER -1OCT"
```

The catalogue is **read-only**.

⚠️ Decoded contents above were captured from a firmware-level-3
GX-10 on 2026-05-14. An earlier version of this section cited
"BOUTIQUE AMP HB" as an example name — that turns out to have been
from a different firmware or unit.

### 3.6 `0x60400000` — user patch slots (RAM)

Each user patch occupies a 64 KiB-aligned slot:

```
slot N at 0x60400000 + N * 0x10000     (N = 0..15)
  +0x00   16 B   Name (ASCII, space-padded)
  +0x10   ~      Patch parameters (effect chain, blocks, settings)
```

A factory-fresh GX-10 has all 16 slots named `USER 1` … `USER 16`. The
parameter block of an INIT slot starts with the byte sequence
`03 0F 08 00 00 ...` — this looks like the encoded "INIT" patch:
likely 1 effect on (`03`) of type `0x0F`, level `0x08`, with the rest zero.

### 3.6.5 `0x00200000` — editor metadata

Discovered when the WRITE button dropdown was clicked: Tone Studio queries
this region with `RQ1 0x00200040 size=0x53` and `RQ1 0x00200140 size=0x53`,
and the device replies with two large blocks (~96 bytes each) populated with
binary-flag patterns:

- `0x00200040`: `01 01 00 00 01 01 01 01 01 01 ...` — array of 0/1 flags
- `0x00200140`: `77 77 10 10 77 77 77 77 77 77 ...` — array of mostly-0x77 status bytes

These look like per-slot or per-effect "is dirty / is configured" flags used
by Tone Studio to decide which UI buttons to enable. Layout not yet decoded.

### 3.7 `0x7F000000` — system status

Single-byte registers at fixed offsets, observed (Linux probes
`reports/linux_probe_results.md` §P2-4 + Windows BTS captures
`reports/bts_capture_findings.md` §1+§2):

| Address | Role | Notes |
|---------|------|-------|
| `0x7F000000` | **EDITOR_COMMUNICATION_LEVEL** — firmware capability level | BTS's per-version compatibility gate. On connect BTS reads this byte and compares it to its own `ProductSetting.communicationLevel`; mismatch → "older firmware" or "older BTS" dialog and offline mode. Observed values: **`0x03`** on this unit (firmware-level-3, the launch family — confirmed against fw 1.00 captures and a 2026-05-09 Linux probe of fw 1.04). BTS v1.0.0 (`bts_gx10_m100.zip`) hard-codes 3; BTS v1.0.2 (current Roland release) hard-codes 4. Inferred mapping: fw ≤ 1.04 → 3, fw 1.05 → 4. See `docs/firmware_versions.md` and BTS source `Resources/html/js/businesslogic/midi_connect_controller.js:207`. **DT1 writes are silently ignored** — read-only firmware flag, not a settable register. |
| `0x7F000001` | **editor-attached handshake bit** | host writes `0x01` on connect, device echoes; host writes `0x00` on disconnect. BTS writes it twice back-to-back at startup. |
| `0x7F000002` | **RunningMode mirror** | mirrors `0x00000007`. `0x00`=EDIT (BTS startup default), `0x01`=MONO TUNER, `0x02`=POLY TUNER, `0x03`=TT TUNER. **Silent until the editor-attach bit is set.** |
| `0x7F000003` | **EDITOR_COMMUNICATION_REVISION** — firmware capability sub-revision | Second leg of the BTS firmware gate (read right after `0x7F000001` is written). Compared to `ProductSetting.communicationRevision`. **`0x00`** observed on every firmware we've seen and expected by every BTS we've inspected (v1.0.0, v1.0.2); reserved for future use. See `docs/firmware_versions.md`. |
| `0x7F000300` | **TUNER pitch streaming buffer** (48 bytes) | streamed by device every ~200 ms while in TUNER mode; layout = 8 string slots × 6 bytes each, encoding per-string pitch / detection state. Empty pattern is `00 01 03 08 08 00` per string. |
| `0x7F000701` | **state-mirror for chain edit** | BTS writes `0x05` when a chain edit begins (paired with `0x00200003 = 0x01`) and `0x03` when it ends (paired with `0x00200003 = 0x00`). Within 0–10 ms of the trigger. Member of the same "global state mirror" family as `0x7F000002`. |
| `0x7F000703` | **second handshake-style toggle** | host writes `0x00` then `0x01` at startup, mirroring the `0x7F000001` pattern. Purpose unknown — possibly a separate broadcast-subscribe channel. Silent on Linux probe without `0x7F000001 = 0x01` first. |
| `0x7F000705` | **LOOPER_CONTROL — writable looper transport** (verified on GX-10 fw 1.00, 2026-07-11, `tools/probe_looper_control.py`) | Named in BTS `address_const.js` `COMMAND` block; only referenced from commented-out GT-1000-era connect code (`RQ1(…, 4)` gated on com-level ≥ 2), so BTS never exercises it — but the GX-10 firmware implements it. **Writes drive the transport** (DT1 1 byte): the byte behaves like the LOOP CTL pedal's engage state, with `02`/`03` as direct verbs on top. Verified: `01` from empty = **start RECORD**; `01` (0→1 edge) while playing = **start OVERDUB**; `00` while rec/dub = **end rec/dub → PLAY**; `02` from play = **STOP**; `03` from stop = **PLAY**. The firmware acts on register *value changes* — writing `01` when the register already holds `01` does nothing (re-arm by writing `00` first). **CLEAR: unreachable by write** — exhaustively verified 2026-07-11: every single-byte value `0x00`–`0x7F` was written from the STOP state (batched, 300 ms apart, play-test after each batch) and loop content survived all of them; toggling the PHRASE LOOP FxItem's OFF/ON byte (`0x1000_2501` on the test patch) doesn't drop the phrase either; manual CLEAR emits no unique broadcast (only the `0x10000154` LED-bitmap event). `02` during DUB ends the dub into PLAY (it does NOT clear — clean retest). **Reads: content flag, only stable at rest.** Verified: reads `00` when the loop is empty/cleared and `01` when stopped with content (both directions confirmed via manual-clear diff + write-driven re-record). While the transport is rolling (rec/play) reads are inconsistent (`00` and `01` both observed in play-with-content) — to detect content presence, stop first (`02`), then RQ1 1 byte. Not a transport-state readout. No readable transport-state register exists in `0x7F000700`–`0x7F00070F` (only `0x704`, constant `00`, and `0x705` reply), `0x0020_0000`, or the patch region (PHRASE LOOP's only patch param is LOOP LEVEL). Track transport shadow-state host-side from the verbs you issue + `0x10000154` LED broadcasts (physical presses / blink cadence, attach required). **Provenance (GT-1000 BTS v3.20.2, mined 2026-07-11):** on the GT-1000 this register is the looper *chain-block enable* — `effect_controller.js turnOn()` writes only `1`/`0`, `midi_observe_controller.js` decodes inbound broadcasts (byte 0 = on/off), `chain_controller.js` re-reads it after chain-order changes. No BTS for any device ever writes transport or CLEAR values; the GX-10's rec/play/stop verb behavior is firmware capability beyond Roland's own editor. The GX-10 also **broadcasts `0x705` unsolicited on looper pedal events** (confirmed: tonight's value transitions coincided with physical presses) — subscribe (editor-attach) and treat broadcasts as the recording-engaged signal. **CLEAR verdict: not remotely reachable** — exhausted all single-byte writes, slot toggle, and Roland's own editor source; remaining exotic ideas (multi-byte payloads, `0x704` writes) are low-probability. |
| `0x00001036` | **MODE_SWITCH (BTS name)** — not implemented on GX-10 | Read by the same commented-out GT-1000 code ("get control mode status"). RQ1 of 1 or 4 bytes is silently ignored on GX-10 fw 1.00 (2026-07-11 probe); use `0x00001034` CONTROL_MODE instead. |

### 3.8 `0x00000007` — UI-mode register

A single-byte register at offset `0x00000007` controls Tone Studio's "mode":

| Value | Mode |
|-------|------|
| `0x01` | TUNER MONO |
| `0x02` | TUNER POLY |
| `0x03` | TUNER TT |

Writing here triggers the device to enter that mode and start emitting the
appropriate streaming data at `0x7F000300`. The device mirrors the value
into `0x7F000002`. Writing `0x00` (or no DT1 to this register on close)
exits the mode.

### 3.8.1 Editor-controlled tuner toggle (verified 2026-06-28 / 2026-07-09)

Hardware-verified on a GX-10 (sw_rev `01.00.00.00`) via
`tools/probe_tuner_toggle.py` and follow-up echo-trail captures. An editor
can drive the device's on-screen tuner directly — enough to host a "watch
the tuner on the device" toggle without rendering anything. Consumed by
gxnarly's MENU→TUNER buttons.

**Register semantics on this firmware** (each verified on the pedal's
display; they contradict parts of §3.8, `API.md` §156, and `menus.md`):

| Write | Effect on display |
|---|---|
| `0x7F000002 = 0x00` | exit to play screen (this, NOT `0x01`, exits) |
| `0x7F000002 = 0x01` | MONO tuner view |
| `0x7F000002 = 0x02` | POLY tuner view / tuner-active |
| `0x7F000002 = 0x03` | **Input Settings screen — NOT a tuner** |
| `0x00000007 = 1/2/3` | switches the tuner view (MONO/POLY/TT) **only while a tuner is already displayed**; TT is reachable ONLY this way |

The display follows the **last write**, so order matters.

**Working sequence (any mode, incl. TT):**
1. `DT1 0x7F000001 = 0x01` — editor-attach (required first; these
   registers are deaf without it; give it settle time).
2. `DT1 0x7F000002 = 0x02` — activate the tuner FIRST.
3. `DT1 0x00000007 = 1|2|3` — THEN select MONO / POLY / TT.
4. (BTS also writes `0x00000006 = 0x00` here. Register purpose
   unidentified — cargo-cult with caution.)

Exit: `DT1 0x7F000002 = 0x00`. `API.md` §156's "deactivate with `= 0x01`"
is wrong on this firmware — `0x01` switches to the MONO view instead.
`API.md`'s mode-first-then-activate order is also wrong (last-write-wins
means you get the activate value's view, not the requested mode).

**Echo behaviour (measured, critical for editor UI sync):**

- While *switching* tuner views the device emits transient
  `0x7F000002 = 00` echoes (observed +7 ms and +17 ms after the write
  burst) — identical in value to a genuine exit. An editor that treats
  every `00` as "tuner closed" will falsely clear its UI state.
  **Suppress `00` within ~1 s of your own tuner writes**; echo tail of the
  full sequence runs to ~460 ms.
- Mode-flavoured `0x7F000002 = 01/02` echoes are unreliable for sync
  (a `01` was observed even after switching to TT). Ignore them.
- A genuine **front-panel exit** emits `0x7F000002 = 00` (outside any
  write window) — the one reliable device→host tuner signal.
- `0x00000007` echoes lag by ~100–460 ms and are sometimes absent.

**Related chart discrepancy:** the official chart lists TUNER TYPE
(`0x00000007`) values 1 and 3 only (MONO, TT) — POLY (2) is a BTS-GUI
extension that the hardware accepts (see `official_xref.md` §"Tuner
mode").

**Pitch stream.** `0x7F000300` only carries frames when there is detected
input (a plucked string). With no signal connected the stream stays silent
even though the tuner display is active — expected, not a fault.

---

## 4. Connection sequence Tone Studio runs at startup

Captured at the wire level via USBPcap (~5.5s of traffic, 222 SysEx
messages, 148 host → device + 74 device → host). Times below are relative
to the first observed request; round-trip latency for a small read is
~3–10 ms.

| t (s) | dir | message | meaning |
|------:|-----|---------|---------|
| 0.000 | H→D | `RQ1 0x10000069 size=0x14`           | Read 20 bytes of current patch metadata. Tone Studio's *very first* message, before identity. |
| 0.007 | D→H | `DT1 0x10000069 (20 B)`              | Patch metadata block. |
| 0.022 | H→D | `F0 7E 7F 06 01 F7`                  | Universal Identity Request. |
| 0.024 | D→H | Identity Reply                       | family `0x040B`, model `0x0000`, sw `01000000`. |
| 0.188 | H→D | `RQ1 0x7F000000 size=1`              | Read system flag. |
| 0.191 | D→H | `DT1 0x7F000000 = 0x03`              |  |
| 0.208 | H→D | `DT1 0x7F000001 = 0x01`              | **Editor-attached handshake bit.** Tone Studio writes this to announce itself. The device echoes it back at +3 ms. |
| 0.215 | H→D | `RQ1 0x7F000003 size=1`              | Read another system flag. |
| 0.218 | D→H | `DT1 0x7F000003 = 0x00`              |  |
| 0.237 | H→D | `RQ1 0x50000000 size=0x100` × 38     | Bulk read of the entire patch name catalogue. BTS does 38 separate requests; the device returns one 128-byte DT1 per request (size 0x100 is a request ceiling — see §3.1.2). A single `RQ1 size=0x2600` returns the whole catalogue as 24 DT1s in ~0.85 s, 3.3× faster than the 38-RQ1 pattern. |
| ~3.0  | H→D | `RQ1 0x60400000 size=0x100` × 16     | Bulk read all 16 user patch slot headers (name + first parameters). |
| ~4.5  | H→D | `RQ1 0x10000XXX size=0x2D` × many   | Walk the live patch buffer in 0x40-byte pages, reading the full effect-chain configuration. |
| ~5.5  | —   | idle                                  | No further traffic until user edits a parameter. |

> **`0x7F000001` is a host-controlled register.** Don't blindly write to it
> from your own scripts — Tone Studio uses it to declare itself active to
> the GX-10's firmware. Writing the wrong value, or writing while Tone
> Studio is also connected, may put the device into an unexpected state.

After this initial sync, normal librarian-list clicks and hex-block clicks
in the editor are largely client-side. Only certain operations push DT1 to
the device (parameter-edit operations like turning effect blocks on/off via
the on-block toggle, knob drags, dropdown selections of effect type, etc.).

---

## 5. Tools in this repo

All under `tools/`. They use only ctypes bindings to `winmm.dll` plus a few
pure-Python wheels — no driver install, no compilation, no admin.

| Tool | What it does |
|------|--------------|
| `list_midi.py` | Enumerate MIDI input/output ports. |
| `midi_sniff.py` | Open a MIDI input by name and log every short message + SysEx as JSONL with high-res timestamps. Includes a label-fifo so an external script can write context lines that get interleaved into the log. |
| `midi_send.py` | Open a MIDI output by name; build & send Roland DT1, RQ1 and Universal Identity Request. Importable as a library. |
| `address_scan.py` | Combine sniffer + sender in one process to sweep address-space probe plans. Plans included: `top-regions`, `live-patch`, `user-bank`, `system`. |
| `sysex_decode.py` | Parse the JSONL logs into structured Roland records, validate checksums, render ASCII payloads, and summarise unique addresses. |
| `inspect_ui.py` | Dump the Tone Studio window's UIA tree (used to discover that the editor is a WebView2 and must be driven by coordinates). |
| `screenshot.py` | Capture the Tone Studio window or full screen as PNG (used to derive coordinates for the driver). |
| `drive_tone_studio.py` | Autonomous Tone Studio UI driver. Walks scripted action sequences (patch sweep, effect-block sweep, knob drag, dropdown sweep, etc.) and writes each action to the sniffer's label fifo, so the JSONL log shows which UI action produced which MIDI traffic. |
| `pcap_to_jsonl.py` | Convert a USBPcap `.pcap` (capture with `--inject-descriptors` so Wireshark's USBMIDI dissector recognises the GX-10) into the same JSONL shape `midi_sniff.py` produces, with a `dir` field of `host->dev` / `dev->host`. Wraps `tshark -V` and parses the reassembled SysEx hex per frame. |

### 5.1 Typical workflows

Passive listen for 30 s while you use Tone Studio yourself:

```powershell
python tools\midi_sniff.py --port "GX-10" --log captures\session.jsonl --seconds 30
python tools\sysex_decode.py captures\session.jsonl --ascii
```

Active probe of a new region:

```powershell
python tools\address_scan.py --plan custom --addr 60400000 --size 200 \
                             --log captures\probe.jsonl
python tools\sysex_decode.py captures\probe.jsonl --ascii
```

Drive the editor and capture in parallel (in two shells):

```powershell
# shell A
python tools\midi_sniff.py --log captures\driven.jsonl --label-fifo captures\labels.txt --seconds 60
# shell B (after sniffer is running)
python tools\drive_tone_studio.py --label-fifo captures\labels.txt --scripts knob blocks
```

---

## 5.5 Menu-by-menu observations

Captured by clicking each top-level Tone Studio toolbar item with USBPcap
running.

| Menu | Click triggers SysEx? | Notes |
|------|-----------------------|-------|
| EDITOR        | none — local view switch | reactivating EDITOR after another tab does query the live patch buffer (typical re-read) |
| LIBRARIAN     | none — local list view | preset/user names already cached at startup |
| TONE EXCHANGE | none on click; cloud feature | likely emits when actually downloading a patch |
| TUNER         | **yes** — see §3.8 / §3.7 | enters tuner mode, device begins streaming pitch buffer |
| IR LOADER     | none on open; the IR slot list is local | clicking LOAD with a real `.wav` would trigger the bulk binary upload (not yet captured) |
| MENU          | **untested by design** | may include factory reset, deferred to phase 6 |
| IN/OUT SETTINGS | none on open; modal shows current routing | toggling GLOBAL EQ / changing INPUT / OUTPUT presumably emits DT1 (UI-driving via mouse was unreliable; direct DT1 to suspected addresses is the better path) |
| CTL/EXP | none on open | same situation as IN/OUT |

For *any* setting to commit to the device, the user has to interact with
its specific control inside the modal, which our coordinate-based UI driver
struggles with reliably (WebView2 doesn't expose control IDs to UIA). The
sniff-and-poll-at-DT1 approach scales better.

## 5.6 Chain slot manipulation (INSERT / DELETE / OVERWRITE / MOVE)

Reverse-engineered from BTS's `chain_controller.js`. The chain is a
linked list living in `MemoryEfct` — chain order is independent of
which `MemoryFxItem` slot stores each effect's parameters.

**Linked list layout** (per chart, `MemoryEfct` block):

```
0x10000F0C   CHAIN TOP ITEM       (1 byte, 0..49 stored, semantics: -1..48)
0x10000F0D   CHAIN NEXT ITEM 0    (1 byte, 0..49 stored)
0x10000F0E   CHAIN NEXT ITEM 1
0x10000F0F   CHAIN NEXT ITEM 2
...
0x10000F3D   CHAIN NEXT ITEM 48
```

The byte values are off-by-one: `0` means "end of chain" (sentinel for
`-1`), `1` means "FxItem #0", `2` means "FxItem #1", etc. so `byte =
fxItem_index + 1`. There are 49 FxItem storage slots (indices 0..48)
plus a special `MASTER` slot.

**Chain ordering algorithm** (from `chain_controller.js:sendOrderChange`):

1. The blockNumOrder array `O[0..48]` holds, for each storage slot
   index `i`, the next-FxItem index that follows it in the chain
   (`-1` if end-of-chain or unused).
2. Build 50 contiguous bytes: byte 0 = `top + 1`, bytes 1..49 = each
   `O[i] + 1`.
3. Bulk DT1 to `0x10000F0C` with those 50 bytes as the payload.

**INSERT new effect at position N** (e.g. INSERT button after typebar selection):

1. `sendChainEditTrigger(true)` — DT1 `0x00200003 = 0x01`.
2. Pick the first unused FxItem storage index `k` (where the slot's
   TYPE byte is unused — BTS calls `findTheFirstUnusedIndex`).
3. Write the new effect's TYPE to FxItem #k:
   - DT1 to `0x10001100 + k * 0x200` (offset 0x00 of FxItem #k) with
     the 1-byte TYPE enum value (0..82, see `tools/fx_type_enum.py`).
4. Patch the linked list to point the chain through the new node:
   - If inserting at top: set `byte0 = k + 1`, set `O[k] = oldTop`.
   - Otherwise: set `O[prev] = k + 1`, set `O[k] = oldNext`.
5. Bulk DT1 the modified 50-byte chain block at `0x10000F0C`.
6. `sendChainEditTrigger(false)` — DT1 `0x00200003 = 0x00`.

**DELETE at position N** (DELETE button after chain-slot selection):

1. `sendChainEditTrigger(true)`.
2. Linked-list patch: find the predecessor of FxItem #N in the chain,
   set its `O[prev] = O[N]` (skip over N).
3. Mark FxItem #N as unused: clear its TYPE byte (DT1 to
   `0x10001100 + N * 0x200`, payload = 0 or some "EMPTY" sentinel).
   *(BTS doesn't always do this — the leaked node simply gets reused
   on the next INSERT.)*
4. Bulk DT1 the modified chain block.
5. `sendChainEditTrigger(false)`.

**OVERWRITE at position N** (OVERWRITE button after typebar selection):

In BTS this is implemented as DELETE-then-INSERT in one transaction
(see `chain_controller.js:917`: "BTS should send 'deleted chain' and
'inserted chain' for overwrite. Just Delete the block first, then Add
the new one again after the device is ready"):

1. `sendChainEditTrigger(true)`.
2. Bookkeeping: capture `{deletedIndex: N, insertIndex: prevOf(N),
   insertType: newType}` so the device sees both ops as one edit.
3. Run the DELETE flow, then the INSERT flow (no separate trigger
   transitions in between).
4. `sendChainEditTrigger(false)`.

**MOVE/REORDER (drag-drop within chain)**:

Pure linked-list reordering — no FxItem TYPE writes needed, only the
50-byte chain payload at `0x10000F0C` changes.

**The ChainEditTrigger gotcha**:

Address `0x00200003` (`Setup_temp ChainEditTrigger`, INTEGER1x7) acts
as a *handshake* between BTS and the device: BTS writes `1` before any
chain edit and `0` after. BTS also caches its last sent value in
`window.globalIsChainEditing` and short-circuits redundant writes. If
this flag is left at `1` on the device when BTS shuts down, the next
launch reads `1` into `globalIsChainEditing`, then refuses to send any
new "begin edit" trigger because the value already matches — and every
INSERT / DELETE / OVERWRITE button silently no-ops.

Mitigation: `tools/fix_stuck_chain_edit.py` writes `0` to that address
with BTS killed, then relaunches BTS. Always run after long capture
sessions to avoid leaving the device stuck.

## 5.7 ALL DATA BACKUP / RESTORE flow

Reverse-engineered from `all_data.js` + `editor_setting.js` +
`librarian_setting.js`.

**BACKUP (read all)** is implemented as a sequenced RQ1 sweep over the
list of address blocks BTS already knows about. The blocks are split
into two groups:

System blocks (`SystemSetting.blockSet` — `editor[2].config`):
```
System_common         (offset 0x00000000, 45 bytes)
System_control        (offset 0x00001000)
System_midi           (offset 0x00003000)
System_inout          (offset 0x00004000)
System_efct           (offset 0x00005000)
System_pitch          (offset 0x00006000)
Pcmap_bank(1..3)      (offsets 0x00100000, 0x00100400, 0x00100800)
Setup_temp            (offset 0x00200000)  ← includes ChainEditTrigger
Setup_temp2           (offset 0x00200???)
Setup_temp3
Setup_efct
System_inputSetting(1..10) (offsets 0x00006100..0x00006a00)
System_globalEq(1)    (offset 0x00006b00)
```

User-patch blocks (`LibrarianSetting.blockSet` — `librarian[0].config`),
read once per memory (`rows = 198` for GX-10, so 198 reads of each):
```
User_patch%common       (per memory: offset 0x000000)
User_patch%led          (offset 0x000140)
User_patch%assign(1..20) (offsets 0x000200, 0x000240, ..., 0x000B40)
User_patch%efct          (offset 0x000F00)
User_patch%fxItem(1..20) (offsets 0x001100, 0x001300, ..., 0x003700)
```

For each `(memory_n, blockName)` pair, BTS computes the absolute
address as `0x20000000 + memory_n * 0x60000 + offset` (using 7-bit-per-
byte arithmetic — see `tools/probe_user_memory_names_burst.py`'s
`memory_addr` helper) and issues an RQ1 covering that block's
declared `size`. The device replies with a series of DT1 packets
(usually one per block; for large blocks like FxItem, several).

**RESTORE (write all)** mirrors the read: for each block in the saved
JSON, BTS issues a sequence of DT1 writes covering the same address
ranges. (Source: `all_data.js:write`.)

**Why we don't replicate this end-to-end**: the read flow is
non-destructive but redundant — `address_scan.py` already reads any
chart-documented address range, and the chart already lists every
block above with its size. The write flow is destructive (overwrites
all 198 user memories), so we keep RESTORE deferred under destructive
operations.

## 5.7b Pedal mode + LED colour derivation

The chart's `MemoryLed.ON_OFF_STATE` bitmap reflects each footswitch's
**manual-mode toggle state**, not the displayed LED colour. To know the
actual displayed colour you also need:

1. **The current pedal-operating mode** at `SystemControl.ControlMode`,
   address `0x00001034` (1 byte). The chart documents only `(0..3)`
   with **no value labels** — and BTS's `resource.js` line 458 string
   `"UP/DOWN, BANK/NUM, MANUAL"` is UI display order, NOT the byte
   mapping. The authoritative source is BTS's `disableFunCtl()` switch
   in `control_mode_controller.js`. Verified empirically on GX-10:
   - `0` = **UP/DOWN** — BANK pedals always blue (bank navigation)
   - `1` = **MANUAL** — each pedal toggles its assigned effect; LED
     colour comes from the active Assign for that pedal
   - `2` = **BANK/NUM** — slot-pedal for current patch lights blue,
     others dark; CUR NUM assigns can re-colour the current-slot pedal
   - `3` = MANUAL (writing this byte via DT1 was confirmed to produce
     the same device state as `1` — front-panel menu shows "manual
     mode" and LEDs follow the assigns identically). The front-panel
     mode button only cycles `0/1/2`, so `3` is reachable only via
     SysEx write — useful when scripting an explicit "make sure we're
     in MANUAL" call.

   GX-100 is expected to use the same byte mapping — the chart and
   BTS code are shared, and `disableFunCtl` is model-agnostic. Only
   the physical-pedal layout differs per model. On GX-10, the 3
   hardware footswitches (BANK ▼, BANK ▲, CTL 1) alias to the
   GX-100's MAN NUM 1/2/3 sources in the Assign block during MANUAL
   mode (see `tools/device_profile.py` → `manual_mode_source_aliases`).

2. **The Assign block** (20 entries × 0x40 bytes at MemoryCommon offset
   `0x000200`). For each pedal in MANUAL mode:
   - Walk the 20 Assigns, find one with `SW=1` and `SOURCE` matching
     the pedal's source-table index (chart's Assign source enum:
     `NUM 1..NUM 4, MAN 1..MAN 4, CUR NUM, BANK DOWN, BANK UP,
     CTL 1..CTL 4, EXP 1 SW, EXP 1, EXP 2, INT PDL, WAVE PDL, INPUT,
     CC#1..CC#31, CC#64..CC#95`).
   - Read its `TARGET` (4-nibble at offset 0x02..0x05, 0..740 →
     `ASSIGN_TARGET_TABLE` index).
   - Look up the target's `category` field (e.g. `"OVERDRIVE"`,
     `"AIRD PREAMP"`, `"DIVIDER"`).
   - For the meta-target `EFFECT(RENAMED WITH TYPE)` (target #1):
     dereference via `TARGET_FX_ITEM` (offset 0x01) to read that
     FxItem's actual TYPE byte at `0x10001100 + TARGET_FX_ITEM * 0x200`,
     then look up the effect via `FX_TYPE_NAME`.
   - Map the effect/category name to a colour via `EFFECT_COLOR`
     (the same palette BTS uses for its chain hexes).

3. **Special cases** beyond the assign block:
   - **AMP CTL 1/2** function → red (AIRD PREAMP color)
   - **TUNER** function → green
   - **BPM TAP** → yellow (blink at tempo)
   - **DIV CH.SEL** → green when path A active, red when path B
   - **LOOP CTL/STOP/CLEAR** → red (PHRASE LOOP color)
   - **MEMORY -1/+1, BANK ▼/▲, "1"** → blue (memory-navigation colour)

Tools: `tools/effect_colors.py` exports `EFFECT_COLOR` (effect → colour
name) + `BASIC_COLOR_RGB` (colour name → RGB hex) + `FUNCTION_COLOR`
(Function name → static colour). `tools/read_pedal_status.py` runs the
full chain (read mode + pedal Functions + Assign block + FxItem TYPEs),
then prints each pedal with its derived colour.

## 5.8 GX-10 vs GX-100 model differences

The DT1/RQ1 framing, address map, MemoryFxItem/MemoryEfct/MemoryCommon
layouts, and all per-effect parameter ranges are **identical** between
GX-10 and GX-100. Only a few user-facing things differ:

| Item                          | GX-100         | GX-10          |
|-------------------------------|----------------|----------------|
| Identity Reply product flag (b10) | `0x00`     | `0x01`         |
| Front-panel footswitches      | NUM 1-4, BANK ▼, BANK ▲, CTL 1, CTL 2 | **▼, ▲, C1** (▼/▲ written as DOWN/UP; C1 = CTL 1) — no NUM pads, no front CTL 2-4 |
| External jacks                | CTL 2-4, EXP 2 | (none — only EXP 1 + EXP 1 SW) |
| User memory count             | 200 (U01-1..U50-4) | 198 (U01-1..U66-3 + 2 NIU) |
| BANK EXTENT MIN/MAX offset    | SystemCommon 0x09/0x0A | SystemCommon 0x19/0x1A |
| `MemoryLed.ON_OFF_STATE` bits | Chart `*3` table is correct | bits 5/6 unused; **DOWN = bit 18, UP = bit 19** (the GX-100 BANK ▼/▲ wire positions) |

> **GX-10 ▼/▲ ≠ GX-100 BANK ▼/▲.** The GX-10's two memory-navigation
> footswitches are silkscreened **▼** and **▲** on the device (no "BANK"
> prefix). In plain text we write these as **DOWN** (▼) and **UP** (▲).
> One press steps a single user memory (in UP/DN mode) — they are **not**
> the GX-100's **BANK ▼ / BANK ▲**, which carry the "BANK" prefix and
> step a whole bank. The GX-10's third front footswitch is labelled **C1**
> and is the **CTL 1** control. All three share the same SysEx wire
> positions as their GX-100 counterparts (Function/Mode bytes, CC# slots,
> and the `ON_OFF_STATE` LED bits below), so this repo keys the arrows
> under the GX-100/source-enum name `BANK DOWN`/`BANK UP` (see
> `tools/source_names.py`, `tools/device_profile.py`) — but a GX-10-facing
> UI should render them as **▼ / ▲** (DOWN/UP) and **C1**. The GX-10 has
> no NUM pads and no front CTL 2-4; its MIDI CC# page (PAGE 2) lists the
> sources as UP, DOWN, CTL 1, EXP 1, EXP 1 SW, plus the rear CTL 2,
> CTL 3, EXP 2.

**Detection at runtime**: `tools/detect_device.py` sends an Identity
Request and reads byte 10 (the product flag) of the reply. `tools/
device_profile.py` exports a profile dict per model with the right
bit mappings, physical-pedal sets, and memory counts. Other tools
(`read_pedal_status.py`, `watch_pedal_status.py`,
`probe_user_memory_names_burst.py`) call `detect_and_profile()` at
startup and adapt automatically — they all work on either model
without flags.

**Empirical GX-10 LED bitmap** (verified 2026-05-03 by physical
button-press → bit-toggle observation):

| bit | GX-10 hardware                          | chart for GX-100 |
|-----|-----------------------------------------|------------------|
|  7  | C1 (= CTL 1)                            | CTL 1            |
| 12  | EXP 1 SW                                | EXP 1 SW         |
| 18  | **▼ (DOWN)** (memory −1; = GX-100 BANK ▼ wire bit) | (NIU) |
| 19  | **▲ (UP)** (memory +1; = GX-100 BANK ▲ wire bit)   | (NIU) |
| 15, 20, 21, 26 | status / indicator (always set when "all LEDs on") | (NIU) |

The chart's `*3 ON_OFF_STATE_TABLE` (bit 5 = BANK ▼, bit 6 = BANK ▲)
applies to GX-100 only; on GX-10 the equivalent **▼ / ▲** (DOWN/UP)
switches live at bits 18/19 and the chart's bits 5/6 read 0 even when
the buttons are physically lit.

## 5.9 Assign-row writes — group-parameter gotcha

The chart documents the [Assign] row at `MemoryCommon` offsets
`0x000200..0x000B40` (20 entries × 0x40 stride, 0x2D used bytes per
entry). The chart says: *"From SW to MIDI BANK LSB are group parameters.
The DT1 to each parameter is temporarily suspended, and the DT1 to the
group parameter final address automatically checks the pending parameters,
and if there is no problem, the value is set. If the value is incomplete
it will not be set."*

**Empirical finding (2026-05-03):** a *single* bulk DT1 sending all 45
bytes to address `0x10000200` does **not** commit the TARGET sub-group.
SW / TARGET_FX_ITEM / TARGET / TARGET MIN / TARGET MAX get cleared to
defaults (SW=0, TARGET=0, MIN=0, MAX=0xFFFF). SOURCE / MODE / ACT RANGE /
MIDI CC fields commit fine.

**Working approach:** issue **one DT1 per chart-listed field**, ending
with the field whose final byte is `0x2C` (MIDI BANK LSB low nibble).
Verified via `tools/test_assign_concrete.py` (concrete TARGET=374) and
`tools/test_assign_onoff.py` (generic TARGET=1 EFFECT ON/OFF). The
17-DT1 sequence in `tools/demo_full_patch.py:write_assign_fields()`
is the canonical implementation.

```
DT1 0x10000200 0x01            # SW=ON
DT1 0x10000201 <fx_item>       # TARGET_FX_ITEM (chain position 0..19)
DT1 0x10000202 <4 nibbles>     # TARGET (0..740, ASSIGN TARGET TABLE index)
DT1 0x10000206 <4 nibbles>     # TARGET MIN (raw value - 0x8000 = display min)
DT1 0x1000020A <4 nibbles>     # TARGET MAX
DT1 0x1000020E <byte>          # SOURCE (0..83 enum: NUM/MAN/CTL/EXP/CC#1..31/CC#64..95)
DT1 0x1000020F <0|1>           # MODE (0=TOGGLE, 1=MOMENT)
DT1 0x10000215 <4 nibbles>     # ACT RANGE LO
DT1 0x10000219 <4 nibbles>     # ACT RANGE HI
DT1 0x1000021D <byte>          # MIDI CH (0=SYSTEM, 1..16=ch+1)
DT1 0x1000021E <byte>          # MIDI CC# (output)
DT1 0x1000021F <4 nibbles>     # MIDI CC VAL MIN
DT1 0x10000223 <4 nibbles>     # MIDI CC VAL MAX
DT1 0x10000227 0x00            # N/A fixed
DT1 0x10000228 <byte>          # MIDI PC#
DT1 0x10000229 <2 nibbles>     # MIDI BANK MSB (OFF / 1..128)
DT1 0x1000022B <2 nibbles>     # MIDI BANK LSB (FINAL — triggers group commit-check)
```

Probable cause: the device's parameter-pending pipeline keys per-DT1.
A bulk DT1 of N bytes is treated as one pending entry at the lowest
address (start of the DT1), not as N separate per-byte field-pendings.
The group-commit check finds only that one pending entry and rejects
the rest as "incomplete". Field-by-field puts each chart field in the
pending queue independently, and the commit check passes.

This rule probably applies to other "group parameter" structures too
(e.g., MEMORY MIDI 1..4 entries — also marked group params in the chart).
Worth re-checking those when writing programmatically.

**Constraints validated empirically against the chart's wording:**

- `TARGET MIN/MAX` are **offset-binary** — add `0x8000` to the displayed
  value before encoding as 4 nibbles. For ON/OFF (range 0..1):
  MIN=0x8000=`08 00 00 00`, MAX=0x8001=`08 00 00 01`.
- `TARGET=1` (generic *EFFECT(RENAMED WITH TYPE) → ON/OFF*) requires
  `TARGET_FX_ITEM` to point at a chain position holding a real effect.
  The device dynamically renames the assign category from the FxItem's
  TYPE byte. This is the ONLY ON/OFF-style row in the table.
- `SOURCE` enum **excludes CC#32..CC#63** (CC#32 is MIDI Bank-Select
  LSB; 33..63 are reserved by Roland). Use CC#1..31 (SOURCE bytes 21..51)
  or CC#64..95 (SOURCE bytes 52..83).
- The device's **on-screen assign-category label** is cached. Bytes
  written via SysEx update the underlying state but the label only
  re-renders when the user navigates into the assign settings view OR
  triggers a WRITE flow. The bytes are correct; the display lags. This
  was verified by reading bytes back (showed REVERB) while the device's
  main display still showed PARAMETRIC EQ — refreshed after a WRITE.

## 5.10 Programmatic patch construction (end-to-end)

Verified end-to-end by `tools/demo_full_patch.py`: build BOOST CLEAN +
PEQ + REV PLATE chain, configure all 4 main-display knobs, and write
Assign #1 to toggle REV ON/OFF from MIDI CC#64.

**Phase 1 — chain edit transaction:**

1. `DT1 0x00200003 = 01` — `Setup_temp.ChainEditTrigger` ON
2. For each FxItem slot k used by the new chain:
   - `DT1 0x10001100 + k*0x200 + 0x00 = <FX TYPE byte>`
     (1 byte, 0..82; see `tools/fx_type_enum.py`)
   - `DT1 0x10001100 + k*0x200 + 0x01 = 0x01` (ON)
   - `DT1 0x10001100 + k*0x200 + 0x03 = <4 nibbles>` (FX Param 1 =
     per-effect TYPE selector; `tools/per_effect_types.py`. The
     value is offset-binary: write `(value + 0x8000)` as 4 nibbles.)
3. `DT1 0x10000F0C` with 50-byte chain linked-list payload:
   - byte 0 = `top_slot + 1` (0 = no chain)
   - bytes 1..49 = `next[i] + 1` for each storage slot index i
4. `DT1 0x00200003 = 00` — ChainEditTrigger OFF

**Phase 2 — main-display knob settings:**

- `DT1 0x10000069` with 4 bytes: `KnobN SettingFxItem` (0..19, chain
  position) for each of the 4 knobs.
- `DT1 0x1000006D` with 16 bytes: `KnobN SETTING` (4 nibbles each =
  ASSIGN TARGET TABLE index 0..740).

The 4-byte and 16-byte writes work as bulk DT1s here (different address
space from the [Assign] group). Group-param treatment seems specific
to the [Assign] row.

**Phase 3 — assign-row write:**

Field-by-field as documented in §5.9 above.

**Reversibility:** writes target memory_temp at `0x10000000+`. Pressing
any patch button on the device discards the live edit buffer and
restores the saved patch.

**On-device WRITE button** copies memory_temp into the target user
memory slot at `0x20000000 + memory_n × 0x60000` (chart-stride 7-bit
arithmetic). This is also when the on-screen assign-category cache
re-renders.



- **Host → device sniffing**: a WinMM input-port sniffer can only see what
  the device sends back. Tone Studio's outgoing RQ1/DT1 traffic isn't
  visible there. We capture it two ways:
  - **Active probe** (`address_scan.py`) — we *become* the host and issue
    our own RQ1, so the device's reply tells us everything we need; no
    need to see Tone Studio's RQ1 directly.
  - **USBPcap + Wireshark** — captures at the USB layer and decodes both
    directions via the `usbaudio` dissector. **Important caveats observed
    on this machine**:
    - One-time admin install of USBPcap. The kernel filter binds itself as
      a class upper-filter on the USB device class; *a reboot is required*
      after install before the filter actually attaches to the running
      USB host controllers.
    - Always pass `--inject-descriptors` to `USBPcapCMD`. Without it, the
      capture starts mid-stream, Wireshark sees only raw `URB_BULK`
      transfers, and the `usbaudio` / `sysex` dissectors don't run.
    - USBPcap 1.5.4 (the current stable on Windows) doesn't ship as a
      Wireshark extcap, so `dumpcap -D` / `tshark -D` won't list
      `USBPcap1`/etc. Capture from CLI and read the resulting `.pcap` in
      Wireshark or via `tools/pcap_to_jsonl.py`.

- **DT1 writes from us**: we never *write* anything to the device in this
  workflow — only read. Writing patches (e.g. uploading a captured patch to
  a different slot, or modifying parameters) is structurally trivial via
  `midi_send.build_dt1(addr, payload)`, but is intentionally avoided here
  because it modifies device state.

- **IR loader / TONE EXCHANGE / Tuner**: these Tone Studio features each
  have their own protocol regions we have not yet exercised. The IR loader
  in particular is likely a chunked binary upload at a yet-unmapped address.

- **Per-parameter address map within a patch**: the 16 KiB-ish layout of
  `0x10000000+` (effect type per slot, knob values, on/off bits, routing
  matrix, etc.) is observed but not yet fully decoded. The effective way
  forward is to (a) probe single byte ranges with `address_scan.py custom`,
  (b) use `drive_tone_studio.py` to make the user click the on/off icon /
  drag a known knob, and (c) diff the patch dump before vs after.

---

## 5.11 MIDI Control Change & Program Change — transmit vs receive

Source: Roland's official **GX-100 MIDI Implementation** (ver1.10,
March 3rd 2022) — `static.roland.com/assets/media/pdf/GX-100_MIDI_Implementation.pdf`.
The doc is GX-100-titled but the message handling is shared with the
GX-10 (the combined Implementation Chart is byte-identical between
models bar the version strings). This resolves the **"MIDI IN reception"**
gap that `gaps.md` flagged as untested.

**Direction of the per-controller CC# fields (`SystemMidi 0x08–0x14`).**
These are **transmit-only**. Under *§2 Transmitted data → Control Change*:

> "When you operate a controller, the CC# specified by
> `MENU:MIDI:MIDI SETTING:NUM1 CC# - EXP2 CC#` is transmitted."

i.e. pressing a physical controller (NUM, BANK ▼/▲, CTL, EXP…) makes the
device **send** that controller's configured CC#. The same fields do
**not** appear anywhere in *§1 Recognized data* — sending a CC equal to,
say, `BANK▼ CC#` back into the device does **nothing** by itself.

**How the device acts on a *received* Control Change.** Only via the
Assign engine. *§1 Recognized data → Control Change*:

> "Recognized if the `MENU:ASSIGN SETTING:SOURCE` setting is
> CC#1 - #31 or CC#64 - #95."

So an inbound CC drives a target parameter **iff** some Assign has that
CC# as its SOURCE (target value computed from the assign's ACT LOW/HIGH
range). There is no native "received CC → footswitch/bank/CTL action"
path outside Assigns. This matches our catalogue: `SourceController`
already enumerates `CC#1–31 / 64–95` as assign sources.

**Memory / bank changes over MIDI = Program Change (+ Bank Select).**
*§1 Recognized data → Program Change*:

> "This message switches to the memory that is specified by
> `MENU:MIDI:PROGRAM MAP`."

Bank Select (CC 0 MSB / CC 32 LSB) is recognised and latches the bank
for the next PC. **Bank/patch navigation is not a Control Change** — a
remote controller steps memories with PC, or a host writes the
patch-select register directly (§3.2).

**Implication for editor/companion apps.** To make an on-screen pedal
take effect on the device:
- **Memory nav (UP/DOWN/BANK)** → write the patch-select register (§3.2)
  or send Program Change; CC is the wrong tool.
- **Arbitrary CTL/EXP action** → send a CC that the user has configured
  as an Assign SOURCE (the user picks/owns that CC#, so it can avoid
  conflicts). The controller's own transmit-CC# is not a back-channel.

(BTS confirms the negative case: in `captures/bts_button_dead.jsonl`,
clicking BTS's on-screen buttons sends **zero** host→device bytes.)

---

## 7. License / use

Personal reverse-engineering against owned hardware, for interoperability
and educational documentation. No redistribution of Roland firmware data;
only protocol observations.
