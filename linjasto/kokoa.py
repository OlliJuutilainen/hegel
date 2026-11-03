"""Asema 6: markdown sivujen arvioiduista sanoista (liputus.arvioi_sivu).

- Juokseva otsikko ja sivunumero: sivun ensimmäinen tai viimeinen rivi, joka toistuu (kirjaimet ilman numeroita)
  vähintään juoksevan osuuden sivuista, poistetaan; sen numero on sivun numero. Alle kolmen sivun erässä
  lyhyt reunarivi, joka alkaa tai loppuu numeroon, tulkitaan juoksevaksi otsikoksi.
- Sivumerkki <!-- s. N --> sivun ensimmäisen sanan eteen, myös kesken sanan (LUiN poistaa sen näkyvistä).
  Tuntematon numero päätellään naapureista vain, jos molemmat naapurit sopivat siihen; muuten <!-- s. ? … -->.
- Kappale vaihtuu, kun Tesseractin kappale vaihtuu, paitsi jos edellinen rivi loppuu tavuviivaan tai ilman
  lopetusmerkkiä ja seuraava alkaa pienellä (palsta tai sivu vaihtuu kesken kappaleen).
- Tavutuksen purku: iso alkukirjain jatkossa pitää yhdysmerkin (Anthropologie-Vorlesung), und/oder/... pitää
  viivan ja välilyönnin (Verstandes- und), muuten yhdistetään; ellei yhdistettyä sanaa tunneta, se kirjataan.
- Tasolla 1 liputettu sana saa perään [?].
"""

from __future__ import annotations

import csv
import re
import statistics
import unicodedata
from collections import Counter
from datetime import date

from .liputus import ydin

LOPETUS = ".:!?“”\")»…"
SIDOKSET = {"und", "oder", "bzw.", "sowie", "and", "or", "ja", "tai", "sekä", "och", "eller", "et", "ou", "e", "o"}
NUMERO = re.compile(r"^\d{1,4}$")


def _rivin_teksti(r: dict) -> str:
    return " ".join(w["teksti"] for w in r["sanat"])


def _avain(r: dict) -> str:
    return re.sub(r"[^\w]|\d|_", "", _rivin_teksti(r).lower())


def _numero(r: dict) -> int | None:
    nums = [w["teksti"] for w in r["sanat"] if NUMERO.match(w["teksti"])]
    return int(nums[0]) if len(nums) == 1 else None


def _reunavyo(s: dict, yla: bool) -> list[dict]:
    """Sivun ylin (tai alin) rivivyö kuvan paikan mukaan, ei Tesseractin lukujärjestyksen: parittoman sivun
    oikealle tasattu juokseva otsikko luetaan usein vasta vasemman palstan jälkeen (Kant-Lexikon, 3.11.2026)."""
    rivit = s["rivit"]
    if not rivit:
        return []
    kork = statistics.median([r["korkeus"] for r in rivit])
    if yla:
        raja = min(r["bbox"][1] for r in rivit) + 0.8 * kork
        return [r for r in rivit if r["bbox"][1] <= raja]
    raja = max(r["bbox"][3] for r in rivit) - 0.8 * kork
    return [r for r in rivit if r["bbox"][3] >= raja]


def juoksevat(sivut: list[dict], osuus: float) -> tuple[dict[int, set], dict[int, int | None]]:
    """Poistettavat rivit sivuittain (rivi-id:t) ja luetut sivunumerot.

    Sivunumeroksi kelpaa ylimmän tai alimman rivivyön numero (1–4 numeroa) vain, jos se sopii sivujen
    järjestykseen: numero − sivun järjestysnumero on sama kuin useimmilla sivuilla. Silloin koko vyö on
    juoksevaa otsikkoa, vaikka sen teksti vaihtuisi sivulta toiselle (lexikonin alahakusana). Lisäksi
    reunavyö poistetaan, jos sen teksti (kirjaimet ilman numeroita) toistuu vähintään osuuden sivuista.
    Alle kolmen sivun erässä numeroa ei voi verrata järjestykseen, joten silloin riittää lyhyt reunarivi,
    joka alkaa tai loppuu numeroon.
    """
    poista = {s["sivu"]: set() for s in sivut}
    numerot = {s["sivu"]: None for s in sivut}
    ehdokas = {}
    for i, s in enumerate(sivut):
        for yla in (True, False):
            vyo = _reunavyo(s, yla)
            luvut = [int(w["teksti"]) for r in vyo for w in r["sanat"] if NUMERO.match(w["teksti"])]
            if len(luvut) == 1 and sum(len(r["sanat"]) for r in vyo) <= 10:
                ehdokas.setdefault(s["sivu"], (luvut[0], vyo, i))
    # Numero kelpaa, jos se sopii järjestykseen ainakin yhden enintään kolmen sivun päässä olevan ehdokkaan kanssa.
    # Paikallinen vertailu sietää puuttuvan sivun: Vernunft-erästä puuttui _21.jpg, ja koko erän yhteinen
    # erotus hylkäsi kaikki sen jälkeiset sivut (3.11.2026).
    jono = [(i, n) for n, _, i in ehdokas.values()]
    for sivu, (n, vyo, i) in ehdokas.items():
        pieni_era = len(sivut) < 3 and all(len(r["sanat"]) <= 6 for r in vyo)
        sopii = any(0 < abs(j - i) <= 3 and m - n == j - i for j, m in jono)
        if (len(sivut) >= 3 and sopii) or pieni_era:
            numerot[sivu] = n
            poista[sivu].update(r["id"] for r in vyo)
    if len(sivut) >= 3:
        for yla in (True, False):
            vyot = [(s, _reunavyo(s, yla)) for s in sivut]
            laskuri = Counter(_avain(r) for _, v in vyot for r in v)
            for s, v in vyot:
                for r in v:
                    k = _avain(r)
                    if k and laskuri[k] / len(sivut) >= osuus:
                        poista[s["sivu"]].add(r["id"])
    return poista, numerot


def paattele_numerot(jarjestys: list[int], numerot: dict, loki: list) -> dict:
    out = dict(numerot)
    tunnetut = [(i, numerot[s]) for i, s in enumerate(jarjestys) if numerot[s] is not None]
    for (i, n), (j, m) in zip(tunnetut, tunnetut[1:]):
        if m - n > j - i:  # numeroita on enemmän kuin kuvia välissä: sivu tai sivuja puuttuu
            if j != i + 1:
                puuttuu = f"{m - n - (j - i)} sivua välillä {n}–{m}"
            elif m - n <= 4:
                puuttuu = ", ".join(str(x) for x in range(n + 1, m))
            else:
                puuttuu = f"{n + 1}–{m - 1}"
            loki.append({"sivu": jarjestys[j], "id": "", "lukemat": "", "valittu": "", "tila": "sivu_puuttuu",
                         "peruste": f"puuttuu: {puuttuu}"})
    for i, s in enumerate(jarjestys):
        if out[s] is not None:
            continue
        ed = numerot.get(jarjestys[i - 1]) if i > 0 else None
        se = numerot.get(jarjestys[i + 1]) if i + 1 < len(jarjestys) else None
        if ed is not None and se is not None and se - ed == 2:
            out[s] = ed + 1
            loki.append({"sivu": s, "id": "", "lukemat": "", "valittu": str(ed + 1), "tila": "sivunumero_paatelty",
                         "peruste": f"naapurit {ed} ja {se}"})
    return out


def _nayta(w: dict, taso: int) -> str:
    t = w["teksti"]
    return t + "[?]" if w["liput"] and taso == 1 else t


def kokoa(sivut: list[dict], tiedostot: dict[int, str], sanakirjat, a: dict, taso: int, sivumerkki: str,
          etukentta: dict) -> tuple[str, list[dict]]:
    loki: list[dict] = []
    poista, numerot = juoksevat(sivut, a["juokseva_osuus"])
    numerot = paattele_numerot([s["sivu"] for s in sivut], numerot, loki)

    # Kirjan sanasto tavutuksen purkuun: rivien keskeltä luetut sanat ja yhdysmerkkiset sanat.
    sanasto, yhdyssanat = set(), set()
    for s in sivut:
        for r in s["rivit"]:
            for w in r["sanat"][1:-1]:
                y = ydin(w["teksti"]).lower()
                (yhdyssanat if "-" in y else sanasto).add(y)

    def tunnettu(sana: str) -> bool:
        return sana.lower() in sanasto or (bool(sanakirjat.kirjat) and sanakirjat.tuntee(sana))

    def merkki(sivu: int) -> str:
        n = numerot.get(sivu)
        if sivumerkki == "nakyva":
            return f"{{s. {n if n is not None else '?'}}}"
        return f"<!-- s. {n} -->" if n is not None else f"<!-- s. ? {tiedostot[sivu]} -->"

    # Rivit järjestyksessä: (sivu, rivi, onko sivun ensimmäinen leipätekstirivi)
    jono = []
    for s in sivut:
        for r in s["rivit"]:
            if r["id"] in poista[s["sivu"]]:
                loki.append({"sivu": s["sivu"], "id": r["id"], "lukemat": _rivin_teksti(r), "valittu": "",
                             "tila": "juokseva_otsikko_poistettu", "peruste": "toistuva reunarivi"})
                continue
            jono.append((s, r))
        for w in (w for r in s["rivit"] for w in r["sanat"]):
            if w["peruste"]:
                loki.append({"sivu": s["sivu"], "id": w["id"], "lukemat": " | ".join(f"{k}: {v}" for k, v in w["lukemat"].items()),
                             "valittu": w["teksti"], "tila": "toinen_lukija", "peruste": w["peruste"]})
            if w["liput"]:
                loki.append({"sivu": s["sivu"], "id": w["id"], "lukemat": " | ".join(f"{k}: {v}" for k, v in w["lukemat"].items()),
                             "valittu": w["teksti"] + ("[?]" if taso == 1 else ""), "tila": "liputettu",
                             "peruste": ", ".join(w["liput"])})

    korkeudet = {s["sivu"]: statistics.median([r["korkeus"] for r in s["rivit"]] or [1]) for s in sivut}
    # Palstan leveys: vähintään viiden sanan rivien leveyden mediaani. Tasatussa tekstissä vain kappaleen viimeinen
    # rivi (ja otsikko tai allekirjoitus) on selvästi lyhyempi.
    palsta = {}
    for s in sivut:
        lev = [r["bbox"][2] - r["bbox"][0] for r in s["rivit"] if len(r["sanat"]) >= 5]
        palsta[s["sivu"]] = statistics.median(lev) if lev else None
    kappaleet: list[list] = []  # [tyyppi, teksti]
    ed_sivu, ed_rivi, ed_tess, ed_lyhyt = None, None, None, False
    for s, r in jono:
        sanat = [_nayta(w, taso) for w in r["sanat"]]
        uusi_sivu = s["sivu"] != ed_sivu
        if uusi_sivu:
            sanat[0] = merkki(s["sivu"]) + (" " if sivumerkki == "nakyva" else "") + sanat[0]
        otsikko = len(r["sanat"]) <= 6 and r["korkeus"] >= a["otsikko_kerroin"] * korkeudet[s["sivu"]]
        teksti = " ".join(sanat)
        tess = (s["sivu"], r["tesseract"][0], r["tesseract"][1])
        p = palsta[s["sivu"]]
        # Oikealle siirtynyt rivi (esim. allekirjoitus) aloittaa oman kappaleen; sisennys on paljon pienempi.
        oikealla = (p is not None and ed_rivi is not None and tess[:2] == (ed_tess or ())[:2]
                    and r["bbox"][0] - ed_rivi["bbox"][0] > 0.3 * p)
        if otsikko:
            kappaleet.append(["otsikko", teksti])
        elif (not kappaleet or kappaleet[-1][0] == "otsikko" or ed_lyhyt or oikealla
              or tess != ed_tess and not _jatkuu(ed_rivi, r)):
            kappaleet.append(["kpl", teksti])
        else:
            kappaleet[-1][1] = _liita(kappaleet[-1][1], teksti, ed_rivi, r, tunnettu, yhdyssanat, s["sivu"], loki)
        ed_lyhyt = (p is not None and r["bbox"][2] - r["bbox"][0] < a["lyhyt_rivi"] * p
                    and not r["sanat"][-1]["teksti"].endswith("-"))
        ed_sivu, ed_rivi, ed_tess = s["sivu"], r, tess

    runko = []
    for tyyppi, t in kappaleet:
        t = re.sub(r"^([#>+*-])", r"\\\1", t)  # rivin alun merkit eivät saa muuttua otsikoksi, lainaukseksi tai listaksi
        runko.append(("## " + t.lstrip("\\")) if tyyppi == "otsikko" else t)
    fm = ["---"] + [f"{k}: {v}" for k, v in etukentta.items() if v not in (None, "")] + ["---", ""]
    md = "\n".join(fm) + "\n" + "\n\n".join(runko) + "\n"
    return unicodedata.normalize("NFC", md), loki


def _jatkuu(ed: dict | None, r: dict) -> bool:
    if ed is None:
        return False
    viim = ed["sanat"][-1]["teksti"]
    eka = r["sanat"][0]["teksti"]
    return viim.endswith("-") or (viim[-1:] not in LOPETUS and eka[:1].islower())


def _liita(kpl: str, rivi: str, ed: dict, r: dict, tunnettu, yhdyssanat, sivu: int, loki: list) -> str:
    """Rivin liitos kappaleeseen, tavutus purettuna. Sivumerkki voi olla rivin alussa."""
    lippu = kpl.endswith("-[?]")
    pohja = kpl[:-3] if lippu else kpl
    if not pohja.endswith("-") or pohja.endswith("--"):
        return kpl + " " + rivi
    kpl = pohja
    m = re.match(r"^((?:<!--.*?-->|\{s\. [^}]*\})?)(\S*)(.*)$", rivi, re.S)
    merkki, jatko, loput = m.group(1), m.group(2), m.group(3)
    if jatko.endswith("[?]"):
        jatko, lippu = jatko[:-3], True
    if lippu:  # tavutetun sanan lippu yhdistetyn sanan perään
        jatko += "[?]"
    alku = kpl.rsplit(" ", 1)[-1][:-1]
    a, b = ydin(alku), ydin(jatko.replace("[?]", ""))
    if jatko[:1].isupper():
        tulos, tila = kpl + merkki + jatko + loput, "yhdysmerkki_säilytetty"
    elif b.lower() in SIDOKSET:
        tulos, tila = kpl + " " + merkki + jatko + loput, "yhdysmerkki_ja_sidos"
    elif f"{a}-{b}".lower() in yhdyssanat and not tunnettu(a + b):
        tulos, tila = kpl + merkki + jatko + loput, "yhdysmerkki_säilytetty"
    else:
        tulos = kpl[:-1] + merkki + jatko + loput
        tila = "tavutus_purettu" if tunnettu(a + b) else "tavutus_purettu_epävarma"
    if tila != "tavutus_purettu":
        loki.append({"sivu": sivu, "id": r["id"], "lukemat": f"{alku}- {jatko}", "valittu": "", "tila": tila,
                     "peruste": "yhdistetty sana ei ole sanastossa" if tila.endswith("epävarma") else ""})
    return tulos


def kirjoita_loki(loki: list[dict], csv_polku, md_polku, otsikko: str) -> None:
    kentat = ["sivu", "id", "lukemat", "valittu", "tila", "peruste"]
    with open(csv_polku, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=kentat)
        w.writeheader()
        w.writerows(loki)
    c = Counter(r["tila"] for r in loki)
    rivit = [f"# Muutokset: {otsikko}", "", f"Koottu {date.today().isoformat()}.", ""]
    rivit += [f"- {t}: {n}" for t, n in sorted(c.items())] + [""]
    rivit += ["| sivu | id | lukemat | valittu | tila | peruste |", "|---|---|---|---|---|---|"]
    rivit += [f"| {r['sivu']} | {r['id']} | {str(r['lukemat']).replace('|', '/')} | {r['valittu']} | {r['tila']} | {r['peruste']} |"
              for r in loki]
    md_polku.write_text("\n".join(rivit) + "\n", encoding="utf-8")
