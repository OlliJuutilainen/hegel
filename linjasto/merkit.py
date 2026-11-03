"""Merkit, joita kummankaan lukijan mallissa ei ole: nuoli → (Kant-Lexikonin ristiviite).

Tesseract lukee nuolen merkeiksi '>', '&', '+', '-' tai '2', joskus kiinni seuraavaan sanaan ('-Spontaneität').
Kirjan nuoli on aina samannäköinen, joten sen mallikuva rakennetaan kirjan omista selvistä tapauksista
(sana on pelkkä '>'), ja jokaisen epäilyttävän sanan ensimmäistä mustekuviota verrataan malliin. Vertailu on
algoritminen (korrelaatio ja koko suhteessa riviin); tekoälyä ei käytetä.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage

KOKO = (24, 16)  # mallikuvan leveys, korkeus
SEKAANNUKSET = set(">&+-—–2")
RAJA = 0.45  # korrelaatio mallikuvaan; testisivuilla nuolet 0,47–0,91, muut kuviot enintään 0,34


def _kuviot(g: np.ndarray, bbox) -> list[tuple]:
    """Sanan laatikon mustekuviot vasemmalta oikealle: (x0, y0, x1, y1, maski)."""
    x0, y0, x1, y1 = bbox
    alue = g[y0:y1, x0:x1]
    if alue.size == 0:
        return []
    muste = alue < min(140, int(np.median(alue)) - 40)
    nimet, n = ndimage.label(muste, structure=np.ones((3, 3), dtype=bool))
    out = []
    for i, sl in enumerate(ndimage.find_objects(nimet), 1):
        m = nimet[sl] == i
        if m.sum() < 4:
            continue
        # Harmaasävy (käännettynä) kuvion laatikosta, muut kuviot pyyhitty: sileämpi kuin pelkkä maski.
        harmaa = (255.0 - alue[sl].astype(np.float32)) * ndimage.binary_dilation(m, iterations=1)
        out.append((sl[1].start, sl[0].start, sl[1].stop, sl[0].stop, harmaa))
    return sorted(out, key=lambda k: k[0])


def _normaali(m: np.ndarray) -> np.ndarray:
    im = Image.fromarray(np.clip(m, 0, 255).astype(np.uint8)).resize(KOKO, Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32) / 255.0
    return a - a.mean()


def rivikorkeudet(sanat: list) -> dict:
    """Sanan indeksi -> rivin sanojen korkeuden mediaani (nuolen koon vertailuun)."""
    rivit = {}
    for i, s in enumerate(sanat):
        rivit.setdefault(s.rivi, []).append(i)
    out = {}
    for idx in rivit.values():
        h = float(np.median([sanat[i].y1 - sanat[i].y0 for i in idx]))
        out.update({i: max(1.0, h) for i in idx})
    return out


class Nuoli:
    def __init__(self):
        self.malli = None
        self.mittasuhde = None  # (leveys / rivin korkeus, korkeus / rivin korkeus)
        self.n = 0

    def opi(self, kuvat_ja_sanat: list[tuple[np.ndarray, list]]) -> None:
        """kuvat_ja_sanat: [(harmaa kuva, [sanat])]. Selvät tapaukset: sana on pelkkä '>'."""
        normit, suhteet = [], []
        for g, sanat in kuvat_ja_sanat:
            rk = rivikorkeudet(sanat)
            for i, s in enumerate(sanat):
                if s.teksti != ">":
                    continue
                kuv = _kuviot(g, (s.x0, s.y0, s.x1, s.y1))
                if len(kuv) != 1:
                    continue
                x0, y0, x1, y1, m = kuv[0]
                h = rk[i]
                normit.append(_normaali(m))
                suhteet.append(((x1 - x0) / h, (y1 - y0) / h))
        self.n = len(normit)
        if self.n >= 3:
            self.malli = np.median(np.stack(normit), axis=0)
            self.mittasuhde = tuple(np.median(np.array(suhteet), axis=0))

    def tunnista(self, g: np.ndarray, s, h: float) -> int | None:
        """Kuvion indeksi (0 tai 1), jos sanan alussa on nuoli, muuten None. h = rivin sanojen korkeus."""
        if self.malli is None or not s.teksti or s.teksti[0] not in SEKAANNUKSET | {"("}:
            return None
        odotettu = self.mittasuhde[0] * h  # nuolen leveys pikseleinä tällä rivillä
        for k, (x0, y0, x1, y1, m) in enumerate(_kuviot(g, (s.x0, s.y0, s.x1, s.y1))[:2]):
            if x1 - x0 > 1.3 * odotettu:
                # Nuoli kiinni seuraavassa kirjaimessa ('-Spontaneität'): verrataan vain nuolen levyistä alkua.
                m = m[:, :max(1, round(odotettu))]
                x1 = x0 + m.shape[1]
            lw, lh = (x1 - x0) / h, (y1 - y0) / h
            if not (0.65 <= lw / self.mittasuhde[0] <= 1.5 and 0.65 <= lh / self.mittasuhde[1] <= 1.5):
                continue
            a = _normaali(m)
            r = float((a * self.malli).sum() / (np.linalg.norm(a) * np.linalg.norm(self.malli) + 1e-9))
            if r >= RAJA:
                return k
        return None


def korvaa(teksti: str, kuvio: int) -> str | None:
    """Sanan teksti, jossa alun sekaannusmerkki on nuoli. None, jos tekstin alku ei vastaa kuviota."""
    if kuvio == 0 and teksti[0] in SEKAANNUKSET:
        loput = teksti[1:].lstrip(">")
        return "→" + (" " + loput if loput else "")
    if kuvio == 1 and teksti[:1] == "(" and teksti[1:2] in SEKAANNUKSET:
        loput = teksti[2:]
        return "(→" + (" " + loput if loput else "")
    return None
