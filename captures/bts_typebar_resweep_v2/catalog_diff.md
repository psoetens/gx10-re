# Catalog diff — typebar_full claims vs v2 ground truth

| TYPE | Effect | typebar count | v2 count | mapped | status |
|------|--------|--------------:|---------:|-------:|--------|
| `0x00` | AC_SIM | 4 | 0 | 0 | ❓ v2 found 0 knobs (BTS UI race) |
| `0x01` | AC_RESO | 3 | 3 | 3 | ✅ exact match |
| `0x02` | AMP | 11 | 3 | 3 | ❌ 3 permuted |
| `0x03` | AMP_BASS | 12 | 3 | 3 | ❌ 3 permuted |
| `0x04` | CHO | 9 | 8 | 4 | ❌ 4 permuted |
| `0x05` | CHO_BASS | 7 | 7 | 4 | ⚠️ 3 typebar-only |
| `0x06` | CHO_PRIME | 11 | 0 | 0 | ❓ v2 found 0 knobs (BTS UI race) |
| `0x07` | CLASS_VIBE | 4 | 4 | 3 | ❌ 3 permuted |
| `0x08` | COMP | 5 | 5 | 5 | ✅ exact match |
| `0x09` | X-COMP | 6 | 0 | 0 | ❓ v2 found 0 knobs (BTS UI race) |
| `0x0A` | X_COMP_BASS | 6 | 0 | 0 | ❓ v2 found 0 knobs (BTS UI race) |

## Detail per effect

### `0x00` AC_SIM

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001107` → typebar said **BODY**
- `0X1000110B` → typebar said **LOW**
- `0X1000110F` → typebar said **HIGH**
- `0X10001113` → typebar said **LEVEL**

### `0x01` AC_RESO

Correct:
- `0X10001107` → **RESONANCE**
- `0X1000110B` → **TONE**
- `0X1000110F` → **LEVEL**

### `0x02` AMP

**Permuted (typebar wrong):**
- `0X10001107` → real **RESONANCE** (typebar said: GAIN)
- `0X1000110B` → real **TONE** (typebar said: LEVEL)
- `0X1000110F` → real **LEVEL** (typebar said: GAIN SW)

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001113` → typebar said **BASS**
- `0X10001117` → typebar said **MIDDLE**
- `0X1000111B` → typebar said **TREBLE**
- `0X1000111F` → typebar said **PRESENCE**
- `0X10001123` → typebar said **SOLO SW**
- `0X10001127` → typebar said **SOLO LEVEL**
- `0X1000112B` → typebar said **SAG**
- `0X1000112F` → typebar said **RESONANCE**

### `0x03` AMP_BASS

**Permuted (typebar wrong):**
- `0X10001107` → real **RESONANCE** (typebar said: GAIN)
- `0X1000110B` → real **TONE** (typebar said: LEVEL)
- `0X1000110F` → real **LEVEL** (typebar said: GAIN SW)

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001113` → typebar said **BASS**
- `0X10001117` → typebar said **MIDDLE**
- `0X1000111B` → typebar said **TREBLE**
- `0X1000111F` → typebar said **PRESENCE**
- `0X10001123` → typebar said **BRIGHT SW**
- `0X10001127` → typebar said **SOLO SW**
- `0X1000112B` → typebar said **SOLO LEVEL**
- `0X1000112F` → typebar said **SAG**
- `0X10001133` → typebar said **RESONANCE**

### `0x04` CHO

**Permuted (typebar wrong):**
- `0X10001107` → real **DIRECT LEVEL** (typebar said: RATE)
- `0X1000110B` → real **RATE** (typebar said: EFFECT LEVEL)
- `0X1000110F` → real **DEPTH** (typebar said: WAVEFORM)
- `0X10001113` → real **EFFECT LEVEL** (typebar said: HIGH CUT)

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001117` → typebar said **BPM**
- `0X1000111B` → typebar said **2: RATE**
- `0X1000111F` → typebar said **2: DEPTH**
- `0X10001123` → typebar said **2: EFFECT LEVEL**
- `0X10001127` → typebar said **2: PRE-DELAY**

### `0x05` CHO_BASS

Correct:
- `0X10001107` → **RATE**
- `0X1000110B` → **DEPTH**
- `0X1000110F` → **EFFECT LEVEL**
- `0X1000111B` → **DIRECT LEVEL**

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001113` → typebar said **LOW CUT**
- `0X10001117` → typebar said **HIGH CUT**
- `0X1000111F` → typebar said **BPM**

### `0x06` CHO_PRIME

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001107` → typebar said **RATE**
- `0X1000110B` → typebar said **DEPTH**
- `0X1000110F` → typebar said **EFFECT LEVEL**
- `0X10001113` → typebar said **PRE-DELAY**
- `0X10001117` → typebar said **WAVEFORM**
- `0X1000111B` → typebar said **LOW CUT**
- `0X1000111F` → typebar said **HIGH CUT**
- `0X10001123` → typebar said **SWEETNESS**
- `0X10001127` → typebar said **BELL**
- `0X1000112B` → typebar said **OUTPUT MODE**
- `0X1000112F` → typebar said **BPM**

### `0x07` CLASS_VIBE

**Permuted (typebar wrong):**
- `0X10001107` → real **RATE** (typebar said: MODE)
- `0X1000110B` → real **DEPTH** (typebar said: RATE)
- `0X1000110F` → real **LEVEL** (typebar said: DEPTH)

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001113` → typebar said **LEVEL**

### `0x08` COMP

Correct:
- `0X10001107` → **SUSTAIN**
- `0X1000110B` → **ATTACK**
- `0X1000110F` → **LEVEL**
- `0X10001113` → **TONE**
- `0X10001117` → **DIRECT MIX**

### `0x09` X-COMP

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001107` → typebar said **SUSTAIN**
- `0X1000110B` → typebar said **ATTACK**
- `0X1000110F` → typebar said **LEVEL**
- `0X10001113` → typebar said **TONE**
- `0X10001117` → typebar said **RATIO**
- `0X1000111B` → typebar said **DIRECT MIX**

### `0x0A` X_COMP_BASS

Typebar-only (not visible in v2 — possibly enum/hidden):
- `0X10001107` → typebar said **THRESHOLD**
- `0X1000110B` → typebar said **ATTACK**
- `0X1000110F` → typebar said **LEVEL**
- `0X10001113` → typebar said **TONE**
- `0X10001117` → typebar said **RATIO**
- `0X1000111B` → typebar said **DIRECT MIX**
