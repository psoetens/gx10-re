# BTS-on-Mac chain-button bug (DELETE / INSERT / OVERWRITE)

**Status:** investigation paused 2026-05-15. Diagnosis solid; full fix
deferred. Device is confirmed sane — the bug is entirely client-side
in BTS, triggered by a device-side setting the user can change.

## Symptom

In BTS-for-Mac (v1.0.0 verified, v1.0.2 inferred), the chain-bar
**INSERT / DELETE / OVERWRITE** buttons depress visually when clicked
(CSS `:active`) but do not perform their action. Drag-and-drop on the
chain still works. The device's chain remains unchanged. No
ChainEditTrigger byte gets stuck on the device — `0x00200003` reads as
`0x00` after the misfire.

## Trigger condition — device-side `USB IN THRU` setting

**This is not a driver issue.** The macOS, Windows, and Linux MIDI
stacks all behave correctly. The loopback that causes the bug is
performed by the **GX-10 itself**: when the device's MENU →
MIDI SETTINGS → **USB IN THRU** is set to `USB OUT` (or `USB & MIDI`),
the device routes every SysEx it receives on USB MIDI IN back out on
USB MIDI OUT. Any tool talking to the device sees its own outgoing
DT1/RQ1 traffic returned as incoming.

With `USB IN THRU = OFF` (and presumably `MIDI` — DIN-only), the
device does **not** echo, and the buttons work normally. Confirmed
empirically 2026-05-15 by toggling the device's USB IN THRU off:
INSERT/DELETE/OVERWRITE then function without any patching of BTS.

The BTS v1.0.2 source comment cites the same trigger condition for the
guard added to `chain_controller.js:4221-4223`:

> *"A workaround for the problem of the DELETE or OVERWRITE function
> when the USB IN THRU of the device is set to USB OUT or USB & MIDI."*

Roland clearly knew about the issue but their guard is incomplete
(see "Why BTS fails anyway" below).

## Implications for other tooling

Any host program that talks to the GX-10 over USB MIDI must be
loopback-aware: outgoing SysEx may return as incoming within
single-digit milliseconds. Patterns that break under the loopback:

- **Receive-driven UI state**: like BTS's `receiveChainEditTrigger`
  flipping UI state on every echoed write.
- **Naive RQ1 round-trip**: an RQ1 sent on USB IN gets echoed back as
  the same RQ1 on USB OUT (not a DT1 reply), so a reader matching on
  address alone will misinterpret it as a reply. Reply parsers must
  filter on `<cmd> = 0x12` (DT1) and not just `0x11`-or-`0x12`.
- **Address-based observers**: any observer that sees DT1 traffic and
  reacts (e.g. "device sent us a new chain state, so re-render") will
  fire twice — once for the host write, once for the real device
  reply.
- **Tools in this repo**: `midi_send.py`, `midi_sniff.py`,
  `example_lib.GX10Session.request()` all work correctly because
  `request()` filters DT1 replies by address match, and DT1 echoes of
  our own writes don't collide with replies to a different RQ1.
  But any new tool that subscribes to incoming streams should
  explicitly suppress echoes of recently-sent traffic (the
  `_gx10re_lastSent` pattern in the BTS patch, or filtering on
  address + opcode against a recently-sent buffer).

The chart-documented `MIDI IN THRU` byte at `0x0000_3004` controls
this setting (see `docs/midi_settings.md` for the field map and the
`tools/midi_settings.py` CLI for read/write access).

## Note on the earlier "driver-level" hypothesis

A 2026-05-14 sweep of the `0x0000_3004` register saw echoes persisting
at all four values 0..3, which initially looked like a host-driver
effect. Re-investigation 2026-05-15 found that **the DT1 writes
didn't take effect** — the device appears to require either a power
cycle or a different write sequence to change this setting, so the
original test was observing stale device behaviour. The static state
on the test unit at that time was indeed `USB IN THRU = USB OUT`,
which is why the loopback appeared unconditional.

## Root cause (the BTS-side reaction to the echo)

When BTS's mousedown handler on a chain-edit button writes
`DT1 0x00200003 = 0x01` to start an edit transaction, that DT1 is
echoed by the device within a few ms. BTS's
`midi_observe_controller.js:402-410` routes the incoming DT1 to
`chainMIDIController.receiveChainEditTrigger(true)`. That function
then **disables the INSERT/DELETE/OVERWRITE buttons** at lines
4226-4232:

```js
btsDOMController.enableBtn('delete-btn', false);
btsDOMController.enableBtn('overwrite-btn', false);
btsDOMController.enableBtn('insert-btn', false);
```

Because the buttons get disabled while the user is still holding the
mouse down, the subsequent `mouseup` and `click` events go to the
*window* rather than the button. The button's `click` handler at
`chain_controller.js:1939-1953` (which actually calls
`chainModelController.delete/.addAfter/.overwrite`) **never fires**.
The window-level `mouseup` handler still runs:

```js
window.addEventListener('mouseup', function(){
  if (isMouseDownOnButton) chainMIDIController.sendChainEditTrigger(false);
  isMouseDownOnButton = false;
});
```

It writes `DT1 0x00200003 = 0x00`, re-enabling the buttons via the
same echo path, so visually nothing looks stuck — but the action
itself was lost.

### Event trace captured (one DELETE click)

```
pointerdown delete-btn
mousedown delete-btn
sendChainEditTrigger(true)  globalIsChainEditing=false
RECV ChainEditTrigger=true                ← loopback echo
                                          ← buttons get disabled here
                                          ← no pointerup / mouseup / click
                                            ever delivered to the button
sendChainEditTrigger(false)               ← from window.mouseup
RECV ChainEditTrigger=false               ← loopback echo
```

## Workaround that worked for DELETE

A 6-line JS patch suppresses the loopback echo by tracking what BTS
just sent and ignoring matching incoming DT1s within a 200 ms window.
With this patch applied via an injected `<script>` into the BTS
bundle's `Contents/Resources/html/index.html`, DELETE works
end-to-end on macOS — the click handler fires, `chainModelController.delete`
runs, the chain bytes are written to the device, and the effect is
removed from the chain.

The suppression hook:

```js
window._gx10re_lastSent = {value: null, t: 0};
// wrap chainMIDIController.sendChainEditTrigger to record:
//   _gx10re_lastSent = {value: !!isEditing, t: performance.now()};
// wrap chainMIDIController.receiveChainEditTrigger so it returns early
// when last.value === !!isEditing && now - last.t < 200ms.
```

This is the same idea as the BTS v1.0.2 BG777BTS-309 guard, just
unconditional (not gated on USB-IN-THRU setting).

## Open issue — OVERWRITE remains stuck

With the echo-suppression patch in place, **DELETE works** but
**OVERWRITE still leaves `globalIsChainEditing = true` stuck**.

OVERWRITE is a two-phase async operation
(`chain_controller.js:888-918`):

1. Sets `window.globalChainOverwritingInfo = {deletedIndex, insertIndex, insertType}`
2. Calls `chainModelController.delete(index, false, true /* doNotRedraw */)`
3. Returns. The flag stays `true`.
4. The completion path lives in `midi_observe_controller.js:389-396`:
   when an incoming DT1 arrives at `bid === FX_SELECTABLE` (the
   FxItemResource map at `0x0020_0040`), if `globalChainOverwritingInfo`
   is set, BTS calls `chainModelController.addAfter(...)`. `addAfter`
   eventually clears the flag with `sendChainEditTrigger(false)`.

The 2026-05-14 test left the flag stuck after an OVERWRITE click —
meaning step 4 never fired. Likely causes (untested):

- The device's `FX_SELECTABLE` DT1 update is being mis-routed when
  `USB IN THRU` echo is active (BTS sees its own outgoing read-back
  rather than the device's authoritative confirm).
- The first-half delete inside OVERWRITE has the `doNotRedraw=true`
  path which omits the explicit `sendChainEditTrigger(false)` that
  the plain delete uses.
- Some part of the observer code's `FX_SELECTABLE` decoding is
  loopback-sensitive in a way the plain `FX_SETUP_TEMP` path isn't.

The deletion half **did** happen (effect was removed from the chain
on device) but the insert half did not — leaving BTS UI showing a
hole and the trigger flag stuck `true`.

### What would resolve OVERWRITE

Either of:

1. **Patch the observer** to call `addAfter` from a slightly different
   trigger, or to ignore loopback echoes of host-originated FX
   ranges the same way we patched ChainEditTrigger.
2. **Wrap `addAfter`** to detect the pending `globalChainOverwritingInfo`
   and run after a short timer if the observer fails to fire.
3. **Replace OVERWRITE in BTS UI** with explicit delete-then-insert
   that calls our own end-of-flow flag clear.

The reset button in the diagnostic overlay (`window.globalIsChainEditing = false;
chainMIDIController.receiveChainEditTrigger(false);`) is a manual
escape hatch but doesn't restore the chain's insert-half. The user
must drag the desired effect into the empty slot to recover, then
re-click reset if the flag is still stuck.

## Files referenced

| File | Role |
|------|------|
| `chain_controller.js:15` | `window.globalIsChainEditing` init |
| `chain_controller.js:20` | `window.globalChainOverwritingInfo` init |
| `chain_controller.js:1923-1954` | INSERT/DELETE/OVERWRITE button event handlers |
| `chain_controller.js:4208` | `sendChainEditTrigger` (BG777BTS-181 guard) |
| `chain_controller.js:4220` | `receiveChainEditTrigger` (the function that disables the buttons) |
| `chain_controller.js:888-918` | `overwrite` — async two-phase logic |
| `chain_controller.js:981-1162` | `delete` |
| `midi_observe_controller.js:389-396` | OVERWRITE completion callback (`FX_SELECTABLE` bid) |
| `midi_observe_controller.js:402-410` | `FX_SETUP_TEMP` bid → `receiveChainEditTrigger` (the loopback path) |

## Why this is parked

- Device is confirmed sane. Every byte of every chart-documented
  address responds correctly. `0x00200003` is never stuck on the
  device side; the bug is purely BTS-side reaction to its own
  loopback echo.
- Cross-platform Python tooling (`midi_send`, `midi_sniff`, `midi_io`,
  `example_lib.GX10Session`) gives end-to-end programmatic chain
  edit, INSERT, DELETE, OVERWRITE via direct DT1/RQ1 — and these
  paths don't suffer the loopback symptom because they don't have a
  client-side `receiveChainEditTrigger` that disables UI on echo.
- Drag-and-drop in BTS works fine for chain manipulation; the buttons
  are convenience UI but functionally redundant.
- Fixing OVERWRITE fully needs a deeper rewrite of either
  `midi_observe_controller` or the overwrite state machine, neither
  of which is small.
- The simplest user-side fix — set USB IN THRU to OFF on the device
  menu — eliminates the bug entirely without any BTS patching.
