# Legal assessment — BTS .js source inspection during interoperability RE

**Not legal advice.** This document is a non-lawyer's working
understanding of where the BTS JS reading/diffing in this repo sits
relative to the legal frameworks that protect reverse engineering for
interoperability. Consult counsel for anything that matters.

## What we did

Two distinct activities show up in this repo's analysis:

1. **Behavioural observation.** Sniffing the SysEx stream between BTS
   and the GX-10 with a passive MIDI sniffer, decoding it against the
   chart, and writing down what we saw. Pure observation; no
   inspection of BTS's internals.

2. **Source inspection.** Reading the JavaScript files Roland ships
   inside the BTS macOS bundle (`Contents/Resources/html/js/...`),
   running `diff -r` between two BTS versions, citing line numbers
   and small code excerpts in our docs to explain how a SysEx
   exchange we observed was constructed on the BTS side. We did this
   for `chain_controller.js`, `midi_observe_controller.js`,
   `midi_connect_controller.js`, `product_setting.js`,
   `librarian_setting.js`, and a handful of others.

Activity (2) is the one this assessment addresses.

## Why BTS's source is legible

Roland ships BTS as an Electron-style desktop application. The JS
files are **plain-text source** in the signed bundle (no obfuscation,
no minification, no bytecode compilation). Anyone who runs the
installer sees them. We did not decompile, disassemble, or strip
DRM — we just read files Roland shipped in cleartext.

This is materially different from cases where RE involves bypassing
a technical protection measure or undoing a compilation step. Our
activity is closer to "reading the installed documentation that the
vendor placed on your disk" than to traditional RE.

## Legal frameworks that protect interoperability RE

A non-exhaustive list of the carve-outs the broader gx10-re project
relies on (already cited in `README.md`):

- **EU Software Directive Article 6** — decompilation for
  interoperability is permitted without the rightsholder's consent
  when (a) it's indispensable to obtain interoperability
  information, (b) the info isn't readily available, and (c) the
  acts are confined to the parts necessary for interoperability.
  In our case the BTS source isn't even compiled, so the threshold
  question of "decompilation" doesn't arise — Article 6 was written
  for harder cases than this.
- **US 17 USC §1201(f)** — DMCA carve-out specifically for
  reverse-engineering for interoperability. §117 covers backup
  copies of lawfully owned software.
- **Equivalent provisions in JP, AU, CA, etc.** — protect RE for
  interop or for non-commercial study.

A user who lawfully owns BTS (via owning a GX-10 and accepting
Roland's EULA at install time) reading the .js files Roland placed
on their own disk for interop purposes is well inside the protected
zone in every jurisdiction these provisions touch.

## EULA terms

BTS's EULA (and Roland's general software license) likely contains
boilerplate "you may not reverse-engineer, decompile, disassemble"
text. In the EU these clauses are **expressly unenforceable** to the
extent they conflict with the Software Directive — Article 8 voids
contractual provisions that try to circumvent the interop carve-out.
US courts are split on enforceability of such clauses for interop
purposes; the safest interpretation for the project is to lean on
§1201(f) rather than try to overrule the EULA contractually.

The project's stance, as already documented in `README.md`:

> "It is independent reverse-engineering of behaviour observable on
> a device the contributors own, performed for the purpose of
> interoperability (driving the device from non-BOSS software). The
> work is permitted under EU Software Directive Article 6
> (decompilation for interoperability), US 17 USC §1201(f) and §117,
> and equivalent provisions in JP/AU/CA."

## Specific things we did and how they sit

| Activity | Risk profile | Mitigation in this repo |
|---|---|---|
| Reading the .js files shipped in BTS's signed bundle | Low. The files are uncompressed, unobfuscated cleartext placed by the vendor on the user's own disk. | None needed beyond not redistributing the files. |
| Citing line numbers + 1–10-line code excerpts in our docs | Low. Small, transformative quotation for documentation/interop purposes — fair use under US law, quotation right under EU law. | Excerpts are kept short (typically ≤ 10 lines), attributed by file + line, used to explain protocol behaviour rather than as a substitute for the original. |
| Running `diff -r` between two BTS versions | Same as reading either alone. | n/a |
| Redistributing the .js files themselves | **Would be infringing.** This is what `README.md` already prohibits ("It is not a redistribution of Roland's documentation or software"). | The .js files are not in this repo. `docs/manuals/` is intentionally empty for the same reason. |
| Modifying the BTS bundle locally (the chain-button-bug overlay patch) | Low. Modifying your own copy of installed software for personal interop use is squarely within §117 (US) and the equivalent in EU. | The patched bundle stays on the maintainer's machine. The patch source is described conceptually in `docs/bts_mac_chain_button_bug.md` but no Roland code is redistributed. |
| Publishing analysis (this repo's docs) | Low. Documenting what we learned, with small quotations, for interop purposes. | The repo's MIT licence only covers the original prose/code; it explicitly disclaims coverage of Roland IP referenced. |

## What we deliberately don't do

- **No redistribution of Roland source files**, compiled binaries,
  or manuals. `docs/manuals/README.md` instructs users to download
  the chart and parameter guide from Roland themselves.
- **No bypassing of DRM or copy protection** — BTS doesn't have any
  that we touched.
- **No use of Roland trademarks to imply endorsement** — the project
  name is `gx10-re` (reverse-engineering); the README opens with a
  thank-you to Roland and frames the work as interop, not competition.
- **No commercial product** built on the RE — this is one person's
  hobby project, MIT-licensed.

## Where we'd want a lawyer

The only activity that's worth a second opinion if the project ever
grows beyond hobby scale:

- **Larger code excerpts** in documentation. We've kept them small
  so far. If a future doc needs to quote a 50-line function verbatim
  to explain a subtle behaviour, talk to a lawyer about fair use /
  quotation right thresholds first.
- **Distributing a patched BTS bundle**. We didn't and won't. If
  someone else wants to, they need their own legal assessment —
  redistribution of a modified copy of a signed proprietary app is a
  different bar than modifying your own copy.
- **Commercial fork**. If the project ever produces a commercial
  product that competes with BTS, the interop defences narrow.
  Hobby/educational use isn't the same as building a competitor.

## Conclusion

The BTS .js inspection and diffing in this repo is well inside the
protected zone for interoperability RE in every relevant jurisdiction.
The activity is closer to "studying the protocol documentation
Roland placed on your disk" than to traditional reverse engineering.
The repo's existing safeguards — no redistribution of Roland's files,
small fair-use quotations, MIT licence on the original work only,
explicit framing as interop — match the standard pattern for this
kind of project (Wine, Mesa, OpenAL, countless device drivers).

If Roland ever objects (the README invites them to do so via a GitHub
issue rather than a takedown), the right move is to engage and adjust
specific framing rather than to fold — the legal posture is solid.
