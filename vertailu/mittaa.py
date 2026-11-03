#!/usr/bin/env python3
"""Measure OCR readings against a gold transcription: CER, WER and plausible wrong words.

    python vertailu/mittaa.py kulta.txt lukema1.txt [lukema2.txt ...] [--hunspell /path/de_DE] [-v]

Both texts are NFC-normalised and their whitespace collapsed, so line breaks don't count.
- CER: character edit distance / gold length. "CER (kirj.)" ignores punctuation, so
  quotes, arrows and commas don't count there.
- WER: word edit operations / gold words, split into substitutions S, insertions I and
  deletions D.
- Uskottavat väärät sanat (the pahvi's hallusinaatioindeksi): substituted or inserted
  words that are themselves valid words in the --hunspell dictionary (spylls). A
  misreading that reads as a real word is what guessing looks like; garbage is not.
  Without --hunspell this column is left out.
"""

from __future__ import annotations

import argparse
import re
import unicodedata

from rapidfuzz.distance import Levenshtein

_EDGE = ".,;:!?()[]„“”\"'‚‘’»«-–—/"


def norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).split())


def letters(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", s).split())


def measure(gold: str, reading: str, dictionary=None) -> dict:
    g, o = norm(gold), norm(reading)
    gl, ol = letters(g), letters(o)
    gw, ow = g.split(), o.split()
    ops = Levenshtein.editops(gw, ow)
    subs = [(gw[a], ow[b]) for kind, a, b in ops if kind == "replace"]
    ins = [ow[b] for kind, a, b in ops if kind == "insert"]
    dels = [gw[a] for kind, a, b in ops if kind == "delete"]
    plausible = None
    if dictionary is not None:
        def valid(w: str) -> bool:
            core = w.strip(_EDGE)
            return bool(core) and core.isalpha() and dictionary.lookup(core)
        plausible = [(a, b) for a, b in subs if valid(b) and letters(a).lower() != letters(b).lower()]
        plausible += [(None, b) for b in ins if valid(b)]
    return {
        "cer": Levenshtein.distance(g, o) / max(len(g), 1),
        "cer_letters": Levenshtein.distance(gl, ol) / max(len(gl), 1),
        "wer": len(ops) / max(len(gw), 1),
        "subs": subs, "ins": ins, "dels": dels, "plausible": plausible,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gold")
    ap.add_argument("readings", nargs="+")
    ap.add_argument("--hunspell", help="hunspell dictionary path without extension, e.g. /usr/share/hunspell/de_DE")
    ap.add_argument("-v", action="store_true", help="list every substitution, insertion and deletion")
    args = ap.parse_args()
    dictionary = None
    if args.hunspell:
        from spylls.hunspell import Dictionary
        dictionary = Dictionary.from_files(args.hunspell)
    gold = open(args.gold, encoding="utf-8").read()
    width = max(len(p) for p in args.readings)
    for path in args.readings:
        r = measure(gold, open(path, encoding="utf-8").read(), dictionary)
        line = (f"{path:{width}s}  CER {r['cer']:6.2%}  CER (kirj.) {r['cer_letters']:6.2%}  "
                f"WER {r['wer']:6.2%}  S {len(r['subs']):3d}  I {len(r['ins']):3d}  D {len(r['dels']):3d}")
        if r["plausible"] is not None:
            line += f"  uskottavat väärät sanat {len(r['plausible'])}"
        print(line)
        if args.v:
            for a, b in r["subs"]:
                print(f"    S  {a}  →  {b}")
            for b in r["ins"]:
                print(f"    I  {b}")
            for a in r["dels"]:
                print(f"    D  {a}")
            for a, b in r["plausible"] or []:
                print(f"    !  {a}  →  {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
