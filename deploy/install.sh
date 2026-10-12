#!/usr/bin/env bash
# Installerer listing-boten på en Ubuntu/Debian-server (Oracle Cloud eller VPS – samme skript).
#
# Bruk (som en bruker med sudo):
#   curl -fsSL https://raw.githubusercontent.com/kkas4845-cmd/binance-listing-bot/main/deploy/install.sh | sudo bash
# Eller med ekte-penger-instans i tillegg:
#   curl -fsSL .../install.sh | sudo bash -s -- --with-live
#
# Kan kjøres på nytt trygt: eksisterende config, nøkler og database blir ikke rørt.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/kkas4845-cmd/binance-listing-bot.git}"
BASE=/opt/listing-bot
APP="$BASE/app"
VENV="$BASE/venv"
INST="$BASE/instances"
SVC_USER=listingbot
WITH_LIVE=0

for arg in "$@"; do
  case "$arg" in
    --with-live) WITH_LIVE=1 ;;
    *) echo "Ukjent valg: $arg"; exit 1 ;;
  esac
done

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }

if [[ $EUID -ne 0 ]]; then
  echo "Kjør med sudo:  sudo bash install.sh"; exit 1
fi
if ! command -v apt-get >/dev/null; then
  echo "Dette skriptet støtter Ubuntu/Debian. Velg Ubuntu 22.04 eller 24.04 når du lager serveren."; exit 1
fi

say "Installerer systempakker"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git ca-certificates unattended-upgrades nano >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

# Små servere (f.eks. Oracle AMD Micro med 1 GB) trenger swap for å installere pakker trygt
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ $MEM_MB -lt 2000 ]] && ! swapon --show | grep -q .; then
  say "Lite minne (${MEM_MB} MB) – lager 2 GB swap"
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "Sørger for riktig klokke (viktig for API-signaturer)"
timedatectl set-ntp true 2>/dev/null || true

say "Lager egen systembruker '$SVC_USER' (boten kjører aldri som root)"
id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir "$BASE" --shell /usr/sbin/nologin "$SVC_USER"
mkdir -p "$BASE" "$INST"

say "Henter koden"
if [[ -d "$APP/.git" ]]; then
  git -C "$APP" pull --ff-only
else
  git clone --depth 1 "$REPO_URL" "$APP"
fi

say "Installerer Python-pakker"
[[ -d "$VENV" ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP/requirements.txt"

say "Kjører testene"
(cd "$APP" && "$VENV/bin/python" -m unittest discover -s tests -t . -q)

make_instance() {
  local name="$1" mode="$2" upper
  upper=$(echo "$name" | tr '[:lower:]' '[:upper:]')
  local dir="$INST/$name"
  mkdir -p "$dir/logs"
  if [[ ! -f "$dir/config.yaml" ]]; then
    cp "$APP/config.example.yaml" "$dir/config.yaml"
    sed -i "s/^name: \"\"/name: \"$upper\"/" "$dir/config.yaml"
    # NB: også live-instansen starter i paper. Ekte penger krever at du selv
    # endrer mode: live OG live_trading_confirmed: true (botctl config live)
    echo "   laget $dir/config.yaml"
  fi
  if [[ ! -f "$dir/.env" ]]; then
    cp "$APP/.env.example" "$dir/.env"
    echo "   laget $dir/.env (fyll inn nøkler)"
  fi
  chmod 600 "$dir/.env" "$dir/config.yaml"
}

say "Setter opp instanser"
make_instance paper paper
[[ $WITH_LIVE -eq 1 ]] && make_instance live live

chown -R "$SVC_USER:$SVC_USER" "$BASE"

say "Installerer systemtjeneste (starter automatisk ved omstart og etter krasj)"
cp "$APP/deploy/listing-bot@.service" /etc/systemd/system/
install -m 755 "$APP/deploy/botctl" /usr/local/bin/botctl
systemctl daemon-reload
systemctl enable --now listing-bot@paper >/dev/null
if [[ $WITH_LIVE -eq 1 ]]; then
  systemctl enable listing-bot@live >/dev/null
  echo "   live-instansen er satt opp, men IKKE startet. Start med: botctl start live"
fi

sleep 3
say "Ferdig!"
systemctl --no-pager --lines=0 status listing-bot@paper | head -3 || true
cat <<EOF

Neste steg:
  1. Legg inn Telegram (og ev. nøkler):   botctl keys paper
  2. Start på nytt så det tas i bruk:       botctl restart paper
  3. Test at alt virker:                    botctl check paper
  4. Øv på en tenkt listing:                botctl simulate paper "Binance Will List Arbitrum (ARB)"

Alle kommandoer:  botctl help
EOF
