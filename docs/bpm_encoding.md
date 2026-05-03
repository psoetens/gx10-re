# BPM byte encoding

The Master BPM at SysEx address `0x1000_0F02` is stored as a 4-byte block
where each byte uses only its low 4 bits (a "nibble" — Roland's standard
multi-byte numeric encoding). The four nibbles form a single big-endian
value:

```
V = nibble[0] * 0x1000  +  nibble[1] * 0x100  +  nibble[2] * 0x10  +  nibble[3]
```

and the BPM displayed in Tone Studio is

```
BPM_display = V / 10
```

That is, the unit on the wire is 0.1 BPM. The GX-10 only lets the user
set integer BPM, so each UP/DOWN arrow press changes V by 10.

| BPM display | V | DT1 payload (4 bytes) |
|------------:|--:|-----------------------|
| 40 (min)  | 400  | `00 01 09 00` |
| 50        | 500  | `00 01 0F 04` (V=500 = 0x1F4) |
| 100       | 1000 | `00 03 0E 08` (V=1000 = 0x3E8) |
| 121       | 1210 | `00 04 0B 0A` (V=1210 = 0x4BA) |
| 200       | 2000 | `00 07 0D 00` (V=2000 = 0x7D0) |
| 250 (max) | 2500 | `00 09 0C 04` (V=2500 = 0x9C4) |

Captured directly: at BPM=250 (after saturating UP), the next DOWN press
emitted `00 09 0C 04`, BPM = 250 confirmed. After saturating DOWN, the
last distinct payload before clamping was `00 01 09 00`, BPM = 40.

This same nibble-pair encoding scheme almost certainly applies to every
BPM-style knob in the GX-10 (delay TIME ms with BPM-sync, harmonist
PRE-DELAY ms, etc. — all advertised in the manual as "0–N ms, BPM ŀ–Ō").
The address differs per knob; the encoding is the same.

## Sweep capture

`tools/investigate_bpm.py` loads CHO into slot 0, focuses the BPM knob
(window-local position 1269, 590), then drives it from 49 → 250 via 250
UP presses, then back down via 220 DOWN + 50 saturating DOWN. The pcap
is at `captures/bpm_test/bpm_sweep.pcap` and the JSONL at
`bpm_sweep.jsonl`. Screenshots `after_up.png` and `after_down.png`
verify the GUI clamped at 250 and 40 respectively.
