# HARMONIST block — hardware verification (2026-07-15)

Live RQ1 probing of a real GX-10 (fw current, patch U18-1) triggered by a
gxnarly bug report ("HR2 knobs frozen at 24"). **Outcome: the catalog's
harmonist entry is fully correct** — addresses, `ofs`, sizes, and
`show_when` all match the device. The bugs were downstream (gxnarly's
codegen); this report records the verification so nobody re-probes it.

## Verified facts

- **Slot-relative addressing confirmed.** Catalog knob addresses
  (`0x100011xx`) are a template for chain-slot base `0x10001100`; real
  base = `0x10001100 + slotIndex * 0x200` (20 slots), TYPE byte at
  `+0x00` (harmonist = `0x1A`), OFF/ON at `+0x01`. A read of slot 0
  mistaken for "the harmonist block" produced a phantom
  address-shift scare — always locate the slot via its TYPE byte first.
- **All probed offsets match the catalog** (device values ⇄ front-panel
  readings): `+0x07` 1:HARMONY (enum idx; −1oct = 7), `+0x0B` 1:LEVEL,
  `+0x0F` 1:PRE-DELAY, `+0x13` 1:FEEDBACK, `+0x17`/`+0x1B`/`+0x1F`
  2:HARMONY/LEVEL/PRE-DELAY, `+0x23` DIRECT LEVEL, `+0x27..+0x83`
  HR1:/HR2: C…B (4 bytes each).
- **VOICE is INTEGER4x4 offset-binary at `+0x03`** like the other
  cells, values 0/1/2 (1VOICE / 2MONO / 2STEREO). Verified by flipping
  VOICE on the device: cell went `0x8018` (stale garbage, see below) →
  `0x8002` on selecting 2STEREO.
- **HR user-shift semantics**: wire = display + 0x8000 (offset-binary),
  display −24…+24 semitones, device INIT = 0x8000 = unison. The
  catalog's `raw_min: 0 / raw_max: 48` for these knobs are **BTS slider
  index units**, while `init: 0` is in **display units** — BTS's own
  resource mixes unit systems here (contrast PITCH SHIFTER, whose
  raw −24..24 and init are both display units). Downstream consumers
  must derive the display range from `template`/`format_js`
  (`formatHarmonistUserShift` → "- 24C" … "+ 24C"), NOT from
  raw_min/raw_max.
- **KEY and BPM are not block fields.** The device's harmonist page
  surfaces the patch-common MASTER KEY (`0x10000F06`) and BPM
  (`0x10000F02`) contextually; the catalog is right to omit them from
  the harmonist knob list.

## Known bug-era debris (edit buffers in the wild)

gxnarly builds before 2026-07-15 collapsed the HR knobs to a one-value
range (display-string sign parsing bug) — clicking them wrote
**+24 semitones** (`0x8018`) into HR cells, and at least one patch also
carried `0x8018` in the VOICE cell. Patches edited with those builds may
hold such values; they are legitimate wire values the device accepts,
just musically unintended. Fix: re-set the knobs (or re-INIT the block).

## Downstream fixes (gxnarly, same date)

In `gxnarly/tools/codegen` (not this repo): sign-aware display-range
parsing ("- 24C" → −24), HR value labels from `formatHarmonistUserShift`,
compound `show_when` clause routing (`(voice…) && hr2-harmony === 29`),
and master KEY/BPM companion knobs in the harmonist inspector.
