"""Effect-name → display colour, harvested directly from BTS's
effect_parameter.js + the BASIC_COLOR palette in chain_config.js.

Last regenerated 2026-05-03 from the local BTS install. The keys here
match the chart's MemoryFxItem TYPE-enum names (and the Parameter
Guide manual headings); values are the BASIC_COLOR palette names BTS
uses for its chain hexes — which are also the colours the device's
firmware paints on its physical LEDs.
"""
BASIC_COLOR_RGB = {
    "blue":       "#7083ff",
    "brown":      "#d2b071",
    "cyan":       "#1ed6be",
    "dark_blue":  "#0951a5",
    "green":      "#76c747",
    "light_blue": "#53b7e6",
    "orange":     "#e69112",
    "pink":       "#f558bb",
    "purple":     "#bb5ecc",
    "red":        "#e6393f",
    "white":      "#d2d4d6",
    "yellow":     "#dbca32",
    "blank_gray": "#444444",
    "gray_blank": "#444444",
}

# Friendly display names matching what a user actually sees on the device's
# LEDs / BTS chain hexes. BTS's internal "blue" key is #7083ff which reads
# as a saturated deep blue/indigo; "light_blue" is sky blue; "cyan" is
# really teal/turquoise.
FRIENDLY_COLOR_NAME = {
    "blue":       "deep blue",
    "light_blue": "light blue",
    "dark_blue":  "dark blue",
    "cyan":       "teal",
    "green":      "green",
    "red":        "red",
    "yellow":     "yellow",
    "orange":     "orange",
    "purple":     "purple",
    "pink":       "pink",
    "brown":      "brown",
    "white":      "white",
    "blank_gray": "(off)",
    "gray_blank": "(off)",
}

# Effect category → colour key. Verified by direct inspection of
# BTS's html/js/config/effect_parameter.js (each effect block has a
# top-level `"color": <name>` field).
EFFECT_COLOR = {
    # Compressor family
    "COMPRESSOR":            "blue",
    "X COMPRESSOR":          "blue",
    "X-COMP":                "blue",
    "X BASS COMPRESSOR":     "blue",
    "X-BASS COMP":           "blue",
    # Booster / Drive family
    "BOOSTER":               "yellow",
    "OVERDRIVE":             "yellow",
    "BASS OVERDRIVE":        "yellow",
    "X OVERDRIVE":           "yellow",
    "X-OD":                  "yellow",
    "X BASS OVERDRIVE":      "yellow",
    "X-BASS OD":             "yellow",
    # Distortion family — orange
    "DISTORTION":            "orange",
    "BASS DISTORTION":       "orange",
    "X DISTORTION":          "orange",
    "X-DS":                  "orange",
    "METAL DISTORTION":      "orange",
    "METAL":                 "orange",
    "BASS METAL DISTORTION": "orange",
    "BASS METAL":            "orange",
    "FUZZ":                  "orange",
    "BASS FUZZ":             "orange",
    # AMP family
    "AIRD PREAMP":           "red",
    "AIRD BASS PREAMP":      "red",
    # Chorus / Overtone
    "CHORUS":                "light_blue",
    "BASS CHORUS":           "light_blue",
    "PRIME CHORUS":          "light_blue",
    "OVERTONE":              "light_blue",
    "VIBRATO":               "light_blue",
    "PRIME VIBRATO":         "light_blue",
    "VIBRATO PRIME":         "light_blue",
    # Flanger family — purple
    "FLANGER":               "purple",
    "BASS FLANGER":          "purple",
    "PRIME FLANGER":         "purple",
    "PRIME BASS FLANGER":    "purple",
    "FLANGER PRIME":         "purple",
    "BASS FLANGER PRIME":    "purple",
    # Phaser family — TEAL (per BTS), often called cyan
    "PHASER":                "cyan",
    "BASS PHASER":           "cyan",
    "PRIME PHASER":          "cyan",
    "PRIME BASS PHASER":     "cyan",
    "SCRIPT PHASER":         "cyan",
    "PARAMETRIC EQUALIZER":  "cyan",
    "GRAPHIC EQUALIZER":     "cyan",
    "PAN":                   "cyan",
    "SEND/RETURN":           "cyan",
    # Pitch shifters — deep blue
    "HARMONIST":             "blue",
    "BASS HARMONIST":        "blue",
    "PITCH SHIFTER":         "blue",
    "BASS PITCH SHIFTER":    "blue",
    "FEEDBACKER":            "blue",
    "SITAR SIM":             "blue",
    "SITAR SIMULATOR":       "blue",
    # Octave / Acoustic / Touch — brown
    "OCTAVE":                "brown",
    "POLY OCTAVE":           "brown",
    "OCTAVE POLY":           "brown",
    "BASS OCTAVE":           "brown",
    "OCTAVE BASS":           "brown",
    "AC GUITAR SIMULATOR":   "brown",
    "AC RESONANCE":          "brown",
    "TOUCH WAH":             "brown",
    "BASS TOUCH WAH":        "brown",
    "AUTO WAH":              "brown",
    "ROTARY":                "brown",
    "HUMANIZER":             "brown",
    # Delay / Tape — white
    "DELAY":                 "white",
    "DELAY PLUS":            "white",
    "ANALOG DELAY":          "white",
    "SPACE ECHO":            "white",
    "SHIMMER DELAY":         "white",
    "TWIST":                 "white",
    "WARP":                  "white",
    "TERA ECHO":             "white",
    "FOOT VOLUME":           "white",
    "DIVIDER":               "white",
    "MIXER":                 "white",
    "NOISE SUPPRESSOR":      "white",
    # Reverb family — pink
    "REVERB":                "pink",
    "REVERB PLUS":           "pink",
    "SHIMMER REVERB":        "pink",
    # Modulation specials — green
    "TREMOLO":               "green",
    "CLASSIC-VIBE":          "green",
    "CLASSIC VIBE":          "green",
    "RING MODULATOR":        "green",
    "SLICER":                "green",
    # Pedal-controlled effects — purple
    "WAH":                   "purple",
    "BASS WAH":              "purple",
    "BASS_WAH":              "purple",
    "PEDAL BEND":            "purple",
    "BASS PEDAL BEND":       "purple",
    "S-BEND":                "purple",
    "BASS S-BEND":           "purple",
    "SLOW GEAR":             "purple",
    "BASS SLOW GEAR":        "purple",
    "DEFRETTER":             "purple",
    "BASS DEFRETTER":        "purple",
    # Loop / non-effect
    "PHRASE LOOP":           "red",
    "MASTER":                "dark_blue",
}


# Pedal Function (per chart's MemoryCommon Function fields) → likely
# LED colour when the pedal is in a STATEFUL configuration (TUNER on,
# AMP CTL on, etc.). Navigation-only Functions (BANK DOWN, MEMORY ±1,
# "1") deliberately omitted — those don't paint a manual-mode LED;
# their LED meaning comes from the global pedal mode (UP/DOWN /
# BANK/NUM) or from an explicit Assign.
FUNCTION_COLOR = {
    "BPM TAP":     "yellow",
    "TUNER":       "green",
    "MEMORY/MAN":  "white",
    "TUNER/MAN":   "green",
    "MAN/TUNER":   "green",
    "AMP CTL 1":   "red",
    "AMP CTL 2":   "red",
    "DIV CH.SEL":  "green",   # state-driven: green path A, red path B
    "SEND/RETURN": "cyan",
    "LOOP CTL":    "red",
    "LOOP STOP":   "red",
    "LOOP CLEAR":  "red",
    "MIDI START":  "white",
}

# Functions that don't paint a manual-mode LED (just navigation actions).
NAVIGATION_FUNCTIONS = {
    "OFF", "1", "BANK DOWN", "BANK UP",
    "MEMORY -1", "MEMORY +1",
}

# Effect TYPE-enum names that respond to a PEDAL (EXP) input. When EXP1 SW
# (or EXP1 itself) is set to "PFX" with no explicit Assign, the device
# routes to whichever of these is in the current chain.
PEDAL_FX_EFFECTS = (
    "WAH", "BASS_WAH", "BASS WAH",
    "PEDAL BEND", "BASS PEDAL BEND",
    "TOUCH WAH", "BASS TOUCH WAH",
    "S-BEND", "BASS S-BEND",
    "AUTO WAH",
)


def friendly(color_name: str) -> str:
    """Return human-friendly name + RGB for a BTS color key, e.g.
    'blue' -> 'deep blue (#7083ff)'."""
    if not color_name:
        return ""
    name = FRIENDLY_COLOR_NAME.get(color_name, color_name)
    rgb = BASIC_COLOR_RGB.get(color_name, "")
    return f"{name} {rgb}".strip()
