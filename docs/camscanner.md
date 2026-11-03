# CamScanner (asema 0)

Laite OnePlus Nord, CamScanner Pro. Tämä tiedosto kirjaa, mitä CamScanner antaa ulos ja millä asetuksilla.
Suositusasetukset `md`- ja `pdf-luku`-profiileille kirjataan, kun vertailu (vaihe 1) on tehty.

## Asiakirjan Lisää-valikko (Ollin kuvakaappaus 3.11.2026)

Valikko avautuu asiakirjan sivunäkymän oikean yläkulman kolmesta pisteestä. 👑 = Premium-ominaisuus.

| Ryhmä | Toiminnot |
|---|---|
| ylärivi | Muokkaa PDF:ää · Lähetä tietokoneeseen · Tallenna galleriaan · Tulosta |
| Muunna | Wordiksi 👑 · Exceliin 👑 |
| Älykkäät työkalut | Tekstiksi 👑 · Kollaasi 👑 · Käännä · Pakkaa 👑 · Ei käsinkirjoitusta · Luo tietovisa · Poimi kaavat · Lukunäyttö |
| Hallitse | Hallitse sivuja · Lukitse 👑 · Yhdistä PDF:t · Kopioi/siirrä |

Linjaston kannalta:
- **Tallenna galleriaan**: JPG-sivut, ensisijainen kuvalähde. Resoluutio on tarkistamatta.
- **Tekstiksi** ja **Wordiksi**: CamScannerin oma OCR eli camscanner-lukija. Teksti tulee ilman sanakoordinaatteja,
  joten se kohdistetaan Tesseractin sanoihin (pahvi 4.2).
- Valikossa ei ole hakukelpoista PDF:ää. Jakonapin PDF-viennistä on tarkistamatta, onko siinä tekstikerros.
- **Lähetä tietokoneeseen** kulkee todennäköisesti CamScannerin palvelimen kautta. Tätä ei ole tarkistettu, joten
  sitä ei käytetä ennen kuin OCR:n paikallisuus on selvä.
- Dropbox-latausta valikossa ei ole.

## Avoimet kokeet (Nordilla)

1. **Tekstiksi lentotilassa**: avaa Kant-Lexikonin sivu 2506 ja valitse Tekstiksi lentotila päällä. Jos tunnistus
   ei toimi, OCR tehdään pilvessä.
2. **Tekstiksi-tulos sivulta 2506**: liitä teksti chattiin. Sille lasketaan CER sivun kultalitterointia vasten,
   jolloin camscanner-lukijaa voi verrata Tesseractiin (`docs/vertailu.md`).
3. **Jaa → PDF** Dropboxiin tai Macille: tarkistan PyMuPDF:llä, onko PDF:ssä tekstikerros ja sanakoordinaatit.
4. **Tallenna galleriaan** ja tiedoston siirto Macille: kuvan koko pikseleinä.
5. Onko CamScannerin asetuksissa automaattinen lataus Dropboxiin?
