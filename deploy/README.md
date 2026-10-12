# Kjør boten på en server (uten at PC-en står på)

To versjoner med **nøyaktig samme bot og funksjoner** – de bruker samme installasjonsskript. Forskjellen er bare hvor serveren kommer fra.

| | [Versjon 1: Oracle Cloud](ORACLE.md) | [Versjon 2: VPS (Hetzner)](VPS.md) |
|---|---|---|
| Pris | **Gratis** | ca. 4–8 €/mnd |
| Oppsett | Litt mer styr (kortbekreftelse, kan være utsolgt) | Enkelt |
| Pålitelighet | Oracle kan ta tilbake servere som ser inaktive ut | Stabil så lenge du betaler |
| Fart mot Binance | Rask hvis du velger Tokyo/Singapore som hjemregion | Rask i Singapore, tregere i Helsinki |
| Passer når | Du vil teste gratis i paper-modus | Du kjører med ekte penger og vil ha forutsigbarhet |

**Forslag:** Start med Oracle (gratis) i paper-modus. Flytt til VPS hvis du går over til ekte penger, eller hvis Oracle-serveren blir stoppet.

Begge kan kjøre **late-penger (paper)** og **ekte penger (live)** samtidig, som to separate instanser med hver sin config, nøkler og database.

---

## Felles for begge versjonene

### Hva skjer på serveren
```
/opt/listing-bot/
├── app/                 koden fra GitHub
├── venv/                Python-pakker
└── instances/
    ├── paper/           late-penger: config.yaml, .env, bot.db, logs/
    └── live/            ekte penger (bare hvis du lager den)
```
Hver instans er en systemtjeneste (`listing-bot@paper`, `listing-bot@live`) som starter automatisk.

### Daglig bruk
Du trenger egentlig bare Telegram:
- 🤖 når boten starter
- 📢 / 🟢 / ⏭️ / ✅ / 🔻 for listinger, kjøp, hopp over og salg
- 💓 statusmelding hver 24. time (oppetid, om kildene virker, åpne posisjoner, resultat)
- ⚠️ hvis boten mister kontakten med Binance-annonseringene i mer enn 5 minutter

**Kommer det ingen 💓 på over et døgn, kjører ikke boten.** Logg inn og kjør `botctl status`.

Når du er logget inn på serveren (fra PC eller Termius på mobilen):

| Kommando | Hva den gjør |
|---|---|
| `botctl status` | Kjører instansene? Er det ekte penger? |
| `botctl logs paper` | Følg loggen live (Ctrl+C for å gå ut) |
| `botctl trades paper` | Handler og resultat |
| `botctl pause paper` | Nødstopp – ingen nye kjøp |
| `botctl resume paper` | Opphev nødstopp |
| `botctl config paper` | Endre innstillinger |
| `botctl keys paper` | Endre nøkler/Telegram |
| `botctl restart paper` | Start på nytt (etter endringer) |
| `botctl update` | Hent ny kode fra GitHub, kjør testene, restart |
| `botctl export paper` | Alle handler til CSV (skattemeldingen) |
| `botctl help` | Alle kommandoer |

### Gå over til ekte penger
1. Hvis du ikke installerte med `--with-live`: `botctl add-live`
2. `botctl keys live` – legg inn børsnøkkel (**kun Spot Trade + Read, aldri uttak, lås til serverens IP**) og Telegram.
3. `botctl config live` – sett `mode: live` **og** `live_trading_confirmed: true`. Start med lav `buy_amount_usdt`.
4. `botctl check live` – sjekker nøkkel og saldo.
5. `botctl start live`

Varslene merkes med `[PAPER]` og `[LIVE]` så du ser hvilken som gjør hva. Begge reagerer på samme listing, så du kan sammenligne simulert og ekte resultat direkte.

### Hvis Binance blokkerer serveren
Noen datasentre blokkeres av Binance. Da får du ⚠️-varselet, og i 💓-meldingen står `polling: feil` / `websocket: feil`. Prøv en annen region eller leverandør.
