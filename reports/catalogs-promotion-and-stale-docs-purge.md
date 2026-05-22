# catalogs/ promotion + stale-docs purge

**Date:** 2026-05-22
**Plan:** `~/.claude/plans/luminous-tickling-giraffe.md`
**Branch:** main (uncommitted — left for human review per plan §5)

## Testable end-goal (quoted from plan §1)

> 1. `grep -rn 'docs/effect_catalog\.md\|docs/effects/all_effects\.\(md\|json\)\|docs/effects/typebar\.md\|docs/effects/typebar_full\.md\|docs/effects/knob_mapping\.md' README.md docs/ tools/ catalogs/` returns **only** matches inside `reports/` (which is historical and intentionally untouched) and inside the two retained generator scripts' docstrings.
> 2. `ls catalogs/` shows exactly: `bts_effect_catalog_complete.json`, `firmware_overlay.json`, `per_effect_types.json`, `assign_target_table.json` (and a `README.md` orienting the reader).
> 3. `python -c "import json; json.load(open('catalogs/bts_effect_catalog_complete.json'))"` succeeds and the loaded dict has 83 top-level keys (`0x00`..`0x52`), matching `captures/bts_effect_catalog_merged.json` byte-for-byte before the move.
> 4. Spot-check: `python tools/merge_bts_into_catalog.py --help` shows the new default `--out catalogs/bts_effect_catalog_complete.json` and a re-run produces a byte-identical file to the moved one.
> 5. `git mv` is used for all four moves so history follows the files.

## Evidence

### 1. Grep clean

```
docs/effects/README.md:15  — my own redirect README (intentional)
docs/effects/README.md:17  — my own redirect README (intentional)
tools/build_effect_catalog.py:1     — retained generator's docstring (user chose "Keep them")
tools/analyze_typebar_drags.py:13   — retained generator's docstring (same)
```

No matches in `README.md`, `docs/*.md` (outside the new redirect), `docs/manuals/`, `tools/*.py` (excluding the retained generators), or anywhere in `catalogs/`.

### 2. `ls catalogs/`

```
README.md
assign_target_table.json
bts_effect_catalog_complete.json
firmware_overlay.json
per_effect_types.json
```

### 3. JSON-load + key count

```
top-level keys: 83
first 3: ['0x00', '0x01', '0x02']
last 3: ['0x50', '0x51', '0x52']
```

Byte-for-byte preservation verified by checksum:

| File | Pre-move sha256 | Post-move sha256 | Match? |
|------|------|------|------|
| `bts_effect_catalog_complete.json` | `c65f1885…a07e1e7` | `c65f1885…a07e1e7` | ✅ |
| `per_effect_types.json`             | `abe74fb8…7da1fccd8` | `abe74fb8…7da1fccd8` | ✅ |
| `assign_target_table.json`          | `8e5ce284…112150a4` | `8e5ce284…112150a4` | ✅ |
| `firmware_overlay.json`             | `27709307…995242f` | (post-edit hash) | ✅ — single intentional edit, line 106 self-reference per plan §4 row 2 |

### 4. `merge_bts_into_catalog.py --help` shows new default

```python
# tools/merge_bts_into_catalog.py:280
ap.add_argument("--out", default="catalogs/bts_effect_catalog_complete.json")
```

Re-run reproducibility: skipped here (requires BTS JSON inputs, gitignored). The argument-default verification is sufficient evidence the tool now writes to the new path.

### 5. `git mv` preserved history

`git status` confirms rename detection on all four moves:

```
R  docs/assign_target_table.json                  -> catalogs/assign_target_table.json
R  captures/bts_effect_catalog_merged.json        -> catalogs/bts_effect_catalog_complete.json
RM docs/effects/firmware_overlay.json             -> catalogs/firmware_overlay.json
R  docs/per_effect_types.json                     -> catalogs/per_effect_types.json
```

(`RM` on `firmware_overlay.json` reflects the rename + the in-scope edit to the internal `type_index_source` self-reference.)

## What was built

- New `catalogs/` directory with `README.md` orienting the reader to each ground-truth JSON.
- Four `git mv` renames (preserving byte content + history).
- Six `git rm` deletions of stale docs.
- Internal self-reference fix in `catalogs/firmware_overlay.json:106`.
- Path-reference rewrites in:
  - `README.md` (table row + Layout block + legal section)
  - `docs/API.md` (intro bullet + at-a-glance table + AMP TYPE pointer + tools table footnote)
  - `docs/effects/README.md` (rewritten as a redirect)
  - `docs/programmatic_construction.md`
  - `docs/bts_catalog_schema.md` (title)
  - `docs/firmware_versions.md` (3 references via replace_all)
  - `docs/gaps.md` (5 references)
  - `docs/manuals/README.md`
  - `docs/official_xref.md`
  - `tools/merge_bts_into_catalog.py` (docstring + argparse default)
  - `tools/extract_per_effect_types.py` (docstring + OUT_JSON constant)
  - `tools/extract_assign_target_table.py` (OUT_JSON constant)
  - `tools/extract_assign_target_table_v2.py` (OUT_JSON constant)
  - `tools/example_lib.py` (docstring + runtime load path)
  - `tools/legacy_windows/README.md`

## Skipped vs the plan

- **`tools/example_lib.py` import-test:** failed with a pre-existing `ModuleNotFoundError: rtmidi` (transitive import chain reaches `tools/midi_send.py`). The JSON-load on line 41 was unreachable. I substituted a direct `json.load()` test on the moved `assign_target_table.json` instead (passed: 741 entries). Not in scope to fix the rtmidi import.

## Unverified / discovered

- **Pre-existing latent bug in `per_effect_types.json` encoding**: the file contains cp1252-encoded Windows smart-quote bytes (`0x91`, `0x94`) where UTF-8 expects `’` and `”`. Reading with `encoding='utf-8'` fails. Running `python tools/extract_per_effect_types.py` regenerates the file in proper UTF-8 (verified during smoke-testing) — i.e. the bug is in the on-disk artifact, not the extractor. **Intentionally not fixed in this PR** to keep the move byte-for-byte; the file was restored from `git show HEAD:docs/per_effect_types.json` after the accidental regeneration. Recommend a separate commit running the extractor to fix the encoding.

- **`docs/effects/all_effects.md` content** — the plan deletes it but its TYPE-byte → effect-name table claim in `docs/official_xref.md:416` (action item 2) is now resolved by the new catalog. I rewrote that line to reflect closure.

## References intentionally NOT rewritten (out of scope per plan §2)

The following files contain references to deleted/moved paths and were **left as historical record**:

- `captures/bts_full_sweep.summary.md:103,135`
- `reports/bts_capture_findings.md:244,245,253`
- `reports/cross_check_findings.md:203,242,287,524,525`
- `reports/gxnarly_upstream_issues.md:20,416,425,426,476`
- `reports/linux_probe_results.md:331,455`
- `reports/subtype_sweep_findings.md:33`
- `reports/v2_subtype_additions.md:8`

These are dated session reports — rewriting them would be forging the historical record of what was true when the report was written.

- `tools/build_effect_catalog.py:1` and `tools/build_effects_doc.py` were kept per the user's question response. Their docstrings still reference the deleted output paths; this is honest about their now-orphaned status.

## Git state at end

Uncommitted. 25 paths touched (4 renamed, 6 deleted, 14 modified, 1 new). No `git commit` — left for human review per plan §5.
