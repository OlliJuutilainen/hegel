---
name: ocr-tarkistus
description: Tarkastaa hegel-linjaston tarkistuspaketin (local/work/<kirja>/paketti/) liputetut OCR-kohdat rajauskuvista ja kirjoittaa vastaukset.json:n. Diplomaattinen litterointi; ei täydennä eikä korjaa kielioppia.
---

# OCR-tarkistus (linjaston asema 5, taso 2)

Suunnitelma: `docs/linjasto.md`, luku 9.1. Tekstin on tuottanut algoritmi. Sinä olet vain tarkastaja: vastaat
jokaisesta liputetusta kohdasta rajauskuvan perusteella. Et kirjoita tekstiä kohteen ulkopuolelle.

## Syöte

`<paketti>/kohteet.json`: lista kohteita.
```
{ "id": "s012-r07-w03", "sivu": 12, "rajaus": "rajaukset/s012-r07.png", "rajaus_original": null,
  "lukemat": {"pää": "Vemunft", "script/Latin": "Vernunft"}, "luotettavuus": 41,
  "syyt": ["matala_luottamus", "lukijat_eri_mieltä"], "konteksti_ennen": "...", "konteksti_jalkeen": "...",
  "kielet": ["deu", "lat", "grc"] }
```
- `id` päättyy `-wNN`: yksi sana. Ilman sitä (`s012-r07`) koko rivi (`syyt` sisältää `rivi_liputettu`), ja
  lukemat ovat koko rivin sanat välilyönnein.
- Rajauskuva on koko rivi ja puoli riviä marginaalia. Sana löytyy rivistä kontekstin avulla, mutta **vastaus tulee
  kuvasta, ei kontekstista**.

## Työjärjestys

1. Lue `kohteet.json`. Ryhmittele kohteet rajauskuvan mukaan, jotta jokainen kuva katsotaan vain kerran.
2. Käy ryhmät läpi enintään 40 kohteen erissä. Katso jokaisen ryhmän kuva Read-työkalulla ennen kuin vastaat
   yhteenkään sen kohteeseen. Ilman kuvaa ei vastata.
3. Kirjoita vastaukset tiedostoon `<paketti>/vastaukset.json` (lista, ks. alla). Jos tiedosto on jo olemassa,
   lisää vain puuttuvat id:t; älä muuta aiempia. Älä koske muihin tiedostoihin.
4. Lopuksi raportoi määrät tiloittain ja varmuuksittain.

## Säännöt

- **Diplomaattinen litterointi**: kirjoita täsmälleen se, mitä kuvassa on painettuna. Säilytä vanhat
  kirjoitusasut (*theils*, *muß*, *Princip*, *urtheilen*), painovirheet (kirjaa ne `huomio`-kenttään, älä korjaa),
  isot ja pienet kirjaimet, lainausmerkit („ “ ‚ ‘ « ») ja välimerkit. Polytoninen kreikka sellaisenaan (NFC).
- Älä modernisoi, älä korjaa kielioppia, älä täydennä. Jos konteksti vetää eri suuntaan kuin kuva (esim. kieliopin
  mukaan *ein*, kuvassa *eine*), kuva voittaa.
- Ristiviitenuoli on `→`, pykälämerkki `§`, tavuviiva rivin lopussa kuuluu sanaan sellaisenaan (`Erschei-`).
- Sanan rajat: vastaa vain kohteen sanalla. Jos lukema on kaksi sanaa yhdessä tai sana on katkennut, kirjoita
  kohteen paikalle se, mitä kuvassa on (välilyönti mukaan, jos kuvassa on kaksi sanaa).
- **Tilat**:
  - `vahvistettu`: jokin lukemista on täsmälleen oikein; `teksti` = se lukema.
  - `korjattu`: kuvassa on eri teksti kuin missään lukemassa; `teksti` = kuvan teksti.
  - `lukukelvoton`: et pysty lukemaan kuvasta varmasti. Älä arvaa.
- **Varmuus**: `korkea` (kuva on selvä), `keski` (yksi merkki epäselvä), `matala` (useampi epäselvä). Epävarmuus
  ilmaistaan tilalla `lukukelvoton` tai matalalla varmuudella, ei arvaamalla.

## Vastauksen muoto

```
{ "id": "s012-r07-w03", "tila": "korjattu", "teksti": "Vernunft", "varmuus": "korkea", "huomio": "" }
```

Vastausten hyväksymisestä päättää `python linja.py kokoa <kirja> --taso 2` (pahvin luku 10), ei tämä taito.
