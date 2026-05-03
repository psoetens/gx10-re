"""Per-effect TYPE/SP TYPE/MIC TYPE value enumerations,
harvested from the GX-10 Parameter Guide. Maps effect name (as
used in MemoryFxItem TYPE enum) to a dict of dropdown -> list
of value labels in declaration order.

Use to decode the byte value of e.g. COMPRESSOR's TYPE knob:
    name = PER_EFFECT_TYPES["COMPRESSOR"]["TYPE"][type_byte]
"""
PER_EFFECT_TYPES = {
    "AC RESONANCE": {
        "TYPE": ['NATURAL', 'WIDE', 'BRIGHT'],
    },
    "AIRD BASS PREAMP": {
        "MIC TYPE": ['DYN57', 'DYN421', 'CND451', 'CND87', 'RBN121', 'BLEND A', 'BLEND B', 'BLEND C', 'FLAT'],
        "SP TYPE": ['OFF', 'ORIGINAL', '1x8”', '1x10”', '1x12”', '2x12”', '4x10”', '4x12”', '8x12”', 'B1x15”', 'B1x18”', 'B2x15”', 'B4x10”', 'B8x10”', 'USER1', 'USER2', 'USER3', 'USER4', 'USER5', 'USER6', 'USER7', 'USER8', 'USER9', 'USER10', 'USER11', 'USER12', 'USER13', 'USER14', 'USER15', 'USER16'],
        "TYPE": ['NATURAL BASS', 'X-DRIVE BASS', 'CONCERT', 'STUDIO BASS', 'SILVER TUBE', 'CLASSIC BLUE', 'SOLID STACK', 'FAT TUBE', 'DARK DRV'],
    },
    "AIRD PREAMP": {
        "MIC TYPE": ['DYN57', 'DYN421', 'CND451', 'CND87', 'RBN121', 'BLEND A', 'BLEND B', 'BLEND C', 'FLAT'],
        "SP TYPE": ['OFF', 'ORIGINAL', '1x8”', '1x10”', '1x12”', '2x12”', '4x10”', '4x12”', '8x12”', 'B1x15”', 'B1x18”', 'B2x15”', 'B4x10”', 'B8x10”', 'USER1', 'USER2', 'USER3', 'USER4', 'USER5', 'USER6', 'USER7', 'USER8', 'USER9', 'USER10', 'USER11', 'USER12', 'USER13', 'USER14', 'USER15', 'USER16'],
        "TYPE": ['TRANSPARENT', 'NATURAL', 'BOUTIQUE', 'SUPREME', 'MAXIMUM', 'JUGGERNAUT', 'X-CRUNCH', 'X-HI GAIN', 'X-MODDED', 'X-ULTRA', 'X-OPTIMA', 'X-TITAN', 'JC-120', 'TWIN COMBO', 'DELUXE COMBO', 'TWEED COMBO', 'DIAMOND AMP', 'BRIT STACK', 'RECTI STACK', 'MATCH COMBO', 'BG COMBO', 'ORNG STACK', 'BGNR UB METAL'],
    },
    "ANALOG DELAY": {
        "TYPE": ['MONO', 'DIR/EFX'],
    },
    "AUTO WAH": {
        "WAVEFORM": ['TRI', 'SINE'],
    },
    "BASS CHORUS": {
        "TYPE": ['MONO', 'STEREO'],
    },
    "BASS DISTORTION": {
        "TYPE": ['BASS DS', 'BASS DI', 'HI BAND DRIVE'],
    },
    "BASS HARMONIST": {
        "VOICE": ['1VOICE', '2MONO', '2STEREO'],
    },
    "BASS PHASER": {
        "STAGE": ['4\xa0STAGE', '8\xa0STAGE', '12  STAGE'],
    },
    "BASS PITCH SHIFTER": {
        "VOICE": ['1 VOICE', '2 MONO', '2 STEREO'],
    },
    "BASS S-BEND": {
        "TRIGGER": ['OFF', 'ON'],
    },
    "BASS TOUCH WAH": {
        "POLARITY": ['DOWN', 'UP'],
    },
    "BOOSTER": {
        "TYPE": ['MID BOOST', 'CLEAN BOOST', 'TREBLE BOOST'],
    },
    "CHORUS": {
        "OUTPUT MODE": ['MONO', 'STEREO'],
        "TYPE": ['MONO', 'DIR/EFX', 'STEREO', 'DUAL'],
        "WAVEFORM": ['TRI', 'SINE'],
    },
    "CLASSIC-VIBE": {
        "MODE": ['CHORUS', 'VIBRATO'],
    },
    "COMPRESSOR": {
        "TYPE": ['BOSS COMP', 'D-COMP', 'ORANGE'],
    },
    "DELAY PLUS": {
        "MODE": ['SERIES', 'PARALLEL', 'L/R'],
        "TYPE": ['MONO', 'DIR/EFX', 'STEREO', 'PAN', 'REVERSE', 'DUAL'],
    },
    "DISTORTION": {
        "TYPE": ['DIST', 'DS-1', 'A-DIST', 'FAT DS', 'LEAD DS', 'RAT', 'GUV DS', 'DIST+'],
    },
    "DIVIDER/MIXER": {
        "MODE": ['STEREO', 'PAN L/R'],
    },
    "FEEDBACKER": {
        "MODE": ['NORMAL', 'OSC'],
        "TRIGGER": ['OFF', 'ON'],
    },
    "FUZZ": {
        "TYPE": ['OCT FUZZ', '‘60S FUZZ', 'MUFF FUZZ'],
    },
    "HARMONIST": {
        "VOICE": ['1 VOICE', '2 MONO', '2 STEREO'],
    },
    "HUMANIZER": {
        "MODE": ['This sets the mode for switching the vowels.', 'PICKING', 'AUTO'],
    },
    "METAL DISTORTION": {
        "TYPE": ['METAL DS', 'METAL ZONE', 'HM-2', 'METAL CORE'],
    },
    "OVERDRIVE": {
        "TYPE": ['NATURAL OD', 'WARM OD', 'BLUES OD', 'OD-1', 'SD-1', 'CRUNCH', 'T-SCREAM', 'TURBO OD', 'CENTA OD'],
    },
    "OVERTONE": {
        "OUTPUT MODE": ['MONO', 'STEREO'],
    },
    "PHASER": {
        "STAGE": ['4\xa0STAGE', '8\xa0STAGE', '12  STAGE'],
    },
    "PITCH SHIFTER": {
        "VOICE": ['1 VOICE', '2 MONO', '2 STEREO'],
    },
    "PRIME BASS FLANGER": {
        "WAVEFORM": ['TRI', 'SINE'],
    },
    "PRIME BASS PHASER": {
        "STAGE": ['2 STAGE', '4\xa0STAGE', '8\xa0STAGE', '16 STAGE', '24\xa0STAGE'],
        "WAVEFORM": ['TRI', 'SINE'],
    },
    "PRIME CHORUS": {
        "OUTPUT MODE": ['MONO', 'STEREO'],
        "WAVEFORM": ['TRI', 'SINE'],
    },
    "PRIME FLANGER": {
        "WAVEFORM": ['TRI', 'SINE'],
    },
    "PRIME PHASER": {
        "STAGE": ['2 STAGE', '4\xa0STAGE', '8\xa0STAGE', '16 STAGE', '24\xa0STAGE'],
        "WAVEFORM": ['TRI', 'SINE'],
    },
    "PRIME VIBRATO": {
        "TRIGGER": ['OFF', 'ON'],
    },
    "REVERB": {
        "TYPE": ['HALL S', 'HALL M', 'PLATE', 'ROOM', 'STUDIO'],
    },
    "REVERB PLUS": {
        "TYPE": ['HALL S', 'HALL M', 'PLATE', 'ROOM S', 'ROOM L', 'AMBIENCE', 'SPRING'],
    },
    "RING MODULATOR": {
        "INTELLIGENT": ['OFF', 'ON'],
    },
    "ROTARY": {
        "SPEED SELECT": ['SLOW', 'FAST'],
    },
    "S-BEND": {
        "TRIGGER": ['OFF', 'ON'],
    },
    "SEND/RETURN": {
        "MODE": ['NORMAL', 'DIRECT MIX', 'BRANCH OUT'],
    },
    "SLICER": {
        "TRIGGER": ['OFF', 'ON'],
    },
    "TERA ECHO": {
        "MODE": ['MONO', 'DIR/EFX', 'STEREO'],
        "TRIGGER": ['OFF', 'ON'],
    },
    "TOUCH WAH": {
        "POLARITY": ['DOWN', 'UP'],
    },
    "TREMOLO": {
        "TRIGGER": ['OFF', 'ON'],
    },
    "TWIST": {
        "MODE": ['RISEÓFALL', 'RISEÓFADE'],
        "TRIGGER": ['OFF', 'ON'],
    },
    "VIBRATO": {
        "TRIGGER": ['OFF', 'ON'],
    },
    "WAH": {
        "WAH TYPE": ['CRY WAH', 'VO WAH', 'FAT WAH', 'LIGHT WAH', '7STRING WAH', 'RESO WAH'],
    },
    "WARP": {
        "TRIGGER": ['OFF', 'ON'],
    },
}
