"""GUI knob-order overrides for effects whose BTS GUI does NOT lay out
knobs in the manual's listed order.

Background: HARMONIST and PITCH SHIFTER (and bass variants) list params
in the Parameter Guide as paired rows like "1: HARMONY  2: HARMONY".
The default xref expand-paired logic renders this as
[1:HARMONY, 2:HARMONY, 1:LEVEL, 2:LEVEL, ...].

But BTS's GUI in default VOICE=1 mode shows ONLY the 1:* params plus
some global knobs (KEY, DIRECT LEVEL, BPM). That's also why the captured
USB sweeps wrote to FX parameter slots in 1-then-global order — not the
paired order.

The captured drag.png screenshots confirm:
  HARMONIST (VOICE=1):     [1:HARMONY, 1:LEVEL, 1:PRE-DELAY,
                            1:FEEDBACK, KEY, DIRECT LEVEL, BPM]
  PITCH SHIFTER (VOICE=1): [1:PITCH, 1:FINE, 1:MODE, 1:PRE-DELAY,
                            1:FEEDBACK, 1:LEVEL, DIRECT LEVEL, BPM]

The bass variants (BASS HARMONIST, BASS PITCH SHIFTER) follow the same
pattern with their own captured knob counts (7 and 8 respectively).
"""

# Map: effect manual heading -> ordered list of knob names as displayed
# in BTS GUI (VOICE=1 default mode after drag-to-empty-slot).
GUI_OVERRIDE = {
    "HARMONIST": [
        "1: HARMONY", "1: LEVEL", "1: PRE-DELAY", "1: FEEDBACK",
        "KEY", "DIRECT LEVEL", "BPM",
    ],
    "BASS HARMONIST": [
        # Bass variant lacks KEY (no diatonic scale param) per chart
        # ASSIGN TARGET indices 522-530. Captured 7 knobs in default state.
        "1: HARMONY", "1: LEVEL", "1: PRE-DELAY", "1: FEEDBACK",
        "DIRECT LEVEL", "BPM", "MEMORY LEVEL",
    ],
    "PITCH SHIFTER": [
        "1: PITCH", "1: FINE", "1: MODE", "1: PRE-DELAY",
        "1: FEEDBACK", "1: LEVEL", "DIRECT LEVEL", "BPM",
    ],
    "BASS PITCH SHIFTER": [
        # Bass variant captured 8 knobs in default state, same pattern.
        "1: PITCH", "1: FINE", "1: MODE", "1: PRE-DELAY",
        "1: FEEDBACK", "1: LEVEL", "DIRECT LEVEL", "BPM",
    ],
}


def get_override(manual_heading: str):
    """Return ordered knob names for `manual_heading`, or None."""
    return GUI_OVERRIDE.get(manual_heading)
