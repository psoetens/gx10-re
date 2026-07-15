#!/usr/bin/env python3
"""Repair MEMORY MIDI on GX-10 user memories to the device convention:
    CH = 1, BANK MSB = 1 + V//99, BANK LSB = 1, PC# = V%99 + 1, CC fields OFF.

Entry layout (RE'd 2026-06-16, exact match on U02-1=PC4 & U24-2=PC71):
    +0 CH(1B)  +1..2 MSB(2nib BE)  +3..4 LSB  +5..6 PC#  +7..12 CC1#/CC1V/CC2#/CC2V

Writes ONLY the 52-byte block at stored_addr+0x35 (direct flash write,
bypasses edit buffer -> no amp-model reset, no WRITE-to-slot trigger).
Verifies the mechanism with a full-body before/after diff on the first
deviant memory before batching the rest.
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from midi_io import GxMidi, parse_dt1_payload

N_USER = 198
BACKUP = Path(__file__).resolve().parents[1] / "snapshots" / "mmidi_backup.json"

def user_addr(n):
    lin = 0x4000000 + n*0x18000
    return ((lin>>21)&0x7F)<<24 | ((lin>>14)&0x7F)<<16 | ((lin>>7)&0x7F)<<8 | (lin&0x7F)

def be2(b,i): return ((b[i]&0xF)<<4)|(b[i+1]&0xF)

def conv(v): return dict(ch=1, msb=1+v//99, lsb=1, pc=v%99+1)

def correct_block(v):
    c = conv(v); msb, pc = c['msb'], c['pc']
    e0 = [1, (msb>>4)&0xF, msb&0xF, 0, 1, (pc>>4)&0xF, pc&0xF, 0,0,0,0,0,0]
    return e0 + [0]*39   # entries 2-4 zero -> 52 bytes total

def read_header(g, v):
    m = g.rq1(user_addr(v), 0x100, timeout=1.5) or g.rq1(user_addr(v), 0x100, timeout=3.0)
    if m is None: return None
    p = list(parse_dt1_payload(m)); p += [0]*(0x80-len(p))
    return p

def mmidi_region(hdr): return hdr[0x35:0x35+52]

def entry0_str(blk):
    return f"CH{blk[0]}/MSB{be2(blk,1)}/LSB{be2(blk,3)}/PC{be2(blk,5)}"

def is_deviant(v, hdr):
    blk = mmidi_region(hdr); c = conv(v)
    want = correct_block(v)
    return blk != want, blk

# ---- full body read (BTS region pattern) for the diff verification ----
def bts_regions():
    r=[(0x0000,0x100),(0x0100,1),(0x0140,28)]
    for pair in range(10):
        rb=0x0200+pair*0x100; r+=[(rb,45),(rb+0x40,45)]
    r+=[(0x0F00,62)]
    for slot in range(20):
        sb=0x1100+slot*0x200; r+=[(sb,0x100),(sb+0x103,48)]
    return r
def read_full(g, v):
    base=user_addr(v); buf=bytearray(0x4000)
    for off,size in bts_regions():
        time.sleep(0.015)
        m=g.rq1(base+off,size,timeout=1.5) or g.rq1(base+off,size,timeout=3.0)
        if m is None: continue
        pl=parse_dt1_payload(m)
        for j,b in enumerate(pl[:size]): buf[off+j]=b
    return bytes(buf)

def write_mmidi(g, v):
    g.dt1(user_addr(v)+0x35, bytes(correct_block(v)))

def main():
    g = GxMidi(port_substr="GX-10")
    print("# scanning 198 user memories...")
    deviant=[]; headers={}
    for v in range(N_USER):
        hdr=read_header(g,v)
        if hdr is None:
            print(f"# WARN read fail V={v}"); continue
        headers[v]=hdr
        dev,blk=is_deviant(v,hdr)
        if dev: deviant.append(v)
    print(f"# deviant memories: {len(deviant)} -> {deviant}")
    if not deviant:
        print("# nothing to do; all memories already match convention."); return
    # backup current mmidi region of deviant memories
    BACKUP.write_text(json.dumps({str(v): headers[v][0x35:0x35+52] for v in deviant}, indent=1))
    print(f"# backed up {len(deviant)} mmidi regions -> {BACKUP}")

    # ---- single verification write + full-body diff ----
    vt=deviant[0]
    print(f"\n# === verification write on V={vt} (U{vt//3+1:02d}-{vt%3+1}) ===")
    before=read_full(g,vt)
    print(f"#   before: mmidi entry0 = {entry0_str(list(before[0x35:0x35+52]))}")
    write_mmidi(g,vt); time.sleep(0.3)
    after=read_full(g,vt)
    print(f"#   after : mmidi entry0 = {entry0_str(list(after[0x35:0x35+52]))}  (want PC{conv(vt)['pc']} MSB{conv(vt)['msb']})")
    diffs=[i for i in range(0x4000) if before[i]!=after[i]]
    in_region=[i for i in diffs if 0x35<=i<0x35+52]
    out_region=[i for i in diffs if not(0x35<=i<0x35+52)]
    print(f"#   bytes changed: {len(diffs)} total | {len(in_region)} in mmidi region | {len(out_region)} OUTSIDE")
    ok_vals = list(after[0x35:0x35+52]) == correct_block(vt)
    if out_region:
        print(f"#   ABORT: write touched bytes outside mmidi region: {[hex(x) for x in out_region[:20]]}")
        print("#   (restore from backup if needed). Not batching.")
        return
    if not ok_vals:
        print("#   ABORT: mmidi region did not read back as the target convention. Not batching.")
        return
    print("#   VERIFIED: only the 52 mmidi bytes changed, value matches convention.")

    # ---- auto-batch the rest ----
    rest=deviant[1:]
    print(f"\n# === batching remaining {len(rest)} memories ===")
    for v in rest:
        write_mmidi(g,v); time.sleep(0.04)
    print("# batch done.")

    # ---- re-audit ----
    print("\n# === re-audit ===")
    still=[]
    for v in deviant:
        time.sleep(0.01)
        hdr=read_header(g,v)
        if hdr is None: still.append((v,"readfail")); continue
        dev,blk=is_deviant(v,hdr)
        if dev: still.append((v,entry0_str(blk)))
    if still:
        print(f"# {len(still)} STILL deviant: {still}")
    else:
        print(f"# ALL {len(deviant)} repaired memories now match convention. ✓")

if __name__=="__main__":
    main()
