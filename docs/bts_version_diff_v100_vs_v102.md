# BTS-for-Mac v1.0.0 vs v1.0.2 — source diff

Captured by `diff -r` between the two expanded `.pkg`s on 2026-05-14.
Both bundles are universal Apple-Silicon / Intel binaries; both target
macOS Ventura/Sonoma/Sequoia. v1.0.2 = build 52, v1.0.0 = build 43.

The motivation for this diff was the firmware-version-gate finding
([[../docs/firmware_versions.md]]): v1.0.2 hard-codes
`communicationLevel = 4` and refuses to connect to a level-3 device,
while v1.0.0 hard-codes `3` and connects. The question this diff
answers: *what does Roland change at the wire when they bump the
communication level?*

## Headline result

**Nothing on the wire.** The protocol surface is byte-identical
between v1.0.0 and v1.0.2:

| File | Bytes-identical? |
|------|------------------|
| `businesslogic/address_const.js`      | ✅ |
| `config/address_map.js`               | ✅ |
| `config/librarian_setting.js`         | ✅ |
| `config/effect_parameter.js`          | ✅ |
| `config/editor_setting.js`            | ✅ |
| `config/memory_data.js`               | ✅ |
| `businesslogic/midi_connect_controller.js` | ✅ |

No new SysEx addresses, no new effects, no new patch-memory layout, no
new handshake steps, no new editor-setting blocks. The `communicationLevel`
threshold (3 → 4) is the only protocol-adjacent change in
`midi_connect_controller.js`'s call site — and that constant lives in
`product_setting.js`, which DID change but **only at the version /
build / level fields**.

## Substantive changes in v1.0.2 — UI controllers + bug fixes

Six small behavioural deltas, all in JS controllers; no firmware-side
protocol shifts inferred.

### 1. USB MIDI THRU + chain-edit workaround `chain_controller.js`

```diff
+      if( globalIsChainEditing === isEditing ) {
+        return;  // A workaround for the problem of the DELETE or OVERWRITE
+                 // function when the "USB IN THRU" of the device is set
+                 // to "USB OUT" or "USB & MIDI"
+      }
```

A second early-return guard inside `sendChainEditTrigger`. The
existing BG777BTS-181 guard at line 4208 was insufficient: when the
device's `MIDI IN THRU` setting (`0x0000_3004`) routes USB IN back to
USB OUT, BTS's own DT1 writes come back as DT1 receives, racing the
`globalIsChainEditing` flag and corrupting the DELETE / OVERWRITE
flow. v1.0.2 adds a more aggressive idempotence check.

**Cross-link**: this is Roland's own confirmation of the loopback
mechanism. The host→device echo observed during the BTS-v1.0.0
handshake capture is the same phenomenon — caused by the device's
`USB IN THRU` setting (chart-documented at `0x0000_3004`) being on.
See `protocol.md` §2.0.1 and `bts_mac_chain_button_bug.md` for the
full analysis.

### 2. TOTAL_USER_PATCH count adjustment `patch_controller.js`

```diff
       return TOTAL_USER_PATCH;
+      /* 単純にTOTAL_USER_PATCHを変更してしまうと、各所のUSER/PRESETの
+         通し番での処理で整合がつかなくなったためここのみ対処 */
+      return TOTAL_USER_PATCH - 2;
```

`TOTAL_USER_PATCH` itself is unchanged (`200` in both versions), but
v1.0.2's accessor returns **198** instead. The Japanese comment says
"simply changing TOTAL_USER_PATCH would break sequential USER/PRESET
numbering elsewhere, so we handle it here only" — i.e. v1.0.2 quietly
treats the device as having 198 user-patch slots, not 200, while
keeping the 200 constant elsewhere to avoid breaking other code paths.

**This is a GX-100 correction, not a GX-10 one.** Per
`firmware_versions.md` "Per-device patch totals":

- **GX-100**: 50 user banks × 4 = 200 user slots in the address
  space at `0x2000_0000 + N × 0x60000`; v1.0.2 reserves the last 2
  → 198 usable.
- **GX-10**: 66 user banks × 3 = 198 user slots (and 33 preset
  banks × 3 = 99 preset). Unchanged across firmwares; 3 NIU slots
  at raw 198, 199, 299 are documented in Roland's MIDI chart and
  apply to every GX-10 firmware.

The arithmetic coincidence that both products end up at "198 user
patches" with BTS v1.0.2's adjustment is just that — a coincidence
of `66 × 3 = 50 × 4 - 2`. The bank decompositions are different.

**Implication for tooling**: bound user-memory iteration at 200 in
the GX-100 + fw < 1.05 case, 198 in the GX-100 + fw ≥ 1.05 case, and
**198 on the GX-10** (regardless of firmware). The address layout
at `0x2000_0000 + N × 0x60000` is the same in both products.

### 3. PREAMP / BASS PREAMP equality fix `assign_page_controller.js`, `item/item_logic.js`

```diff
-            if(categoryStr == "PREAMP") {
+            if(categoryStr.includes("PREAMP")) {
```

Same one-line fix applied in two places. The assign-target category
string can be `"PREAMP"` or `"BASS PREAMP"`; the v1.0.0 strict
equality missed the BASS variant. v1.0.2 uses `.includes()` so both
match the PREAMP branch.

Affects only the BTS UI's assign-target dropdown; no protocol impact.

### 4. POLY tuner mode UI removed `bts_controller.js`, `tuner_controller.js`

v1.0.0 rendered three tuner-mode radio buttons (MONO / POLY / TT) at
33.33% width each; v1.0.2 renders two (MONO / TT) at 50%. POLY mode
is **deleted from the BTS UI**.

```diff
-      +'<label … tuner-mode-btn-0 …; width: 33.33%; …">MONO</label>'
-      +'<input type="radio" id="tuner-mode-btn-1" name="tuner-mode-btn" value="1">'
-      +'<label … tuner-mode-btn-1 …; width: 33.33%; …">POLY</label>'
+      +'<label … tuner-mode-btn-0 …; width: 50%; …">MONO</label>'
```

The tuner_controller.js change picks the POLY label by text-matching
and disables it — defensive code for any DOM that still has the POLY
button. Suggests Roland decided POLY-mode editing from BTS was buggy
on the level-3 firmware and removed it as a stopgap rather than
fixing the underlying issue.

POLY mode itself is still functional on the device (POLY tuner
type/offset state is exposed at `0x0000_6004..6005` per
`docs/protocol.md` §2). Only the BTS UI for it disappeared.

### 5. clearBtx refactor `error_dialog.js`, `util.js`

```diff
-  util.clearBtx();
+  window.btxCommands.updateBTXViewVisible()
```

`util.clearBtx()` removed from `util.js` and its behaviour migrated to
the `btxCommands` module. Pure refactor, no protocol or UX impact.

### 6. Assign target TYPE-list helper `item/select_list_controller.js`

```diff
+  function getValueFromListIndex(index) {
+    let categoryStr = $('#assign-target-category-select-list').find('p').text();
+    let targetStr = $('#assign-target-select-list').find('p').text();
+    let result = index;
+    if(targetStr === 'TYPE') {
+      …  // special-case TYPE-target value handling
+    }
+  }
```

New helper that maps select-list indices to assign-target values when
the target is a TYPE selector. UI/UX improvement for the assign-target
dropdown when the user picks an effect's `TYPE` field. No protocol
impact.

## Side observations (not behavioural)

- v1.0.0 ships `bg709-pc.elf` AND `bg846-pc.elf`. v1.0.2 ships only
  `bg846-pc.elf`. `bg709` is the GX-100; v1.0.2 dropped the GX-100
  helper image. (The same .pkg is built per-product, so a GX-10 BTS
  shipping GX-100 firmware appears to be an oversight in v1.0.0
  rather than a removed feature.)
- Several `*_v3.*` files in v1.0.0 (`bts-librarian-btn_v3.css`,
  `item_v3.json`, `layout_v3.div`) are replaced by `*_v2_bk.*` in
  v1.0.2 (e.g. `bts-librarian-btn_v2_bk.css`). Roland appears to have
  attempted a "v3" UI iteration in v1.0.0, then reverted to a "v2
  backup" UI in v1.0.2 (the `_bk` suffix is suggestive). Cosmetic;
  doesn't touch the protocol.
- `terms_of_use/app_terms_of_use.txt` differs. Boilerplate.
- `license.div` differs. Boilerplate.
- Default `index.html` and `export.html` differ — UI shell tweaks.

## Conclusion

The communication-level 3 → 4 bump is **not** a protocol-feature gate.
It's a **safety bump**: Roland identified four small bugs in the
v1.0.0 BTS that misbehave when paired with the launch-family firmware
(USB-THRU chain-edit, off-by-2 patch count, BASS PREAMP category
mismatch, POLY tuner UI) and locked v1.0.2 to only run against
firmware 1.05+ to ensure the matching fixes are present on both
sides. There are no new SysEx addresses, no new editor blocks, no new
effects, and no new patch-memory layout introduced at level 4.

This means **on a level-3 GX-10, running BTS v1.0.0 gives the full
feature set** with the four known caveats:

1. ⚠ If the device's `MIDI IN THRU` (`0x0000_3004`) is set to
   `USB OUT` or `USB & MIDI`, chain-edit DELETE/OVERWRITE will
   misbehave because of the resulting USB loopback echo. Workaround:
   keep THRU = OFF. (Same effect on Windows; BTS v1.0.2 ships a JS
   guard for this scenario.)
2. ⚠ The BTS v1.0.2 `TOTAL_USER_PATCH - 2` change is a GX-100
   correction (50 banks × 4 = 200 slots, with 2 reserved → 198
   usable). It does not affect the GX-10's own user-patch count of
   132 — see `firmware_versions.md` for per-device totals.
3. ⚠ Assign-target dropdown won't match `"BASS PREAMP"` when looking
   for `"PREAMP"`. Cosmetic only.
4. ⚠ BTS v1.0.0's POLY tuner UI is present and works against the
   level-3 firmware; Roland removed it in v1.0.2 but the underlying
   protocol still functions either way.

Practical implication for this repo: **none of the protocol RE work
is invalidated by firmware 1.05**, since the address surface is
unchanged. The tooling already supports both firmware families.
