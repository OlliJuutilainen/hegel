"""Asema 4: lukijoiden vertailu, liputus ja tarkistuspaketti (ei tekoälyä).

Pääkielen lukija tuottaa tekstin. Toinen lukija kohdistetaan siihen sanatasolla. Sana liputetaan, kun
  - Tesseractin luotettavuus on alle rajan (matala_luottamus),
  - lukijat lukevat sen eri tavalla (lukijat_eri_mieltä),
  - siinä on epätavallinen merkki tai kirjaimia ja numeroita sekaisin (outo_merkki),
  - sitä ei ole sanakirjassa eikä kirjan omassa sanastossa ja luotettavuus on alle sanakirjarajan (ei_sanastossa).
Poikkeus: jos toisen lukijan lukemassa on merkki, jota pääkielen mallissa ei ole lainkaan (ř, á, §), pääkielen
lukema ei ole todiste, ja toisen lukijan lukema valitaan (kirjataan lokiin). Muuten tekstiä ei muuteta.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from PIL import Image
from rapidfuzz.distance import Levenshtein

from .lukijat import Sana
from .merkit import korvaa, rivikorkeudet

REUNA = ".,;:!?()[]{}„“”\"'‚‘’»«–—/…*"
OUTO = re.compile(r"[<>+&|\\{}©®°~^¢£¥ı]|^[A-ZÄÖÜ]\d{2,}|\d[A-Za-zÄÖÜäöüß]{2,}|[A-Za-zÄÖÜäöüß]\d")


def ydin(teksti: str) -> str:
    return teksti.strip(REUNA + "-")


def _perus(teksti: str) -> str:
    """Kirjaimet ilman diakriitteja ja umlauteja: 'Karásek' ja 'Karäsek' -> 'Karasek'."""
    return "".join(c for c in unicodedata.normalize("NFD", teksti) if not unicodedata.combining(c))


def kohdista(a: list[str], b: list[str]) -> dict[int, int]:
    """a:n indeksi -> b:n indeksi, kun sanat vastaavat toisiaan yksi yhteen."""
    m = {}
    for op in Levenshtein.opcodes(a, b):
        if op.tag == "equal" or (op.tag == "replace" and op.src_end - op.src_start == op.dest_end - op.dest_start):
            for k in range(op.src_end - op.src_start):
                m[op.src_start + k] = op.dest_start + k
    return m


class Sanakirjat:
    """Profiilin hunspell-sanakirjat (spylls). Puuttuva tiedosto ohitetaan varoituksella."""

    def __init__(self, polut: list[Path]):
        self.kirjat, self.puuttuvat = [], []
        for p in polut:
            if p.with_suffix(".dic").exists() and p.with_suffix(".aff").exists():
                from spylls.hunspell import Dictionary
                self.kirjat.append(Dictionary.from_files(str(p)))
            else:
                self.puuttuvat.append(p)
        self._muisti: dict[str, bool] = {}

    def tuntee(self, sana: str) -> bool:
        if sana not in self._muisti:
            self._muisti[sana] = any(k.lookup(sana) for k in self.kirjat)
        return self._muisti[sana]


def rivit(sanat: list[Sana]) -> list[list[int]]:
    """Sanojen indeksit riveittäin Tesseractin järjestyksessä."""
    out, nyk = [], None
    for i, s in enumerate(sanat):
        if s.rivi != nyk:
            out.append([])
            nyk = s.rivi
        out[-1].append(i)
    return out


def tavutetut(sanat: list[Sana], rivijako: list[list[int]]) -> dict[int, str]:
    """Rivin lopun tavuviivalla katkaistut sanat: kummankin puolikkaan indeksi -> yhdistetty sana."""
    out = {}
    for r, seur in zip(rivijako, rivijako[1:]):
        a, b = sanat[r[-1]].teksti, sanat[seur[0]].teksti
        if a.endswith("-") and len(a) > 1 and b[:1].islower():
            yhd = ydin(a[:-1]) + ydin(b)
            out[r[-1]] = out[seur[0]] = yhd
    return out


def kirjan_sanasto(sivut_sanat: list[list[Sana]], a: dict) -> set[str]:
    """Sanat, jotka toistuvat kirjassa varmasti luettuina: ne tunnetaan, vaikka sanakirja ei tuntisi."""
    c = Counter(ydin(s.teksti) for sanat in sivut_sanat for s in sanat
                if s.conf >= a["kirjan_sanasto_luottamus"] and not s.teksti.endswith("-"))
    return {w for w, n in c.items() if n >= a["kirjan_sanasto_min"] and w}


def arvioi_sivu(sivu: int, paa: list[Sana], muut: dict[str, list[Sana]], paa_merkisto: set[str],
                sanakirjat: Sanakirjat, sanasto: set[str], a: dict, nuoli=None, kuva=None) -> dict:
    """Sivun sanat päätöksineen ja lippuineen."""
    paa_t = [s.teksti for s in paa]
    kohdistus = {m: (kohdista(paa_t, [s.teksti for s in ss]), ss) for m, ss in muut.items()}
    rivijako = rivit(paa)
    tavu = tavutetut(paa, rivijako)
    rk = rivikorkeudet(paa) if nuoli is not None else {}
    tulos_rivit = []
    for rnro, idx in enumerate(rivijako, 1):
        r_sanat = []
        for snro, i in enumerate(idx, 1):
            s = paa[i]
            lukemat, liput = {"pää": s.teksti}, []
            valittu, peruste = s.teksti, ""
            kuvio = nuoli.tunnista(kuva, s, rk[i]) if nuoli is not None and kuva is not None else None
            uusi = korvaa(s.teksti, kuvio) if kuvio is not None else None
            if uusi is not None:
                # Nuoli tunnistettu kuvasta: lukijoiden erimielisyys ja outo merkki koskivat nuolta itseään.
                for m, (k, ss) in kohdistus.items():
                    lukemat[m] = ss[k[i]].teksti if i in k else None
                r_sanat.append({"id": f"s{sivu:03d}-r{rnro:02d}-w{snro:02d}", "teksti": uusi, "lukemat": lukemat,
                                "conf": round(s.conf, 1), "bbox": [s.x0, s.y0, s.x1, s.y1], "liput": [],
                                "peruste": "nuoli → tunnistettu kuvasta (kirjan oma mallikuva)"})
                continue
            paa_sana = tavu.get(i, ydin(s.teksti))
            paa_tunnettu = bool(re.search(r"[^\W\d_]", paa_sana)) and (
                paa_sana in sanasto or (sanakirjat.kirjat and sanakirjat.tuntee(paa_sana)))
            for m, (k, ss) in kohdistus.items():
                toinen = ss[k[i]] if i in k else None
                lukemat[m] = toinen.teksti if toinen else None
                if toinen is None or toinen.teksti == s.teksti:
                    continue
                # Ero vain välilyönnissä: 'B 383' / 'B383' ei ole erimielisyys.
                naapurit = paa_t[max(0, i - 1):i + 2]
                if toinen.teksti in ("".join(naapurit[:2]), "".join(naapurit[-2:])) and len(naapurit) > 1:
                    continue
                uudet = set(toinen.teksti) - paa_merkisto
                vain_aksentit = _perus(toinen.teksti) == _perus(s.teksti)
                if paa_tunnettu and vain_aksentit:
                    # Pääkielen lukema on tunnettu sana ja toinen lukija lisäsi vain aksentin ('ist' / 'íst'):
                    # toisen lukijan kohinaa, ei erimielisyyttä (Kant-Lexikon, 3.11.2026).
                    continue
                if uudet and not paa_tunnettu and toinen.conf >= a["toisen_lukijan_luottamus"]:
                    valittu, peruste = toinen.teksti, f"{m}: merkki {''.join(sorted(uudet))} puuttuu pääkielen mallista"
                else:
                    liput.append("lukijat_eri_mieltä")
            if s.conf < a["luottamus_raja"]:
                liput.append("matala_luottamus")
            if OUTO.search(valittu):
                liput.append("outo_merkki")
            sana = tavu.get(i, ydin(valittu))
            if (sanakirjat.kirjat and re.search(r"[^\W\d_]", sana) and sana not in sanasto
                    and not sanakirjat.tuntee(sana) and s.conf < a["sanakirja_luottamus"]):
                liput.append("ei_sanastossa")
            r_sanat.append({"id": f"s{sivu:03d}-r{rnro:02d}-w{snro:02d}", "teksti": valittu, "lukemat": lukemat,
                            "conf": round(s.conf, 1), "bbox": [s.x0, s.y0, s.x1, s.y1],
                            "liput": sorted(set(liput)), "peruste": peruste})
        n_lip = sum(1 for w in r_sanat if w["liput"])
        bbox = [min(paa[i].x0 for i in idx), min(paa[i].y0 for i in idx),
                max(paa[i].x1 for i in idx), max(paa[i].y1 for i in idx)]
        tulos_rivit.append({"id": f"s{sivu:03d}-r{rnro:02d}", "tesseract": list(paa[idx[0]].rivi), "bbox": bbox,
                            "korkeus": sorted(paa[i].y1 - paa[i].y0 for i in idx)[len(idx) // 2],
                            "liputettu": len(r_sanat) >= 3 and n_lip / len(r_sanat) >= a["rivi_osuus"],
                            "sanat": r_sanat})
    return {"sivu": sivu, "rivit": tulos_rivit}


def paketti(sivut: list[dict], kuvat: dict[int, Path], kohde: Path, kielet: list[str]) -> int:
    """kohteet.json ja rivien rajauskuvat (rivin korkuinen, puolen rivin marginaali)."""
    rajaukset = kohde / "rajaukset"
    rajaukset.mkdir(parents=True, exist_ok=True)
    kohteet = []
    for sivu in sivut:
        kaikki = [w for r in sivu["rivit"] for w in r["sanat"]]
        kuva = None
        for r in sivu["rivit"]:
            liputetut = [w for w in r["sanat"] if w["liput"]]
            if not liputetut and not r["liputettu"]:
                continue
            if kuva is None:
                kuva = Image.open(kuvat[sivu["sivu"]])
            x0, y0, x1, y1 = r["bbox"]
            m = (y1 - y0) // 2
            nimi = f"{r['id']}.png"
            kuva.crop((max(0, x0 - m), max(0, y0 - m), min(kuva.width, x1 + m), min(kuva.height, y1 + m))).save(rajaukset / nimi)

            def kohde_(id_, ws, syyt, conf):
                i, j = kaikki.index(ws[0]), kaikki.index(ws[-1])
                return {"id": id_, "sivu": sivu["sivu"], "rajaus": f"rajaukset/{nimi}", "rajaus_original": None,
                        "lukemat": {k: " ".join(w["lukemat"].get(k) or "∅" for w in ws) for k in ws[0]["lukemat"]},
                        "luotettavuus": conf, "syyt": syyt,
                        "konteksti_ennen": " ".join(x["teksti"] for x in kaikki[max(0, i - 6):i]),
                        "konteksti_jalkeen": " ".join(x["teksti"] for x in kaikki[j + 1:j + 7]),
                        "kielet": kielet}

            if r["liputettu"]:  # koko rivi yhtenä kohteena
                syyt = sorted({l for w in r["sanat"] for l in w["liput"]} | {"rivi_liputettu"})
                kohteet.append(kohde_(r["id"], r["sanat"], syyt, min(w["conf"] for w in r["sanat"])))
            else:
                kohteet.extend(kohde_(w["id"], [w], w["liput"], w["conf"]) for w in liputetut)
        if kuva is not None:
            kuva.close()
    (kohde / "kohteet.json").write_text(json.dumps(kohteet, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(kohteet)
