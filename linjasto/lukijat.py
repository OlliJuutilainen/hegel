"""Asema 3: Tesseract-lukijat. Jokainen lukija on yksi tessdata_best-malli (kieliprofiilin `lukijat`).

Lukemat tallennetaan TSV:nä kansioon lukijat/<malli>/sNNN.tsv ja normalisoidaan sanatason skeemaan
(sivu, rivi, sana, teksti, bbox, luotettavuus, lukija).
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import struct
import subprocess
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Sana:
    teksti: str
    x0: int
    y0: int
    x1: int
    y1: int
    conf: float
    rivi: tuple  # (lohko, kappale, rivi) Tesseractin numeroinnissa


def kansio(malli: str) -> str:
    return malli.replace("/", "_")


def tesseract_saatavilla() -> None:
    if shutil.which("tesseract") is None:
        raise SystemExit("tesseract puuttuu (Macilla MacPortsista: docs/kartoitus.md)")


def lue(kuva: Path, malli: str, kohde: Path, tessdata: Path, psm: int) -> None:
    """Yksi sivu yhdellä mallilla -> TSV."""
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    tulos = subprocess.run(
        ["tesseract", str(kuva), "stdout", "--tessdata-dir", str(tessdata), "-l", malli,
         "--psm", str(psm), "-c", "preserve_interword_spaces=1", "tsv"],
        capture_output=True, env=env)
    if tulos.returncode != 0:
        raise RuntimeError(f"tesseract {malli} {kuva.name}: {tulos.stderr.decode(errors='replace')[-400:]}")
    kohde.write_bytes(tulos.stdout)


def lue_kaikki(tehtavat: list[tuple], tessdata: Path, psm: int, rinnakkain: int, uudelleen: bool) -> list[str]:
    """tehtavat: [(kuva, malli, kohde)]. Palauttaa virheet. Valmiit lukemat ohitetaan, ellei uudelleen."""
    tehtavat = [t for t in tehtavat if uudelleen or not t[2].exists() or t[2].stat().st_mtime < t[0].stat().st_mtime]
    virheet = []

    def yksi(t):
        try:
            t[2].parent.mkdir(parents=True, exist_ok=True)
            lue(t[0], t[1], t[2], tessdata, psm)
            return None
        except Exception as e:  # yksi huono sivu ei kaada koko ajoa
            return str(e)

    with ThreadPoolExecutor(max_workers=max(1, rinnakkain)) as ex:
        for i, v in enumerate(ex.map(yksi, tehtavat), 1):
            if v:
                virheet.append(v)
            print(f"\r  luettu {i}/{len(tehtavat)}", end="", flush=True)
    if tehtavat:
        print()
    return virheet


def sanat(tsv: Path) -> list[Sana]:
    out = []
    rivit = csv.DictReader(io.StringIO(tsv.read_text(encoding="utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE)
    for r in rivit:
        if r.get("level") != "5" or not (r.get("text") or "").strip():
            continue
        x, y, w, h = (int(r[k]) for k in ("left", "top", "width", "height"))
        out.append(Sana(unicodedata.normalize("NFC", r["text"].strip()), x, y, x + w, y + h,
                        float(r["conf"]), (int(r["block_num"]), int(r["par_num"]), int(r["line_num"]))))
    return out


# --------------------------------------------------------------------------------------
# Mallin merkistö: luetaan .traineddata-tiedostosta (LSTM_UNICHARSET, osa 21), ei tarvita
# combine_tessdata-ohjelmaa.
# --------------------------------------------------------------------------------------

_LSTM_UNICHARSET = 21


def merkisto(tessdata: Path, malli: str) -> set[str]:
    data = (tessdata / f"{malli}.traineddata").read_bytes()
    n = struct.unpack_from("<i", data, 0)[0]
    offsetit = list(struct.unpack_from(f"<{n}q", data, 4))
    alku = offsetit[_LSTM_UNICHARSET]
    if alku < 0:
        return set()
    loppu = min([o for o in offsetit if o > alku] + [len(data)])
    rivit = data[alku:loppu].decode("utf-8", errors="replace").splitlines()
    merkit = set()
    for rivi in rivit[1:]:
        m = rivi.split(" ", 1)[0]
        if m and m != "NULL":
            merkit.update(unicodedata.normalize("NFC", m))
    return merkit
