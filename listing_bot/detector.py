"""Lytter etter nye Binance-annonseringer.

To kilder, begge OFFISIELLE Binance-kilder (aldri Twitter/Telegram – der
florerer falske "Binance will list"-meldinger):

1. WebSocket (raskest): Binance sin offisielle annonserings-strøm
   wss://api.binance.com/sapi/wss, topic com_announcement_en.
   Krever en Binance API-nøkkel – bruk en nøkkel med KUN lesetilgang.
2. Polling (reserve): Binance sin offentlige artikkelliste for kategorien
   "New Cryptocurrency Listing" (catalogId 48). Ingen nøkkel trengs.

Begge legger annonseringer i samme kø; appen fjerner duplikater.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import random
import time
import urllib.parse

from .config import Config
from .parser import Announcement

log = logging.getLogger("listing_bot.detector")

WS_BASE = "wss://api.binance.com/sapi/wss"
WS_TOPIC = "com_announcement_en"
LIST_URL = ("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
            "?type=1&catalogId=48&pageNo=1&pageSize=10")
LISTING_CATALOG = "New Cryptocurrency Listing"
UA = "Mozilla/5.0 (compatible; listing-bot/1.0)"


def signed_ws_url(api_key: str, api_secret: str, ts_ms: int | None = None, rnd: str | None = None) -> str:
    params = {
        "random": rnd or "%032x" % random.getrandbits(128),
        "topic": WS_TOPIC,
        "recvWindow": 30000,
        "timestamp": ts_ms or int(time.time() * 1000),
    }
    # Signaturen lages over parametrene sortert alfabetisk (Binance CMS-dokumentasjon)
    payload = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sig = hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{WS_BASE}?{payload}&signature={sig}"


def parse_ws_message(raw: str) -> Announcement | None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if msg.get("type") != "DATA" or msg.get("topic") != WS_TOPIC:
        return None
    data = msg.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    title = data.get("title") or ""
    publish = int(data.get("publishDate") or 0)
    ann_id = "t:" + hashlib.sha1(title.strip().lower().encode()).hexdigest()[:16]
    return Announcement(id=ann_id, title=title, body=data.get("body") or "", publish_ms=publish,
                        source="websocket", catalog=data.get("catalogName") or "")


def parse_list_response(js: dict) -> list[Announcement]:
    out: list[Announcement] = []
    catalogs = ((js or {}).get("data") or {}).get("catalogs") or []
    for cat in catalogs:
        for a in cat.get("articles") or []:
            title = a.get("title") or ""
            out.append(Announcement(
                id="t:" + hashlib.sha1(title.strip().lower().encode()).hexdigest()[:16],
                title=title,
                body="",
                publish_ms=int(a.get("releaseDate") or 0),
                source="polling",
                catalog=cat.get("catalogName") or LISTING_CATALOG,
            ))
    return out


class Detector:
    def __init__(self, cfg: Config, queue: "asyncio.Queue[Announcement]"):
        self.cfg = cfg
        self.queue = queue
        self.healthy = {"websocket": False, "polling": False}

    async def run(self) -> None:
        tasks = []
        d = self.cfg.detector
        if d.use_websocket and self.cfg.binance_api_key and self.cfg.binance_api_secret:
            tasks.append(asyncio.create_task(self._ws_loop()))
        elif d.use_websocket:
            log.warning("WebSocket er på, men BINANCE_API_KEY/SECRET mangler i .env – bruker bare polling")
        if d.use_polling:
            tasks.append(asyncio.create_task(self._poll_loop()))
        if not tasks:
            raise RuntimeError("Ingen annonseringskilde aktiv – slå på use_websocket eller use_polling")
        await asyncio.gather(*tasks)

    # ------------------------------------------------------------ websocket
    async def _ws_loop(self) -> None:
        import websockets  # type: ignore
        backoff = 1
        while True:
            url = signed_ws_url(self.cfg.binance_api_key, self.cfg.binance_api_secret)
            headers = {"X-MBX-APIKEY": self.cfg.binance_api_key}
            try:
                try:
                    conn = websockets.connect(url, additional_headers=headers, ping_interval=25, ping_timeout=20)
                except TypeError:  # eldre websockets-versjon
                    conn = websockets.connect(url, extra_headers=headers, ping_interval=25, ping_timeout=20)
                async with conn as ws:
                    await ws.send(json.dumps({"command": "SUBSCRIBE", "value": WS_TOPIC}))
                    started = time.time()
                    self.healthy["websocket"] = True
                    log.info("WebSocket tilkoblet Binance-annonseringer")
                    backoff = 1
                    while True:
                        # Binance kutter etter 24 t – vi kobler til på nytt etter 23 t
                        if time.time() - started > 23 * 3600:
                            log.info("Fornyer WebSocket (24-timersgrense)")
                            break
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        except asyncio.TimeoutError:
                            continue
                        ann = parse_ws_message(raw)
                        if ann:
                            await self.queue.put(ann)
                        elif '"COMMAND"' in str(raw) and "SUCCESS" not in str(raw):
                            log.warning("WebSocket-svar: %s", raw)
            except Exception as e:  # noqa: BLE001
                self.healthy["websocket"] = False
                log.warning("WebSocket-feil: %s – prøver igjen om %ss", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    # ------------------------------------------------------------ polling
    async def _poll_loop(self) -> None:
        import aiohttp  # type: ignore
        d = self.cfg.detector
        first = True
        backoff = 0.0
        async with aiohttp.ClientSession(headers={"User-Agent": UA, "Accept": "application/json"}) as s:
            while True:
                try:
                    async with s.get(LIST_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status in (403, 418, 429):
                            self.healthy["polling"] = False
                            backoff = min(max(backoff * 2, 30), 600)
                            log.warning("Binance svarte %s (rate limit/blokk) – venter %ss", r.status, backoff)
                            await asyncio.sleep(backoff)
                            continue
                        r.raise_for_status()
                        js = await r.json(content_type=None)
                    backoff = 0.0
                    self.healthy["polling"] = True
                    anns = parse_list_response(js)
                    for ann in anns:
                        # Første runde: alt som allerede ligger ute er gammelt.
                        # Aldersfilteret i appen stopper det uansett, men vi merker det her også.
                        if first:
                            ann.source = "polling-initial"
                        await self.queue.put(ann)
                    first = False
                except Exception as e:  # noqa: BLE001
                    self.healthy["polling"] = False
                    log.warning("Polling-feil: %s", e)
                    await asyncio.sleep(10)
                # Litt tilfeldig variasjon så vi ikke ser ut som en klokke
                await asyncio.sleep(d.poll_interval_sec * random.uniform(0.85, 1.15))


def ws_query_string(url: str) -> dict[str, str]:
    """Hjelper for tester."""
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
