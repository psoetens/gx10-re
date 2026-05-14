# legacy_windows — Windows-only RE tooling (frozen)

These scripts drove BOSS TONE STUDIO's UI on Windows during the original
protocol reverse-engineering effort: UI automation via `uiautomation` /
`pyautogui`, screenshot diffing via PIL on captures of the Windows BTS
window, USBPcap-driven traces, `taskkill`-based BTS lifecycle. They are
**not portable to macOS or Linux without rewriting** against the
platform's native automation / capture APIs.

They are kept here as historical record and as a fallback for anyone
extending the Windows-side RE. The protocol they helped reveal is now
fully decoded (`docs/protocol.md`, `docs/effect_catalog.md`,
`docs/assign_target_table.json`), so day-to-day device interaction does
**not** need anything from this directory.

For cross-platform device interaction, use the tools in `tools/` —
they go through `midi_send` / `midi_sniff` (rtmidi backend on
macOS/Linux, WinMM on Windows) or `midi_io` directly, no UI required.

## Buckets

- `bts_resweep_*` and `bts_capture_and_label` — driven BTS UI captures
  (`uiautomation` + Win32 screenshots). Genuinely Windows-only.
  *(Two portable siblings — `bts_orchestrate` and `bts_capture_with_pause` —
  were promoted to `tools/` on 2026-05-14, behind `tools/bts_launcher.py`,
  once BTS-on-Mac was made to work via v1.0.0.)*
- `capture_*` — driven BTS UI captures (`pyautogui` click + screenshot).
- `diagnose_chain_buttons*` — Win32 SendInput diagnostics for the BTS
  INSERT/DELETE/OVERWRITE buttons (resolved; see `docs/gaps.md` §I).
- `drive_*`, `drag_*`, `explore_*`, `map_all_effects`, `map_knob` —
  driven BTS interactions for the original typebar / effect probe sweeps.
- `probe_*` (the seven in here) — `uiautomation`-driven dropdown probes;
  the rest of the `probe_*` family in `tools/` is portable.
- `compare_*`, `crop_*`, `find_hex_centers`, `find_scrollbar`,
  `inspect_click_coords`, `test_knob_detect`, `zoom_image` — PIL
  postprocessing of Windows BTS screenshots.
- `focus_ts`, `inspect_ui`, `screenshot`, `scroll_typebar`,
  `slot0`, `sweep_all_knobs`, `sweep_knob`, `test_drag`,
  `test_type_selection`, `investigate_bpm` — assorted Win32 UI helpers.
