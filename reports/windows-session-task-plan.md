# Windows-side Claude session: BTS USBPcap captures

You (Windows Claude) are the **executor** for the Windows-side
deferred work; the Linux-side Claude is the manager. The plan-first
restriction does not apply to you — you can write code freely.

This plan is **self-contained**: everything you need is referenced
below. Read the listed files in order before starting Task 1.

---

## 0. Pre-flight checklist

Before any task, confirm the following on this Windows machine. If
any item fails, stop and ask the user.

| # | Check | How |
|---|-------|-----|
| 1 | BOSS GX-10 connected via USB | Device Manager → "Sound, video and game controllers" lists "BOSS GX-10"; Windows Settings → MIDI shows "GX-10 MIDI IN/OUT" |
| 2 | Device firmware is **1.04** | BOSS GX-10 → MENU → SYSTEM → VERSION (or similar). If different, note it in the report. The Linux-side analysis was done at 1.04. |
| 3 | BOSS Tone Studio installed and runs | Open BTS, confirm it sees the GX-10 |
| 4 | USBPcap installed | `usbpcapcmd --extcap-interfaces` lists USB devices |
| 5 | Wireshark installed with USB-MIDI dissector | Wireshark → Edit → Preferences → Protocols → USBAUDIO present |
| 6 | tshark on PATH | `tshark --version` works, OR set in `tools/pcap_to_jsonl.py` `DEFAULT_TSHARK` |
| 7 | Python 3.10+ + venv with `python-rtmidi` | Re-create venv on Windows: `python -m venv .venv; .venv\Scripts\pip install python-rtmidi` |
| 8 | This branch checked out | `git branch --show-current` should be `windows-bts-captures` |

The captures will live in `captures/bts_<topic>/` and decoded JSONL
in `captures/bts_<topic>.jsonl`. The directory `.pcap`/`.jsonl` is
gitignored so the captures themselves don't go into the repo —
**but the decoded summary JSONL and your analysis report do**.

---

## 1. Reference index

Read these in order. They cover the protocol context, what's already
known, and what the captures should resolve.

### Linux-side findings (your "given")

- `reports/cross_check_findings.md` — every divergence between docs,
  manuals, and gxnarly code. Items P0-1..P3-4. **Items P2-2 partial,
  P2-4 partial, and several P1/P0 require BTS observation to settle.**
- `reports/linux_probe_results.md` — the empirical verdicts the
  Linux-side Claude reached against the live device. **Read the
  Summary table in §"Summary table" first; it tells you which items
  are settled vs which need BTS.**
- `reports/bts_alternatives.md` — the rationale for splitting work
  Linux/Windows. The "What requires BTS" section describes what each
  Windows task is meant to discover.

### Protocol & encoding ground truth

- `docs/protocol.md` §1, §2 (SysEx framing), §3.7 (`0x7F000000`
  system status), §3 (memory map). **§3.5 documents FX Parameters
  as 4-nibble big-endian offset binary** — verify this matches what
  BTS sends in Task 3.
- `docs/midi_firmware_analysis.md` — manual diff between v1 and v2.
  §1 covers Identity Reply, §2 the (now-doc-removed) Setup region.
- `docs/manuals/README.md` — URL sources for the Roland manuals.
  **The .md manuals are gitignored** — pull them yourself via the
  scraper `tools/scrape_gx100_v1_manual.py` or download from the
  URLs in that README. You need at minimum the v2 MIDI
  Implementation manual to cross-reference your captures.
- `docs/methodology.md` — the canonical capture pipeline (USBPcap →
  pcap_to_jsonl → sysex_decode). **Specifically read
  §"USBPcap captures both directions"**.

### Tools

- `tools/pcap_to_jsonl.py` — converts `.pcap` to JSONL events
  (timestamp, direction, sysex hex). Calls `tshark -V`. Default
  tshark path is `C:\Program Files\Wireshark\tshark.exe`.
- `tools/sysex_decode.py` — pretty-prints a JSONL event stream into
  named RQ1/DT1 with addresses + payload.
- `tools/midi_sniff.py` — WinMM-based passive MIDI sniffer (Windows
  only). Useful as a sanity check alongside USBPcap.
- `tools/midi_io_linux.py` — the rtmidi-based MIDI I/O written for
  Linux. **It works on Windows too** if you `pip install
  python-rtmidi` — rtmidi auto-selects WinMM/WinRT. Use it for
  active probes (RQ1/DT1) interleaved with BTS observation.
- `tools/probe_v2_findings.py` — Linux-side probe matrix. Useful as a
  template for Windows-side probes.

### Live device state at the time of plan-write (2026-05-09, GX-10 fw 1.04 on Linux)

These are byte-level facts the Linux-side Claude observed. Compare
your captures against them.

```
Identity Reply payload:    01 00 00 00      (sw_rev — does NOT change with firmware)
SystemCommon size:         0x2D bytes
SystemCommon dump:         00 00 0D 06 02 00 00 02 01 00 4A 00 00 01 01 00
                           01 00 01 01 00 00 00 00 00 01 62 00 01 00 00 00
                           00 00 00 00 00 00 00 00 00 02 0B 05 (45 bytes)
SystemControl size:        0x66 bytes (102 payload)
  byte 0x64 = 0x00 (Down & Up Function GX-10 — OFF default)
  byte 0x65 = 0x01 (Up & Ctl1 Function GX-10 — MANUAL default)
0x7F000000 = 0x03           (system flag, "unknown" tag in protocol.md:425)
0x7F000001 = 0x00           (handshake bit — 0x00 because BTS not connected)
0x7F000002, 0x7F000703      (timeout — populated only with active BTS handshake)
Setup region 0x00200000+:   intact (5/6 sub-blocks reply); SetupComm at +0x440 silent
TYPE 78..82 (SLICER/HUMANIZER/FEEDBACKER/SITAR SIM/AUTO WAH): all selectable on GX-10 v1.04
0x60400000:                 reads "USER 1   " — bank-label region, NOT user-patch storage
```

---

## 2. The four tasks

For each task, the structure is:

- **Goal**: what the capture should reveal
- **Procedure**: step-by-step capture instructions
- **Success criteria**: what proves the capture is good
- **Output**: where to commit results

After all four tasks, write a synthesis report (§5) and push the
branch.

---

### Task 1: BTS startup handshake capture

**Goal:** Discover exactly what BTS reads/writes at `0x7F00xxxx`
during connect/disconnect. Linux probes saw `0x7F000002` and
`0x7F000703` go silent without the handshake — capture what BTS does
to make them respond.

**Procedure:**

1. Close BTS if it's running.
2. Start USBPcap targeting the GX-10's USB device.
   ```
   USBPcapCMD.exe --extcap-interface USBPcap1 ^
     --capture --fifo captures\bts_startup\handshake.pcap
   ```
   (Adjust `USBPcap1` to whichever bus the GX-10 is on.)
3. Open BTS. Wait for it to fully load and show the patch list.
4. In BTS, change patch once (any patch). Wait 5 seconds.
5. Close BTS.
6. Stop USBPcap (Ctrl-C).
7. Convert: `python tools\pcap_to_jsonl.py captures\bts_startup\handshake.pcap > captures\bts_startup.jsonl`
8. Decode: `python tools\sysex_decode.py captures\bts_startup.jsonl > captures\bts_startup_decoded.txt`

**Success criteria:**

- The decoded file shows the Identity Request → Identity Reply pair.
- A DT1 to `0x7F000001` with value `0x01` appears (the
  editor-attached bit).
- RQ1 reads at `0x7F000000`, `0x7F000002`, `0x7F000003`,
  `0x7F000703` are visible with their reply DT1 payloads.
- Patch-change traffic at `0x10000000` shows up.
- On disconnect, a DT1 to `0x7F000001` with value `0x00` should
  appear.

**Output:**

- `captures/bts_startup.jsonl` (decoded summary — keep small;
  full pcap stays local and is gitignored)
- `captures/bts_startup_decoded.txt` (human-readable)
- Notes added to `reports/bts_capture_findings.md` §"Startup
  handshake": list of every `0x7F0xxxxx` address BTS touches, with
  the value read or written.

---

### Task 2: BTS chain-edit (INSERT / DELETE / OVERWRITE) capture

**Goal:** Settle `gaps.md §1.1` ("BROKEN" chain-edit buttons).
Determine if BTS still uses the `0x00200003 ChainEditTrigger`
handshake on this firmware, and what it writes around chain
modifications. Setup region was found intact in firmware on Linux —
this task confirms BTS still uses it.

**Procedure:**

1. Have BTS connected with a patch loaded.
2. Start a fresh USBPcap to `captures/bts_chain_edit/insert.pcap`.
3. In BTS, click INSERT on the effect chain (insert a new effect
   between two existing ones).
4. Stop USBPcap.
5. Repeat for DELETE → `delete.pcap`.
6. Repeat for OVERWRITE → `overwrite.pcap`.
7. Convert each via `pcap_to_jsonl.py` → `captures/bts_chain_<op>.jsonl`.

**Success criteria:**

- Around each chain operation, you should see DT1 writes to
  `0x00200003 ChainEditTrigger` with values `0x01` (begin) and
  `0x00` (end).
- Plus DT1 writes to the FxItem chain region near `0x10000F00+`
  (CHAIN linked-list pointers per `protocol.md:248`).
- If `0x00200003` does NOT appear, BTS has switched to a
  different handshake — **document the new addresses you see
  written as the operation begins/ends**.

**Output:**

- `captures/bts_chain_insert.jsonl`,
  `captures/bts_chain_delete.jsonl`,
  `captures/bts_chain_overwrite.jsonl`
- `reports/bts_capture_findings.md` §"Chain edit": SysEx sequence
  per operation, with hypothesised trigger byte. If
  `0x00200003` is replaced by something else, **flag this**.

---

### Task 3: BTS knob-drag for value > 15 — settles P0-1 cross-check

**Goal:** Cross-validate the Linux finding that the device interprets
each FX Parameter cell byte as a single nibble. Linux-side wrote
`[08 00 00 64]` and got back `[08 00 00 04]` — proving truncation.
Confirm BTS sends the canonical 4-nibble form (`[08 00 06 04]` for
value 100) when a slider is set to a value > 15.

**Procedure:**

1. In BTS, navigate to FxItem 1 → COMP. Note the slot/effect index
   so you know which address (per `protocol.md:249`, FxItem 1 base
   `0x10001100`, FX Parameter 2 at `0x10001107`).
2. Set FxItem 1 type to `COMP` if it isn't already.
3. Start USBPcap to `captures/bts_knob_drag/sustain_50.pcap`.
4. In BTS, drag the SUSTAIN slider so the displayed value reads
   exactly **50** — pause to make sure it's stable.
5. Stop USBPcap. Convert.
6. Repeat: drag to **100** → `sustain_100.pcap` → jsonl.
7. Repeat: drag to **1** → `sustain_1.pcap` (a value ≤ 15 — both
   encodings would coincide, sanity check).

**Success criteria:**

- `sustain_50.jsonl` shows a DT1 to `0x10001107` with payload
  exactly `[08 00 03 02]` (canonical 4-nibble form for 50 +
  0x8000 = 0x8032). If it shows `[08 00 00 32]` instead, BTS
  itself is wrong (and the device tolerates both).
- `sustain_100.jsonl` shows payload `[08 00 06 04]`.
- `sustain_1.jsonl` shows `[08 00 00 01]` (in 4-nibble: `08 00 00 01`
  = 0x8001 = 1).

**Output:**

- `captures/bts_sustain_{1,50,100}.jsonl`
- `reports/bts_capture_findings.md` §"Knob encoding": three
  hex strings, one per drag value, with a verdict line:
  > "BTS uses 4-nibble offset binary [confirmed/refuted]; gxnarly's
  > knob_cell encoder fix per P0-1 [stands/needs revision]."

---

### Task 4: BTS firmware-info dialog — discover firmware-version source

**Goal:** Linux-side Claude could not find the firmware version
exposed via SysEx (Identity Reply returns the same `01 00 00 00` on
firmware 1.0 and firmware 1.04). BTS displays the firmware version
somewhere in its UI ("About" / "Device Info" / settings dialog) —
capture the SysEx traffic when that dialog opens to discover the
address it's reading from.

**Procedure:**

1. Connect BTS to the GX-10. Wait for the patch list to load.
2. Start USBPcap to `captures/bts_fw_info/fw_dialog.pcap`.
3. In BTS, open the dialog that displays the firmware version.
   This may be in: Help → About; Settings → Device; the device
   icon/dropdown in the toolbar. **Try every dialog** that mentions
   the device.
4. Note the version BTS displays. Should match the device-screen
   value (1.04). **Take a screenshot** of the BTS dialog to
   `captures/bts_fw_info/dialog.png` for evidence.
5. Stop USBPcap. Convert.

**Success criteria:**

- Decoded JSONL shows an RQ1/DT1 round-trip whose reply contains
  bytes that decode to `1.04` or `0x01 0x04` or `01 00 04 00` or
  similar. Once you see the relevant address, **note it precisely
  in the report**.
- If no such read happens (BTS already cached the version from a
  prior session), **kill BTS, clear its config, reopen** to force a
  fresh fetch.

**Output:**

- `captures/bts_fw_info.jsonl`, `captures/bts_fw_info/dialog.png`
- `reports/bts_capture_findings.md` §"Firmware version source":
  > "BTS reads firmware version at address 0x... size N. Reply
  > payload <hex>. Encoding is <description>. This resolves
  > P1-1 — Linux-side firmware_versions.md should be updated to
  > read the version from this address instead of Identity Reply."

If no firmware-version SysEx is captured, document that and report:
> "BTS displays version <X> but does not appear to fetch it via
> SysEx during the dialog open. Possible: cached from a prior
> session, USB control transfer (not MIDI), or other."

A USB control-transfer capture would still be in the same .pcap;
look at non-MIDI USB endpoints in tshark.

---

## 3. Decoding tooling

`tools/sysex_decode.py` understands the Roland framing. To turn a
JSONL line like

```json
{"t": 1.234, "dir": "host->dev", "hex": "F0 41 10 00 00 00 00 0B 11 10 00 11 07 00 00 00 04 5E F7"}
```

into

```
+1.234s  host->dev  RQ1  addr=0x10001107 size=4
```

run

```
python tools\sysex_decode.py captures\bts_startup.jsonl
```

If `sysex_decode.py` is missing a feature you need, **extend it** —
you don't have the plan-first restriction.

---

## 4. Conventions

### Capture file naming

- Pcap files: `captures/bts_<topic>/<phase>.pcap` (gitignored)
- Decoded JSONL: `captures/bts_<topic>.jsonl` (gitignored too — but
  small enough that you can paste samples into the report)
- Screenshots / supporting images: `captures/bts_<topic>/<name>.png`
  (gitignored)

### What to commit

For each task, commit:
1. The corresponding section in `reports/bts_capture_findings.md`
   (created by you on this branch)
2. A short hex-summary file `captures/bts_<topic>.summary.md` with
   the decisive 5-20 SysEx events from each capture, hand-curated.
   **These ARE tracked.**
3. Any new tools or fixes you wrote (under `tools/`).

### What NOT to commit

- Full `.pcap` files (too big, gitignored anyway)
- Full uncurated `.jsonl` event dumps (gitignored — keep them
  locally for re-analysis)
- Any private system info from the captures (none expected, but
  watch for it)

### Branch & push

You are working on branch `windows-bts-captures`. After completing
the four tasks:

```
git add reports/bts_capture_findings.md captures/bts_*.summary.md tools/...
git commit -m "windows-bts: <one-line summary of biggest finding>"
git push origin windows-bts-captures
```

Then tell the user "Windows session done — Linux side can pull
windows-bts-captures." The Linux-side Claude will integrate.

If a task is blocked (e.g. BTS dialog doesn't fire a SysEx — Task 4
fallback) write up the blocker and continue with the others.

---

## 5. Synthesis report

After all four tasks, write a top-level synthesis at
`reports/bts_capture_findings.md` with this structure:

```
# BTS USBPcap session — findings

## Status table
| Task | Status | Headline |

## §1 Startup handshake (Task 1)
- What BTS reads/writes at 0x7F0xxxxx
- Verdict on cross_check_findings P2-4

## §2 Chain edit (Task 2)
- ChainEditTrigger address (0x00200003 or replacement)
- Verdict on gaps.md §1.1

## §3 Knob encoding (Task 3)
- Three hex strings (sustain=1, 50, 100)
- Verdict on cross_check_findings P0-1 / gxnarly knob_cell

## §4 Firmware version source (Task 4)
- Address (or "not exposed via SysEx")
- Verdict on cross_check_findings P1-1

## Open follow-ups
- Anything BTS did that you couldn't explain
- New addresses observed that aren't in protocol.md
```

That report + the `.summary.md` files in `captures/` are the
deliverable that lets the Linux-side Claude integrate findings.

---

## 6. Things to watch for

### Capture quirks

- **USBPcap requires admin** on first install; once installed, the
  driver is loaded so subsequent runs may not need elevation.
- USBPcap captures **all** USB traffic on the bus — use `tshark -Y
  sysex` or filter in Wireshark to keep noise down.
- `pcap_to_jsonl.py` requires the **reassembly** dissector — older
  Wireshark versions don't reassemble multi-URB SysEx. If decoded
  hex looks truncated, upgrade Wireshark.

### Device tolerances we already learned

- Device truncates each cell byte to its low nibble (4 bits) for FX
  Parameters. So `[08 00 00 64]` is stored as `[08 00 00 04]`. BTS
  presumably knows this — Task 3 confirms.
- Identity Reply does NOT carry firmware version — same `01 00 00 00`
  on firmware 1.0 and 1.04. Don't trust it.
- Address `0x00000080` returns the same data as `0x00000000`
  (SystemCommon aliasing). RQ1 outside known blocks may misbehave.

### BTS quirks

- BTS uses the `0x7F000001 = 0x01` handshake bit (per
  `protocol.md:464`). If a register is silent without the handshake
  (Linux observation), BTS captures should make it talk.
- BTS may cache the firmware version from a prior session
  (Task 4 fallback).
- BTS may use WebView2 for some controls — knob drags ARE MIDI
  traffic regardless, so USBPcap captures them.

---

## 7. If the device hangs

If at any point the device stops responding to MIDI:

1. Stop all captures.
2. Close BTS if open.
3. **Power-cycle the GX-10** (unplug USB, wait 5s, replug).
4. Note in the report that a power-cycle was needed and what triggered it.
5. Resume from the failed task.

Do not write to `0x7F000001 = 0x01` from your own scripts unless
you also write `0x00` on exit — the editor-attached bit must mirror
BTS's behaviour or the device gets confused.

---

## 8. Quick-start TL;DR

```
git checkout windows-bts-captures
git pull
python -m venv .venv
.venv\Scripts\pip install python-rtmidi
# Read reports/cross_check_findings.md and reports/linux_probe_results.md
# Then for each of Task 1..4:
#   1. Start USBPcap
#   2. Drive BTS through the scenario
#   3. Stop USBPcap
#   4. python tools\pcap_to_jsonl.py <pcap> > <topic>.jsonl
#   5. python tools\sysex_decode.py <topic>.jsonl > <topic>.txt
#   6. Curate captures/bts_<topic>.summary.md (committed)
#   7. Append findings to reports/bts_capture_findings.md
# Finally:
git add reports/bts_capture_findings.md captures/bts_*.summary.md
git commit -m "windows-bts: <summary>"
git push origin windows-bts-captures
```

End-of-task reporting: quote each task's "Goal" and state
done/skipped/unverified. Reference the captures and the SysEx
events that prove the verdict.
