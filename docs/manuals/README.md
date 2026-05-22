# Roland documentation — fetch yourself, do not commit

This directory is intentionally empty in the public repository. The
tools that reference Roland's official manuals (`tools/manual_xref_v2.py`,
`tools/build_effect_catalog.py`, `tools/extract_assign_target_table_v2.py`,
`tools/extract_per_effect_types.py`) expect the following files to be
placed here by the user.

| File | Source |
|------|--------|
| `GX-100_GX-10_MIDI_Imple_eng02_W.md` | Convert the **combined MIDI Implementation chart** (PDF on Roland's support site) to Markdown. Documents every SysEx address and parameter for both the GX-100 and the GX-10. |
| `GX-10_Parameter_Guide.txt` | Convert the **GX-10 Parameter Guide** PDF to plain text. |
| `GX-10_Parameter_Guide_0{1-6}_*.md` | Chunked Markdown slices of the GX-10 Parameter Guide. Produced once via `tools/split_pdf.py` followed by Google Docs export (see "Pipeline" below). |
| `GX-100_Parameter_Guide_0{1-6}_*.md` | Same, for the GX-100 v2.0 Parameter Guide PDF. |
| `GX-100_v1_Parameter_Guide_0{1-6}_*.md` | Pre-firmware-2.0 version of the GX-100 Parameter Guide. The PDF available from Roland renders tables as image overlays that don't OCR cleanly, so this set is produced by **scraping the older HTML version** of the manual (see `tools/scrape_gx100_v1_manual.py`). |

## Authoritative parameter references

When the next session needs authoritative knob ranges, defaults, units,
and enum lists, pull them from the **Parameter Guide** (NOT the
Reference Manual — that's user-facing, not protocol-detail):

- **GX-10 v1.0 Parameter Guide** (launch firmware, all effects present):
  <https://static.roland.com/manuals/gx-10_parameter/en-US/index.html>
  - AIRD PREAMP TYPE list (full amp roster): `161209995162206219.html`
  - TARGET list (ASSIGN target catalogue): `96463755159001739.html`
- **GX-100 v2.0 Parameter Guide** (after the v2.0 firmware update,
  matches the GX-10 effect set):
  <https://static.roland.com/manuals/gx-100_parameter_v200/en-US/index.html>
- **GX-100 v1.0 Parameter Guide** (pre-v2.0 firmware, smaller effect
  set — for verifying which effects were actually new in v2.0):
  <https://static.roland.com/manuals/gx-100_parameter/eng/25629758.html>

The GX-10 v1.0 guide and GX-100 v2.0 guide should largely match for the
effects roster (since v2.0 closed the gap). Use the GX-10 v1.0 guide as
the primary source; cross-check the GX-100 v2.0 guide for device-
specific differences (e.g. OUTPUT SELECT list).

## Pipeline

For PDF-derived chunks (GX-10 and GX-100 v2):

1. Download the PDF from Roland's support page.
2. `python tools/split_pdf.py <PDF> docs/manuals/ --ranges <chunks>` slices
   it into ~10–50 page chunks at chapter boundaries. The chunk labels
   used in the existing tracked layout are
   `effects_distortion`, `effects_mod_pitch`, `effects_delay_misc`,
   `effects_bass_master`, `menu`, `write_soundlist`.
3. Upload each chunk to Google Drive, open in Google Docs, then
   File → Download → Markdown (.md). Save back into this directory.
4. Optionally strip the embedded base64 image data (Google Docs
   inlines `[image1]: <data:image/png;base64,…>` definitions that bloat
   the file). A short Python one-liner does it:
   ```python
   import re, pathlib
   for p in pathlib.Path('docs/manuals').glob('*.md'):
       txt = p.read_text(encoding='utf-8')
       lines = [l for l in txt.splitlines() if not re.match(r'^\[image\d+\]:\s*<data:image/', l)]
       p.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
   ```

For the GX-100 v1 chunks (which don't OCR cleanly from the PDF):

```
python tools/scrape_gx100_v1_manual.py
```

Walks the older Confluence-style HTML manual, converts each effect /
section page to Markdown with proper tables, and writes 6 chunk files
matching the rest of the tracked layout. Local cache lives in
`_scrape/`; safe to delete or re-run.

## Why aren't they in the repo?

These documents are © Roland Corporation. The reverse-engineering work
in this repository is independently observable behaviour of devices
you own, written up in our own words — that's standard interoperability
research and is legal in the jurisdictions where the contributors live
(EU, US, JP). Wholesale redistribution of Roland's published manuals,
on the other hand, would be a clear copyright violation regardless of
the engineering exemption. So we don't ship them; we ship the
extraction tooling so you can produce your own copies on a machine you
own.

## Repository works fine without them

Most of the tools work without any manual files present. Only the
manual-cross-reference / catalog-generation tooling needs them. The
canonical `catalogs/bts_effect_catalog_complete.json` and
`catalogs/assign_target_table.json` in this repo are pre-generated
artifacts that capture the relevant information in our own structured
form.
