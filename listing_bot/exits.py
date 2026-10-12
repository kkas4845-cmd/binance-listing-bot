"""Salgslogikk – rene funksjoner, lett å teste.

Prisen som brukes er BESTE BUD (det du faktisk får ved salg), ikke siste handel.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import ExitConfig

MIN_MS = 60_000


@dataclass
class ExitDecision:
    reason: str | None
    new_peak: float
    stop_price: float


def decide(*, entry_price: float, peak_price: float, bid: float, opened_ms: int, now_ms: int,
           binance_open_ms: int | None, cfg: ExitConfig) -> ExitDecision:
    peak = max(peak_price or entry_price, bid)
    hard_stop = entry_price * (1 - cfg.stop_loss_pct / 100)
    stop = hard_stop

    gain_at_peak = peak / entry_price - 1
    if gain_at_peak * 100 >= cfg.trailing_activation_pct:
        trail = peak * (1 - cfg.trailing_distance_pct / 100)
        stop = max(stop, trail)

    pnl_pct = (bid / entry_price - 1) * 100

    if bid <= stop:
        reason = "trailing_stop" if stop > hard_stop else "stop_loss"
        return ExitDecision(reason, peak, stop)
    if cfg.take_profit_pct > 0 and pnl_pct >= cfg.take_profit_pct:
        return ExitDecision("take_profit", peak, stop)
    if now_ms - opened_ms >= cfg.max_hold_minutes * MIN_MS:
        return ExitDecision("max_hold_time", peak, stop)
    if (binance_open_ms and cfg.sell_after_binance_open_minutes >= 0
            and now_ms >= binance_open_ms + cfg.sell_after_binance_open_minutes * MIN_MS):
        return ExitDecision("binance_open", peak, stop)
    return ExitDecision(None, peak, stop)
