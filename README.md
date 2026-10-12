# Binance Listing Bot (med sikkerhetsmarginer)

En bot som lytter etter **«Binance Will List …»**-annonseringer og prøver å kjøpe mynten på en *annen* børs (standard: Gate) før Binance åpner handelen – med langt flere sikkerhetssperrer enn originalen den bygger på ([CyberPunkMetalHead/new-listings-trading-bot](https://github.com/CyberPunkMetalHead/new-listings-trading-bot)).

> **Start alltid i `paper`-modus (simulert).** Boten starter i paper-modus som standard, og live-handel krever to separate bekreftelser i config.

---

## ⚠️ Les dette før du bruker ekte penger

Før boten ble laget, ble det sjekket hva andre har funnet ut om denne strategien. Kort oppsummert: den er langt mindre lønnsom enn originalartikkelen antyder.

| Funn | Kilde |
|---|---|
| $100 i hver av de 92 tokenene Binance listet i 2025 (kjøpt ved første dags slutt) var verdt ca. −71 % i mars 2026. | [Messari via AMBCrypto](https://ambcrypto.com/messari-data-shows-binances-2025-listings-down-71-on-average/) |
| Binance-listinger i 2024 steg i snitt 87 % ved listing, men 98 % av dem falt senere, i snitt −70 %. | [CryptoNinjas](https://www.cryptoninjas.net/exchange/study-cex-listing-effects/) |
| Prisgevinsten kommer i hovedsak *før* handelen åpner (dag 0). Tokens med stor volumøkning på andre børser dagene før, gjorde det dårligere etterpå. | [The Tie](https://www.thetie.io/insights/what-does-an-exchange-listing-actually-deliver-in-2026) |
| En utvikler som kjørte en lignende bot i 2021–22 sier fordelen er borte: det er blitt et kappløp mot raskere HFT-aktører, og han tapte gevinsten på gjentatte stop-outs. | [apebot README](https://github.com/hustnn/apebot) |
| Binance publiserer ingen kalender; annonseringen kommer bare timer til et par dager før handelen åpner. | [The Tie](https://www.thetie.io/insights/what-does-an-exchange-listing-actually-deliver-in-2026) |

**Hva det betyr i praksis:** Dette er et fartsspill der profesjonelle er raskere enn deg. Eksemplet med «10x på Magic Eden» i originalartikkelen er et utvalgt toppeksempel, ikke det normale. Boten er derfor bygd for å ta *små* innsatser, unngå å jage prisen, og selge rundt tidspunktet Binance åpner – fordi det er der toppen ofte er.

---

## Hva er endret fra originalen

| Original | Denne versjonen | Hvorfor |
|---|---|---|
| Markedsordre | **Limit + IOC**: betaler aldri mer enn beste pris + 3 % | Markedsordre i tynne markeder rett etter en annonsering kan gi enorm slippage |
| Stop loss 1 % / take profit 1 % | **Stop loss 10 %**, trailing stop som slås på ved +8 % og følger 6 % under toppen | 1 % utløses av vanlig støy på sekunder. Config avviser stop loss under 3 % |
| Ingen likviditetssjekk | Krever min. 24t-volum, maks spread og at orderboka tåler 3x kjøpet | Unngår døde markeder du ikke kommer deg ut av |
| Ticker-match med regex | **Navnesjekk**: «Magic Eden (ME)» må matche navnet på kjøpsbørsen | Samme ticker kan være en helt annen mynt på en annen børs |
| Ingen sjekk på om du er for sent ute | Hopper over hvis prisen allerede har steget > 25 % siden annonseringen | Ikke kjøp toppen fra de raske |
| Polling av nettside | **Binance sin offisielle annonserings-WebSocket** + polling som reserve | Raskere, og aldri falske annonseringer fra Twitter/Telegram |
| Ingen aldersfilter | Annonseringer eldre enn 120 sek ignoreres | Hindrer kjøp av gamle listinger etter omstart |
| Ingen risikogrenser | Maks åpne posisjoner, daglig kjøpsgrense, daglig tapsgrense, pause etter 3 tap på rad, nødstopp-fil | Én dårlig dag skal ikke tømme kontoen |
| Ingen exit-tid | Selger 10 min etter at Binance åpner, eller etter maks 12 timer | Toppen er ofte ved listing; etterpå faller de fleste |
| — | Halv innsats på **Seed Tag**-tokens | Binance merker selv disse som ekstra risikable |
| — | Håndterer delvis fylte ordre og gebyr trukket i mynten | Ellers prøver boten å selge mer enn du eier |
| — | Varsler til mobil (Telegram), CSV-eksport for skattemeldingen | |
| C# | Python + [ccxt](https://github.com/ccxt/ccxt) | Hastigheten avgjøres av hvor raskt du *ser* annonseringen, ikke språket. Python er enklere å endre |

---

## Oppsett (Windows, steg for steg)

1. **Installer Python 3.11+** fra [python.org](https://www.python.org/downloads/). Huk av «Add Python to PATH».
2. **Last ned koden:** grønn «Code»-knapp → «Download ZIP», pakk ut. (Eller `git clone`.)
3. **Åpne mappen i terminal** (høyreklikk i mappen → «Åpne i terminal») og kjør:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   copy config.example.yaml config.yaml
   copy .env.example .env
   ```
4. **Test oppsettet:** `python -m listing_bot check`
5. **Øv uten penger:** `python -m listing_bot simulate "Binance Will List Arbitrum (ARB)" --watch-minutes 5`
   – boten later som Binance nettopp annonserte ARB, kjører alle sjekkene mot ekte markedsdata på Gate og simulerer kjøp og salg.
6. **Kjør i paper-modus:** `python -m listing_bot run` (eller dobbeltklikk `start.bat`). La den gå i **minst noen uker** og se på resultatene med `python -m listing_bot status`.

Mac/Linux: bruk `source .venv/bin/activate`, `cp` i stedet for `copy`, og `./start.sh`.

### Testing uten nett
`python -m unittest discover -s tests -t .` kjører 36 tester av tolking, risikosperrer, salgslogikk og hele kjøp→salg-flyten med en falsk børs.

---

## API-nøkler – gjør det trygt

**Kjøpsbørsen (f.eks. Gate):**
- Kun **«Spot Trade»** og **«Read»**. **ALDRI «Withdraw»/uttak.** Da kan ingen ta pengene dine ut selv om nøkkelen lekker.
- Lås nøkkelen til **IP-adressen** til maskinen boten kjører på.
- Ha bare så mye USDT på børsen som du er villig til å tape.

**Binance (valgfritt, men raskest):** Lag en nøkkel med **kun lesetilgang**. Den brukes bare til å motta annonseringer – ingen handel skjer på Binance. Uten nøkkel bruker boten polling hvert 5. sekund, som er tregere.

Nøkler legges i `.env`, som aldri lastes opp til GitHub (den står i `.gitignore`).

### Telegram-varsler (gratis)
1. Skriv til **@BotFather** i Telegram → `/newbot` → kopier token til `TELEGRAM_BOT_TOKEN`.
2. Send en melding til din nye bot, åpne `https://api.telegram.org/bot<TOKEN>/getUpdates` og kopier `chat.id` til `TELEGRAM_CHAT_ID`.

---

## Hvor skal boten kjøre?

Boten må kjøre **hele tiden** – en annonsering kan komme når som helst.

- **Egen PC:** gratis, men må stå på og ikke gå i dvale.
- **Gratis sky-server:** f.eks. Oracle Cloud «Always Free». En server i Asia (Tokyo/Singapore) er nærmere Binance og gir lavere forsinkelse.
- **Ikke GitHub Actions:** jobber der har tidsbegrensning og planlagte kjøringer har minst 5 minutters intervall og kan bli forsinket – altfor tregt for dette. GitHub brukes her til å lagre koden og kjøre testene automatisk.

---

## Hvilken børs?

Standard er **Gate** (som originalforfatteren nevner sammen med HTX). Støttet: `gate`, `mexc`, `kucoin`, `bybit`, `bitget`, `htx`, `okx`, `poloniex`.

**Sjekk selv at børsen tar imot norske kunder.** Norge følger EUs kryptoregelverk (MiCA) via EØS, og flere utenlandske børser har strammet inn for europeiske kunder. Kjør `python -m listing_bot check` – den viser også om børsen oppgir fulle myntnavn (trengs for navnesjekken). Hvis ikke, må du sette `entry.name_match: warn`, men da øker risikoen for å kjøpe feil mynt.

---

## Hvorfor disse tallene

- **20 USDT per kjøp, maks 65 per dag, maks 30 tap per dag:** små nok til at en hel dag med feil ikke gjør vondt.
- **Stop loss 10 %:** nye listinger svinger 5–10 % på sekunder. Tettere stopp gir bare tap på støy.
- **Trailing 8 % / 6 %:** når du først er godt i pluss, låses gevinsten gradvis inn.
- **Max slippage 3 % og max chase 25 %:** er prisen allerede løpt, er du sen – da er det bedre å la være.
- **Selg 10 min etter Binance-åpning:** forskningen over viser at gevinsten i stor grad kommer før/ved listing.

Alt kan endres i `config.yaml`. Noen grenser er låst i koden (f.eks. maks 500 USDT per kjøp, stop loss minst 3 %) så en skrivefeil ikke kan tømme kontoen.

---

## Kommandoer

| Kommando | Hva den gjør |
|---|---|
| `python -m listing_bot run` | Start boten |
| `python -m listing_bot check` | Sjekk config, nøkler og børstilkobling |
| `python -m listing_bot simulate "Binance Will List X (X)"` | Øv på en tenkt annonsering (kun paper) |
| `python -m listing_bot parse "tittel"` | Se hvordan en tittel tolkes |
| `python -m listing_bot status` | Åpne posisjoner og resultat |
| `python -m listing_bot export trades.csv` | Alle handler til CSV |

**Nødstopp:** lag en tom fil som heter `STOP` i mappen. Da kjøper boten ingenting nytt (men selger fortsatt åpne posisjoner etter reglene). Slett filen for å starte igjen.

---

## Gå over til ekte penger

Bare etter flere uker i paper-modus der resultatene faktisk er positive *etter gebyr*:

```yaml
mode: live
live_trading_confirmed: true
```

Start med lavt `buy_amount_usdt`.

## Skatt

I Norge er hvert salg av krypto en skattepliktig hendelse, og gevinst/tap skal føres i skattemeldingen. `export`-kommandoen gir deg alle handler med tidspunkt, pris og gebyr. Sjekk [Skatteetaten](https://www.skatteetaten.no/person/skatt/hjelp-til-riktig-skatt/aksjer-og-verdipapirer/om/kryptovaluta/) for gjeldende regler.

## Ansvarsfraskrivelse

Dette er ikke finansiell rådgivning. Koden leveres som den er, uten garantier. Krypto kan gå til null, og automatisert handel kan feile på måter du ikke forventer. Bruk bare penger du har råd til å tape.

## Lisens

MIT
