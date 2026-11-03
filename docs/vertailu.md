# Vertailu (vaihe 1)

Mittari: `vertailu/mittaa.py`. Tekstit NFC-normalisoidaan ja välilyönnit tiivistetään, joten rivinvaihdot eivät
vaikuta tulokseen. CER (kirj.) ei laske välimerkkejä. *Uskottavat väärät sanat* on pahvin hallusinaatioindeksi:
korvatut tai lisätyt sanat, jotka ovat itse oikeita sanoja hunspell-sanakirjassa. Mittari tarkistettiin
keksityllä lukemalla (Kant → Hand ja lisätty Haus): se antoi 2 osumaa.

Kultalitteroinnit eivät ole repossa (tekijänoikeus). Ne ovat Ollin koneella kansiossa `local/kultaotos/`.

## Esikoe 3.11.2026: Kant-Lexikon s. 2506

Aineisto on yksi sivu, jonka Olli lähetti chattiin: JPEG 1135 × 2000 px, todennäköisesti chatin pienentämä
(Tesseractin arvio 214 dpi). CamScannerin vanhat asetukset: oletuskoko, Magic Pro, värit säilytetty. Sivulla on
kaksi palstaa, 627 sanaa ja 97 riviä, ei kreikkaa. Kultalitteroinnin teki Claude kuvasta, ja Olli tarkistaa sen.

Tesseract 5.3.4 (Ubuntu) ja tessdata_best, `--psm 3 -c preserve_interword_spaces=1`, ei esikäsittelyä.
Sanakirja hunspell de_DE.

| Kielet | Kuva | CER | CER (kirj.) | WER | Uskottavat väärät sanat |
|---|---|---|---|---|---|
| deu | alkuperäinen | 0,55 % | 0,24 % | 3,80 % | 0 |
| deu+lat | alkuperäinen | 1,16 % | 0,64 % | 7,29 % | 0 |
| deu+lat+grc | alkuperäinen | 1,16 % | 0,64 % | 7,29 % | 0 |
| deu | 2× | 0,52 % | 0,21 % | 3,33 % | 0 |
| deu+lat+grc | 2× | 1,09 % | 0,59 % | 6,81 % | 0 |

Havainnot:
- **Latinan lisääminen kaksinkertaistaa virheet.** ä luetaan á:ksi (*eingeschránkt*, *rásoniert*, *grundsátz-*,
  *unzulássigen*, *Erklárung*, *Pháno-*, *rásonniren*), ö ü:ksi (*Unvermügen*), ja lainausmerkit „ “ hajoavat
  muotoihin `,` `,,` `"`. Pelkällä deu:lla á:ta ei tule kertaakaan. Sivun latina (*Conceptus
  ratiocinans/ratiocinatus*, *a priori*) luettiin oikein pelkällä deu:lla. Pahvin luvun 13 sääntö, että
  Tesseractille annetaan profiilin kielet, ei siis toimi sellaisenaan. Pääkieli luetaan yksin, ja muut kielet ovat
  toinen lukija tai lukevat vain liputetut sanat. Kreikkaa pitää kokeilla sivulla, jolla sitä on.
- **deu:n loput virheet**:
  - nuolet → luettiin muodossa `>` tai `&`, tai ne puuttuivat (5)
  - piste luettiin pilkuksi sumeassa kuvassa (6)
  - *Jindřich* → *Jindfich* ja *Karásek* → *Karäsek*
  - *seiner* → *selner*
  - oikean palstan yläkulman kaarevuus: *Wi-* → *wj.*, *allgemei-* → *allgemej.*
  - välilyöntejä katosi: *A326*, *d.i.*, *A63/B*
- **Uskottavia vääriä sanoja ei tullut yhtään.** Kaikki virheet olivat ei-sanoja tai välimerkkejä, joten sanakirja
  liputtaisi ne.
- 2× suurennus auttaa vähän (CER 0,55 → 0,52 %).
- tessdata_bestin latinan merkistössä on á, é, í ja ó, mutta ei makroneita (`combine_tessdata -u`).
  Kun deu+lat-ajosta kiellettiin aksentit (`tessedit_char_blacklist=áéíóúÁÉÍÓÚàèìòù`), umlautit korjaantuivat, mutta
  CER oli silti 1,03 %. Latinan malli rikkoo edelleen lainausmerkit ja lukee *weil* → *well* ja *Subalterne* →
  *Subalteme*.
- Saksan sanakirja (hunspell de_DE) ei tunne deu-lukeman 583 sanasta 59:ää. Niistä vain noin 8 on lukuvirheitä.
  Loput ovat oikeita sanoja: Kantin vanha oikeinkirjoitus (*theils*, *muß*, *Princip*, *urtheilen*, *blos*),
  termit (*Vernunfteinheit*, *KrV*) ja latina (*Conceptus*, *ratiocinans/ratiocinatus*). Pelkkä sanakirja liputtaa
  siis liikaa. Avuksi tarvitaan kirjan oma sanasto (sanat, jotka toistuvat korkealla luotettavuudella), vanhan
  oikeinkirjoituksen säännöt ja Tesseractin luotettavuus.

### Nimet ja diakriitit; kaksi lukijaa

- Saksan mallin merkistössä ei ole ř:ää, á:ta, č:tä, š:tä, ž:ää, ą:ta, ę:tä, ł:ää tai ő:tä, joten se ei voi lukea
  nimeä *Jindřich Karásek* oikein (*Jindfich Karäsek*). tessdata_bestin kirjaimistomalli `script/Latin` (101 Mt)
  sisältää ne kaikki ja luki nimen oikein sekä alkuperäisestä että 2× rajauksesta.
- Koko sivulla `script/Latin` sai CER 0,48 % (deu 0,55 %), mutta kirjainvirheitä tuli enemmän (CER (kirj.) 0,31 %
  vs. 0,24 %). Sen omia virheitä olivat *Vermiünfteln*, *niünftigen* ja *muß* → *mu*.
- Kun deu ja `script/Latin` ovat kaksi lukijaa ja sanat kohdistetaan kultaan:
  - 599 sanaa on samoja ja oikein.
  - 18 sanaa eroaa. Niistä 16:ssa toinen lukijoista on oikeassa.
  - 6 sanaa on samoja mutta väärin: nuoli kahdesti `>`, yksi piste pilkkuna, *selner*, *wj.* ja *allgemej.*.
    Niistä neljä on ei-sanoja tai epätavallisia merkkejä, joten liputus löytäisi ne. Vain piste–pilkku menisi
    läpi huomaamatta.

### Kursiivi

Mittaus `ocr/scanpage.word_slant`illa. Sivulla on 10 kursiivisanaa.
- Nykyiset kynnykset (kulma 8–20°, gain ≥ 1,1) löysivät 2× kuvasta niistä 2. Lisäksi ne merkitsivät väärin 7
  sanaa: vinoviiva `/` luettiin kursiiviseksi I:ksi, samoin numerot `A326` ja `644`.
- Sanat erottuvat silti selvästi. 2× kuvassa kaikkien 10 kursiivisanan kulma on 6–10° ja gain 1,03–1,15. Pystyistä
  sanoista (550 kpl, vähintään 3 kirjainta) 97 %:lla kulma on 0°, ja 90 %:lla gain on enintään 1,01.
- Kynnyksen kulma ≥ 5° ja gain ≥ 1,025 ylittivät vain kolme vinoviivallista numeroa, joiden kulma oli 16°.
- Alkuperäisessä koossa kolme kursiivisanaa jää alle 5°:n.

Johtopäätös: kursiivin tunnistus on tällä kirjalla mahdollinen. Kynnykset kalibroidaan kirjakohtaisesti, eikä
vinoviivaa lasketa kursiiviksi. Tarkistetaan täyden resoluution skanneilla.

### Note Air -rajaus

`vcrop.py` ajettiin pilvessä opencv 4.12:lla.
- Rajaus vei ylhäältä 105 px ja alhaalta 186 px. Oikean reunan merkinnät ja vasemman alakulman jälki jäivät
  rajauksen ulkopuolelle (debug-kuva tarkistettu).
- Rajatun sivun koko on 1135 × 1709 ja kuvasuhde 0,664 (3:4 = 0,750).
- Laskettu näytölle 1404 × 1872 ja tiheydelle 227 ppi. Arvot ovat Note Air3:n (ei C-mallin) julkaistut tiedot
  (10,3", Carta 1200; the-ebook-reader.com ja notebookcheck.net). Laitteen oma `wm size` on vielä tarkistamatta.
  Sovituskerroin on 1,095, ja sivun vierelle jää yhteensä 161 px. Riviväli on 34 px eli 3,8 mm.
- Sivu on kaksipalstainen, joten pahvin luvun 12.2 b) mukaan täyttöpalkkeja ei lisätä.
