# Versjon 2: Betalt VPS (eksempel: Hetzner)

Boten kjører døgnet rundt på en leid server. PC-en kan være av. Du følger med via Telegram på mobilen.

**Pris:** ca. 4–8 € i måneden (se under). Betales per time – sletter du serveren, stopper kostnaden.
**Tid:** ca. 20 minutter første gang.

> Samme bot og samme funksjoner som [Oracle-versjonen](ORACLE.md). Fordelen med VPS: serveren blir aldri tatt tilbake, og oppsettet er enklere.
> Guiden bruker Hetzner, men fungerer hos alle som tilbyr **Ubuntu 24.04** (DigitalOcean, Vultr, Contabo osv.).

---

## 1. Lag SSH-nøkkel på PC-en (én gang)

I **PowerShell** på Windows:
```powershell
ssh-keygen -t ed25519
```
Trykk Enter på alle spørsmål. Vis den offentlige nøkkelen:
```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub
```
Kopier hele linjen (starter med `ssh-ed25519`).

## 2. Lag serveren

1. Lag konto på [hetzner.com/cloud](https://www.hetzner.com/cloud/) og legg inn betaling.
2. Lag et prosjekt → **Add Server**.
3. **Location** – velg én:
   | Valg | Plan | Omtrentlig pris | Fart mot Binance |
   |---|---|---|---|
   | **Singapore** (anbefalt) | CPX22 (2 vCPU, 4 GB) | ca. 8 €/mnd | Rask |
   | **Helsinki** (billigst) | CX23 (2 vCPU, 4 GB) | ca. 4 €/mnd | Tregere |

   Hetzner økte prisene i 2026, så sjekk prisen som vises før du bestiller. ([oversikt](https://learnwithhasan.com/self-hosting-hub/vps-providers/hetzner/))
4. **Image:** Ubuntu 24.04.
5. **SSH keys:** *Add SSH key* → lim inn linjen fra steg 1.
6. **Firewalls:** *Create firewall* → behold bare regelen for **SSH (port 22)** inn. Ingen andre porter trengs.
7. **Create & Buy now.** Noter **IP-adressen** (f.eks. `5.223.40.17`).

## 3. Koble til serveren

```powershell
ssh root@5.223.40.17
```
Svar `yes` første gang.

**Fra mobilen:** Appen **Termius** (gratis): *New host* → IP-adressen, brukernavn `root`, og legg inn nøkkelen under *Keys* (eller lag en ny nøkkel i Termius og legg den til i Hetzner).

## 4. Installer boten (én kommando)

```bash
curl -fsSL https://raw.githubusercontent.com/kkas4845-cmd/binance-listing-bot/main/deploy/install.sh | sudo bash
```

Med ekstra instans for ekte penger (står i paper til du bytter selv):
```bash
curl -fsSL https://raw.githubusercontent.com/kkas4845-cmd/binance-listing-bot/main/deploy/install.sh | sudo bash -s -- --with-live
```

Skriptet installerer alt, kjører testene og starter boten i **paper-modus**. Boten kjører som en egen begrenset bruker (ikke root) og starter automatisk etter omstart eller krasj.

## 5. Koble til Telegram og test

```bash
botctl keys paper        # lim inn TELEGRAM_BOT_TOKEN og TELEGRAM_CHAT_ID (Ctrl+O, Enter, Ctrl+X)
botctl restart paper     # nå skal du få 🤖 "Listing-bot startet" på mobilen
botctl check paper
botctl simulate paper "Binance Will List Arbitrum (ARB)"
```

Ferdig – logg ut med `exit` og slå av PC-en.

---

## Spesielt for VPS

- **Lås API-nøklene til serverens IP.** Både på børsen og Binance kan du legge inn serverens IP-adresse som eneste tillatte adresse. Da er nøklene ubrukelige for andre selv om de lekker.
- **Sikkerhetskopi (valgfritt):** Hetzner kan ta automatiske backups for et lite påslag. Ellers: `botctl export paper` jevnlig.
- **Avslutte:** slett serveren i Hetzner-konsollen. Bare å slå den av stopper *ikke* fakturaen.

---

Daglig bruk, oppdateringer og ekte penger: se [Felles for begge versjonene](README.md#felles-for-begge-versjonene).
