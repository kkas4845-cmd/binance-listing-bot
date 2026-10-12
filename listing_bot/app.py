"""Hovedløkken: annonsering -> tolkning -> sjekker -> kjøp -> overvåking -> salg."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from . import exits, risk
from .config import Config
from .detector import Detector
from .market import Market
from .notify import Notifier
from .parser import Announcement, ListingSignal, parse
from .store import Position, Store, now_ms

log = logging.getLogger("listing_bot")


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = Store(cfg.database)
        self.market = Market(cfg)
        self.notify = Notifier(cfg.name)
        self.detector: Detector | None = None
        self.started_ms = now_ms()
        self.announcements_seen = 0
        self.queue: asyncio.Queue[Announcement] = asyncio.Queue()
        self._buy_lock = asyncio.Lock()
        self._selling: set[int] = set()
        self._fail_notified: dict[int, float] = {}

    # ------------------------------------------------------------ oppstart
    async def start(self) -> None:
        await self.market.connect()
        mode = "LIVE – EKTE PENGER" if self.cfg.is_live else "PAPER (simulert, ingen ekte penger)"
        if self.cfg.is_live:
            bal = await self.market.free_quote_balance()
            if bal < self.cfg.entry.buy_amount_usdt:
                raise RuntimeError(f"For lite {self.cfg.quote} på {self.cfg.exchange}: {bal:.2f}")
            mode += f" | saldo {bal:.2f} {self.cfg.quote}"
        open_pos = self.store.open_positions(self.cfg.mode)
        hb = (f" Statusmelding hver {self.cfg.heartbeat_hours:g}. time." if self.cfg.heartbeat_hours else "")
        await self.notify.send(f"🤖 Listing-bot startet på {self.cfg.exchange} i {mode}. "
                               f"Åpne posisjoner: {len(open_pos)}.{hb}")

    async def run(self) -> None:
        await self.start()
        self.detector = Detector(self.cfg, self.queue)
        try:
            await asyncio.gather(self.detector.run(), self._consume(), self._exit_loop(),
                                 self._health_loop())
        finally:
            await self.market.close()

    # ------------------------------------------------------------ helse
    def status_text(self) -> str:
        mode = self.cfg.mode
        open_pos = self.store.open_positions(mode)
        day = 86_400_000
        pnl_24h = self.store.realized_pnl_since(now_ms() - day, mode)
        pnl_all = self.store.realized_pnl_since(0, mode)
        h = self.detector.healthy if self.detector else {}
        src = ", ".join(f"{k}: {'OK' if v else 'feil'}" for k, v in h.items()
                        if (k == "websocket" and self.cfg.detector.use_websocket and self.cfg.binance_api_key)
                        or (k == "polling" and self.cfg.detector.use_polling))
        up_h = (now_ms() - self.started_ms) / 3_600_000
        stop = " | ⛔ NØDSTOPP AKTIV" if os.path.exists(self.cfg.risk.kill_switch_file) else ""
        return (f"Oppe i {up_h:.0f} t | Kilder: {src or 'ingen'} | Åpne posisjoner: {len(open_pos)} | "
                f"Resultat 24t: {pnl_24h:+.2f}, totalt: {pnl_all:+.2f} {self.cfg.quote}{stop}")

    async def _health_loop(self) -> None:
        """Sender jevnlig "jeg lever"-melding, og varsler hvis boten ikke får inn annonseringer."""
        last_beat = time.time()
        down_since: float | None = None
        warned = False
        await asyncio.sleep(60)
        while True:
            h = self.detector.healthy if self.detector else {}
            if h and not any(h.values()):
                down_since = down_since or time.time()
                if not warned and time.time() - down_since > 300:
                    warned = True
                    await self.notify.send("⚠️ Boten har ikke kontakt med Binance-annonseringene (5+ min). "
                                           "Den ser ingen nye listinger før dette løser seg. Sjekk logs/bot.log.")
            else:
                if warned:
                    await self.notify.send("✅ Kontakten med Binance-annonseringene er tilbake.")
                down_since, warned = None, False
            if self.cfg.heartbeat_hours > 0 and time.time() - last_beat >= self.cfg.heartbeat_hours * 3600:
                last_beat = time.time()
                await self.notify.send("💓 " + self.status_text())
            await asyncio.sleep(30)

    # ------------------------------------------------------------ annonseringer
    async def _consume(self) -> None:
        while True:
            ann = await self.queue.get()
            self.announcements_seen += 1
            try:
                await self.handle_announcement(ann)
            except Exception as e:  # noqa: BLE001
                log.exception("Feil ved håndtering av annonsering")
                self.store.log("error", f"{ann.title}: {e}")

    async def handle_announcement(self, ann: Announcement, *, force_fresh: bool = False) -> None:
        if self.store.seen(ann.id):
            return
        d = self.cfg.detector
        age_s = (now_ms() - ann.publish_ms) / 1000 if ann.publish_ms else None

        sig = parse(ann, must_start_with=d.title_must_start_with, blocked_words=d.blocked_title_words,
                    include_seed_tag=d.include_seed_tag)
        if sig is None:
            self.store.mark_seen(ann.id, ann.title, ann.source, ann.publish_ms, "ignorert: ikke ny spot-listing")
            return

        if not force_fresh and (ann.source == "polling-initial" or age_s is None or age_s > d.max_announcement_age_sec):
            self.store.mark_seen(ann.id, ann.title, ann.source, ann.publish_ms,
                                 f"ignorert: for gammel ({age_s if age_s is not None else '?'} s)")
            log.info("Gammel listing ignorert: %s", ann.title)
            return

        self.store.mark_seen(ann.id, ann.title, ann.source, ann.publish_ms, "behandlet")
        lag = f"{age_s:.1f}s" if age_s is not None else "?"
        log.info("NY LISTING (%s, %s etter publisering): %s", ann.source, lag, ann.title)
        await self.notify.send(f"📢 Binance-listing oppdaget ({lag}): {ann.title}")
        results = await asyncio.gather(*(self._try_buy(sig, t.ticker, t.name) for t in sig.tokens),
                                       return_exceptions=True)
        for tok, res in zip(sig.tokens, results):
            if isinstance(res, Exception):
                log.error("Kjøp av %s feilet: %s", tok.ticker, res)
                await self._skip(tok.ticker, f"Feil: {res}")

    async def _try_buy(self, sig: ListingSignal, ticker: str, name: str) -> None:
        amount = self.cfg.entry.buy_amount_usdt
        if sig.seed_tag:
            amount *= self.cfg.detector.seed_tag_size_factor

        # Låsen gjør at to samtidige kjøp ikke begge slipper gjennom risikosjekken
        async with self._buy_lock:
            why_not = risk.check_can_buy(self.cfg, self.store, ticker, amount)
            if why_not:
                await self._skip(ticker, why_not)
                return
            t0 = time.perf_counter()
            pre = await self.market.pre_trade_checks(ticker, name, amount, sig.announcement.publish_ms)
            if not pre.ok:
                await self._skip(ticker, pre.reason)
                return
            if self.cfg.is_live:
                bal = await self.market.free_quote_balance()
                if bal < amount:
                    await self._skip(ticker, f"For lite {self.cfg.quote} ({bal:.2f})")
                    return
            fill = await self.market.buy(pre, amount)
            ms = (time.perf_counter() - t0) * 1000
            if not fill or fill.amount <= 0:
                await self._skip(ticker, "Ordren ble ikke fylt innen prisgrensen (IOC kansellert)")
                return
            pos_id = self.store.open_position(
                mode=self.cfg.mode, exchange=self.cfg.exchange, ticker=ticker, symbol=pre.symbol,
                amount=fill.held, entry_price=fill.avg_price, cost=fill.cost, entry_fee=fill.fee_usdt,
                opened_ms=now_ms(), peak_price=fill.avg_price, binance_open_ms=sig.binance_open_ms,
                announcement_id=sig.announcement.id,
            )
        slip = (fill.avg_price / pre.best_ask - 1) * 100 if pre.best_ask else 0
        await self.notify.send(
            f"🟢 KJØPT {ticker} ({'LIVE' if self.cfg.is_live else 'paper'}) #{pos_id}: "
            f"{fill.amount:.6g} @ {fill.avg_price:.6g} = {fill.cost:.2f} {self.cfg.quote} "
            f"(slippage {slip:.2f} %, {ms:.0f} ms fra sjekk til fylt)"
            + (" ⚠️ Seed Tag" if sig.seed_tag else "")
        )

    async def _skip(self, ticker: str, reason: str) -> None:
        self.store.log("skip", f"{ticker}: {reason}")
        await self.notify.send(f"⏭️ Hoppet over {ticker}: {reason}")

    # ------------------------------------------------------------ salg
    async def _exit_loop(self) -> None:
        while True:
            for pos in self.store.open_positions(self.cfg.mode):
                if pos.id in self._selling:
                    continue
                try:
                    await self.check_exit(pos)
                except Exception as e:  # noqa: BLE001
                    log.warning("Exit-sjekk feilet for %s: %s", pos.ticker, e)
            await asyncio.sleep(self.cfg.exit.check_interval_sec)

    async def check_exit(self, pos: Position, *, now: int | None = None) -> None:
        bid, _, _ = await self.market.best_bid_ask(pos.symbol)
        if bid <= 0:
            return
        dec = exits.decide(entry_price=pos.entry_price, peak_price=pos.peak_price, bid=bid,
                           opened_ms=pos.opened_ms, now_ms=now or now_ms(),
                           binance_open_ms=pos.binance_open_ms, cfg=self.cfg.exit)
        if dec.new_peak > (pos.peak_price or 0):
            self.store.update_peak(pos.id, dec.new_peak)
        if dec.reason:
            await self.close(pos, dec.reason)

    async def close(self, pos: Position, reason: str) -> None:
        self._selling.add(pos.id)
        try:
            fill = await self.market.sell(pos.symbol, pos.amount)
            if not fill:
                # Prøves igjen ved neste runde; varsle maks hvert 5. minutt
                if time.time() - self._fail_notified.get(pos.id, 0) > 300:
                    self._fail_notified[pos.id] = time.time()
                    await self.notify.send(f"🔴 KLARTE IKKE Å SELGE {pos.ticker} (#{pos.id}, {reason}). "
                                           f"Prøver igjen – sjekk børsen manuelt!")
                return
            sold_frac = min(fill.amount / pos.amount, 1.0) if pos.amount else 1.0
            if sold_frac < 0.99:
                # Delvis salg: del posisjonen i en solgt del og en gjenværende del
                left = pos.amount - fill.amount
                self.store.reduce_position(pos.id, left, pos.cost * (1 - sold_frac), pos.entry_fee * (1 - sold_frac))
                part_id = self.store.open_position(
                    mode=pos.mode, exchange=pos.exchange, ticker=pos.ticker, symbol=pos.symbol,
                    amount=fill.amount, entry_price=pos.entry_price, cost=pos.cost * sold_frac,
                    entry_fee=pos.entry_fee * sold_frac, opened_ms=pos.opened_ms, peak_price=pos.peak_price,
                    binance_open_ms=pos.binance_open_ms, announcement_id=pos.announcement_id)
                self.store.close_position(part_id, fill.avg_price, fill.cost, fill.fee_usdt, reason + " (delvis)")
                await self.notify.send(f"🟠 Delvis solgt {pos.ticker}: {sold_frac*100:.0f} % @ {fill.avg_price:.6g}. Resten prøves igjen.")
                return
            self.store.close_position(pos.id, fill.avg_price, fill.cost, fill.fee_usdt, reason)
            pnl = fill.cost - fill.fee_usdt - pos.cost - pos.entry_fee
            pct = pnl / (pos.cost + pos.entry_fee) * 100 if pos.cost else 0
            icon = "✅" if pnl >= 0 else "🔻"
            await self.notify.send(f"{icon} SOLGT {pos.ticker} #{pos.id} ({reason}) @ {fill.avg_price:.6g}: "
                                   f"{pnl:+.2f} {self.cfg.quote} ({pct:+.1f} %)")
        finally:
            self._selling.discard(pos.id)
