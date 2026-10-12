"""Varsler til mobilen via Telegram (gratis). Valgfritt – uten oppsett logges bare til skjerm/fil."""
from __future__ import annotations

import logging
import os

log = logging.getLogger("listing_bot.notify")


class Notifier:
    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send(self, text: str) -> None:
        log.info("VARSEL: %s", text)
        if not self.enabled:
            return
        try:
            import aiohttp  # type: ignore
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json={"chat_id": self.chat_id, "text": text[:4000]},
                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        log.warning("Telegram svarte %s", r.status)
        except Exception as e:  # noqa: BLE001 – varsling skal aldri stoppe boten
            log.warning("Kunne ikke sende Telegram-varsel: %s", e)
