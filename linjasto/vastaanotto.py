"""Asema 1: sivut luonnolliseen järjestykseen ja manifestiin. Alkuperäisiin kuviin ei kosketa."""

from __future__ import annotations

import csv
import re
import shutil
from pathlib import Path

from PIL import Image

KUVAT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def luonnollinen(nimi: str) -> list:
    """'sivu_2' ennen 'sivu_10'."""
    return [int(osa) if osa.isdigit() else osa.lower() for osa in re.split(r"(\d+)", nimi)]


def kopioi(lahde: Path, alkup: Path) -> int:
    """Kopioi lähdekansion kuvat kansioon alkup/ (olemassa olevia ei korvata)."""
    alkup.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in lahde.iterdir():
        if p.is_file() and p.suffix.lower() in KUVAT and not (alkup / p.name).exists():
            shutil.copy2(p, alkup / p.name)
            n += 1
    return n


def manifesti(alkup: Path, kohde: Path) -> list[dict]:
    """Sivut järjestyksessä: [{'n', 'tiedosto', 'leveys', 'korkeus'}]. Kirjoittaa manifesti.csv:n."""
    tiedostot = sorted((p for p in alkup.iterdir() if p.is_file() and p.suffix.lower() in KUVAT),
                       key=lambda p: luonnollinen(p.name))
    sivut = []
    for n, p in enumerate(tiedostot, 1):
        with Image.open(p) as im:
            sivut.append({"n": n, "tiedosto": p.name, "leveys": im.width, "korkeus": im.height})
    with open(kohde, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["n", "tiedosto", "leveys", "korkeus"])
        w.writeheader()
        w.writerows(sivut)
    return sivut
