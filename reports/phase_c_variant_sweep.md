# Phase C variant-conditional sweep

Source: live BTS-UIA sweep at 2026-05-11 09:52.
Effects probed: **20**

## Variant-conditional knobs

Total conditional entries: **47**

Each row is `(effect, knob_label, visible_on_variants)`.

- `0x02` AIRD PREAMP: **BRIGHT SW** -> visible_on_variants=[1, 2, 6, 9, 10, 12] (NATURAL, BOUTIQUE, X-CRUNCH, JC-120, TWIN COMBO, TWEED COMBO)
- `0x03` BASS AIRD PREAMP: **BRIGHT SW** -> visible_on_variants=[0, 2, 5, 8] (NATURAL BASS, CONCERT, CLASSIC BLUE, DARK DRV)
- `0x04` CHORUS: **1: WAVEFORM** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **2: DEPTH** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **WAVEFORM** -> visible_on_variants=[0, 1, 2] (MONO, DIR/EFX, STEREO)
- `0x04` CHORUS: **2: LOW CUT** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **1: HIGH CUT** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **2: RATE** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **DEPTH** -> visible_on_variants=[0, 1, 2] (MONO, DIR/EFX, STEREO)
- `0x04` CHORUS: **LOW CUT** -> visible_on_variants=[0, 1, 2] (MONO, DIR/EFX, STEREO)
- `0x04` CHORUS: **2: PRE-DELAY** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **1: RATE** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **1: EFFECT LEVEL** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **1: PRE-DELAY** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **1: LOW CUT** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **1: DEPTH** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **EFFECT LEVEL** -> visible_on_variants=[0, 1, 2] (MONO, DIR/EFX, STEREO)
- `0x04` CHORUS: **OUTPUT MODE** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **RATE** -> visible_on_variants=[0, 1, 2] (MONO, DIR/EFX, STEREO)
- `0x04` CHORUS: **2: WAVEFORM** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **2: HIGH CUT** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **TRI** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **HIGH CUT** -> visible_on_variants=[0, 1, 2] (MONO, DIR/EFX, STEREO)
- `0x04` CHORUS: **2: EFFECT LEVEL** -> visible_on_variants=[3] (DUAL)
- `0x04` CHORUS: **PRE-DELAY** -> visible_on_variants=[0, 1, 2] (MONO, DIR/EFX, STEREO)
- `0x0E` DELAY+: **FEEDBACK** -> visible_on_variants=[0, 1, 2, 3, 4] (MONO, DIR/EFX, STEREO, PAN, REVERSE)
- `0x0E` DELAY+: **1: HIGH CUT** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **MODE** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **1: FEEDBACK** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **TAP TIME** -> visible_on_variants=[3] (PAN)
- `0x0E` DELAY+: **2: FEEDBACK** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **1: EFFECT LEVEL** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **TIME** -> visible_on_variants=[0, 1, 2, 3, 4] (MONO, DIR/EFX, STEREO, PAN, REVERSE)
- `0x0E` DELAY+: **2: TIME** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **1: TYPE** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **1: TIME** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **EFFECT LEVEL** -> visible_on_variants=[0, 1, 2, 3, 4] (MONO, DIR/EFX, STEREO, PAN, REVERSE)
- `0x0E` DELAY+: **AUTO TRIGGER** -> visible_on_variants=[4] (REVERSE)
- `0x0E` DELAY+: **2: HIGH CUT** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **HIGH CUT** -> visible_on_variants=[0, 1, 2, 3, 4] (MONO, DIR/EFX, STEREO, PAN, REVERSE)
- `0x0E` DELAY+: **2: EFFECT LEVEL** -> visible_on_variants=[5] (DUAL)
- `0x0E` DELAY+: **2: TYPE** -> visible_on_variants=[5] (DUAL)
- `0x12` TWIST DELAY: **FADE TIME** -> visible_on_variants=[1] (RISE -> FADE)
- `0x12` TWIST DELAY: **FALL TIME** -> visible_on_variants=[0] (RISE -> FALL)
- `0x4D` SEND/RETURN: **INVERT** -> visible_on_variants=[0, 1] (NORMAL, DIRECT MIX)
- `0x4D` SEND/RETURN: **RETURN LEVEL** -> visible_on_variants=[0, 1] (NORMAL, DIRECT MIX)
- `0x4D` SEND/RETURN: **ADJUST** -> visible_on_variants=[0, 1] (NORMAL, DIRECT MIX)