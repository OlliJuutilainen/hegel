# Ohjeet Claudelle

Vastaa suomeksi, tiiviisti. Älä väitä toimivaksi mitään, mitä et ole ajanut.

**Linjasto** (suunnitelma `docs/linjasto.md`, käyttäjän pahvi 3.11.2026): CamScanner-kuvat → OCR → tarkistus →
markdown ja/tai Note Air3:lle sovitettu PDF. Tekstin tuottaa algoritmi. Tekoäly tarkastaa vain liputetut kohdat
rajauskuvista, ja jokainen muutos kirjataan lokiin. CamScannerin OCR:ää ei käytetä (päätös 3.11.).
**Vaiheet** (luku 14): 0 kartoitus ja Ollin vastaukset (`docs/kartoitus.md`) · 1 vertailu: esikoe yhdellä sivulla
(`docs/vertailu.md`), odottaa oikeita skanneja · 2 asemat 1–4 ja md · 3 tarkistustaito · 4 pdf-luku · 5 taso 3.
**Käyttöperiaatteet** (luku 1): skannaukset, työtiedostot ja tulokset vain kansioon `local/` (gitignore). Repoon
menee vain koodi, asetukset, dokumentaatio ja public domain -testiaineisto. Ei julkaisua. Linjauksen ylittävästä
pyynnöstä huomauta kerran, älä holhoa.
**Ympäristö**: macOS 11.7.10, Intel. Tarkista pyörät ennen kirjaston valintaa: opencv-python ja ocrmypdf eivät
asennu Python 3.14:lle (`docs/kartoitus.md`). Älä asenna järjestelmäohjelmia kysymättä. Älä riko README:n työkaluja.
