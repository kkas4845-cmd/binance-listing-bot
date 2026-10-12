"""Innstillinger med innebygde sikkerhetsgrenser.

Alle verdier leses fra config.yaml. Verdier som er utenfor de harde grensene
under blir AVVIST, slik at en skrivefeil (f.eks. 2000 i stedet for 20) ikke
kan tømme kontoen.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, asdict
from typing import Any

# --- Harde grenser (kan bare endres i koden, ikke i config) -----------------
HARD_MAX_TRADE_USDT = 500.0
HARD_MAX_DAILY_SPEND_USDT = 2000.0
HARD_MAX_OPEN_POSITIONS = 10
HARD_MAX_SLIPPAGE_PCT = 10.0
HARD_MIN_STOP_LOSS_PCT = 3.0   # tettere enn dette = utløses av vanlig støy
HARD_MAX_STOP_LOSS_PCT = 50.0

SUPPORTED_EXCHANGES = {"gate", "mexc", "kucoin", "bybit", "bitget", "htx", "poloniex", "okx"}


class ConfigError(ValueError):
    pass


@dataclass
class DetectorConfig:
    use_websocket: bool = True          # krever (lese-)API-nøkkel fra Binance
    use_polling: bool = True            # reserveløsning uten nøkkel
    poll_interval_sec: float = 5.0      # ikke sett under 3 – risiko for IP-blokk
    max_announcement_age_sec: int = 120  # eldre annonseringer ignoreres (f.eks. etter omstart)
    include_seed_tag: bool = True       # Seed Tag = Binance sin "høy risiko"-merking
    seed_tag_size_factor: float = 0.5   # kjøp halv størrelse på Seed Tag-tokens
    title_must_start_with: str = "Binance Will List"
    blocked_title_words: list[str] = field(default_factory=lambda: [
        "futures", "perpetual", "margin", "delist", "removal", "monitoring tag",
        "alpha", "pre-market", "options", "convert",
    ])


@dataclass
class EntryConfig:
    buy_amount_usdt: float = 20.0
    max_slippage_pct: float = 3.0       # betaler aldri mer enn beste ask + 3 %
    max_spread_pct: float = 2.0         # hopp over markeder med stor spread
    min_24h_volume_usdt: float = 100_000.0
    min_depth_multiple: float = 3.0     # orderbok må tåle 3x kjøpsbeløpet innen slippage
    max_chase_pct: float = 25.0         # har prisen steget > 25 % siden annonsering: for sent
    name_match: str = "strict"          # strict | warn | off  (ticker-forveksling)


@dataclass
class ExitConfig:
    stop_loss_pct: float = 10.0
    trailing_activation_pct: float = 8.0
    trailing_distance_pct: float = 6.0
    take_profit_pct: float = 0.0        # 0 = av. F.eks. 100 = selg alt ved +100 %
    max_hold_minutes: int = 720
    sell_after_binance_open_minutes: int = 10  # -1 = av
    max_sell_slippage_pct: float = 5.0
    check_interval_sec: float = 2.0


@dataclass
class RiskConfig:
    max_open_positions: int = 3
    max_daily_spend_usdt: float = 65.0  # 3 kjøp à 20 + gebyr
    daily_loss_limit_usdt: float = 30.0
    max_consecutive_losses: int = 3
    pause_hours_after_losses: int = 24
    ticker_cooldown_days: int = 30
    kill_switch_file: str = "STOP"


@dataclass
class Config:
    mode: str = "paper"                 # paper | live
    live_trading_confirmed: bool = False
    exchange: str = "gate"
    quote: str = "USDT"
    taker_fee_pct: float = 0.2          # brukes i paper mode
    database: str = "bot.db"
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    entry: EntryConfig = field(default_factory=EntryConfig)
    exit: ExitConfig = field(default_factory=ExitConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    # Hemmeligheter fra .env (aldri i config.yaml)
    @property
    def exchange_api_key(self) -> str:
        return os.getenv("EXCHANGE_API_KEY", "")

    @property
    def exchange_api_secret(self) -> str:
        return os.getenv("EXCHANGE_API_SECRET", "")

    @property
    def exchange_api_password(self) -> str:
        return os.getenv("EXCHANGE_API_PASSWORD", "")  # KuCoin/OKX/Bitget passphrase

    @property
    def binance_api_key(self) -> str:
        return os.getenv("BINANCE_API_KEY", "")

    @property
    def binance_api_secret(self) -> str:
        return os.getenv("BINANCE_API_SECRET", "")

    @property
    def is_live(self) -> bool:
        return self.mode == "live" and self.live_trading_confirmed

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fill(cls, data: dict[str, Any] | None):
    data = data or {}
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"Ukjente innstillinger i {cls.__name__}: {sorted(unknown)}")
    return cls(**data)


def from_dict(data: dict[str, Any]) -> Config:
    data = dict(data or {})
    sub = {
        "detector": _fill(DetectorConfig, data.pop("detector", None)),
        "entry": _fill(EntryConfig, data.pop("entry", None)),
        "exit": _fill(ExitConfig, data.pop("exit", None)),
        "risk": _fill(RiskConfig, data.pop("risk", None)),
    }
    cfg = _fill(Config, data)
    for k, v in sub.items():
        setattr(cfg, k, v)
    validate(cfg)
    return cfg


def load(path: str) -> Config:
    try:
        import yaml  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ConfigError("PyYAML mangler. Kjør: pip install -r requirements.txt") from e
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    if not os.path.exists(path):
        raise ConfigError(f"Fant ikke {path}. Kopier config.example.yaml til {path} først.")
    with open(path, encoding="utf-8") as f:
        return from_dict(yaml.safe_load(f) or {})


def validate(cfg: Config) -> None:
    errs: list[str] = []
    e, x, r, d = cfg.entry, cfg.exit, cfg.risk, cfg.detector

    if cfg.mode not in ("paper", "live"):
        errs.append("mode må være 'paper' eller 'live'")
    if cfg.exchange not in SUPPORTED_EXCHANGES:
        errs.append(f"exchange må være en av {sorted(SUPPORTED_EXCHANGES)}")
    if cfg.exchange == "binance":
        errs.append("Kjøpsbørsen kan ikke være Binance – mynten finnes ikke der ennå")

    if not 0 < e.buy_amount_usdt <= HARD_MAX_TRADE_USDT:
        errs.append(f"entry.buy_amount_usdt må være mellom 0 og {HARD_MAX_TRADE_USDT}")
    if not 0 < e.max_slippage_pct <= HARD_MAX_SLIPPAGE_PCT:
        errs.append(f"entry.max_slippage_pct må være mellom 0 og {HARD_MAX_SLIPPAGE_PCT}")
    if e.max_spread_pct <= 0:
        errs.append("entry.max_spread_pct må være > 0")
    if e.min_depth_multiple < 1:
        errs.append("entry.min_depth_multiple må være minst 1")
    if e.name_match not in ("strict", "warn", "off"):
        errs.append("entry.name_match må være strict, warn eller off")

    if not HARD_MIN_STOP_LOSS_PCT <= x.stop_loss_pct <= HARD_MAX_STOP_LOSS_PCT:
        errs.append(f"exit.stop_loss_pct må være mellom {HARD_MIN_STOP_LOSS_PCT} og {HARD_MAX_STOP_LOSS_PCT}")
    if x.trailing_distance_pct <= 0 or x.trailing_activation_pct <= 0:
        errs.append("exit.trailing_* må være > 0")
    if x.trailing_distance_pct >= x.trailing_activation_pct + x.stop_loss_pct:
        errs.append("exit.trailing_distance_pct er så stor at trailing stop aldri gir mening")
    if x.max_hold_minutes <= 0:
        errs.append("exit.max_hold_minutes må være > 0")

    if not 1 <= r.max_open_positions <= HARD_MAX_OPEN_POSITIONS:
        errs.append(f"risk.max_open_positions må være 1–{HARD_MAX_OPEN_POSITIONS}")
    if not 0 < r.max_daily_spend_usdt <= HARD_MAX_DAILY_SPEND_USDT:
        errs.append(f"risk.max_daily_spend_usdt må være mellom 0 og {HARD_MAX_DAILY_SPEND_USDT}")
    if r.max_daily_spend_usdt < e.buy_amount_usdt:
        errs.append("risk.max_daily_spend_usdt er lavere enn ett kjøp")
    if r.daily_loss_limit_usdt <= 0:
        errs.append("risk.daily_loss_limit_usdt må være > 0")

    if d.poll_interval_sec < 3:
        errs.append("detector.poll_interval_sec under 3 sek gir stor risiko for IP-blokk fra Binance")
    if not 0 < d.seed_tag_size_factor <= 1:
        errs.append("detector.seed_tag_size_factor må være mellom 0 og 1")

    if cfg.mode == "live" and not cfg.live_trading_confirmed:
        errs.append("mode: live krever også live_trading_confirmed: true (bevisst dobbel bekreftelse)")

    if errs:
        raise ConfigError("Ugyldig konfigurasjon:\n  - " + "\n  - ".join(errs))
