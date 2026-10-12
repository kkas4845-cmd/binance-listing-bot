"""Børs-tilkobling (via ccxt), markedssjekker før kjøp, og ordreutførelse.

Kjøp skjer med LIMIT + IOC (immediate-or-cancel) i stedet for markedsordre:
du betaler aldri mer enn beste pris + max_slippage_pct, og det som ikke kan
fylles umiddelbart blir kansellert. Markedsordre i tynne markeder etter en
annonsering kan ellers gi ekstrem slippage.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .config import Config
from .parser import names_match

log = logging.getLogger("listing_bot.market")


@dataclass
class Fill:
    amount: float
    avg_price: float
    cost: float
    fee_usdt: float
    net_amount: float | None = None  # mengde du faktisk eier (gebyr kan trekkes i mynten)

    @property
    def held(self) -> float:
        return self.net_amount if self.net_amount is not None else self.amount


@dataclass
class PreTradeResult:
    ok: bool
    reason: str = ""
    symbol: str = ""
    limit_price: float = 0.0
    amount: float = 0.0
    best_ask: float = 0.0


# ---------------------------------------------------------------- rene hjelpere
def walk_book(levels: list[list[float]], *, limit_price: float, side: str,
              max_cost: float | None = None, max_amount: float | None = None) -> tuple[float, float]:
    """Simulerer en IOC-ordre mot orderboken. Returnerer (mengde, kostnad/salgssum).

    side='buy' går gjennom asks opp til limit_price; side='sell' gjennom bids ned til limit_price.
    """
    amount = 0.0
    cost = 0.0
    for lvl in levels:
        price, size = float(lvl[0]), float(lvl[1])
        if side == "buy" and price > limit_price:
            break
        if side == "sell" and price < limit_price:
            break
        take = size
        if max_amount is not None:
            take = min(take, max_amount - amount)
        if max_cost is not None:
            take = min(take, (max_cost - cost) / price)
        if take <= 0:
            break
        amount += take
        cost += take * price
    return amount, cost


def spread_pct(bid: float, ask: float) -> float:
    mid = (bid + ask) / 2
    return (ask - bid) / mid * 100 if mid > 0 else float("inf")


# ---------------------------------------------------------------- børsklasse
class Market:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ex = None

    async def connect(self) -> None:
        import ccxt.async_support as ccxt  # type: ignore
        klass = getattr(ccxt, self.cfg.exchange)
        params = {"enableRateLimit": True, "options": {"defaultType": "spot"}}
        if self.cfg.exchange_api_key:
            params.update(apiKey=self.cfg.exchange_api_key, secret=self.cfg.exchange_api_secret)
            if self.cfg.exchange_api_password:
                params["password"] = self.cfg.exchange_api_password
        elif self.cfg.is_live:
            raise RuntimeError("Live-modus krever EXCHANGE_API_KEY og EXCHANGE_API_SECRET i .env")
        self.ex = klass(params)
        await self.ex.load_markets()
        try:
            await self.ex.fetch_currencies()
        except Exception:  # noqa: BLE001 – ikke alle børser støtter dette uten nøkkel
            pass
        log.info("Koblet til %s, %d markeder lastet", self.cfg.exchange, len(self.ex.markets))

    async def close(self) -> None:
        if self.ex:
            await self.ex.close()

    async def reload_markets(self) -> None:
        await self.ex.load_markets(reload=True)

    def symbol_for(self, ticker: str) -> str:
        return f"{ticker}/{self.cfg.quote}"

    def exchange_name_of(self, ticker: str) -> str | None:
        cur = (self.ex.currencies or {}).get(ticker) or {}
        name = cur.get("name")
        if not name:
            info = cur.get("info") or {}
            if isinstance(info, dict):
                name = info.get("fullName") or info.get("name")
            elif isinstance(info, list) and info and isinstance(info[0], dict):
                name = info[0].get("fullName") or info[0].get("name")
        if name and name.upper() == ticker.upper():
            return None  # børsen oppgir bare tickeren – ingen informasjon
        return name

    async def free_quote_balance(self) -> float:
        bal = await self.ex.fetch_balance()
        return float((bal.get("free") or {}).get(self.cfg.quote) or 0)

    async def best_bid_ask(self, symbol: str) -> tuple[float, float, dict]:
        ob = await self.ex.fetch_order_book(symbol, limit=50)
        bid = float(ob["bids"][0][0]) if ob["bids"] else 0.0
        ask = float(ob["asks"][0][0]) if ob["asks"] else 0.0
        return bid, ask, ob

    # ------------------------------------------------------------ sjekker
    async def pre_trade_checks(self, ticker: str, token_name: str, amount_usdt: float,
                               announce_ms: int) -> PreTradeResult:
        e = self.cfg.entry
        symbol = self.symbol_for(ticker)
        if symbol not in self.ex.markets:
            await self.reload_markets()  # kan være nylig lagt til
        m = self.ex.markets.get(symbol)
        if not m:
            return PreTradeResult(False, f"{symbol} handles ikke på {self.cfg.exchange}")
        if not m.get("spot") or m.get("active") is False:
            return PreTradeResult(False, f"{symbol} er ikke et aktivt spot-marked")

        # Ticker-forveksling
        if e.name_match != "off":
            ex_name = self.exchange_name_of(ticker)
            match = names_match(token_name, ex_name)
            if match is False:
                msg = f"Navn stemmer ikke: Binance '{token_name}' vs {self.cfg.exchange} '{ex_name}' – trolig en annen mynt"
                if e.name_match == "strict":
                    return PreTradeResult(False, msg)
                log.warning(msg)
            elif match is None and e.name_match == "strict":
                return PreTradeResult(False, f"{self.cfg.exchange} oppgir ikke fullt navn for {ticker}; kan ikke utelukke forveksling (sett entry.name_match: warn for å tillate)")

        # Volum
        t = await self.ex.fetch_ticker(symbol)
        qv = t.get("quoteVolume")
        if qv is None and t.get("baseVolume") and t.get("last"):
            qv = t["baseVolume"] * t["last"]
        if (qv or 0) < e.min_24h_volume_usdt:
            return PreTradeResult(False, f"For lite volum: {qv or 0:,.0f} < {e.min_24h_volume_usdt:,.0f} USDT/24t")

        # Orderbok: spread og dybde
        bid, ask, ob = await self.best_bid_ask(symbol)
        if bid <= 0 or ask <= 0:
            return PreTradeResult(False, "Tom orderbok")
        sp = spread_pct(bid, ask)
        if sp > e.max_spread_pct:
            return PreTradeResult(False, f"For stor spread: {sp:.2f} % > {e.max_spread_pct} %")

        limit_price = ask * (1 + e.max_slippage_pct / 100)
        _, depth_cost = walk_book(ob["asks"], limit_price=limit_price, side="buy")
        need = amount_usdt * e.min_depth_multiple
        if depth_cost < need:
            return PreTradeResult(False, f"For tynn orderbok: {depth_cost:.0f} USDT innen {e.max_slippage_pct} % (trenger {need:.0f})")

        # Ikke jag prisen
        chase = await self._move_since(symbol, announce_ms, ask)
        if chase is not None and chase > e.max_chase_pct:
            return PreTradeResult(False, f"Prisen har allerede steget {chase:.1f} % siden annonseringen – for sent")

        # Presisjon og minstekrav
        amount = amount_usdt / limit_price
        amount = float(self.ex.amount_to_precision(symbol, amount))
        limit_price = float(self.ex.price_to_precision(symbol, limit_price))
        lim = m.get("limits") or {}
        min_amt = (lim.get("amount") or {}).get("min") or 0
        min_cost = (lim.get("cost") or {}).get("min") or 0
        if amount <= 0 or amount < min_amt or amount * limit_price < min_cost:
            return PreTradeResult(False, f"Ordren er under børsens minstekrav (min mengde {min_amt}, min kost {min_cost})")

        return PreTradeResult(True, "", symbol, limit_price, amount, ask)

    async def _move_since(self, symbol: str, announce_ms: int, ask: float) -> float | None:
        if not announce_ms or not self.ex.has.get("fetchOHLCV"):
            return None
        try:
            candles = await self.ex.fetch_ohlcv(symbol, "1m", since=announce_ms - 120_000, limit=5)
        except Exception as ex:  # noqa: BLE001
            log.debug("OHLCV feilet: %s", ex)
            return None
        if not candles:
            return None
        ref = float(candles[0][1])  # åpningspris rett før annonseringen
        return (ask / ref - 1) * 100 if ref > 0 else None

    # ------------------------------------------------------------ ordre
    async def buy(self, pre: PreTradeResult, amount_usdt: float) -> Fill | None:
        if not self.cfg.is_live:
            _, _, ob = await self.best_bid_ask(pre.symbol)
            amt, cost = walk_book(ob["asks"], limit_price=pre.limit_price, side="buy", max_cost=amount_usdt)
            if amt <= 0:
                return None
            fee = cost * self.cfg.taker_fee_pct / 100
            return Fill(amt, cost / amt, cost, fee)

        order = await self.ex.create_order(pre.symbol, "limit", "buy", pre.amount, pre.limit_price,
                                           {"timeInForce": "IOC"})
        return await self._settle(order, pre.symbol)

    async def sell(self, symbol: str, amount: float) -> Fill | None:
        """Selger med IOC-limit, utvider prisgrensen litt for hvert forsøk."""
        x = self.cfg.exit
        remaining = amount
        total_amt = total_cost = total_fee = 0.0
        for attempt in range(5):
            bid, _, ob = await self.best_bid_ask(symbol)
            if bid <= 0:
                await asyncio.sleep(1)
                continue
            slip = x.max_sell_slippage_pct * (1 + attempt * 0.5)
            limit_price = bid * (1 - min(slip, 30) / 100)
            if not self.cfg.is_live:
                amt, cost = walk_book(ob["bids"], limit_price=limit_price, side="sell", max_amount=remaining)
                fill = Fill(amt, cost / amt if amt else 0, cost, cost * self.cfg.taker_fee_pct / 100) if amt else None
            else:
                qty = float(self.ex.amount_to_precision(symbol, remaining))
                if qty <= 0:
                    break
                order = await self.ex.create_order(symbol, "limit", "sell", qty,
                                                   float(self.ex.price_to_precision(symbol, limit_price)),
                                                   {"timeInForce": "IOC"})
                fill = await self._settle(order, symbol)
            if fill and fill.amount > 0:
                total_amt += fill.amount
                total_cost += fill.cost
                total_fee += fill.fee_usdt
                remaining -= fill.amount
            if remaining <= amount * 0.001:
                break
            await asyncio.sleep(1)
        if total_amt <= 0:
            return None
        return Fill(total_amt, total_cost / total_amt, total_cost, total_fee)

    async def _settle(self, order: dict, symbol: str) -> Fill | None:
        oid = order.get("id")
        for _ in range(10):
            if order.get("status") in ("closed", "canceled", "expired", "rejected"):
                break
            await asyncio.sleep(0.5)
            order = await self.ex.fetch_order(oid, symbol)
        filled = float(order.get("filled") or 0)
        if filled <= 0:
            return None
        cost = float(order.get("cost") or 0) or filled * float(order.get("average") or order.get("price") or 0)
        fee = 0.0
        base_fee = 0.0
        for f in order.get("fees") or ([order["fee"]] if order.get("fee") else []):
            if not f or f.get("cost") is None:
                continue
            c = float(f["cost"])
            cur = f.get("currency")
            if cur == self.cfg.quote:
                fee += c
            elif cur and symbol.startswith(cur + "/"):
                fee += c * (cost / filled)  # gebyr tatt i mynten → omregn til USDT
                base_fee += c
        if fee == 0:
            fee = cost * self.cfg.taker_fee_pct / 100  # anslag hvis børsen ikke oppgir
        return Fill(filled, cost / filled, cost, fee, net_amount=max(filled - base_fee, 0.0))
