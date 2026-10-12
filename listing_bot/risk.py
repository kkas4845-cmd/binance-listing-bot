"""Risikosperrer som MÅ passere før hvert eneste kjøp."""
from __future__ import annotations

import os

from .config import Config
from .store import Store, now_ms, utc_day_start_ms

DAY_MS = 86_400_000
HOUR_MS = 3_600_000


def check_can_buy(cfg: Config, store: Store, ticker: str, amount_usdt: float,
                  ts_ms: int | None = None) -> str | None:
    """Returnerer None hvis kjøp er lov, ellers en forklaring på hvorfor ikke."""
    ts = ts_ms or now_ms()
    r = cfg.risk
    mode = cfg.mode

    if os.path.exists(r.kill_switch_file):
        return f"Nødstopp aktiv (filen '{r.kill_switch_file}' finnes). Slett den for å tillate kjøp igjen."

    if store.bought_ticker_since(ticker, ts - r.ticker_cooldown_days * DAY_MS, mode):
        return f"{ticker} er allerede kjøpt de siste {r.ticker_cooldown_days} dagene"

    open_n = len(store.open_positions(mode))
    if open_n >= r.max_open_positions:
        return f"Maks antall åpne posisjoner nådd ({open_n}/{r.max_open_positions})"

    day0 = utc_day_start_ms(ts)
    spent = store.spent_since(day0, mode)
    if spent + amount_usdt > r.max_daily_spend_usdt:
        return f"Dagsgrense for kjøp nådd ({spent:.2f} + {amount_usdt:.2f} > {r.max_daily_spend_usdt:.2f} USDT)"

    pnl_today = store.realized_pnl_since(day0, mode)
    if pnl_today <= -r.daily_loss_limit_usdt:
        return f"Daglig tapsgrense nådd ({pnl_today:.2f} USDT). Ingen nye kjøp før neste døgn (UTC)."

    recent = store.recent_closed(mode, r.max_consecutive_losses)
    if (len(recent) == r.max_consecutive_losses and all((p.pnl or 0) < 0 for p in recent)):
        last_close = recent[0].closed_ms or 0
        until = last_close + r.pause_hours_after_losses * HOUR_MS
        if ts < until:
            hrs = (until - ts) / HOUR_MS
            return f"{r.max_consecutive_losses} tap på rad – pause i {hrs:.1f} timer til"

    return None
