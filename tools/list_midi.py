"""List MIDI input/output ports via python-rtmidi (cross-platform)."""
import rtmidi

print("=== MIDI INPUT ===")
mi = rtmidi.MidiIn()
for i, name in enumerate(mi.get_ports()):
    print(f"  [{i}] {name}")
del mi

print("\n=== MIDI OUTPUT ===")
mo = rtmidi.MidiOut()
for i, name in enumerate(mo.get_ports()):
    print(f"  [{i}] {name}")
del mo
