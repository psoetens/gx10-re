# Address-gap scan

Per-effect, FxItem param offsets missing from the catalog between the first and last claimed offset. A gap is suspicious — either the catalog is missing an entry the device exposes, or the gap is real (FxItem header bytes, fixed-zero filler bytes from the chart, or addresses with no UI exposure).

Source: `captures/bts_effect_catalog.json`
Effects with gaps: **5**

## 0x0E DELAY+

- Span: 0x03 … 0x47
- Claimed: 17 knobs
- Missing: 0x1F

## 0x30 OVERTONE

- Span: 0x03 … 0x23
- Claimed: 8 knobs
- Missing: 0x17

## 0x40 SHIMMER REVERB

- Span: 0x03 … 0x4F
- Claimed: 19 knobs
- Missing: 0x2B

## 0x4B VIBRATO

- Span: 0x03 … 0x1B
- Claimed: 6 knobs
- Missing: 0x0B

## 0x4F HUMANIZER

- Span: 0x03 … 0x23
- Claimed: 8 knobs
- Missing: 0x0F
