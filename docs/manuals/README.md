# Roland documentation — fetch yourself, do not commit

This directory is intentionally empty in the public repository. The
tools that reference Roland's official manuals (`tools/manual_xref_v2.py`,
`tools/build_effect_catalog.py`, `tools/extract_assign_target_table_v2.py`,
`tools/extract_per_effect_types.py`) expect the following two files to
be placed here by the user:

| File | Source |
|------|--------|
| `GX-100_GX-10_MIDI_Imple_eng02_W.md` | Convert page 1 of the **MIDI Implementation chart** (PDF on Roland's support site) to Markdown. The chart documents every SysEx address and parameter of the GX-100 / GX-10. |
| `GX-10_Parameter_Guide.txt` | Convert the **Parameter Guide** PDF to plain text. Source: Roland's support page for the GX-10. |

The Markdown chunks (`GX-10_Parameter_Guide_0[1-6]_*.md`) used by some
tools are split slices of `GX-10_Parameter_Guide.txt`. The
chunked layout matches the manual's section breaks and is produced by
a one-time `tools/split_parameter_guide.py` script (left to the reader
as it depends on the local PDF→text tool of choice).

## Why aren't they in the repo?

These documents are © Roland Corporation. The reverse-engineering work
in this repository is independently observable behaviour of devices
you own, written up in our own words — that's standard interoperability
research and is legal in the jurisdictions where the contributors live
(EU, US, JP). Wholesale redistribution of Roland's published manuals,
on the other hand, would be a clear copyright violation regardless of
the engineering exemption. So we don't ship them.

If you want the optional manual-cross-reference features, download the
official PDFs from <https://www.boss.info/global/support/by_product/gx-10/updates_drivers/>
(or the equivalent Roland regional site) and place the conversions in
this directory.

## Repository works fine without them

Most of the tools work without any manual files present. Only the
manual-cross-reference / catalog-generation tooling needs them. The
canonical `docs/effect_catalog.md` and `docs/assign_target_table.json`
in this repo are pre-generated artifacts that capture the relevant
information in our own structured form.
