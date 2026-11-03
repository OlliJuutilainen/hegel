#!/usr/bin/env python3
"""Linjasto: kamerakuvista tarkistettuun markdowniin (docs/linjasto.md).

    python linja.py valmistele <kirja> [--kielet kant-lexikon] [--lahde KANSIO] [--debug] [--uudelleen]
    python linja.py kokoa <kirja> [--otsikko ...] [--teos ...] [--sivumerkki nakyva]
    python linja.py siivoa <kirja>

Kuvat ovat kansiossa local/work/<kirja>/alkup/ (tai ne kopioidaan sinne --lahde-kansiosta). Niitä ei muokata.

valmistele (asemat 1–4): manifesti, tekstilohko ja OCR-naamio, Tesseract kieliprofiilin lukijoilla rinnakkain,
    liputus ja tarkistuspaketti (local/work/<kirja>/paketti/). Valmiit lukemat käytetään uudelleen.
kokoa (asema 6): local/out/<kirja>/<kirja>.md sekä muutokset.csv ja muutokset.md.
siivoa: poistaa välivaiheet (naamio, lukijat, sivut, paketti, debug). Alkuperäiset ja tulokset jäävät.

Taso 1: tekoälyä ei käytetä, ja jokainen liputettu sana saa tekstissä perään [?].
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date
from pathlib import Path

from linjasto import asetukset as A
from PIL import Image

from linjasto import geometria, kokoa, liputus, lukijat, vastaanotto


def valmistele(args, aset: dict) -> int:
    k = A.kirja(args.kirja, aset)
    profiilin_nimi = args.kielet or k.lue_tila().get("kielet") or aset["ajo"]["oletus_kielet"]
    profiili = A.lue_profiili(profiilin_nimi)
    tessdata = A.JUURI / aset["polut"]["tessdata"]
    lukijat.tesseract_saatavilla()
    for m in profiili["lukijat"]:
        if not (tessdata / f"{m}.traineddata").exists():
            raise SystemExit(f"Malli {m} puuttuu kansiosta {tessdata} (docs/kartoitus.md, luku 2.3)")

    if args.lahde:
        n = vastaanotto.kopioi(Path(args.lahde).expanduser(), k.alkup)
        print(f"Kopioitu {n} kuvaa kansioon {k.alkup}")
    if not k.alkup.is_dir():
        raise SystemExit(f"Kansiota {k.alkup} ei ole. Laita kuvat sinne tai anna --lahde.")
    k.work.mkdir(parents=True, exist_ok=True)
    sivut = vastaanotto.manifesti(k.alkup, k.work / "manifesti.csv")
    if not sivut:
        raise SystemExit(f"Kansiossa {k.alkup} ei ole kuvia.")
    print(f"Asema 1: {len(sivut)} sivua ({k.work / 'manifesti.csv'})")

    # Asema 2: tekstilohko ja naamio
    t0 = time.time()
    k.naamio.mkdir(exist_ok=True)
    if args.debug:
        (k.work / "debug").mkdir(exist_ok=True)
    lohkot = {}
    for s in sivut:
        kohde = k.naamio / f"s{s['n']:03d}.png"
        lahde = k.alkup / s["tiedosto"]
        if kohde.exists() and not args.uudelleen and kohde.stat().st_mtime >= lahde.stat().st_mtime and not args.debug:
            continue
        with Image.open(lahde) as kuva:
            g = geometria.harmaa(kuva)
            lohko = geometria.tekstilohko(g, aset["geometria"])
            if lohko is None or not lohko.ok(g.shape[0], aset["geometria"]["min_lohko"]):
                print(f"  {s['tiedosto']}: tekstilohkoa ei löytynyt, OCR lukee koko sivun")
                lohko = None
                naamio = g
            else:
                naamio = geometria.naamioi(g, lohko, aset["geometria"]["pad"])
            Image.fromarray(naamio).save(kohde)
            if args.debug:
                geometria.debug_kuva(kuva, lohko, k.work / "debug" / f"s{s['n']:03d}.jpg")
        lohkot[s["n"]] = None if lohko is None else [lohko.x0, lohko.y0, lohko.x1, lohko.y1]
    print(f"Asema 2: tekstilohkot ja naamiot ({time.time() - t0:.0f} s)")

    # Asema 3: lukijat rinnakkain
    t0 = time.time()
    tehtavat = [(k.naamio / f"s{s['n']:03d}.png", m, k.lukijat / lukijat.kansio(m) / f"s{s['n']:03d}.tsv")
                for m in profiili["lukijat"] for s in sivut]
    virheet = lukijat.lue_kaikki(tehtavat, tessdata, aset["ajo"]["psm"], aset["ajo"]["rinnakkain"], args.uudelleen)
    for v in virheet:
        print("  VIRHE:", v)
    print(f"Asema 3: {len(profiili['lukijat'])} lukijaa ({time.time() - t0:.0f} s)")

    # Asema 4: liputus ja paketti
    paa, *muut = profiili["lukijat"]
    lue = lambda m, n: lukijat.sanat(k.lukijat / lukijat.kansio(m) / f"s{n:03d}.tsv")
    paa_sanat = {s["n"]: lue(paa, s["n"]) for s in sivut}
    sanakirjat = liputus.Sanakirjat([A.JUURI / p for p in profiili.get("sanakirjat", [])])
    for p in sanakirjat.puuttuvat:
        print(f"  Huom: sanakirja {p}.dic/.aff puuttuu; sanakirjaliputus ohitetaan sen osalta")
    sanasto = liputus.kirjan_sanasto(list(paa_sanat.values()), aset["liputus"])
    paa_merkisto = lukijat.merkisto(tessdata, paa)
    k.sivut.mkdir(exist_ok=True)
    arvioidut = []
    for s in sivut:
        arvio = liputus.arvioi_sivu(s["n"], paa_sanat[s["n"]], {m: lue(m, s["n"]) for m in muut},
                                    paa_merkisto, sanakirjat, sanasto, aset["liputus"])
        arvio["tiedosto"] = s["tiedosto"]
        arvio["lohko"] = lohkot.get(s["n"])
        (k.sivut / f"s{s['n']:03d}.json").write_text(json.dumps(arvio, ensure_ascii=False), encoding="utf-8")
        arvioidut.append(arvio)
    n_kohteet = liputus.paketti(arvioidut, {s["n"]: k.alkup / s["tiedosto"] for s in sivut}, k.paketti,
                                profiili["kielet"])
    n_sanat = sum(len(r["sanat"]) for a in arvioidut for r in a["rivit"])
    if n_sanat == 0:
        raise SystemExit("Lukijat eivät tuottaneet yhtään sanaa. Tarkista kansio lukijat/ ja tesseractin virheet.")
    n_lip = sum(1 for a in arvioidut for r in a["rivit"] for w in r["sanat"] if w["liput"])
    n_toinen = sum(1 for a in arvioidut for r in a["rivit"] for w in r["sanat"] if w["peruste"])
    print(f"Asema 4: {n_sanat} sanaa, liputettu {n_lip} ({n_lip / max(n_sanat, 1):.1%}), toisen lukijan lukema "
          f"{n_toinen}; tarkistuspaketissa {n_kohteet} kohdetta ({k.paketti / 'kohteet.json'})")
    k.kirjoita_tila({"kielet": profiilin_nimi, "lukijat": profiili["lukijat"], "valmisteltu": date.today().isoformat()})
    return 0


def kokoa_(args, aset: dict) -> int:
    k = A.kirja(args.kirja, aset)
    tila = k.lue_tila()
    if not tila:
        raise SystemExit(f"Aja ensin: python linja.py valmistele {args.kirja}")
    profiili = A.lue_profiili(tila["kielet"])
    sivut = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(k.sivut.glob("s*.json"))]
    sanakirjat = liputus.Sanakirjat([A.JUURI / p for p in profiili.get("sanakirjat", [])])
    numerot = kokoa.juoksevat(sivut, aset["kokoa"]["juokseva_osuus"])[1]
    tunnetut = sorted(n for n in numerot.values() if n is not None)
    etukentta = {
        "title": args.otsikko or args.kirja,
        "teos": args.teos,
        "sivut": (f"{tunnetut[0]}–{tunnetut[-1]}" if len(tunnetut) > 1 else (str(tunnetut[0]) if tunnetut else "")),
        "kaytto": "oma",
        "lukijat": ", ".join(f"tesseract {m}" for m in tila["lukijat"]),
        "taso": 1,
        "kieliprofiili": tila["kielet"],
        "muunnettu": date.today().isoformat(),
    }
    md, loki = kokoa.kokoa(sivut, {s["sivu"]: s["tiedosto"] for s in sivut}, sanakirjat, aset["kokoa"], 1,
                           args.sivumerkki, etukentta)
    k.out.mkdir(parents=True, exist_ok=True)
    (k.out / f"{args.kirja}.md").write_text(md, encoding="utf-8")
    kokoa.kirjoita_loki(loki, k.out / "muutokset.csv", k.out / "muutokset.md", args.otsikko or args.kirja)
    print(f"Kirjoitettu {k.out / (args.kirja + '.md')} ja muutokset.csv/.md ({len(loki)} kirjausta)")
    return 0


def siivoa(args, aset: dict) -> int:
    k = A.kirja(args.kirja, aset)
    for d in (k.naamio, k.lukijat, k.sivut, k.paketti, k.work / "debug"):
        if d.exists():
            shutil.rmtree(d)
            print("Poistettu", d)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="komento", required=True)
    v = sub.add_parser("valmistele", help="asemat 1–4")
    v.add_argument("kirja")
    v.add_argument("--kielet", help="kieliprofiili (kieliprofiilit.toml)")
    v.add_argument("--lahde", help="kopioi kuvat tästä kansiosta kansioon alkup/")
    v.add_argument("--debug", action="store_true", help="pienennetyt kuvat tekstilohkoista kansioon debug/")
    v.add_argument("--uudelleen", action="store_true", help="tee naamiot ja lukemat uudelleen")
    c = sub.add_parser("kokoa", help="asema 6: markdown")
    c.add_argument("kirja")
    c.add_argument("--otsikko")
    c.add_argument("--teos")
    c.add_argument("--sivumerkki", choices=["kommentti", "nakyva"], default="kommentti")
    s = sub.add_parser("siivoa", help="poista välivaiheet")
    s.add_argument("kirja")
    args = ap.parse_args()
    aset = A.lue_asetukset()
    return {"valmistele": valmistele, "kokoa": kokoa_, "siivoa": siivoa}[args.komento](args, aset)


if __name__ == "__main__":
    sys.exit(main())
