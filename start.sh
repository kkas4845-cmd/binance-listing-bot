#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
while true; do
  python -m listing_bot run
  echo "Boten stoppet. Starter på nytt om 10 sekunder (Ctrl+C for å avslutte)..."
  sleep 10
done
