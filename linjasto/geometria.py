"""Asema 2: tekstilohko ja OCR-naamio (vcrop.py:n logiikka numpylla ja scipyllä, ilman opencv:tä).

Tekstilohko etsitään kuten vcrop.py:ssä: adaptiivinen kynnystys, vaakalaajennus, alueet; pöly ja skannerin
reunaa koskettavat matalat alueet hylätään, rivin korkuinen pieni alue (yksinäinen sivunumero) pidetään.
OCR saa naamioidun kopion, jossa kaikki lohkon ulkopuolella on paperin väristä. Alkuperäinen kuva ei muutu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

PIENENNYS = 2  # tunnistus tehdään puolikkaasta kuvasta: nopeampi, eikä tarkkuutta tarvita


@dataclass
class Lohko:
    x0: int
    y0: int
    x1: int
    y1: int
    pidetyt: list = field(default_factory=list)  # (x0, y0, x1, y1) täyden koon pikseleinä
    hylatyt: list = field(default_factory=list)
    paperi: int = 255

    def ok(self, korkeus: int, min_lohko: float) -> bool:
        return self.y1 - self.y0 >= min_lohko * korkeus


def harmaa(kuva: Image.Image) -> np.ndarray:
    return np.asarray(kuva.convert("L"))


def tekstilohko(g: np.ndarray, a: dict) -> Lohko | None:
    """Sivun sisällön rajat. a = asetukset['geometria']."""
    pieni = g[::PIENENNYS, ::PIENENNYS].astype(np.float32)
    h, w = pieni.shape
    koko = max(15, (min(h, w) // 30) | 1)
    tasoitettu = ndimage.median_filter(pieni, size=3)
    muste = tasoitettu < ndimage.uniform_filter(tasoitettu, size=koko) - 15
    leveys = max(3, int(w * a["laajennus"]))
    rivit = ndimage.maximum_filter1d(muste.astype(np.uint8), size=leveys, axis=1) > 0

    nimet, n = ndimage.label(rivit, structure=np.ones((3, 3), dtype=bool))
    if n == 0:
        return None
    alat = np.bincount(nimet.ravel())
    alueet = []
    for i, sl in enumerate(ndimage.find_objects(nimet), 1):
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        reunalla = x0 == 0 or y0 == 0 or x1 >= w or y1 >= h
        alueet.append(((x0, y0, x1, y1), alat[i] >= a["min_alue"] * h * w, reunalla))

    rivikorkeudet = [b[3] - b[1] for b, iso, reuna in alueet if iso and not reuna]
    min_teksti = 0.5 * float(np.median(rivikorkeudet)) if rivikorkeudet else np.inf

    s = PIENENNYS
    pidetyt, hylatyt = [], []
    for b, iso, reunalla in alueet:
        k = b[3] - b[1]
        tekstikokoinen = iso or k >= min_teksti
        taysi = tuple(v * s for v in b)
        if not tekstikokoinen or (reunalla and k < a["reuna_max_korkeus"] * h):
            hylatyt.append(taysi)
        else:
            pidetyt.append(taysi)
    if not pidetyt:
        return None
    lohko = Lohko(min(b[0] for b in pidetyt), min(b[1] for b in pidetyt),
                  max(b[2] for b in pidetyt), max(b[3] for b in pidetyt), pidetyt, hylatyt)
    # Paperin sävy: lohkon sisällä olevien ei-mustepikselien mediaani.
    alue = pieni[lohko.y0 // s:lohko.y1 // s, lohko.x0 // s:lohko.x1 // s]
    alue_muste = muste[lohko.y0 // s:lohko.y1 // s, lohko.x0 // s:lohko.x1 // s]
    tausta = alue[~alue_muste]
    lohko.paperi = int(np.median(tausta)) if tausta.size else 255
    return lohko


def naamioi(g: np.ndarray, lohko: Lohko, pad: float) -> np.ndarray:
    """Kopio, jossa lohkon (+ pad) ulkopuoli on paperin väristä."""
    h, w = g.shape
    p = round(pad * h)
    x0, y0 = max(0, lohko.x0 - p), max(0, lohko.y0 - p)
    x1, y1 = min(w, lohko.x1 + p), min(h, lohko.y1 + p)
    out = np.full_like(g, lohko.paperi)
    out[y0:y1, x0:x1] = g[y0:y1, x0:x1]
    return out


def debug_kuva(kuva: Image.Image, lohko: Lohko | None, polku, korkeus: int = 1200) -> None:
    """Pienennetty kuva: hylätyt alueet punaisella, pidetyt vihreällä, lohko paksulla vihreällä."""
    s = min(1.0, korkeus / kuva.height)
    pieni = kuva.convert("RGB").resize((max(1, round(kuva.width * s)), max(1, round(kuva.height * s))))
    d = ImageDraw.Draw(pieni)
    if lohko is not None:
        for b in lohko.hylatyt:
            d.rectangle([v * s for v in b], outline=(220, 0, 0))
        for b in lohko.pidetyt:
            d.rectangle([v * s for v in b], outline=(0, 170, 0))
        d.rectangle([lohko.x0 * s, lohko.y0 * s, lohko.x1 * s, lohko.y1 * s], outline=(0, 170, 0), width=3)
    pieni.save(polku, quality=85)
