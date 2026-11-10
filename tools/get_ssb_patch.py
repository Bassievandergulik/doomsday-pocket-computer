#!/usr/bin/env python3
"""Download the Si4735/Si4732 SSB patch once and save it as data/ssb_patch.bin.

Weather fax and RTTY need the radio in SSB (USB) mode, which the chip can only
do after Silicon Labs' SSB patch is loaded into it at every power-up. The patch
is not part of this software and is not ours to redistribute: it was published
by Vadim Afonkin and is kept, as C source, in Ricardo Caratti's (PU2CLR) SI4735
Arduino library. For personal, non-commercial use only.

    python3 tools/get_ssb_patch.py              # -> data/ssb_patch.bin
    python3 tools/get_ssb_patch.py --from patch_full.h out.bin   # offline, from a file you copied
"""
import argparse
import os
import re
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/pu2clr/SI4735/master/src/patch_full.h"
HERE = os.path.dirname(os.path.abspath(__file__))


def convert(text):
    body = text[text.index("ssb_patch_content"):]
    body = body[body.index("{") + 1:body.index("}")]
    data = bytes(int(h, 16) for h in re.findall(r"0x([0-9A-Fa-f]{2})", body))
    if not data or len(data) % 8 or data[0] != 0x15 or data[-8] != 0x15:
        raise ValueError("this does not look like an SSB patch (%d bytes)" % len(data))
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=os.path.join(HERE, "..", "data", "ssb_patch.bin"))
    ap.add_argument("--from", dest="src", help="convert a patch_full.h you already have instead of downloading")
    a = ap.parse_args()
    if a.src:
        with open(a.src, encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        print("Downloading", URL)
        with urllib.request.urlopen(URL, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
    data = convert(text)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "wb") as f:
        f.write(data)
    print("Saved %d bytes (%d rows) to %s" % (len(data), len(data) // 8, os.path.abspath(a.out)))


if __name__ == "__main__":
    sys.exit(main())
