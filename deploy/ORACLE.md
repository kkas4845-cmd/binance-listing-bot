# Versjon 1: Gratis Oracle Cloud-server

Boten kjører døgnet rundt på en gratis server hos Oracle. PC-en kan være av. Du følger med via Telegram på mobilen.

**Pris:** 0 kr. Oracle krever kortnummer ved registrering for å bekrefte identitet, men trekker ikke penger for «Always Free»-ressurser.
**Tid:** ca. 30 minutter første gang.

> Samme bot og samme funksjoner som [VPS-versjonen](VPS.md). Det eneste som er forskjellig er hvor serveren kommer fra.

---

## 1. Lag Oracle-konto

1. Gå til [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) → **Start for free**.
2. **Home Region – viktig, kan ikke endres senere.** Gratis-serveren må ligge i hjemregionen.
   - **Japan East (Tokyo)** eller **Singapore**: raskest mot Binance → anbefalt for denne boten.
   - **Sweden Central (Stockholm)**: nærmest deg, men tregere mot Binance.
3. Fullfør registreringen (e-post, telefon, kort). Det kan ta litt tid før kontoen er aktiv.

## 2. Lag serveren

1. Logg inn → menyen ☰ → **Compute** → **Instances** → **Create instance**.
2. **Name:** `listing-bot`
3. **Image and shape** → **Edit**:
   - **Image:** *Change image* → **Canonical Ubuntu** → **24.04**.
   - **Shape:** *Change shape* → **Virtual machine** → **AMD** → **VM.Standard.E2.1.Micro** (merket *Always Free-eligible*). 1 GB minne er nok – installasjonen lager ekstra swap automatisk.
   - *Alternativ:* **Ampere** → **VM.Standard.A1.Flex** med 1 OCPU / 6 GB hvis den er ledig (kraftigere, også gratis).
4. **Add SSH keys:** velg **Generate a key pair for me** → trykk **Save private key**. Ta vare på filen (f.eks. `ssh-key-2026-10-12.key`) – uten den kommer du ikke inn.
5. **Create**. Etter et par minutter står det **Running** og en **Public IP address** (f.eks. `140.238.12.34`). Noter den.

**Får du «Out of host capacity»?** Gratis-servere er midlertidig utsolgt i regionen. Prøv et annet *Availability domain* (AD-2/AD-3) i samme skjema, eller prøv igjen senere på dagen.

> Du trenger **ikke** åpne noen porter i brannmuren. Boten tar bare kontakt *utover* (til Binance, børsen og Telegram).

## 3. Koble til serveren

**Fra Windows-PC (PowerShell):**
```powershell
cd Downloads
icacls ssh-key-2026-10-12.key /inheritance:r /grant:r "$($env:USERNAME):(R)"
ssh -i ssh-key-2026-10-12.key ubuntu@140.238.12.34
```
(Bytt filnavn og IP med dine. Den første linjen fikser rettighetene på nøkkelfilen, ellers nekter Windows å bruke den. Svar `yes` første gang.)

**Fra mobilen eller uten PC:** Bruk appen **Termius** (gratis, iOS/Android): *New host* → IP-adressen, brukernavn `ubuntu`, og importer nøkkelfilen under *Keys*.

## 4. Installer boten (én kommando)

Når du er inne på serveren (du ser noe som `ubuntu@listing-bot:~$`), lim inn:

```bash
curl -fsSL https://raw.githubusercontent.com/kkas4845-cmd/binance-listing-bot/main/deploy/install.sh | sudo bash
```

Vil du ha en ekstra instans for ekte penger også (står i paper til du bytter selv):
```bash
curl -fsSL https://raw.githubusercontent.com/kkas4845-cmd/binance-listing-bot/main/deploy/install.sh | sudo bash -s -- --with-live
```

Skriptet installerer alt, kjører testene og starter boten i **paper-modus** (late-penger). Den starter automatisk igjen hvis serveren starter på nytt eller boten krasjer.

## 5. Koble til Telegram og test

```bash
botctl keys paper        # lim inn TELEGRAM_BOT_TOKEN og TELEGRAM_CHAT_ID (Ctrl+O, Enter, Ctrl+X for å lagre)
botctl restart paper     # nå skal du få 🤖 "Listing-bot startet" på mobilen
botctl check paper       # tester børstilkoblingen
botctl simulate paper "Binance Will List Arbitrum (ARB)"
```

Ferdig – du kan logge ut (`exit`) og slå av PC-en.

---

## Spesielt for Oracle: inaktive gratis-servere

Oracle kan ta tilbake gratis-servere som ser ubrukte ut. Ifølge Oracles egne regler skjer det hvis CPU-, nettverks- og (for Ampere) minnebruk alle ligger under 20 % over en uke – og en liten bot som venter på annonseringer bruker lite. Dette gjelder Always Free-ressurser også om du oppgraderer kontoen. ([Oracle-dokumentasjon](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm))

Slik er du dekket:
- Boten sender en **💓 statusmelding hver 24. time**. Uteblir den, sjekk Oracle-konsollen.
- Står serveren som **Stopped**: trykk **Start**. Boten starter automatisk, og databasen ligger igjen på disken.
- Er serveren slettet: lag en ny (steg 2–5). Det tar 10 minutter.

Hvis dette blir et problem, er [VPS-versjonen](VPS.md) mer forutsigbar.

---

Daglig bruk, oppdateringer og ekte penger: se [Felles for begge versjonene](README.md#felles-for-begge-versjonene).
