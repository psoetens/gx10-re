# BTS-on-Mac "LIVESET" / set list storage

Reverse engineering of how BOSS TONE STUDIO for macOS stores user
set lists (Roland calls them "LIVESETs"). The TL;DR: set lists are
client-side JSON nested inside BTS's preferences `.plist`. Each
liveset holds a full, self-contained snapshot of every patch's
device-block bytes — i.e. exactly what would be read with bulk RQ1s
from the device's user-memory slot. No proprietary binary format, no
external `.btx` files (despite the existence of a `.btx` import path
in BTS for cross-device library exchange).

Verified 2026-05-14 against BTS-for-Mac v1.0.0 with the user's two
live livesets ("LIVESET 1" and "Mac Test").

## On-disk location

```
~/Library/Preferences/jp.co.roland.BOSS-TONE-STUDIO-for-GX-10.plist
```

Standard binary plist, owned by the user, bundle-id keyed (shared
across BTS v1.0.0 and v1.0.2 — installing/uninstalling either does
not touch user data).

## Top-level plist layout

```python
{
    "pref":                <BTS general prefs JSON string, ~382 chars>,
    "NSWindow Frame mainWindow": "...",          # macOS window state
    "CONFIRM_FLAG":        "0/1",                # internal flag
    "NSNavPanelExpandedSizeForOpenMode": "...",  # macOS file-dialog state
    "ID_LIST":             '{"list":[1,0]}',     # liveset display ordering
    "0":                   <JSON-string of liveset #0>,
    "1":                   <JSON-string of liveset #1>,
    ...                                          # numeric string keys per liveset
    "NSOSPLastRootDirectory": <bytes>,           # macOS file-dialog state
}
```

- Each **liveset slot** is keyed by a numeric string (`"0"`, `"1"`,
  …) and the value is a **doubly-JSON-encoded** string (the plist
  string contains a JSON string which itself contains a JSON object —
  Roland appears to round-trip through `JSON.stringify` twice).
- `ID_LIST` is a JSON string `{"list":[1,0]}` whose `list` array gives
  the display order. The user's BTS shows liveset 1 first, then liveset
  0 — newest-first ordering.

## Liveset object shape

After double-decoding the plist string value:

```python
{
    "name":      "Mac Test",       # user-typed liveset name
    "formatRev": "0000",            # liveset format version
    "device":    "GX-10",           # target device family
    "data": [                       # 2-D array: outer = banks, inner = patches
        [                           # bank 0
            { "memo": "", "paramSet": {…patch 0 dump…} },
            { "memo": "", "paramSet": {…patch 1 dump…} },
            { "memo": "", "paramSet": {…patch 2 dump…} },
        ],
        # potentially more banks
    ],
}
```

- The "BTS RE" set list (`"0"`) has `data = [[…1 patch…]]`.
- The "Mac Test" set list (`"1"`) has `data = [[…3 patches…]]`.
- Both observed sets use a single outer bank. The schema permits more.
- `memo` is a per-patch free-text note (empty by default).

## paramSet block layout

Every entry under `data[bank][patch].paramSet` is a list of **hex
byte strings** (e.g. `["42", "54", "53", " ", "52", "45", …]`). Each
list mirrors a chart-documented `[User_patch]` block byte-for-byte:

| paramSet key | Size | Maps to chart block (under `User_patch`) |
|--------------|------|------------------------------------------|
| `User_patch%common`     | 129 bytes | `MemoryCommon` (`0x10000000` in live edit buffer). First 16 bytes = ASCII patch name. |
| `User_patch%led`        | 28 bytes  | LED color settings |
| `User_patch%assign(N)`  | 45 bytes  | `[Assign]` table N for N=1..20 (matches chart's `0x2D` per-assign stride) |
| `User_patch%efct`       | 62 bytes  | `MemoryEfct` (`0x10000F00`+, the chain block, 0x3E bytes per chart §3.3) |
| `User_patch%fxItem(N)`  | 179 bytes | `MemoryFxItem` slot N for N=1..20 (the per-effect block) |

Total per patch: 129 + 28 + (20 × 45) + 62 + (20 × 179) = **4699 bytes**
of raw block data, plus the JSON wrapping. A 3-patch set list ends up
~100 KB of plist after double-JSON encoding (the user's "Mac Test"
liveset is 102,361 chars in `defaults read` output).

## Implications for protocol work

- **Set lists do not need any new SysEx address.** They're built
  entirely from chart-documented blocks. A homemade "send liveset to
  device" tool would simply: for each patch in the array, issue DT1
  writes to `0x10000000` (memory_temp) + WRITE-commit at `0x7F000104`
  to a target user-memory slot. Or DT1 directly to the user-memory
  region at `0x20000000 + N*0x60000`. We've verified both flows in
  the existing protocol RE.
- **Set lists carry across BTS versions.** Bundle ID `jp.co.roland.BOSS-TONE-STUDIO-for-GX-10`
  is identical between v1.0.0 and v1.0.2 (we verified this during the
  Mac install swap). The plist file is reused unchanged.
- **Cross-platform interchange.** The Windows BTS uses the same JSON
  schema (BTS is the same Electron app); the Windows preferences are
  stored under HKEY_CURRENT_USER\Software\BOSS\BOSS TONE STUDIO for
  GX-10 rather than a .plist, but the JSON payload should be identical.
  Mac ↔ Windows liveset exchange is therefore a copy job between
  the OS-native settings stores, not a format conversion.
- **External `.btx` export is a separate path.** BTS also supports
  exporting individual patches as `.btx` files for sharing on Tone
  Exchange. That format is not analyzed here; it's likely a thin
  JSON wrapper around the same `paramSet` blocks (`export/item.json`
  and `export/layout.div` in the BTS bundle hint at this).

## Liveset ↔ device transfer protocol

The on-disk plist is the storage; the transfer to/from the GX-10 is
plain DT1/RQ1 traffic over the chart-documented user-memory region at
`0x20000000 + N * 0x60000`. No new SysEx commands, no new addresses
beyond what we already had documented.

Captured live 2026-05-14 with BTS-for-Mac v1.0.0 against this unit;
JSONL traces at `captures/bts_liveset_load.jsonl` (push) and
`captures/bts_liveset_download.jsonl` (download).

### Push: liveset → device (write direction)

When the user clicks "Send liveset to device" in BTS, the editor walks
each patch in the liveset's `data[bank][patch]` array and writes its
`paramSet` blocks to the corresponding user-memory slot. The slot
index increments per patch starting at slot 0. **The user's existing
patches at the target slots are overwritten.**

For each patch (slot `S`), **64 DT1 writes** are issued to
`0x20000000 + S * 0x60000 + offset`, ~30 ms apart, ~2 seconds total
per patch. The chunk layout matches the plist `paramSet` keys
one-for-one:

| Offset within slot | Size | Block (paramSet key)             |
|--------------------|------|----------------------------------|
| `0x00000`          | 128B | `User_patch%common` (first 128 of 129 bytes — first 16 are the patch name) |
| `0x00100`          | 1B   | `User_patch%common` (last byte) |
| `0x00140`          | 28B  | `User_patch%led` |
| `0x00200, 0x00240` | 45B each | `User_patch%assign(1)`, `(2)` |
| `0x00300, 0x00340` | 45B each | `User_patch%assign(3)`, `(4)` |
| …                  | 45B  | continues for 20 assigns at stride pair `(0x100, 0x140)` |
| `0x00B00, 0x00B40` | 45B each | `User_patch%assign(19)`, `(20)` |
| `0x00F00`          | 62B  | `User_patch%efct` (chain block) |
| `0x01000, 0x01003` | (48B + 131B) | `User_patch%fxItem(1)` — split |
| `0x01100, 0x01103` | (48B + 131B) | `User_patch%fxItem(2)` — split |
| …                  |      | continues for 20 FxItems |
| `0x03700, 0x03803` | (48B + 131B) | `User_patch%fxItem(19)`, `(20)` |

**Total payload per patch:** exactly **4699 bytes** — matches the sum
of `paramSet` block sizes byte-for-byte. The single-byte write at
`0x00100` is the 129th byte of the common block, separated from the
preceding 128-byte chunk to keep address arithmetic on `0x100`-aligned
boundaries (the 7-bit address byte rule, see `protocol.md` §3.1.1).

After all slots are written, BTS re-reads the `0x50000000` preset name
catalogue (38 × `RQ1 size=0x100`, each returning a 128-byte DT1) to
refresh its UI patch list. **No WRITE-commit trigger** (`0x7F000104`)
is sent — the user-memory region appears to be flash-backed and
written-through directly.

### Download: device → liveset (read direction)

When the user picks "Download to liveset" in BTS, the editor issues
**64 RQ1 reads** against `0x20000000 + S * 0x60000 + offset` for the
chosen slot `S`. Read takes ~2 seconds.

Per `protocol.md` §3.1.2, the **size field in each RQ1 is a request
ceiling, not the response length** — the device replies with one DT1
per natural record at the addresses inside the requested range.
Below, "request size" is what BTS sends; "response" is what the device
returns:

| Offset within slot | BTS req size | Response | Block            |
|--------------------|--------------|----------|------------------|
| `0x00000`          | `0x100` (256B)  | 128 B   | `User_patch%common` head |
| `0x00100`          | `0x01` (1B)     | 1 B     | misc byte (the 129th; BTS reads it explicitly even though a larger common read would cover it) |
| `0x00140`          | `0x1C` (28B)    | 28 B    | `User_patch%led` |
| `0x00200..0x00B40` | `0x2D` (45B) × 20 | 45 B each | `User_patch%assign(1)..(20)` |
| `0x00F00`          | `0x3E` (62B)    | 62 B    | `User_patch%efct` |
| Per FxItem (×20)   | `0x103`+`0x30` (259B+48B) | 131 B + 48 B | `User_patch%fxItem(N)` |

BTS sizes the RQ1s to overshoot each natural record. A single
`RQ1 size=0x4000` against the slot base reads the same data as one
round-trip — empirical 11.9× speedup; see
`reports/merge_read_findings.md`.

Captured against slot 5 (`0x201E0000`) on 2026-05-14 while pulling
the user's "BTS RE" patch into a liveset entry. BTS then JSON-encodes
the returned bytes into the `paramSet` lists and writes the result
back to the plist.

### What's NOT in the wire flow

- The liveset **name** (e.g. "Mac Test") and **memo** fields are
  client-side only — they never traverse MIDI. The device knows the
  16-byte per-patch name (it's the first 16 bytes of the common
  block); but the liveset's own name, ordering, and any per-patch
  user notes live exclusively in the plist.
- `ID_LIST` display ordering is plist-only.
- "Switch active liveset in BTS UI" does not produce any MIDI traffic
  — we verified this by clicking a liveset in the librarian view
  with the sniffer running (window 0 of the push capture shows no
  device-bound writes until the explicit "Send to device" action).

### Replicating either flow without BTS

Either direction is reproducible with the existing tooling. To push a
liveset's first patch from a parsed plist to user slot N:

```python
from example_lib import GX10Session
SLOT_BASE = 0x20000000 + N * 0x60000
sess = GX10Session()

# walk the (offset, paramSet-key) table above
WRITE_PLAN = [
    (0x00000, "User_patch%common",   slice(0, 128)),
    (0x00100, "User_patch%common",   slice(128, 129)),
    (0x00140, "User_patch%led",      None),
    *[(0x00200 + (i // 2) * 0x100 + (i % 2) * 0x40,
       f"User_patch%assign({i+1})", None) for i in range(20)],
    (0x00F00, "User_patch%efct",     None),
    # FxItems split (offset_a, 48 bytes), (offset_b, 131 bytes)
    *[(0x01000 + i * 0x100,    f"User_patch%fxItem({i+1})", slice(0, 48))   for i in range(20)],
    *[(0x01003 + i * 0x100,    f"User_patch%fxItem({i+1})", slice(48, 179)) for i in range(20)],
]
for offset, key, sl in WRITE_PLAN:
    bytes_list = patch["paramSet"][key]
    payload = bytes(int(h, 16) for h in (bytes_list[sl] if sl else bytes_list))
    sess.write(SLOT_BASE + offset, payload)
```

Reverse for the read direction.

```python
import json, plistlib
from pathlib import Path

PLIST = Path.home() / "Library/Preferences/jp.co.roland.BOSS-TONE-STUDIO-for-GX-10.plist"
pl = plistlib.load(PLIST.open("rb"))
for key, val in pl.items():
    if not key.isdigit(): continue
    obj = json.loads(json.loads(val))     # outer string, inner JSON object
    print(f"liveset[{key}] = {obj['name']!r}  device={obj['device']!r}")
    for bi, bank in enumerate(obj["data"]):
        for pi, patch in enumerate(bank):
            name_bytes = bytes(int(h, 16) for h in
                               patch["paramSet"]["User_patch%common"][:16])
            print(f"  [{bi},{pi}]  {name_bytes.decode('ascii').rstrip()!r}"
                  f"  memo={patch['memo']!r}")
```

Run against this unit produces:

```
liveset[0] = 'LIVESET 1'  device='GX-10'
  [0,0]  'BTS RE'  memo=''
liveset[1] = 'Mac Test'  device='GX-10'
  [0,0]  'NATURAL AMP HB'  memo=''
  [0,1]  'HEAVY METAL'  memo=''
  [0,2]  'SUPREME AMP HB'  memo=''
```
