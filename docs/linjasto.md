# PAHVI: Hegel-linjasto – kamerakuvasta tarkistettuun markdowniin ja luettavaan PDF:ään

> Kohde: Claude Code, repo `~/hegel`. Tallenna tämä sellaisenaan tiedostoon `docs/linjasto.md`. Lisää `CLAUDE.md`:hen enintään 15 rivin tiivistelmä (tavoite, vaiheiden tila, käyttöperiaatteet lyhyesti) ja viittaus tähän tiedostoon. Älä paisuta CLAUDE.md:tä.

## 0. Tavoite

Valmis, toistettava linjasto: CamScanner-kuvat → OCR → tarkistus → markdown ja/tai Note Air3:lle sovitettu PDF. Ei aloitusta tyhjästä joka kerta.

Perusperiaate: **tekstin tuottaa algoritmi, ja tekoäly toimii vain tarkastajana.** Algoritmi lukee kaiken ja merkitsee epävarmat kohdat. Tekoäly näkee vain merkityt kohdat kuvarajauksena ja vastaa niistä rajattuun kysymykseen. Tekoäly ei koskaan kirjoita tekstiä merkityn kohdan ulkopuolelle. Jokainen muutos kirjataan lokiin.

Kaksi tavoitetta, joiden välillä tasapainoillaan:
1. Totuudenmukaisuus: tekoäly ei saa "täydentää" lauseita. Algoritminen lukema voi joskus säilyttää alkuperäisen paremmin.
2. Tekoälyn käytön minimointi: tokeneita vain sinne, missä algoritmi on epävarma.

Hegel pysyy itsenäisenä oliona. Tekoälyasema on irrotettava välivaihe, ja saman tarkistuspaketin voi käydä läpi myös ihminen.

## 1. Käyttöperiaatteet (tekijänoikeus ja etiikka)

Ollin linjaus:
- Tekijänoikeudella suojattuja tekstejä ei lisätä projekteihin pysyviksi referensseiksi.
- Kirjojen otteiden skannaus PDF:ksi tai markdowniksi **omaan käyttöön** on sallittua, samoin niiden väliaikainen lataaminen Claudelle käsittelyä ja keskustelua varten. Clauden koulutuskäyttö on Ollin asetuksissa pois päältä.
- Esimerkki sallitusta käytöstä: Kant-Lexikonin Vernunft-artikkelin ote skannataan ja muunnetaan markdowniksi, ja sen sisällöstä keskustellaan erillisessä chatissa.

Toteutus:
- Kaikki skannaukset, työtiedostot ja tulosteet ovat kansiossa `local/` (gitignore). Repoon menee vain koodi, asetukset, dokumentaatio ja public domain -testiaineisto.
- Tulos-MD:n YAML-otsakkeeseen kirjataan `kaytto: oma`, lähde ja sivut.
- `siivoa <kirja>` poistaa tarkistuspaketit ja välivaiheet. Tulokset jäävät.
- Tuloksia ei julkaista GitHub Pagesiin eikä minnekään muualle. Jos pyyntö näyttää ylittävän linjauksen (koko teoksen skannaus, jakaminen, julkaisu), huomauta siitä kerran ystävällisesti. Älä holhoa.
- Kolmannen osapuolen palvelut: selvitä ja kirjaa `docs/vertailu.md`:hen, tekeekö CamScannerin OCR tunnistuksen laitteella vai lähettääkö se kuvat pilveen. Olli päättää, mitä aineistoa sinne menee.

## 2. Ympäristö

- MacBook Pro mid-2014, macOS 11.7.10, x86_64. Python 3.14, venv `~/hegel/venv` (ei `ocrmypdf-venv`).
- Komentosarjat alkavat aina näin:
  ```
  cd ~/hegel
  source venv/bin/activate
  ```
- Tarkista kunkin kirjaston saatavuus tälle alustalle ENNEN kuin valitset sen: tesseract + tessdata_best, ocrmypdf, opencv-python (onko pyöriä Python 3.14:lle ja macOS 11:lle; jos ei ole, käytä Pillow + numpy -toteutusta tai kysy Ollilta), PyMuPDF, rapidfuzz, libvoikko + voikko-fi tai vaihtoehtoisesti hunspell-sanakirjat puhtaalla Pythonilla (esim. spylls).
- Älä asenna järjestelmätason ohjelmia (Homebrew) kysymättä.
- Uudelleenkäytä olemassa olevaa koodia (esim. `vcrop.py`, tekstilohkon tunnistus). Älä riko nykyisiä toimintoja.
- Alkuperäisiä kuvia ei muokata koskaan.

## 3. Arkkitehtuuri

### 3.1 Lukijat (vaihdettavia)
Kaikki lukijat normalisoidaan samaan sanatason skeemaan: `sivu, rivi_id, sana_id, teksti, bbox | null, luotettavuus | null, lukija`.
- `tesseract`: paikallinen, tessdata_best, hOCR/TSV sanakohtaisine luotettavuusarvoineen. Toimii myös koordinaattiankkurina muille lukijoille.
- `camscanner`: CamScannerin oma OCR, tuodaan sen viennistä (ks. 4.2).
- `claude`: vain tasolla 3, koko sivun itsenäinen luenta (ks. 9.3).

### 3.2 Tasot
- **Taso 1:** pelkkä algoritmi ja liputus. Epävarmat kohdat merkitään tulokseen, eikä tekoälyä käytetä.
- **Taso 2:** tekoäly tarkastaa vain liputetut kohdat.
- **Taso 3:** erittäin vaikea materiaali. Tekoäly lukee koko sivun itsenäisesti, ja Hegel vertaa tulosta muihin lukijoihin. Kohdat, joissa lukijat ovat samaa mieltä, hyväksytään. Erot käsitellään kuten tason 2 kohteet.

### 3.3 Tulosprofiilit
- `md`: tavoitteena vain mahdollisimman hyvä teksti. Kuvien ulkonäöllä ei ole väliä.
- `pdf-luku`: luettava ja merkittävä PDF Note Air3:lle ja Macin näytölle, tekstikerroksella.
- `molemmat`.

### 3.4 Käyttöliittymä (nimet saa sovittaa repon tapoihin)
`python linja.py <kirja> --profiili md|pdf-luku|molemmat --taso 1|2|3 --kielet <profiili>`
Alikomennot: `valmistele` (asemat 1–4), `kokoa` (asemat 6–7), `siivoa`.

### 3.5 Kansiot
- Saapuvat: `~/Dropbox/hegel-inbox/<kirja>/`, vain luku. Kopioi kuvat kansioon `local/work/<kirja>/alkup/`.
- Työtiedostot: `local/work/<kirja>/`. Tulokset: `local/out/<kirja>/`.

## 4. Asema 0: CamScanner (Olli tekee, Claude Code kirjoittaa ohjeen)

### 4.1 Kuvaus
- Laite: OnePlus Nord, CamScanner (Pro-lisenssi).
- Lähtöasetukset: Scan Settings → High Quality Scan päällä. Oletussuodatin Magic Pro / Omnifix, joka poistaa sormet, varjot ja epätarkkuudet. Automaattinen rajaus sivun reunoihin, koska oikaisu tarvitsee niitä.
- Riski: Magic Pro on tekoälykäsittelyä, ja haalealla tekstillä se voi muuttaa kirjainmuotoja. Vertailu (vaihe 1) ratkaisee, kannattaako `md`-profiilissa käyttää Original-suodatinta, Magic Prota vai molempia. Tarkistusrajauksiin liitetään Original-versio, jos se on saatavilla.
- Viehättävät jäljet (sivupainot, varjot, roskat, sotku) saavat jäädä näkyviin. Niitä ei poisteta kosmeettisista syistä, vain OCR:n näkökentästä (asema 2).

### 4.2 Vienti
Olli kokeilee Nordilla, mitkä vientimuodot Pro-lisenssi tarjoaa, ja Claude Code kirjaa tulokset tiedostoon `docs/camscanner.md`:
- JPG-sivut täydellä resoluutiolla. Tämä on aina ensisijainen kuvalähde.
- Hakukelpoinen PDF, jossa on CamScannerin OCR-tekstikerros. Jos sellainen saadaan, sanakoordinaatit saa ulos PyMuPDF:llä `get_text("words")`. Tämä on paras muoto, koska se antaa camscanner-lukijalle koordinaatit.
- TXT/DOCX. Jos koordinaatteja ei saada, kohdista teksti Tesseractin sanoihin sekvenssikohdistuksella (rapidfuzz/difflib).
- Testaa, toimiiko automaattinen lataus Dropboxiin kansioon `hegel-inbox/<kirja>/`.

Kun vertailu on tehty, `docs/camscanner.md`:hen kirjataan suositusasetukset erikseen `md`- ja `pdf-luku`-profiilille.

## 5. Asema 1: Vastaanotto
- Sivut luonnolliseen järjestykseen (sivu2 ennen sivu10).
- Manifesti `local/work/<kirja>/manifesti.csv`: tiedosto, sivunumero (jos tunnistettavissa), suodatinversio, lähde.
- Jos sama sivu on sekä Magic Pro- että Original-versiona, yhdistä ne pariksi.

## 6. Asema 2: Geometria ja OCR-naamio
- Tekstilohkon tunnistus (vcrop-logiikka: adaptiivinen kynnystys, vaakalaajennus, reunaa koskettavien ja pienten alueiden hylkäys).
- OCR:lle tehdään **naamioitu kopio**, jossa kaikki tekstilohkon ulkopuolinen on taustan väristä. Peukalot, painot ja reunasotku katoavat vain OCR:n näkökentästä.
- Visuaalinen tulos tehdään aina alkuperäisestä kuvasta (asema 7).
- Monipalstaisuus tunnistetaan (esim. leksikot), ja lukujärjestys tarkistetaan.
- `--debug`: pienennetyt kuvat, joihin naamio ja lohkot on piirretty.

## 7. Asema 3: Lukijat
- `tesseract`: kielet kieliprofiilista (luku 12), `preserve_interword_spaces=1`, PSM valitaan sivun rakenteen mukaan. Tallenna hOCR ja TSV.
- `camscanner`: tuonti ja normalisointi (4.2).
- Kaikki lukemat tallennetaan kansioon `local/work/<kirja>/lukijat/<lukija>/`.

## 8. Asema 4: Liputus ja tarkistuspaketti (ei tekoälyä)

### 8.1 Liputusperusteet (kynnysarvot tiedostossa `asetukset.toml`)
- Tesseractin sanaluotettavuus alle kynnyksen.
- Sana ei löydy profiilin kielten sanakirjoista. Suomelle Voikko, joka käsittelee taivutuksen. Muille hunspell. Kieli valitaan merkistön perusteella (kreikka Unicode-lohkosta) ja kokeilemalla profiilin kieliä.
- Lukijat ovat eri mieltä (kun lukijoita on useampi kuin yksi).
- Epätavalliset merkit tai merkkiyhdistelmät, rikkinäiset diakriitit, numeroiden ja kirjainten sekoitukset.
- Rivi, jolla on paljon liputettuja sanoja, liputetaan rivinä.

### 8.2 Paketti
`local/work/<kirja>/paketti/kohteet.json` ja `paketti/rajaukset/<id>.png`. Rajaus on rivin korkuinen, ja sen ympärillä on puolen rivin marginaali. Jos Original-versio on saatavilla, mukaan tulee myös sen rajaus.

Kohteen skeema:
```
{ "id": "s012-r07-w03", "sivu": 12,
  "rajaus": "rajaukset/s012-r07.png", "rajaus_original": "rajaukset/s012-r07-orig.png" | null,
  "lukemat": {"tesseract": "Vernunft", "camscanner": "Vemunft"},
  "luotettavuus": 41, "syyt": ["matala_luottamus", "lukijat_eri_mieltä"],
  "konteksti_ennen": "...", "konteksti_jalkeen": "...", "kielet": ["deu"] }
```

## 9. Asema 5: Tarkastus

### 9.1 Skill `ocr-tarkistus`
Kirjoita `.claude/skills/ocr-tarkistus/SKILL.md`. Säännöt:
- Lue vain paketti. Katso jokaisen kohteen rajauskuva (Read) ennen kuin vastaat. Vastauksen on perustuttava kuvaan, ei kontekstiin.
- Diplomaattinen litterointi: säilytä alkuperäinen oikeinkirjoitus, vanhat kirjoitusasut, painovirheet (kirjaa ne huomioon, älä korjaa), polytoninen kreikka sellaisenaan (NFC). Älä modernisoi, älä korjaa kielioppia äläkä täydennä.
- Tilat: `vahvistettu` (jokin lukemista on oikein), `korjattu` (eri teksti, kuvassa näkyvä), `lukukelvoton`. Merkitse varmuus: `korkea | keski | matala`.
- Epävarmuus ilmaistaan `lukukelvoton`-tilalla tai matalalla varmuudella, ei arvaamalla.
- Käsittele kohteet enintään 40 kohteen erissä. Kirjoita tulos tiedostoon `paketti/vastaukset.json`. Älä koske muihin tiedostoihin. Raportoi lopuksi määrät tiloittain.

Vastauksen skeema: `{ "id": "...", "tila": "...", "teksti": "...", "varmuus": "...", "huomio": "" }`

### 9.2 Ihmistarkistus (valinnainen, vaihe 3b)
`local/work/<kirja>/tarkistus.html` on paikallinen sivu, joka näyttää rajaukset ja lukemat ja on näppäimistöllä ohjattava. Se kirjoittaa saman `vastaukset.json`-tiedoston, joten ihminen voi korvata tekoälyaseman.

### 9.3 Taso 3: kokosivuluenta
Skillin tila `--kokosivu`: tekoäly lukee sivukuvat lukujärjestyksessä ja kirjoittaa tiedostot `lukijat/claude/sNNN.txt`. Samat diplomaattiset säännöt pätevät, ja epävarmat kohdat merkitään `[?]`. Hegel kohdistaa tuloksen Tesseractiin sanatasolla. Kohdat, joissa lukemat ovat samat, hyväksytään. Eroista tehdään uusi paketti (9.1), jossa tekoäly katsoo rajauksen uudelleen tai ihminen ratkaisee.

## 10. Hyväksymissäännöt ja lokit
- `vahvistettu`: hyväksytään, jos teksti on jokin lukemista.
- `korjattu`: hyväksytään automaattisesti, jos editointietäisyys johonkin lukemaan on enintään max(2, 25 % pituudesta) JA vähintään yksi seuraavista täyttyy: toinen lukija tukee korjausta, sanakirja hyväksyy sanan tai varmuus on korkea. Muuten kohtaan tulee `sana[?]`, ja vaihtoehdot kirjataan lokiin.
- `lukukelvoton`: paras OCR-lukema ja `[?]`, tai `[…?]`, jos lukemaa ei ole (asetus).
- Jokainen päätös kirjataan tiedostoihin `local/out/<kirja>/muutokset.csv` ja `muutokset.md`: sivu, id, alkuperäiset lukemat, valittu teksti, tila, varmuus, peruste.
- Tasolla 1 kaikki liputetut kohdat merkitään `[?]`.

## 11. Asema 6: Markdown
- YAML-otsake: `lahde, sivut, pvm, lukijat, taso, kieliprofiili, kaytto: oma`.
- Lukujärjestys Tesseractin lohkoista. Monipalstaiset sivut luetaan palsta kerrallaan.
- Sivuotsikot ja alatunnisteet: rivit, jotka toistuvat sumeasti vähintään 30 %:lla sivuista sivun ylä- tai alareunassa, poistetaan. Sivunumero siirretään sivumerkkiin.
- Sivumerkki on oletuksena `<!-- s. 12 -->`. Valinta `--sivumerkki nakyva` tuottaa muodon `{s. 12}`.
- Tavutuksen poisto kielikohtaisesti. Rivin lopun yhdysmerkki ja pienellä alkava seuraava rivi yhdistetään, jos yhdistetty sana löytyy sanakirjasta. Aidot yhdysmerkit säilyvät (esim. "EU-maa", "Kant-tutkimus", saksan "Vernunft- und Verstandesbegriffe" eli yhdysmerkin jälkeen välilyönti ja und/oder/and/ja/tai). Epäselvät tapaukset säilytetään ja kirjataan lokiin.
- Kappaleet tunnistetaan sisennyksestä ja pystyvälistä hOCR-koordinaattien avulla.
- Alaviitteet: pienempi x-korkeus sivun alareunassa muuttuu muotoon `[^s12-1]`.
- Unicode NFC. Diakriitit eivät saa kadota (testi).
- Kursiivi ja lihavointi eivät säily Tesseractista. Jos niitä tarvitaan (esim. leksikon hakusanat), lisää myöhemmin valinnainen skill-tila, joka merkitsee vain muotoilun eikä muuta tekstiä. Älä toteuta ennen kuin Olli pyytää.

## 12. Asema 7: PDF-profiilit

### 12.1 Yhteistä
- Kuvat tulevat alkuperäisistä (valittu suodatinversio). Tekstikerros tehdään sandwich-tekniikalla (Tesseractin textonly_pdf tai ocrmypdf:n hOCR-renderöinti). Hyväksytyt korjaukset viedään tekstikerrokseen, jos se onnistuu kohtuudella muokkaamalla hOCR:ää. Muuten käytetään raakaa OCR:ää ja kirjataan se lokiin.
- Oletuksena harmaasävy, koska Olli ei halua värejä lopputuloksiin (värikkäät reunat häiritsevät). Valinta `--varit` säilyttää värit. Toteutus esim. Ghostscriptin `ColorConversionStrategy=Gray` tai muunnos jo kuvavaiheessa.

### 12.2 `pdf-luku`: Note Air3
- Rajaa ylhäältä ja alhaalta mahdollisimman paljon tekstilohkoon (pieni pad). Sivunumerot ja otsikot ovat sisältöä. Leveyteen ei kosketa rajauksessa.
- Kohdekuvasuhde: tarkista ensin `adb -s C99BDC8E shell wm size` (odotus 1404x1872 eli 3:4 pystyssä). Kirjaa tulos asetuksiin.
- **Täyttöpalkit:** ylimääräistä tyhjää pintaa lisätään sivuun, jotta sen kuvasuhde vastaa Note Airin näyttöä.
  - Peruste: lukija sovittaa sivun näyttöön, joten näytön kuvasuhteeseen täyttäminen ei pienennä tekstiä. Se muuttaa näytön tyhjän alueen sivun pinnaksi, johon voi kirjoittaa marginaalimerkintöjä. E-inkilläkään ei voi merkitä, jos tyhjää pintaa ei ole.
  - Lisää palkit vain, jos KAIKKI seuraavat täyttyvät:
    a) syntyvä marginaalikaista on vähintään asetettu osuus (oletus 8 %) sivun leveydestä, eli siitä on merkitsemiseen todellista hyötyä
    b) teksti ei ole valmiiksi pientä eikä palstoitettua. Arvioi x-korkeus näytön pikseleinä sovituksen jälkeen ja palstojen määrä. Kynnys on korkea, koska silloin Olli zoomaa tai käyttää lukijan omaa rajausta, ja palkit haittaavat sitä.
    c) sauma ei näy: täyttöväri on sivun oman paperisävyn mediaani reunan läheltä (ei puhdasta valkoista, ellei tausta ole valkoinen). Reunassa ei saa olla voimakkaita artefakteja (peukalo, varjo, painot), jotka katkeaisivat täyttöön. Jos sauma näkyisi, jätä palkki pois siltä sivulta tai siltä puolelta ja kirjaa se lokiin.
  - Ei kehyksiä eikä viivoja. Teennäisyys ei saa näkyä.
  - Sijoitus: oletuksena tasan molemmille puolille. Valinta `--marginaali ulko` lisää täytön ulkoreunaan sivuparillisuuden mukaan. Ylä- ja alatäyttö vain, jos sivu on näytön kuvasuhdetta leveämpi.
  - Mittakaava: jos rajatut sivukorkeudet vaihtelevat paljon, harkitse koko kirjalle yhtenäistä mittakaavaa, jottei tekstikoko hypi sivulta toiselle. Ehdota ratkaisua Ollille ennen toteutusta.
  - Levytila: raportoi PDF:n koko palkeilla ja ilman. Jos kasvu ylittää 15 %, raportoi se ja ehdota pakkausasetuksia.
- `--esikatselu` tekee kontaktiarkin kuudesta satunnaisesta sivusta Macilla katsottavaksi. Testi-PDF:n saa Note Airille vain pyynnöstä: `adb -s C99BDC8E push <pdf> /sdcard/Documents/hegel-testi/`.

### 12.3 `md`
Kuvaus optimoidaan vain OCR:lle. PDF:ää ei tehdä, ellei sitä pyydetä.

## 13. Kielet ja kieliprofiilit

Ihanne: linjasto lukee mitä tahansa näistä kielistä tai niiden sekoitusta pelkillä asetuksilla:
- ensisijaiset: englanti (eng), suomi (fin), saksa (deu), latina (lat), muinaiskreikka (grc)
- myöhemmin: italia (ita), ranska (fra), tanska (dan), liettua (lit), ruotsi (swe)
- lisäksi fraktuura (deu_latf / frk) ja vanha suomen kirjoitusasu

Vaatimukset:
- Kieltä ei kovakoodata missään profiilien ulkopuolella. Profiilit tiedostossa `kieliprofiilit.toml`, esim. `[kant-lexikon] kielet = ["deu", "lat", "grc"]`, `sanakirjat = [...]`, `fraktuura = false`, `normalisoi_pitka_s = false`.
- Tesseractille annetaan vain profiilin kielet, koska jokainen ylimääräinen kieli hidastaa ja sekoittaa. Järjestys on dominanssin mukainen.
- Sanakirjat kielittäin: Voikko suomelle, hunspell muille. Latinan ja kreikan sanakirjat ovat heikkoja, joten niillä nojataan enemmän luotettavuusarvoon ja lukijoiden yksimielisyyteen, ja automaattisen hyväksynnän kynnys on tiukempi.
- Tavutuksen poistossa ja yhdysmerkkisäännöissä on kielikohtaiset säännöt.
- Diakriittitestit: å ä ö æ ø, liettuan ą č ę ė į š ų ū ž, polytonisen kreikan aksentit ja henkäysmerkit eivät saa kadota missään vaiheessa.
- Vaiheessa 2 riittää yksi profiili. Rakenne tehdään kuitenkin heti sellaiseksi, että kielten lisääminen on pelkkä asetusmuutos.

## 14. Vaiheistus ja pysähdyspisteet
Jokaisen vaiheen lopussa raportoi Ollille ja pysähdy odottamaan.

- **Vaihe 0: kartoitus.** Lue repo ja nykyinen CLAUDE.md. Vertaa olemassa olevaa koodia asemiin 1–7. Tarkista ympäristö (luku 2) ja kirjaa, mitkä kirjastot ovat saatavilla. Kysy luvun 15 avoimet kysymykset, joihin repo ei vastaa. Älä vielä kirjoita toteutuskoodia.
- **Vaihe 1: vertailu.** Kultaotos: 6–10 sivua kolmelta vaikeustasolta, joista vähintään yksi suomenkielinen ja yksi saksankielinen. Mieluiten public domain -aineistoa (silloin `tests/fixtures/`, muuten `local/kultaotos/`). Kultalitteroinnit tekee Olli tai Claude, ja Olli tarkistaa ne.
  - Muuttujat: suodatin (Original / Magic Pro) × lukija (tesseract / camscanner / claude-kokosivu).
  - Mittarit: CER, WER sekä **hallusinaatioindeksi**, eli sanat, joita lukema sisältää mutta kultalitterointi ei (lisäykset ja korvaukset, jotka eivät näy kuvassa). Tämä mittaa arvailua.
  - Raportti `docs/vertailu.md`: taulukko, CamScannerin OCR:n paikallisuus tai pilvi (luku 1) ja suositus.
  - Päätössääntö: jos camscanner on selvästi paras (CER korkeintaan puolet Tesseractin CER:stä ja hallusinaatioindeksi lähes nolla), siitä tulee ensisijainen lukija. Tesseract jää koordinaattiankkuriksi ja toiseksi mielipiteeksi, ja linjasto kevenee vastaavasti. Markdown-kokoaminen tarvitaan joka tapauksessa. Kerro, onko taso 2 vaivan arvoinen.
- **Vaihe 2:** asemat 1–4, taso 1 ja asema 6 (md). Tästä syntyy käyttökelpoinen linjasto ilman tekoälyä.
- **Vaihe 3:** skill `ocr-tarkistus` (taso 2) ja hyväksymissäännöt. Vaihe 3b: ihmistarkistussivu.
- **Vaihe 4:** `pdf-luku`-profiili ja Note Air3 -sovitus.
- **Vaihe 5:** taso 3 ja lisää kieliprofiileja.

## 15. Avoimet kysymykset Ollille (vaihe 0)
1. Mitä kieliä ja kirjasintyyppejä (fraktuura, vanha kirjoitusasu) lähiajan materiaalissa on?
2. Mihin markdownia käytetään (Zettelkasten-lainaukset iA Writerissa, LUiN, gradun viitteet)? Käyttötarkoitus ratkaisee sivumerkkien ja alaviitteiden muodon.
3. Mistä teoksista kultaotos tehdään?
4. Mitä vientimuotoja CamScannerin Pro-lisenssi tarjoaa Nordilla, ja toimiiko automaattinen lataus Dropboxiin?
