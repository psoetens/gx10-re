"""Dump human-readable strings from BTS's WebView2 LocalStorage leveldb.

LocalStorage values are mostly JSON strings; keys look like
META:<origin> + <utf16-encoded-key>. We just walk the binary files
and extract every UTF-8 / UTF-16 run >=4 chars.
"""
import re
import sys
from pathlib import Path

LS = Path(r"C:\Users\Peter\AppData\Local\Roland\BOSS TONE STUDIO for GX-10\EBWebView\Default\Local Storage\leveldb")


def utf8_strings(blob: bytes, min_len=6):
    """All printable ASCII/UTF-8 runs of length >= min_len."""
    out = []
    cur = []
    for b in blob:
        if 32 <= b < 127:
            cur.append(chr(b))
        else:
            if len(cur) >= min_len:
                out.append("".join(cur))
            cur = []
    if len(cur) >= min_len:
        out.append("".join(cur))
    return out


def utf16le_strings(blob: bytes, min_len=4):
    """UTF-16 LE strings (every other byte is 0). LocalStorage keys
    sometimes use this when stored via JS strings."""
    out = []
    cur = []
    i = 0
    while i + 1 < len(blob):
        lo, hi = blob[i], blob[i + 1]
        if hi == 0 and 32 <= lo < 127:
            cur.append(chr(lo))
            i += 2
        else:
            if len(cur) >= min_len:
                out.append("".join(cur))
            cur = []
            i += 1
    if len(cur) >= min_len:
        out.append("".join(cur))
    return out


def main():
    files = sorted(LS.glob("*.log")) + sorted(LS.glob("*.ldb"))
    if not files:
        print(f"No log/ldb files found in {LS}")
        return

    # Per-file walk: print short strings that look like state (not i18n/UI text).
    # Heuristic to skip i18n: drop strings that contain '$t(' or excessive
    # uppercase identifier sequences (looks like message catalog keys).
    for f in files:
        data = f.read_bytes()
        ascii_strs = utf8_strings(data, min_len=4)
        utf16_strs = utf16le_strings(data, min_len=4)
        all_strs = ascii_strs + utf16_strs
        # Filter: keep things that look like state (not i18n keys / file paths)
        kept = []
        for s in all_strs:
            sl = s.strip()
            if len(sl) > 800:
                continue
            if "$t(" in sl or "://" in sl:
                continue
            if sl.count("_") > 6 and sl.upper() == sl:  # i18n keys CONSTANT_LIKE_THIS
                continue
            # Drop if it's clearly a sentence (UI text)
            if " " in sl and sum(c.islower() for c in sl) > 10:
                continue
            kept.append(sl)
        # Dedupe but keep order
        seen = set()
        kept_unique = []
        for s in kept:
            if s in seen:
                continue
            seen.add(s)
            kept_unique.append(s)
        print(f"\n=== {f.name}  ({len(data)} bytes, {len(kept_unique)} state-like strings) ===")
        for s in kept_unique[:200]:
            tag = ""
            for w in ("insert", "delete", "overwrite", "selected", "chain",
                      "slot", "modal", "dialog", "edit", "transaction",
                      "pending", "lock", "block", "warning"):
                if w in s.lower():
                    tag = " <-- BUG?"
                    break
            print(f"  {s}{tag}")


if __name__ == "__main__":
    main()
