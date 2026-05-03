# GX-10 Type-Bar Effects — Complete Mapping (Slot 0)

This document maps all 30 effect categories from Tone Studio's top type bar
to their **byte values** in the patch buffer at `0x10001100`, plus the
**effect name** and the **knobs** each effect exposes.

Captured by `tools/drag_each_typebar.py` (drag from type bar onto chain
slot 0 after restoring U10-1 INIT) + screenshots inspected after each drag.
The triplet at `0x10001100..0x10001102` is `XX 01 00` for every effect,
where `XX` is the value listed in the **Cat byte** column.

The "atomic command sequence" for setting slot 0 to any of these effects
is documented per-effect in `docs/effects/typebar.md`. It's six DT1 writes:

```
DT1 0x00200003 = 01                     # editor flag set
DT1 0x10001100 = <cat>                  # category byte
DT1 0x10001102 = 0x00                   # modifier byte
DT1 0x10001101 = 0x01                   # subtype byte
DT1 0x10000F00 = 0C 01 00 02..31        # chain order (constant)
DT1 0x00200003 = 00                     # editor flag clear
```

To change the effect *currently in slot 0*, replay this sequence with the
desired Cat byte. Replays without restoring U10-1 INIT first usually do
NOT take effect (the chain stays on whatever effect was last placed via a
clean drag).

## Master mapping table

| #  | Type bar    | Cat byte | Effect name (header) | Per-type dropdown(s) | Knobs |
|----|-------------|---------|----------------------|----------------------|-------|
| 0  | COMP        | `0x08`  | COMPRESSOR           | TYPE = `BOSS COMP` | SUSTAIN, ATTACK, LEVEL, TONE, DIRECT MIX |
| 1  | X-COMP      | `0x09`  | X COMPRESSOR         | —                  | SUSTAIN, ATTACK, LEVEL, TONE, RATIO, DIRECT MIX |
| 2  | BOOST       | `0x24`  | BOOSTER              | TYPE = `CLEAN BOOST` | BOOST, TONE, LEVEL, BOTTOM, DIRECT MIX, SOLO SW, SOLO LEVEL |
| 3  | OD          | `0x25`  | OVERDRIVE            | TYPE = `OD-1`       | DRIVE, TONE, LEVEL, BOTTOM, DIRECT MIX, SOLO SW, SOLO LEVEL |
| 4  | X-OD        | `0x2B`  | X OVERDRIVE          | —                  | DRIVE, TONE, BOTTOM, LEVEL, DIRECT MIX, SOLO SW, SOLO LEVEL |
| 5  | DIST        | `0x27`  | DISTORTION           | TYPE = `DIST`       | DRIVE, TONE, LEVEL, BOTTOM, DIRECT MIX, SOLO SW, SOLO LEVEL |
| 6  | X-DIST      | `0x2D`  | X DISTORTION         | —                  | DRIVE, TONE, BOTTOM, LEVEL, DIRECT MIX, SOLO SW, SOLO LEVEL |
| 7  | METAL       | `0x2E`  | METAL DISTORTION     | TYPE = `METAL DS`   | DIST, TONE, LEVEL, BOTTOM, DIRECT MIX, SOLO SW, SOLO LEVEL |
| 8  | FUZZ        | `0x29`  | FUZZ                 | TYPE = `'60S FUZZ`  | FUZZ, TONE, LEVEL, BOTTOM, DIRECT MIX, SOLO SW, SOLO LEVEL |
| 9  | AMP         | `0x02`  | AIRD PREAMP          | TYPE = `NATURAL`, SP TYPE = `ORIGINAL` | GAIN, LEVEL, GAIN SW, BASS, MIDDLE, TREBLE, PRESENCE, BRIGHT SW, SOLO SW, SOLO LEVEL, SAG, RESONANCE, DIRECT MIX, MIC TYPE, MIC DISTANCE, MIC POSITION, MIC LEVEL |
| 10 | PEQ         | `0x14`  | PARAMETRIC EQUALIZER | —                  | LOW GAIN, HIGH GAIN, LEVEL, LOW-MID FREQ, LOW-MID Q, LOW-MID GAIN, HIGH-MID FREQ, HIGH-MID Q, HIGH-MID GAIN, LOW CUT, HIGH CUT |
| 11 | GEQ         | `0x15`  | GRAPHIC EQUALIZER    | —                  | 31.5Hz, 63Hz, 125Hz, 250Hz, 500Hz, 1kHz, 2kHz, 4kHz, 8kHz, 16kHz, LEVEL |
| 12 | CHO         | `0x04`  | CHORUS               | TYPE = `MONO`       | RATE, DEPTH, EFFECT LEVEL, PRE-DELAY, WAVEFORM, LOW CUT, HIGH CUT, DIRECT LEVEL, BPM |
| 13 | CHO PRIME   | `0x06`  | PRIME CHORUS         | —                  | RATE, DEPTH, EFFECT LEVEL, PRE-DELAY, WAVEFORM, LOW CUT, HIGH CUT, SWEETNESS, BELL, OUTPUT MODE, BPM |
| 14 | FL          | `0x16`  | FLANGER              | —                  | RATE, DEPTH, RESONANCE, MANUAL, LOW CUT, STEP RATE, EFFECT LEVEL, DIRECT MIX, BPM |
| 15 | FL PRIME    | `0x18`  | PRIME FLANGER        | STAGE = `4 STAGE`   | RATE, DEPTH, RESONANCE, MANUAL, WAVEFORM, SEPARATION, STEP RATE, IN-PHASE, LOW RAMP, HIGH RAMP, LOW CUT, HIGH CUT, EFFECT LEVEL, DIRECT MIX, BPM |
| 16 | PH          | `0x37`  | PHASER               | STAGE = `4 STAGE`   | RATE, DEPTH, RESONANCE, MANUAL, STEP RATE, EFFECT LEVEL, DIRECT MIX, BPM |
| 17 | PH SCRIPT   | `0x3B`  | SCRIPT PHASER        | —                  | RATE, DEPTH, EFFECT LEVEL, DIRECT MIX, BPM |
| 18 | PH PRIME    | `0x39`  | PRIME PHASER         | STAGE = `4 STAGE`   | RATE, DEPTH, RESONANCE, MANUAL, WAVEFORM, SEPARATION, STEP RATE, IN-PHASE, LOW RAMP, HIGH RAMP, LOW CUT, HIGH CUT, EFFECT LEVEL, DIRECT MIX, BPM |
| 19 | CLASS VIBE  | `0x07`  | CLASSIC-VIBE         | MODE = `CHORUS`     | RATE, DEPTH, LEVEL, BPM |
| 20 | ROTARY      | `0x43`  | ROTARY               | —                  | SPEED SELECT, SLOW RATE, FAST RATE, EFFECT LEVEL, RISE TIME, FALL TIME, MIC DISTANCE, ROTOR/HORN, DRIVE, DIRECT MIX, BPM |
| 21 | VIB         | `0x4B`  | VIBRATO              | —                  | RATE, DEPTH, RISE TIME, EFFECT LEVEL, TRIGGER, BPM |
| 22 | VIB PRIME   | `0x4C`  | PRIME VIBRATO        | —                  | RATE, DEPTH, COLOR, EFFECT LEVEL, TRIGGER, RISE TIME, DIRECT MIX, BPM |
| 23 | TREM        | `0x4A`  | TREMOLO              | —                  | RATE, DEPTH, WAVEFORM, EFFECT LEVEL, TRIGGER, RISE TIME, DIRECT MIX, BPM |
| 24 | PAN         | `0x31`  | PAN                  | —                  | RATE, DEPTH, WAVEFORM, EFFECT LEVEL, DIRECT MIX, BPM |
| 25 | RING MOD    | `0x42`  | RING MODULATOR       | INTELLIGENT = `OFF` | FREQUENCY, MOD RATE, MOD DEPTH, EFFECT LEVEL, DIRECT MIX, BPM |
| 26 | SLICER      | `0x4E`  | SLICER               | —                  | PATTERN, RATE, TRIGGER, EFFECT LEVEL, ATTACK, DUTY, DIRECT MIX, BPM |
| 27 | HMN         | `0x4F`  | HUMANIZER            | —                  | MODE, VOWEL1, VOWEL2, RATE, DEPTH, MANUAL, LEVEL, BPM |
| 28 | PS          | `0x3C`  | PITCH SHIFTER        | VOICE = `1 VOICE`   | 1: PITCH, 1: FINE, 1: MODE, 1: PRE-DELAY, 1: FEEDBACK, 1: LEVEL, DIRECT LEVEL, BPM |
| 29 | HARM        | `0x1A`  | HARMONIST            | VOICE = `1 VOICE`   | 1: HARMONY, 1: LEVEL, 1: PRE-DELAY, 1: FEEDBACK, KEY, DIRECT LEVEL, BPM |

## Default values per knob (slot 0, freshly-dropped)

These are the defaults the device assigns when an effect is first dropped
into a slot. Real min/max/step ranges still need to be probed per knob (see
"Next steps" below).

### COMP (BOSS COMP)
SUSTAIN=50, ATTACK=50, LEVEL=60, TONE=0, DIRECT MIX=0

### X-COMP
SUSTAIN=50, ATTACK=50, LEVEL=60, TONE=0, RATIO=6:1, DIRECT MIX=0

### BOOST (CLEAN BOOST)
BOOST=50, TONE=0, LEVEL=50, BOTTOM=0, DIRECT MIX=0, SOLO SW=OFF, SOLO LEVEL=50

### OD (OD-1)
DRIVE=50, TONE=0, LEVEL=50, BOTTOM=0, DIRECT MIX=0, SOLO SW=OFF, SOLO LEVEL=50

### X-OD
DRIVE=50, TONE=0, BOTTOM=0, LEVEL=50, DIRECT MIX=0, SOLO SW=OFF, SOLO LEVEL=50

### DIST (DIST)
DRIVE=50, TONE=0, LEVEL=50, BOTTOM=0, DIRECT MIX=0, SOLO SW=OFF, SOLO LEVEL=50

### X-DIST
DRIVE=50, TONE=0, BOTTOM=0, LEVEL=50, DIRECT MIX=0, SOLO SW=OFF, SOLO LEVEL=50

### METAL (METAL DS)
DIST=50, TONE=0, LEVEL=50, BOTTOM=0, DIRECT MIX=0, SOLO SW=OFF, SOLO LEVEL=50

### FUZZ ('60S FUZZ)
FUZZ=50, TONE=0, LEVEL=50, BOTTOM=0, DIRECT MIX=0, SOLO SW=OFF, SOLO LEVEL=50

### AMP (AIRD PREAMP, TYPE=NATURAL, SP TYPE=ORIGINAL)
GAIN=50, LEVEL=50, GAIN SW=MIDDLE, BASS=50, MIDDLE=50, TREBLE=50, PRESENCE=0,
BRIGHT SW=OFF, SOLO SW=OFF, SOLO LEVEL=50, SAG=0, RESONANCE=0, DIRECT MIX=0,
MIC TYPE=DYN57, MIC DISTANCE=SHORT, MIC POSITION=5cm, MIC LEVEL=100

### PEQ
LOW GAIN=0dB, HIGH GAIN=0dB, LEVEL=0dB,
LOW-MID FREQ=500Hz, LOW-MID Q=1, LOW-MID GAIN=0dB,
HIGH-MID FREQ=4.00kHz, HIGH-MID Q=1, HIGH-MID GAIN=0dB,
LOW CUT=FLAT, HIGH CUT=FLAT

### GEQ
all 10 bands = 0dB, LEVEL = 0dB

### CHO (MONO)
RATE=50, DEPTH=40, EFFECT LEVEL=100, PRE-DELAY=4.0ms, WAVEFORM=TRI,
LOW CUT=31.5Hz, HIGH CUT=6.30kHz, DIRECT LEVEL=100, BPM=120

### CHO PRIME
RATE=50, DEPTH=40, EFFECT LEVEL=100, PRE-DELAY=4.0ms, WAVEFORM=TRI,
LOW CUT=31.5Hz, HIGH CUT=6.30kHz, SWEETNESS=50, BELL=50, OUTPUT MODE=STEREO, BPM=120

### FL
RATE=25, DEPTH=60, RESONANCE=35, MANUAL=55, LOW CUT=80.0Hz, STEP RATE=OFF,
EFFECT LEVEL=100, DIRECT MIX=0, BPM=120

### FL PRIME (4 STAGE)
RATE=25, DEPTH=60, RESONANCE=35, MANUAL=55, WAVEFORM=TRI, SEPARATION=OFF,
STEP RATE=OFF, IN-PHASE=-80, LOW RAMP=-80, HIGH RAMP=80.0Hz, LOW CUT=15.0kHz,
HIGH CUT=FLAT, EFFECT LEVEL=100, DIRECT MIX=0, BPM=120

### PH (4 STAGE)
RATE=30, DEPTH=70, RESONANCE=30, MANUAL=50, STEP RATE=OFF, EFFECT LEVEL=100,
DIRECT MIX=0, BPM=120

### PH SCRIPT
RATE=50, DEPTH=50, EFFECT LEVEL=100, DIRECT MIX=0, BPM=120

### PH PRIME (4 STAGE)
RATE=30, DEPTH=70, RESONANCE=30, MANUAL=TRI, WAVEFORM=OFF, SEPARATION=-50,
STEP RATE=-50, IN-PHASE=FLAT, LOW RAMP=FLAT, HIGH RAMP=120, … BPM=120

### CLASS VIBE (CHORUS mode)
RATE=50, DEPTH=100, LEVEL=100, BPM=120

### ROTARY
SPEED SELECT=FAST, SLOW RATE=50, FAST RATE=50, EFFECT LEVEL=100, RISE TIME=50,
FALL TIME=50, MIC DISTANCE=100, ROTOR/HORN=100:100, DRIVE=0, DIRECT MIX=0, BPM=120

### VIB
RATE=80, DEPTH=20, RISE TIME=30, EFFECT LEVEL=100, TRIGGER=ON, BPM=120

### VIB PRIME
RATE=80, DEPTH=20, COLOR=0, EFFECT LEVEL=100, TRIGGER=ON, RISE TIME=30,
DIRECT MIX=0, BPM=120

### TREM
RATE=75, DEPTH=50, WAVEFORM=50, EFFECT LEVEL=100, TRIGGER=ON, RISE TIME=0,
DIRECT MIX=0, BPM=120

### PAN
RATE=50, DEPTH=50, WAVEFORM=50, EFFECT LEVEL=100, DIRECT MIX=0, BPM=120

### RING MOD (INTELLIGENT=OFF)
FREQUENCY=50, MOD RATE=50, MOD DEPTH=0, EFFECT LEVEL=100, DIRECT MIX=0, BPM=120

### SLICER
PATTERN=P1, RATE=50, TRIGGER=OFF, EFFECT LEVEL=100, ATTACK=50, DUTY=50,
DIRECT MIX=0, BPM=120

### HMN
MODE=AUTO, VOWEL1=a, VOWEL2=i, RATE=50, DEPTH=100, MANUAL=50, LEVEL=100, BPM=120

### PS (1 VOICE)
1: PITCH=-5, 1: FINE=+10, 1: MODE=MEDIUM, 1: PRE-DELAY=0ms, 1: FEEDBACK=0,
1: LEVEL=100, DIRECT LEVEL=100, BPM=120

### HARM (1 VOICE)
1: HARMONY=-3rd, 1: LEVEL=100, 1: PRE-DELAY=0ms, 1: FEEDBACK=0, KEY=C(Am),
DIRECT LEVEL=100, BPM=120

## Open: per-knob byte address mapping

Each effect has its parameter values stored at byte addresses inside the
slot's region (likely under `0x10000200..0x10000B7F` and/or
`0x10001100..0x100011FF`). To map them: load each effect via the drag
sequence above (or replay the captured drag pcap), snapshot the patch via
`tools/rapid_probe.py`, drag a single knob in Tone Studio to a known new
value, snapshot again, and diff. The byte that changed is the parameter's
address; the diffs across "min knob" / "default" / "max knob" snapshots
give the byte range / step.

The `tools/patch_snapshot.py --diff` flow already supports this.
