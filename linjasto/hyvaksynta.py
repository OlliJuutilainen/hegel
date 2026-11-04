"""Taso 2: tarkastuksen (ocr-tarkistus-taito tai ihminen) vastausten hyväksyminen (docs/linjasto.md, luku 10).

- vahvistettu: hyväksytään, jos teksti on jokin lukemista; muuten käsitellään kuten korjattu.
- korjattu: hyväksytään, jos editointietäisyys johonkin lukemaan on enintään max(2, 25 % pituudesta) ja vähintään
  yksi tukee: toinen lukija luki saman, sanakirja tai kirjan oma sanasto tuntee sanan, tai varmuus on korkea.
  Muuten sana jää liputetuksi ([?]), ja ehdotus kirjataan lokiin.
- lukukelvoton: paras OCR-lukema jää ja liputettuna.
Pelkkä välilyöntiero johonkin lukemaan hyväksytään, kun varmuus on korkea tai keski (laajennus pahviin, 4.11.2026).
Rivikohde (id ilman -wNN) jaetaan sanoiksi vain, jos sanamäärä on sama kuin rivillä; muuten rivi jää ennalleen.
"""

from __future__ import annotations

import math
import re
import unicodedata

from rapidfuzz.distance import Levenshtein

from .liputus import ydin


def _paatos(w: dict, teksti: str, tila: str, varmuus: str, sanakirjat, sanasto: set) -> tuple[bool, str]:
    lukemat = [v for v in w["lukemat"].values() if v]
    if tila == "lukukelvoton":
        return False, "lukukelvoton"
    if teksti in lukemat:
        return True, "jokin lukemista" if tila == "vahvistettu" else "korjaus on jokin lukemista"
    if not lukemat:
        return False, "ei lukemia verrattavaksi"
    if any(teksti.replace(" ", "") == l.replace(" ", "") for l in lukemat) and varmuus in ("korkea", "keski"):
        # Pelkkä välilyöntiero ('A63/B' / 'A 63 / B'): kirjaimet ovat lukijan, tarkastus vain jakaa ne.
        return True, "vain välilyönnit eroavat"
    etaisyys = min(Levenshtein.distance(teksti, l) for l in lukemat)
    raja = max(2, math.ceil(0.25 * len(teksti)))
    if etaisyys > raja:
        return False, f"etäisyys {etaisyys} > {raja}"
    toinen = any(v == teksti for k, v in w["lukemat"].items() if k != "pää" and v)
    sana = ydin(teksti)
    tunnettu = bool(sana) and (sana in sanasto or (sanakirjat.kirjat and sanakirjat.tuntee(sana)))
    tuki = [n for n, ok in (("toinen lukija", toinen), ("sanakirja", tunnettu), ("varmuus korkea", varmuus == "korkea")) if ok]
    if not tuki:
        return False, f"etäisyys {etaisyys} ≤ {raja}, mutta ei tukea"
    return True, f"etäisyys {etaisyys} ≤ {raja}; tuki: {', '.join(tuki)}"


def sovella(sivut: list[dict], vastaukset: list[dict], sanakirjat, sanasto: set, loki: list) -> dict:
    """Muuttaa sivujen sanat paikallaan. Palauttaa määrät."""
    v = {x["id"]: x for x in vastaukset}
    maarat = {"hyväksytty": 0, "hylätty": 0, "ei vastausta": 0}
    for s in sivut:
        for r in s["rivit"]:
            rivi_v = v.get(r["id"])
            osat = None
            if rivi_v:
                osat = unicodedata.normalize("NFC", rivi_v.get("teksti", "")).split()
                if len(osat) != len(r["sanat"]):
                    loki.append({"sivu": s["sivu"], "id": r["id"], "lukemat": " ".join(w["teksti"] for w in r["sanat"]),
                                 "valittu": "", "tila": "tarkastus_hylätty",
                                 "peruste": f"rivin sanamäärä {len(osat)} ≠ {len(r['sanat'])}: {rivi_v.get('teksti', '')}"})
                    osat = None
            for j, w in enumerate(r["sanat"]):
                x = v.get(w["id"])
                if x is None and osat is not None:
                    x = dict(rivi_v, teksti=osat[j])
                if x is None:
                    if w["liput"]:
                        maarat["ei vastausta"] += 1
                    continue
                teksti = unicodedata.normalize("NFC", x.get("teksti", "")).strip()
                if osat is not None and teksti == w["teksti"] and not w["liput"]:
                    continue  # rivikohteen sana, jota ei ollut liputettu ja joka pysyi samana
                ok, peruste = _paatos(w, teksti, x.get("tila", ""), x.get("varmuus", ""), sanakirjat, sanasto)
                lukemat = " | ".join(f"{k}: {val}" for k, val in w["lukemat"].items())
                if ok:
                    muuttui = teksti != w["teksti"]
                    w["teksti"], w["liput"] = teksti, []
                    maarat["hyväksytty"] += 1
                    loki.append({"sivu": s["sivu"], "id": w["id"], "lukemat": lukemat, "valittu": teksti,
                                 "tila": "tarkastus_korjattu" if muuttui else "tarkastus_vahvistettu",
                                 "peruste": f"{x.get('tila')}, {x.get('varmuus')}: {peruste}" + (f"; {x['huomio']}" if x.get("huomio") else "")})
                else:
                    maarat["hylätty"] += 1
                    loki.append({"sivu": s["sivu"], "id": w["id"], "lukemat": lukemat, "valittu": w["teksti"],
                                 "tila": "tarkastus_hylätty",
                                 "peruste": f"ehdotus '{teksti}' ({x.get('tila')}, {x.get('varmuus')}): {peruste}"})
    return maarat
