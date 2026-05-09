# BTS-screenshot resweep — ground truth label↔address mapping per effect

**Method**: programmatic SysEx writes drive the device, BTS auto-updates,
screenshots capture the result. No USBPcap needed.

For each effect TYPE 0x00..0x52:
1. SysEx: write TYPE byte to 0x10001100
2. SysEx: write Param 1 (sub-type) = 0
3. Wait 900 ms for BTS to redraw
4. Screenshot the slot-0 knob area → `<TT>_<NAME>_default.png`
5. SysEx: write distinctive values **1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12**
   to consecutive FX Param slots at offsets 0x07, 0x0B, 0x0F, 0x13, 0x17,
   0x1B, 0x1F, 0x23, 0x27, 0x2B, 0x2F, 0x33 (Param 2..13)
6. Wait 900 ms
7. Screenshot → `<TT>_<NAME>_filled.png`

The "filled" screenshots pair each distinctive value with the BTS label
sitting next to it — that's the ground-truth label→address map.

## Output

166 PNG files (83 effects × 2) in `captures/bts_typebar_resweep/`
(~6.3 MB total). Tracked in git (overrides the captures/**/*.png ignore
rule).

## Headline findings (from the first batch of screenshots)

### COMP (TYPE 0x08): typebar_full was correct ✓

5 knobs in screen-left-to-right order: SUSTAIN=1, ATTACK=2, LEVEL=3,
TONE=+4, DIRECT MIX=5. typebar_full's COMP mapping is right.

### X-COMP (TYPE 0x09): typebar_full incomplete

6 knobs visible: SUSTAIN=5, ATTACK=0, LEVEL=1, TONE=+2, RATIO=1.6:1,
DIRECT MIX=4. typebar_full only listed 5 of these (missed RATIO,
ATTACK, DIRECT MIX as separate knob_idx entries).

| Address | Real label |
|---------|-----------|
| `0x10001107` | LEVEL |
| `0x1000110B` | TONE |
| `0x1000110F` | RATIO |
| `0x10001113` | DIRECT MIX |
| `0x10001117` | SUSTAIN |
| `0x1000111B` | ATTACK |

### WAH (TYPE 0x35, sub-type 0 CRY WAH): typebar_full names are PERMUTED

5 knobs in screen-left-to-right order: EFFECT LEVEL=4, DIRECT MIX=5,
PEDAL POSITION=1, PEDAL MIN=2, PEDAL MAX=3 (typebar_full had no
PEDAL MAX entry).

| Address | Real label | typebar_full claim |
|---------|-----------|---------------------|
| `0x10001107` | **PEDAL POSITION** | WAH TYPE ✗ |
| `0x1000110B` | **PEDAL MIN** | EFFECT LEVEL ✗ |
| `0x1000110F` | **PEDAL MAX** | DIRECT MIX ✗ |
| `0x10001113` | **EFFECT LEVEL** | PEDAL POSITION ✗ |
| `0x10001117` | **DIRECT MIX** | PEDAL MIN ✗ |

Confirms what user discovered manually — typebar_full's WAH
labels-to-address pairing is shifted/permuted. Likely caused by the
typebar_full extractor reading labels in screen-x order but pairing
them with addresses in a different order.

### CHO (TYPE 0x04): typebar_full incomplete

9 knobs visible left-to-right: RATE=2, DEPTH=3, EFFECT LEVEL=4,
PRE-DELAY=3.5ms, WAVEFORM=(enum), LOW CUT=50.0Hz, HIGH CUT=80.0Hz,
DIRECT LEVEL=1, BPM=120. The first knob (DIRECT LEVEL=1) maps to
`0x10001107` — confirming the NUMBER-1 leftmost knob is at the
lowest address. Other knobs follow in address order.

| Address | Real label |
|---------|-----------|
| `0x10001107` | DIRECT LEVEL |
| `0x1000110B` | RATE |
| `0x1000110F` | DEPTH |
| `0x10001113` | EFFECT LEVEL |
| `0x10001117` | PRE-DELAY (ms scale) |
| `0x1000111B` | WAVEFORM (enum) |
| `0x1000111F` | LOW CUT (Hz scale) |
| `0x10001123` | HIGH CUT (Hz scale) |
| `0x10001127` | BPM |

### AC_SIM (TYPE 0x00): mapping correct, but per-knob encodings vary

Wrote 1, 2, 3, 4 to Params 2..5; BTS shows BODY=0, LOW=-49, HIGH=-48,
LEVEL=3. This is NOT a name-permutation — the addresses are right —
but each knob has its own encoding/clamping:

- BODY: enum range 0..N, my value 1 clamped or remapped to 0
- LOW / HIGH: bipolar -50..+50 with non-zero baseline causing my
  small writes to display as -49 / -48
- LEVEL: standard 0..100, displays my 4 minus 1 = 3
  (or has a baseline offset of 0x8001)

Per-knob encoding is firmware-defined and isn't worth reverse-
engineering address-by-address — the SCREENSHOTS are the truth for
each effect's display formula.

## Caveat: BTS-UI lag for some TYPE byte changes

Two TYPEs (0x02 AMP and 0x03 AMP_BASS) show BTS still rendering the
previous effect's UI (AC_RESONANCE) despite the device having
switched. The values shown are correct for the new TYPE (50, +50, 50
defaults of TYPE 0x02), but BTS hasn't redrawn the labels.

Cause: SysEx-only TYPE byte writes don't always trigger BTS's UI
update path. The chain-edit handshake (DT1 0x00200003 = 0x01 / 0x00
around the TYPE write) probably forces BTS to re-pull. A v2 sweep
should add that.

For now: TYPE 0x02 and 0x03 screenshots show stale labels but correct
values; ignore those for label-mapping purposes. Most other TYPEs
work cleanly.

## Files

- `bts_typebar_resweep/00_AC_SIM_default.png` … `52_A_WAH_default.png`
  — pre-write screenshots showing each effect's default values + labels
- `bts_typebar_resweep/00_AC_SIM_filled.png` … `52_A_WAH_filled.png`
  — post-write screenshots showing distinctive values 1..12 next to
  each label, giving the ground-truth label↔address map
- `bts_typebar_resweep/_emergency_snapshot.bin` — pre-sweep snapshot
  of FxItem #0 (your WAH patch); restored at sweep end, verified
  byte-for-byte

## Tool

`tools/bts_resweep_via_sysex.py` — runs the sweep. Single command,
~6 minutes for all 83 effects. Snapshots + restores FxItem #0
automatically.

## Next steps for a complete catalog

1. Re-run with chain-edit handshake (DT1 0x00200003 begin/end around
   each TYPE write) to fix the BTS-UI-lag effects (0x02, 0x03, possibly
   others).
2. Per sub-type sweep: for effects with `type_max > 0` (e.g. WAH 0..5,
   COMP 0..2, AMP many), repeat the screenshot pass for each sub-type
   value. Different sub-types may show different knob counts/labels at
   the same addresses.
3. OCR or UI Automation extraction from the screenshots to build a
   machine-readable label→address mapping JSON for the catalog
   regenerator.
