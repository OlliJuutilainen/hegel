# Vaihe 0: kartoitus (3.11.2026)

Pahvin (`docs/linjasto.md`) vaihe 0. Tehty pilviympäristössä (Linux, Python 3.13), ei Ollin Macilla.
Macin oma tila (venv, tesseract, adb) on tarkistamatta, ja sen tarkistuskomennot ovat luvussa 2.3.

## 1. Nykyinen koodi asemittain

Repossa ei ole testejä eikä testiaineistoa. Kaikki OCR-työkalut ottavat syötteeksi PDF:n, ja kuvakansiota
lukee vain `vcrop.py`.

| Asema | On jo | Puuttuu |
|---|---|---|
| 0 CamScanner | – | kaikki |
| 1 Vastaanotto | `vcrop.natural_key` (sivu2 ennen sivu10) | manifesti, inbox → `local/work/<kirja>/alkup/`, Magic Pro- ja Original-parit |
| 2 Geometria | `vcrop.detect_text_block` (adaptiivinen kynnystys, vaakalaajennus, pienten ja reunaa koskettavien alueiden hylkäys), `--debug`; `ocr/preprocess.py`: aukeaman jako, reunavarjojen valkaisu, suoristus ±5° ja `Region.to_source` koordinaattien paluuseen; palstat `pdf_to_markdown._column_groups` (riveistä) | naamio koko tekstilohkon ulkopuolelle (nyt valkaistaan vain reunasta sisään ulottuvat varjot), naamio paperin sävyllä (nyt 255) |
| 3 Lukijat | Tesseract: `ocr/tesseract_ocr.py` (TSV ja sanaluotettavuus) ja `ocr/scanpage.py` (hOCR ja `x_wconf`, rivit, perusviivat). PDF:n oma OCR-kerros luetaan pdfminerillä ja äänestetään Tesseractia vastaan (`_choose`, sanakirja erotuomarina). | yhteinen sanaskeema, lukemien tallennus, tessdata_best, PSM, `preserve_interword_spaces` |
| 4 Liputus | luotettavuutta käytetään vain suodattimena (`--min-conf`) ja käsialarivien tunnistukseen (`_handwriting`) | kaikki liputus ja paketti |
| 5 Tarkastus | – | kaikki |
| 6 Markdown | `pdf_to_markdown.py`: juoksevat otsikot ja sivunumerot pois, sivunumeroiden korjaus naapureista, sivumerkki `{p. 25}`, tavutuksen poisto, alaviitteet `[^1]`, kursiivi viivojen kallistumasta, etukenttä (Crossref, Latomon avaimet) | NFC (ei `unicodedata`-normalisointia missään), kielikohtaisuus, `[^s12-1]` |
| 7 PDF | `run_tesseract.py` + `ocr/overlay.py`: sandwich-PDF (kuva ja näkymätön, sanoihin kohdistettu tekstikerros, reportlab), `--split-spreads`; `vcrop.py` tekee luvun 12.2 ensimmäisen kohdan sellaisenaan (rajaus ylhäältä ja alhaalta, leveyteen ei kosketa) | harmaasävy, täyttöpalkit, korjausten vienti tekstikerrokseen |

`add_outline.py`, `parse_printed_toc.py`, `find_headings.py` ja `migrate_annotations.py` eivät kuulu linjastoon
ja jäävät ennalleen.

Huomioita:
- Jos CamScanner vie hakukelpoisen PDF:n, `pdf_to_markdown.py` todennäköisesti tekee jo tesseract- ja
  camscanner-lukijan äänestyksen. CamScannerin PDF:llä tätä ei ole testattu.
- Äänestys valitsee lukeman hiljaa eikä kirjaa eroja. Tämä on pahvin perusperiaatteen vastaista: ero pitää
  kirjata lokiin ja liputtaa, kun sanakirja ei ratkaise.
- Kieliriippuvuudet: `Lexicon` lukee vain `/usr/share/dict/words`-listan ja englannin päätteet. Tavutuksen
  poiston yhdysmerkkisäännöt ovat englantia. Juoksevan otsikon vertailuavain on `re.sub(r"[^a-z]", "", …)`
  (`pdf_to_markdown.py:947`, `:1008`), joten ä, ö ja kreikka katoavat avaimesta, ja kreikankielisen otsikon
  avain on tyhjä.

## 2. Ympäristö

### 2.1 Python-kirjastot (PyPI 3.11.2026)

Kustakin paketista on haettu uusin pyörä, jonka pip hyväksyy macOS 11:n x86_64:llä ja CPython 3.14:llä
(alustatunniste enintään `macosx_11_0`, cp314 tai abi3).

| Kirjasto | Käyttökelpoinen pyörä | Huom |
|---|---|---|
| numpy | 2.5.4 (macosx_10_15) | |
| Pillow | 13.0.0 | |
| scipy | 1.18.1 | `ndimage.label` korvaa opencv:n `connectedComponentsWithStats` |
| PyMuPDF | 1.28.2 (abi3, macosx_10_15) | |
| rapidfuzz | 3.14.6 | |
| lxml | 6.1.3 | |
| pytesseract, pdf2image, pypdf, reportlab, pdfminer.six, tqdm | puhdasta Pythonia | nykyiset riippuvuudet |
| spylls 0.1.7 | puhdasta Pythonia | hunspell-sanakirjat |
| pyhfst 1.4.0 | puhdasta Pythonia | HFST-transduktorit. Suomen sanatarkistus Giellateknon analysaattorilla (`analyser`, 25 Mt, ladataan kerran uralicNLP:n kautta) antoi pilvessä samat tulokset kuin Voikko 20 testisanalla (10 oikeaa, 10 OCR-virheellistä); 220 sanaa 0,03 s:ssa |
| libvoikko 4.3 | puhdasta Pythonia | vain sidos: vaatii järjestelmään C-kirjaston libvoikko ja voikko-fi-sanaston. Homebrew'ssa ei ole libvoikko-pakettia Big Surille (Intel-paketit vain macOS 13 ja 14), joten Homebrew kääntäisi sen lähdekoodista |
| **opencv-python** | **ei käytettävissä** | viimeinen macOS 11:lle sopiva pyörä on 4.9.0.80 (macosx_10_16), 4.10 ja uudemmat vaativat macOS 12–14:n. 4.9 on käännetty numpy 1.x:ää vasten: täällä kokeiltu numpy 2:lla, `import cv2` → `ImportError: numpy.core.multiarray failed to import`. numpy 1.26:sta ei ole cp314-pyörää. |
| **ocrmypdf** | **ei käytettävissä** | 17.13 on puhdasta Pythonia, mutta riippuu pikepdf:stä, jonka macOS x86_64 -pyörät vaativat macOS 15:n. Lisäksi se tarvitsee Ghostscriptin. |

Seuraukset:
- `vcrop.py` ei toimi Python 3.14 -venvissä. README:n ohje `"opencv-python<4.10" "numpy<2"` toimii vain
  Pythonilla, jolle numpy 1.26:sta on pyörä (enintään 3.12). Linjaston uusi koodi käyttää Pillowia, numpya ja
  scipyä. `vcrop.py` jätetään ennalleen.
- Tekstikerros tehdään ocrmypdf:n sijaan nykyisellä `ocr/overlay.py`:llä.
- Harmaasävy tehdään ilman Ghostscriptia, kuvavaiheessa Pillowin `convert("L")`:llä.

Homebrew (formulae.brew.sh, 3.11.2026): **tesseractille ei ole valmista pakettia millekään Intel-macOS:lle**
(vain arm64 ja Linux). Jos Macilla ei ole tesseractia valmiina, Homebrew kääntäisi sen lähdekoodista riippuvuuksineen
(cairo, pango, icu4c, leptonica…) macOS-versiolla, jota se ei enää tue. Siksi Macin `tesseract --version` pitää
tarkistaa ennen vaihetta 2.

### 2.2 tessdata_best

Tarkistettu HEAD-pyynnöillä (`raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/`), kaikista tuli 200:
eng, fin, deu, lat, grc, ell, ita, fra, dan, lit, swe, deu_latf (12,9 Mt) ja script/Fraktur.
**frk puuttuu tessdata_bestista (404)**, joten fraktuuraan käytetään deu_latf:ia tai script/Frakturia.

### 2.3 Mac (Ollin ajo 3.11.2026)

- `~/hegel/venv` **ei ole olemassa**, toisin kuin pahvi olettaa. Python-versio jäi siksi selvittämättä.
- tesseract 5.4.1 (leptonica 1.87) on asennettu **MacPortsista**. Sen tessdata-kansio on `/opt/local/share/tessdata/`,
  ja kieliä on vain kaksi: eng ja fin. tessdata_bestin mallit ladataan omaan kansioonsa
  (`local/tessdata/`, käytetään `--tessdata-dir`- tai `TESSDATA_PREFIX`-asetuksella), joten järjestelmään ei tarvitse
  koskea.
- Löytyvät: `/usr/local/bin/brew`, `/opt/local/bin/port` ja `/usr/local/bin/adb`.
- Python: `/usr/local/bin/python3` on 3.14.5. MacPortsista on lisäksi python312 (3.12.13) ja python314 (3.14.5).
  Frameworks-asennusta ei ole.
- poppler 26.02 on asennettu MacPortsista (`/opt/local/bin/pdftoppm`).
- tessdata_best on ladattu kansioon `~/hegel/local/tessdata/`: deu, eng, fin, grc, lat ja script/Latin.
  `tesseract --tessdata-dir` löytää ne.
- Note Air3:n näyttö on 1404 × 1872 ja 227 ppi (julkaistut tiedot, `docs/vertailu.md`).
- Tesseract (MacPorts) käyttää yhtä ydintä: Kant-Lexikonin sivu 2152 × 3408 px `deu`-mallilla vie 11,5 s (real ≈ user).
  `hw.ncpu` on 8 (neljä fyysistä ydintä ja hyperthreading), joten sivut luetaan rinnakkain useana prosessina.

Alkuperäinen tarkistuslista:

```
cd ~/hegel && source venv/bin/activate
python --version
python -c "import numpy; print(numpy.__version__)"; python -c "import cv2; print(cv2.__version__)"
ls /Library/Frameworks/Python.framework/Versions/
tesseract --version; tesseract --list-langs
which gs qpdf adb brew port
adb -s C99BDC8E shell wm size
adb -s C99BDC8E shell wm density
```

## 3. CamScannerin OCR: laitteella vai pilvessä?

Asia on ratkaisematta. Lähteet eivät kerro, tehdäänkö tunnistus laitteella.
- INTSIGin tietosuojakäytäntö 25.5.2018 ([s.intsig.net](https://s.intsig.net/r/terms/PP_CamScanner_en-us.html)):
  *"To process Cloud OCR, we process these requests through our cloud"*. Palvelimet voivat olla Kiinassa.
- Päiväämätön versio ([static.intsig.net](https://static.intsig.net/r/terms/PP_CamScanner_en-us.html)):
  *"If you only set to use CamScanner in locate mobile terminal device, we are not able to collect any of your
  information."* (sic). Sana OCR ei esiinny siinä lainkaan.
- Hakupalvelun tiivistelmän mukaan uudempi käytäntö (voimassa 20.1.2026) mainitsee OCR:ää varten ladatut
  tiedostot. Nykyistä käytäntöä (JavaScript-sivu) en saanut auki, joten tieto on tarkistamatta.

Koe vaiheessa 1: Nord lentotilaan ja OCR uudelle sivulle. Jos tunnistus ei toimi offline, se tehdään pilvessä.
Jos se toimii, tunnistus voi olla paikallinen, mutta synkronointi saattaa silti lähettää kuvat myöhemmin.
Tulos kirjataan `docs/vertailu.md`:hen.

## 4. Ristiriidat pahvin ja repon välillä

1. **Etukentän avain `lahde`** (luku 11): LUiN ja Latomo (`luin/md.js`, `ALIAS`) lukevat avaimet `lahde`,
   `source` ja `url` verkko-osoitteeksi. Sama ansa korjattiin jo `pdf_to_markdown.py`:ssä, jossa `source`
   vaihdettiin muotoon `journal`/`volume`/`issue`/`pages`. Myöskään `pvm` ei ole aliaksissa.
2. **Sivumerkki**: `pdf_to_markdown.py` käyttää muotoa `{p. 25}`, pahvi muotoja `<!-- s. 12 -->` ja
   `{s. 12}`. LUiN poistaa `<!-- -->`-kommentit näkyvistä.
3. **Kursiivi** (luku 11): pahvi olettaa, ettei kursiivia saada, mutta repo tunnistaa sen jo skanneilta viivojen
   kallistumasta (`scanpage.word_slant`). Tunnistus on algoritmista, ei tekoälyä.
4. **Python 3.14 ja opencv** (luku 2): ks. 2.1.
5. **venv**: README:n Setup-osio käyttää kansiota `.venv`, vcrop-osio ja pahvi kansiota `~/hegel/venv`.
6. Luku 7 viittaa kieliprofiileihin lukuna 12, mutta ne ovat luvussa 13. Pahvi on tallennettu sellaisenaan.
7. Luku 13: Tesseractille ei voi antaa kaikkia profiilin kieliä kerralla. Latinan lisääminen kaksinkertaisti
   virheet saksankielisellä sivulla (`docs/vertailu.md`).

## 5. Ollin vastaukset (3.11.2026) ja niistä seuraavat päätökset

1. **Kielet**: Kant-Lexikonissa pääkieli on saksa, ja mukana on ainakin latinaa ja ehkä kreikkaa. Muuten
   ensisijaisia ovat suomi ja englanti. Aluksi tehdään vain nämä: deu, lat, grc, fin ja eng. Myöhemmin tulevat
   romania, tanska, ruotsi, ranska ja italia (liettuaa ei mainittu). Muihin kieliin ei käytetä nyt aikaa.
2. **Markdown**: sen pitää toimia LUiN:ssa ja Clauden lähdeaineistona. LUiN-muotoa muutetaan Claudelle
   sopivammaksi vain, jos nykyinen ei ole kunnossa. Päätökset:
   - Etukenttä käyttää Latomon avaimia: `title`, `teos`, `toimittaja`, `sivut` jne. Lähdeteos ei mene avaimeen
     `lahde`, koska LUiN lukee sen verkko-osoitteeksi.
   - Linjaston omat avaimet (`kaytto: oma`, `lukijat`, `taso`, `kieliprofiili`) kulkevat mukana. md.js säilyttää
     ne (`raaka`), eivätkä ne vaikuta viitteeseen (mitattu).
   - Pahvin sivumerkki `<!-- s. N -->` jää. md.js poistaa sen näkyvistä myös kesken tavutetun sanan
     (`gege<!-- s. 2507 -->benen` → *gegebenen*), ja Claude näkee sen raakatekstistä. `{p. N}` näkyisi LUiN:ssa
     tekstinä (mitattu node-ajossa).
3. **Kultaotos**: Kant-Lexikonin juuri tehty skannaus vanhoilla asetuksilla (oletuskoko, Magic Pro, värit
   säilytetty). Ensisijainen tulos on md, mutta samalla testataan myös pdf-luku. Olli ei rajaa sivuja käsin
   CamScannerissa, eikä Note Air -sovitukseen lisätä tekoälyvaihetta.
   - Ratkaisu: ylä- ja alarajaus tehdään algoritmisesti sivu kerrallaan (vcrop-logiikka), joten tekstilohkon paikka
     saa vaihdella sivulta toiselle. Testisivulla se toimi (`docs/vertailu.md`).
   - Avoinna: jotta tekstikoko ei hypi, sivut skaalataan rivivälin mukaan samaan mittakaavaan. Ehdotus odottaa
     Ollin hyväksyntää ja vaatii vähintään 10 oikeaa sivua.
4. **CamScannerin vienti**: valikko on kirjattu `docs/camscanner.md`:hen, ja kokeet ovat siellä.
5. **Voikko**: Olli antoi luvan asentaa, jos asennus kannattaa. Järjestelmäasennusta ei tehdä: Big Surille ei ole
   Homebrew-pakettia, ja pyhfst ja Giellateknon analysaattori (puhdasta Pythonia) antoivat samat tulokset kuin
   Voikko. Tämä tarkistetaan vielä isommalla sanajoukolla vaiheessa 2.
6. **Kursiivi**: tavoitellaan. Testisivulla kursiivisanat erottuvat kallistumasta selvästi, mutta nykyiset
   kynnykset eivät sovi tähän kirjaan (`docs/vertailu.md`).
