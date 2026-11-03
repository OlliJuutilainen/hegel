# CamScanner (asema 0)

Laite OnePlus Nord, CamScanner Pro. Tämä tiedosto kirjaa, mitä CamScanner antaa ulos ja millä asetuksilla.

**Käyttäjän päätös 3.11.2026: CamScannerin omaa OCR:ää ei käytetä.** CamScanner on vain kuvalähde (JPG-sivut).
camscanner-lukija (pahvi 3.1 ja 4.2) jää pois, eikä OCR:n paikallisuutta tarvitse selvittää. Lukijoina ovat Tesseract
`deu` ja `script/Latin` (`docs/vertailu.md`), tasolla 3 myös Claude.

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

## Kuvausresoluutio (3.11.2026)

Valittuna oli 8M (3840 × 2160, 16:9). Suositus on 12M (4000 × 3000, 4:3), joka on listan suurin. Se on kummaltakin
sivultaan vähintään yhtä suuri kuin 16:9-kuva (4000 ≥ 3840 ja 3000 ≥ 2160), joten sivu saa samalta etäisyydeltä
vähintään yhtä monta pikseliä, ja sivun leveydelle jää enemmän tilaa. Lyhyellä sivulla pikseleitä on 39 % enemmän.
Haittana ovat isommat tiedostot. Viedyn JPG:n todellinen koko tarkistetaan ensimmäisestä viennistä
(`sips -g pixelWidth -g pixelHeight sivu.jpg`).

## Avoimet kokeet (Nordilla)

1. **Tallenna galleriaan** ja tiedoston siirto Macille: kuvan koko pikseleinä ja JPEG-laatu.
2. Original- ja Magic Pro -suodattimen vertailu samoilla sivuilla (vaihe 1).
