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
- **HR user-shift semantics** (CORRECTED 2026-07-16): the wire carries
  the **slider index 0…48** offset-binary (cell = index + 0x8000), NOT
  the signed display. Hardware-verified: with USER scales active and
  every knob showing "0" on the device, all 24 cells read `0x8018`
  (= index 24 = unison). Selecting HARMONY=USER makes the device
  initialise the cells to `0x8018` itself; the INIT capture's `0x8000`
  is just a zeroed inactive field (index 0 = −24, never sounding). The
  catalog's `raw_min: 0 / raw_max: 48` are therefore the true wire
  range; `init: 0` is bogus (would mean −24) — trust the device's own
  initialisation (24). Display comes from `format_js`
  (`formatHarmonistUserShift` → "- 24C" … "0C" … "+ 24C").
  (A first reading of this data concluded "wire = display + 0x8000,
  INIT = unison" — wrong; recorded here so nobody re-derives it.)
- **KEY and BPM are not block fields.** The device's harmonist page
  surfaces the patch-common MASTER KEY (`0x10000F06`) and BPM
  (`0x10000F02`) contextually; the catalog is right to omit them from
  the harmonist knob list.

## Known bug-era debris (edit buffers in the wild)

gxnarly builds before 2026-07-15 collapsed the HR knobs to a one-value
range (display-string sign parsing bug) — clicking them wrote `0x8018`
into HR cells. With the corrected unit model that value is **unison**
(harmless — the same value the device initialises USER cells to). The
one real corruption observed was `0x8018` in a VOICE cell (out-of-range
for its 0..2 enum); flipping VOICE on the device rewrites it cleanly.

## Downstream fixes (gxnarly, same date)

In `gxnarly/tools/codegen` (not this repo): sign-aware display-range
parsing ("- 24C" → −24), HR value labels from `formatHarmonistUserShift`,
compound `show_when` clause routing (`(voice…) && hr2-harmony === 29`),
and master KEY/BPM companion knobs in the harmonist inspector.
