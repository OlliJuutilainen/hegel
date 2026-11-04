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

## Esikoe 2: Kant-Lexikon s. 2486 (artikkelin ensimmäinen sivu)

Aineisto: chattiin lähetetty kuva (1263 × 2000 px, pienennetty Macin 2152 × 3408 px:n tiedostosta). Kultalitterointi
on tehty eri tavalla kuin sivulla 2506: pohjana on deu-lukema, johon Claude korjasi kuvasta 17 kohtaa. Siksi deu:n
CER on tässä alaraja: virhe, jonka sekä Tesseract että Claude ohittivat, ei näy. Olli tarkistaa litteroinnin.

| Lukija | CER | CER (kirj.) | WER | Uskottavat väärät sanat |
|---|---|---|---|---|
| deu | 0,47 % | 0,20 % | 3,52 % | 0 (mittari laski yhden, ks. alla) |
| script/Latin | 0,47 % | 0,22 % | 4,00 % | 1: *Erkenntniß* → *Erkenntnis* |

- Mittarin osuma deu:lle on mittausvirhe: nuoli puuttui (`-Spontaneität`), ja vertailu luki loput sanasta oikeaksi
  sanaksi.
- **script/Latin muutti kerran vanhan kirjoitusasun nykyiseksi** (*Erkenntniß* → *Erkenntnis*). Se on juuri sitä
  uskottavaa arvailua, jota diplomaattinen litterointi ei salli, ja syy pitää deu ensisijaisena lukijana.
- **Nuolta → ei ole kummankaan mallin merkistössä**, eikä §:ää ole deu:n merkistössä. Nuolet luetaan merkeiksi `>`,
  `+` ja `-`, ja § luetaan 8:ksi (*§ 3* → *8 3*). Sivulla on 7 nuolta ja 2 §-merkkiä. Tesseract ei voi oppia näitä
  ilman uudelleenkoulutusta. Ehdotus: koska kirjan nuoli on aina samannäköinen, se etsitään kuvasta mallikuvalla
  (algoritminen sovitus), ja sen paikalle kirjoitetaan →. Sama tehdään §:lle.
- Muut deu-virheet ovat samaa tyyppiä kuin sivulla 2506: piste luettiin pilkuksi (5), *Ratlonalität* ja
  *affıcirt* (fi-ligatuuri), lisäksi välilyöntejä katosi (*A326*, *302/B*).

## Nuolentunnistus (3.11.2026)

`linjasto/merkit.py`: mallikuva tehdään kirjan omista selvistä tapauksista, joissa sana on pelkkä `>`. Epäilyttävän
sanan (alkaa merkillä `> & + - — – 2` tai `(`) ensimmäistä tai toista mustekuviota verrataan malliin
korrelaatiolla, ja koko mitataan suhteessa rivin korkeuteen. Seuraavaan kirjaimeen kiinni olevasta kuviosta verrataan
vain nuolen levyistä alkua.

Kahdella testisivulla (puolikokoiset chattikuvat) nuolia on 10. Niistä tunnistettiin 6, eikä yhtään väärää
korvausta tullut. Koottu md poikkesi kullasta CER 0,52 % → 0,42 %. Nuolten korrelaatio oli 0,47–0,91 ja muiden
kokoehdon läpäisseiden kuvioiden enintään 0,34. Raja on 0,45, eli väli on kapea. Täysikokoisilla sivuilla väli
tarkistetaan muutoslokin tilasta `nuoli_tunnistettu`.

Vernunft, 33 sivua (Ollin Mac, 3.11.2026): mallikuva syntyi 80 tapauksesta, ja nuolia korjattiin 73.
- Alkuperäiset lukemat: `>` 54, `&` 9, `—` 2 ja loput kiinni seuraavaan sanaan. Numeroita joukossa ei ollut.
- Liputettuja yksinäisiä `>`-merkkejä jäi 30. Niistä 13 oli kokonaisia nuolia varsineen: kuvio 1,4–1,8 kertaa mallia
  leveämpi, korrelaatio 0,88–0,97. Mallin mediaani on kapea, koska useimmissa selvissä tapauksissa varsi ja kärki
  ovat erillisiä kuvioita. Nyt tällainen leveä kuvio hyväksytään korrelaatiolla ≥ 0,85.
- Loput 17 ovat joko kapeita kuvioita, joiden korrelaatio on 0,09–0,44, tai litteitä viivoja (korkeus 0,04–0,17
  mallista). Ne jäävät liputetuiksi.

## Piste vai pilkku (4.11.2026)

Sanan lopun pilkku ratkaistaan kuvasta (`merkit.loppumerkki`), koska pilkku ulottuu perusviivan alle ja on
korkeampi. Mitat ovat x-korkeuden osina, testisivuilta:
- oikeat pilkut laskeutuvat 0,06–0,46 ja ovat 0,38–0,64 korkeita
- pilkuksi luetut pisteet laskeutuvat enintään 0,08 ja ovat 0,23–0,38 korkeita

Kun lukijat ovat eri mieltä, raja on väljä (laskeuma ≤ 0,10 ja korkeus ≤ 0,45). Kun molemmat lukivat pilkun, raja
on tiukka (≤ 0,02 ja ≤ 0,40). Testisivuilla kaikki 11 pilkuksi luettua pistettä korjautuivat, eikä yksikään oikea
pilkku muuttunut. Koottu md poikkesi kullasta CER 0,42 % → 0,29 %. **Rajat on määritetty samoilla kahdella
sivulla**, joten ne tarkistetaan uusilla kultasivuilla. Muutosloki: tila `piste_kuvasta`.

## Yksimielinen matala luotettavuus (4.11.2026)

Kun molemmat lukijat lukivat sanan täsmälleen samoin, pelkkä matala luotettavuus ei enää liputa. Testisivuilla
kaikki 8 tällaista sanaa olivat oikein (*empirischer*, *Idee,*, *B*, *672).*, *Philosophische*…). Liputettujen
osuus laski 3,9 %:sta 3,2 %:iin. Testisivujen virheistä ilman lippua jäi yksi: *Ratlonalität*, jonka molemmat
lukijat lukivat samoin ja luotettavuudella ≥ 90. Tämän rajan alle sanakirjalippu ei ulotu.

## Taso 2 testisivuilla (4.11.2026)

Tarkastustaito `.claude/skills/ocr-tarkistus` ja hyväksymissäännöt (`linjasto/hyvaksynta.py`, pahvin luku 10;
laajennus: pelkkä välilyöntiero hyväksytään varmuudella korkea tai keski). Claude tarkasti testisivujen 39 kohdetta
31 rajauskuvasta: 27 vahvistettu, 12 korjattu, joista 3 matalalla varmuudella. 38 hyväksyttiin ja 2 hylättiin:
*Wi-* (etäisyys 3) ja *allgemei-* (ei tukea), jotka jäivät liputetuiksi.

| Taso | CER | CER (kirj.) | WER | Liputuksia | Uskottavat väärät sanat |
|---|---|---|---|---|---|
| 1 | 0,29 % | 0,18 % | 2,26 % | 38 | 0 |
| 2 | 0,12 % | 0,09 % | 0,59 % | 2 | 0 |

**Varaus:** sama Claude teki kultalitteroinnin ja tarkastuksen, joten ne eivät ole toisistaan riippumattomia. *seiner*
hyväksyttiin matalalla varmuudella sanakirjan tuella, koska rajauskuvassa i:n piste ei erotu. Tulos on oikea, mutta
se on päätelty eikä luettu kuvasta, ja se näkyy lokissa.

## Taso 2 koko artikkelilla: Vernunft (4.11.2026)

33 sivua (s. 2486–2519, kuvasta puuttuu s. 2506), 20 948 sanaa. Taso 1 liputti 3,3 % sanoista, ja paketissa oli
671 kohdetta 539 rajauskuvasta. Claude tarkasti kaikki 671 kohdetta: 444 vahvistettu, 216 korjattu ja 11
lukukelvoton. Sivun 16 vasemman palstan rivinalut puuttuvat jo alkuperäisestä kuvasta. Olli luki ne
alkuperäisestä kuvasta (14 vastausta, joista neljä koskee rivejä, joita linjasto ei liputtanut). Tästä syystä
lukukelvoton-vastaus liputtaa nyt myös liputtamattoman sanan.

Macin ajo (`kokoa --taso 2`): hyväksytty 673, hylätty 19, ei vastausta 4. Tekstiin jäi 23 lippua:

| Syy | Lippuja |
|---|---|
| Rivinalku puuttuu kuvasta (s. 16) | 7 |
| Haamurivit (viereisen tekstin leikattu kopio, 2 riviä) | 4 |
| Haamusanat (lukukelvoton) | 2 |
| Korjaus varmuudella keski, ei tukea (mm. 4 × `[...]`, `–`, `§ 8`) | 10 |

Kultaotosta ei ole, joten CER:ää ei mitattu. Rajauskuvien perusteella yleisimmät korjaukset ovat välilyönti
viitteissä (`A 326`, `B 7).`, `d. h.`), nuoli `→`, ajatusviiva lukuväleissä, yksinkertaiset lainausmerkit (`‚Tat‘`)
ja yksittäiset kirjaimet (`Funktlon` → `Funktion`).
