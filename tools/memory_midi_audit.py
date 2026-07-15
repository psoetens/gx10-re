#!/usr/bin/env python3
"""Read-only audit of every user memory's MEMORY MIDI block.

One RQ1 per memory at the body base returns the ~129-byte header record
(MEMORY MIDI 1..4 live at body offset 0x35..0x68, 4 entries x 13 bytes).

Entry layout (RE'd 2026-06-16 from hardware + the PC=slot+1 convention,
exact match on U02-1=PC4 and U24-2=PC71):
    +0       CHANNEL   1 byte
    +1..2    BANK MSB  2-nibble big-endian
    +3..4    BANK LSB  2-nibble big-endian
    +5..6    PC#       2-nibble big-endian
    +7..12   CC1#/CC1V/CC2#/CC2V
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from midi_io import GxMidi, parse_dt1_payload

def user_addr(n):
    base_lin=0x4000000; stride=0x18000
    lin=base_lin+n*stride
    return ((lin>>21)&0x7F)<<24|((lin>>14)&0x7F)<<16|((lin>>7)&0x7F)<<8|(lin&0x7F)

def be2(b,i): return ((b[i]&0xF)<<4)|(b[i+1]&0xF)

def entry(hdr, k):
    o=0x35+k*13
    return dict(ch=hdr[o], msb=be2(hdr,o+1), lsb=be2(hdr,o+3), pc=be2(hdr,o+5),
                cc1n=hdr[o+7], cc2n=hdr[o+10])

def main():
    n_total = int(sys.argv[1]) if len(sys.argv)>1 else 198
    g=GxMidi(port_substr="GX-10")
    rows=[]
    for v in range(n_total):
        addr=user_addr(v)
        msg=g.rq1(addr,0x100,timeout=1.5)
        if msg is None:
            msg=g.rq1(addr,0x100,timeout=3.0)
        if msg is None:
            rows.append((v,None)); continue
        p=parse_dt1_payload(msg)
        hdr=list(p)+[0]*(0x80-len(p))
        name=''.join(chr(c) for c in hdr[0:16]).rstrip()
        ents=[entry(hdr,k) for k in range(4)]
        rows.append((v,(name,ents)))
    # classify
    OFF=[]; DEFAULT=[]; ANOM=[]; FAIL=[]
    for v,r in rows:
        if r is None: FAIL.append(v); continue
        name,ents=r
        e0=ents[0]; rest=ents[1:]
        allzero = all(all(x==0 for x in e.values()) for e in ents)
        rest_used = any(any(e.values()) for e in rest)
        is_def = (e0['ch']==1 and e0['msb']==1 and e0['lsb']==1 and e0['pc']==v+1
                  and e0['cc1n']==0 and e0['cc2n']==0 and not rest_used)
        if allzero: OFF.append(v)
        elif is_def: DEFAULT.append(v)
        else: ANOM.append((v,name,e0,rest_used))
    print(f"\n=== MEMORY MIDI audit: {n_total} user memories ===")
    print(f"  OFF (all zero)          : {len(OFF)}")
    print(f"  DEFAULT (CH1/1/1, PC=V+1): {len(DEFAULT)}")
    print(f"  ANOMALOUS (custom/wrong): {len(ANOM)}")
    print(f"  READ FAILED             : {len(FAIL)} {FAIL if FAIL else ''}")
    if OFF:
        print(f"\n  OFF list (V): {OFF[:40]}{' ...' if len(OFF)>40 else ''}")
    if ANOM:
        print(f"\n  ANOMALOUS detail:")
        for v,name,e0,ru in ANOM[:60]:
            print(f"    V={v:3d} bank{v//3+1:02d}-{v%3+1} {name!r:18s} "
                  f"CH={e0['ch']} MSB={e0['msb']} LSB={e0['lsb']} PC={e0['pc']} (expPC={v+1}) "
                  f"{'+entries2-4' if ru else ''}")
    # also dump a few V>127 DEFAULT/any to learn bank-wrap convention
    print(f"\n  Sample raw entry0 across range (to learn bank-wrap):")
    for v in [0,1,2,69,70,127,128,129,197]:
        r=dict(rows).get(v)
        if r: 
            e=r[1][0]; print(f"    V={v:3d}: CH={e['ch']} MSB={e['msb']} LSB={e['lsb']} PC={e['pc']}")

if __name__=="__main__":
    main()
