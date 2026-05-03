"""
Authoritative catalog of all 81 GX-10 effects across 3 type-bar pages.

Per-effect data:
  - page (0, 1, 2) — scrollbar position
  - idx (0..N-1) — position on the page
  - name — human-readable
  - color — predominant hex color (RGB)
  - x_win — window-local x of the hex center (for drag-from)

The 30 hexes on a page are equally spaced at ~56px from x≈254 to x≈1884.
Page 2 (bass) only has 21 effects.
"""

# Each entry: (name, color_RGB)
# Page 0 (default view, COMP through HARM)
PAGE_0 = [
    ("COMP",        (124, 119, 199)),  # purple
    ("X-COMP",      (124, 119, 199)),
    ("BOOST",       (200, 195, 50)),   # yellow
    ("OD",          (200, 195, 50)),
    ("X-OD",        (200, 195, 50)),
    ("DIST",        (218, 130, 32)),   # orange
    ("X-DIST",      (218, 130, 32)),
    ("METAL",       (218, 130, 32)),
    ("FUZZ",        (218, 130, 32)),
    ("AMP",         (210, 38, 48)),    # red
    ("PEQ",         (110, 183, 231)),  # cyan
    ("GEQ",         (110, 183, 231)),
    ("CHO",         (110, 183, 231)),
    ("CHO_PRIME",   (110, 183, 231)),
    ("FL",          (165, 84, 175)),   # magenta
    ("FL_PRIME",    (165, 84, 175)),
    ("PH",          (75, 200, 165)),   # teal
    ("PH_SCRIPT",   (75, 200, 165)),
    ("PH_PRIME",    (75, 200, 165)),
    ("CLASS_VIBE",  (160, 196, 60)),   # lime
    ("ROTARY",      (160, 140, 70)),   # tan/olive
    ("VIB",         (110, 183, 231)),  # cyan
    ("VIB_PRIME",   (110, 183, 231)),
    ("TREM",        (160, 196, 60)),   # lime
    ("PAN",         (160, 196, 60)),
    ("RING_MOD",    (160, 140, 70)),   # tan
    ("SLICER",      (110, 183, 231)),
    ("HMN",         (165, 84, 175)),   # magenta
    ("PS",          (124, 119, 199)),  # purple
    ("HARM",        (124, 119, 199)),
]

# Page 1 (OVER TONE through LOOP)
PAGE_1 = [
    ("OVER_TONE",       (110, 183, 231)),  # cyan
    ("OCT",             (200, 195, 50)),
    ("OCT_POLY",        (200, 195, 50)),
    ("DELAY",           (200, 200, 200)),  # white/gray
    ("DELAY_PLUS",      (200, 200, 200)),
    ("DELAY_ANALOG",    (200, 200, 200)),
    ("SPACE_ECHO",      (200, 200, 200)),
    ("DELAY_SHIMMER",   (200, 200, 200)),
    ("TERA_ECHO",       (200, 200, 200)),
    ("DELAY_TWIST",     (200, 200, 200)),
    ("DELAY_WARP",      (200, 200, 200)),
    ("REV",             (220, 80, 150)),   # pink
    ("REV_PLUS",        (220, 80, 150)),
    ("REV_SHIMMER",     (220, 80, 150)),
    ("AC_SIM",          (180, 160, 100)),  # tan
    ("AC_RESO",         (180, 160, 100)),
    ("FB",              (220, 220, 220)),  # white
    ("SITAR_SIM",       (165, 84, 175)),   # magenta/purple
    ("SG",              (165, 84, 175)),
    ("DEFRET",          (165, 84, 175)),
    ("T_WAH",           (165, 84, 175)),
    ("A_WAH",           (165, 84, 175)),
    ("S_BEND",          (220, 220, 220)),  # white
    ("WAH",             (165, 84, 175)),
    ("PB",              (165, 84, 175)),
    ("FOOT_VOL",        (220, 220, 220)),
    ("NS",              (220, 220, 220)),
    ("DIV_MIX",         (200, 200, 200)),
    ("SEND_RETURN",     (75, 200, 165)),   # teal
    ("LOOP",            (210, 38, 48)),    # red
]

# Page 2 (bass effects)
PAGE_2 = [
    ("X_COMP_BASS",     (124, 119, 199)),
    ("OD_BASS",         (200, 195, 50)),
    ("X_OD_BASS",       (200, 195, 50)),
    ("DIST_BASS",       (218, 130, 32)),
    ("METAL_BASS",      (218, 130, 32)),
    ("FUZZ_BASS",       (218, 130, 32)),
    ("AMP_BASS",        (210, 38, 48)),
    ("CHO_BASS",        (75, 200, 165)),
    ("FL_BASS",         (165, 84, 175)),
    ("FL_PRIME_BASS",   (165, 84, 175)),
    ("PH_BASS",         (75, 200, 165)),
    ("PH_PRIME_BASS",   (75, 200, 165)),
    ("PS_BASS",         (124, 119, 199)),
    ("HARM_BASS",       (124, 119, 199)),
    ("OCT_BASS",        (200, 195, 50)),
    ("SG_BASS",         (165, 84, 175)),
    ("DEFRET_BASS",     (165, 84, 175)),
    ("T_WAH_BASS",      (180, 160, 100)),
    ("S_BEND_BASS",     (220, 220, 220)),
    ("WAH_BASS",        (165, 84, 175)),
    ("PB_BASS",         (165, 84, 175)),
]


def hex_x_pos(idx_on_page: int, total_on_page: int = 30):
    """Window-local x for a hex on a 30-position grid."""
    # COMP center is at x=254, HARM at x=1884. Stride = (1884-254) / 29 = 56.2
    return int(254 + idx_on_page * 56.2)


def all_effects():
    """Yield (page, idx, name, color, x_win) for every effect."""
    for page, lst in enumerate([PAGE_0, PAGE_1, PAGE_2]):
        for i, (name, color) in enumerate(lst):
            yield page, i, name, color, hex_x_pos(i)


HEX_Y = 156   # window-local y of hex centers in type bar
SLOT0_X = 285
SLOT0_Y = 312


if __name__ == "__main__":
    for page, idx, name, color, x in all_effects():
        print(f"page={page} idx={idx:2d} x={x:4d}  {name:20s}  rgb={color}")
    total = sum(len(p) for p in [PAGE_0, PAGE_1, PAGE_2])
    print(f"\nTotal: {total} effects")
