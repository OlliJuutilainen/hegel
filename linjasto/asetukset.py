"""Asetukset, kieliprofiilit ja kirjan kansiot."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

JUURI = Path(__file__).resolve().parent.parent


def lue_asetukset() -> dict:
    with open(JUURI / "asetukset.toml", "rb") as f:
        return tomllib.load(f)


def lue_profiili(nimi: str) -> dict:
    with open(JUURI / "kieliprofiilit.toml", "rb") as f:
        profiilit = tomllib.load(f)
    if nimi not in profiilit:
        raise SystemExit(f"Kieliprofiilia '{nimi}' ei ole tiedostossa kieliprofiilit.toml "
                         f"(on: {', '.join(profiilit)})")
    return profiilit[nimi]


@dataclass
class Kirja:
    nimi: str
    work: Path
    out: Path

    @property
    def alkup(self) -> Path:
        return self.work / "alkup"

    @property
    def naamio(self) -> Path:
        return self.work / "naamio"

    @property
    def lukijat(self) -> Path:
        return self.work / "lukijat"

    @property
    def sivut(self) -> Path:
        return self.work / "sivut"

    @property
    def paketti(self) -> Path:
        return self.work / "paketti"

    @property
    def tila(self) -> Path:
        return self.work / "linja.json"

    def lue_tila(self) -> dict:
        return json.loads(self.tila.read_text(encoding="utf-8")) if self.tila.exists() else {}

    def kirjoita_tila(self, tila: dict) -> None:
        self.tila.write_text(json.dumps(tila, ensure_ascii=False, indent=1), encoding="utf-8")


def kirja(nimi: str, asetukset: dict) -> Kirja:
    p = asetukset["polut"]
    return Kirja(nimi, JUURI / p["work"] / nimi, JUURI / p["out"] / nimi)
