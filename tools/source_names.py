"""ASSIGN SOURCE byte → human-readable name enum.

Flat list where position == SOURCE byte (0..83). Mirrors
`catalogs/source_names.json`; keep the two in sync.

Use to decode the byte value of an ASSIGN row's SOURCE field:
    name = SOURCE_NAMES[source_byte]
"""
SOURCE_NAMES = (
    ["NUM 1", "NUM 2", "NUM 3", "NUM 4",
     "MAN 1", "MAN 2", "MAN 3", "MAN 4",
     "CUR NUM", "BANK DOWN", "BANK UP",
     "CTL 1", "CTL 2", "CTL 3", "CTL 4",
     "EXP 1 SW", "EXP 1", "EXP 2", "INT PDL", "WAVE PDL", "INPUT"]
    + [f"CC#{i}" for i in range(1, 32)]
    + [f"CC#{i}" for i in range(64, 96)]
)
