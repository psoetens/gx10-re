# GX-10 — Per-knob byte mapping (work in progress)

## Demonstrated technique

The reliable way to find a knob's byte address:

1. Restore U10-1 INIT (`tools/restore_snapshot.py snapshots/u10-1_init.json`).
2. Replay the desired effect's drag pcap (e.g. `captures/typebar/drag00_COMP.pcap`).
3. Launch Tone Studio (auto-syncs to the new state).
4. **Click the target knob** in Tone Studio (focuses it).
5. Press **Arrow Up / Arrow Down** to step the value.
6. Capture USBPcap during the arrow presses.
7. Each arrow press fires a **single DT1 host → device** with the 4-byte
   payload `08 00 00 VV` at a stable per-knob address — the address is the
   knob's byte. The value byte is the **last** of the 4 (i.e. parameter
   address + 3).

Coordinate-based knob *drag* (pyautogui mouseDown + mouseMove + mouseUp) is
**not reliable** in WebView2: knob events don't fire. Click + arrow keys
**is** reliable.

## Confirmed mapping — COMP (BOSS COMP, slot 0)

After `restore U10-1 INIT → replay drag00_COMP.pcap → launch Tone Studio →
click SUSTAIN`, then 5× Arrow Up:

| Knob | Address | Cell layout | Value byte | Arrow step |
|------|---------|-------------|------------|------------|
| SUSTAIN | `0x10001107..0x1000110A` | `08 00 00 VV` | `0x1000110A` | +1 |

Each subsequent arrow-up sent:

```
DT1 0x10001107 = 08 00 00 01    (after 1st)
DT1 0x10001107 = 08 00 00 02    (after 2nd)
DT1 0x10001107 = 08 00 00 03    (after 3rd)
DT1 0x10001107 = 08 00 00 04    (after 4th)
DT1 0x10001107 = 08 00 00 05    (after 5th)
```

The 4-byte cell pattern continues across the slot's parameters. Reading
`0x10001107..0x10001116` after the 5 arrow-ups returns:

```
0x10001107  08 00 00 04  ← SUSTAIN (was 5 just before, but click before
                            arrow-down decremented to 4 / 5 depending on
                            click target)
0x1000110B  08 00 03 02  ← (next knob — likely ATTACK or LEVEL)
0x1000110F  08 00 03 0C  ← (next knob)
0x10001113  08 00 00 00  ← (next knob)
```

Each knob takes 4 bytes (`08 XX YY VV`). The first byte is always the
sentinel `0x08`, the next two bytes appear to be a per-knob "scale" or
"sub-format" tag (varies per knob — `00 00`, `00 03`, etc.), and the last
byte is the actual value VV.

## Open: direct DT1 writes to a knob value byte

Writing `08 00 00 14` directly to `0x10001107` (i.e. setting SUSTAIN = 0x14
= 20) does NOT take effect — re-reading returns the previous value (0x04).
The device only accepts certain combinations of the cell tag bytes; the
exact constraint isn't yet decoded. To apply a target SUSTAIN value, the
reliable path is currently:

1. Click SUSTAIN in Tone Studio.
2. Arrow Up to the desired value (one press = +1).
3. Or: capture Tone Studio doing it (e.g. typing a value via numeric entry,
   if Tone Studio supports it) and replay that DT1.

## Mechanism for full sweep

To map all knobs of all 30 effects:

```
for effect in TYPEBAR:
    restore_snapshot u10-1_init.json
    replay drag<effect>.pcap
    launch_tone_studio
    for each visible knob:
        click_knob_at(window_xy)
        for n in range(127):
            arrow_up
            capture_dt1   # records (addr, value_byte, pre/post)
        record min..max range observed
```

Each effect takes ~30 seconds for the visible knob layout + ~127 arrow
presses per knob (~30 s/knob = 5+ min per effect with all knobs). Total for
30 effects × ~7 knobs avg × 30 s = ~1 hour automated sweep. The
infrastructure for this is in place; what's missing is a per-effect knob
position table (knob center coordinates per effect screenshot) — the AMP
preamp's 18 knobs span 2 rows, FUZZ has 7 in one row, etc.

## Range determination

- **Min** of any knob: arrow-down until DT1 stops firing (device clamps).
- **Max**: arrow-up until DT1 stops firing.
- **Step**: 1 per arrow press for most numeric knobs. Some (like KEY,
  WAVEFORM) cycle through enumerated values rather than numbers.

All three can be discovered with the same arrow-key technique.
