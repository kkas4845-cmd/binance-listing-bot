"""Tolker Binance-annonseringer: er dette en ny spot-listing, og hvilke tokens?"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

TOKEN_RE = re.compile(r"([^,()]+?)\s*\(\s*([A-Z0-9]{1,15})\s*\)")
OPEN_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s*\(UTC\)")
# Tickere som aldri er "nye mynter" – stablecoins og kvote-valutaer
NEVER_BUY = {"USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "BTC", "ETH", "BNB", "EUR", "TRY", "USD1", "UTC"}


@dataclass
class Announcement:
    id: str
    title: str
    body: str = ""
    publish_ms: int = 0
    source: str = ""
    catalog: str = ""


@dataclass
class TokenRef:
    name: str
    ticker: str


@dataclass
class ListingSignal:
    announcement: Announcement
    tokens: list[TokenRef]
    seed_tag: bool = False
    binance_open_ms: int | None = None
    notes: list[str] = field(default_factory=list)


def _clean_name(raw: str) -> str:
    name = raw.strip(" .:-")
    name = re.sub(r"^(and|&)\s+", "", name, flags=re.I)
    return name.strip()


def parse_open_time_ms(text: str) -> int | None:
    m = OPEN_TIME_RE.search(text or "")
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def parse(ann: Announcement, *, must_start_with: str, blocked_words: list[str],
          include_seed_tag: bool) -> ListingSignal | None:
    """Returnerer et signal bare for ekte nye spot-listings. Alt annet -> None."""
    title = (ann.title or "").strip()
    if not title.lower().startswith(must_start_with.lower()):
        return None
    low = title.lower()
    for w in blocked_words:
        if w.lower() in low:
            return None
    if ann.catalog and "listing" not in ann.catalog.lower():
        return None

    seed = "seed tag" in low
    if seed and not include_seed_tag:
        return None

    rest = title[len(must_start_with):]
    # Kutt "with Seed Tag Applied" o.l. etter siste parentes
    tokens: list[TokenRef] = []
    seen = set()
    for raw_name, ticker in TOKEN_RE.findall(rest):
        if ticker in NEVER_BUY or ticker in seen:
            continue
        name = _clean_name(raw_name)
        if not name:
            continue
        seen.add(ticker)
        tokens.append(TokenRef(name=name, ticker=ticker))
    if not tokens:
        return None

    return ListingSignal(
        announcement=ann,
        tokens=tokens,
        seed_tag=seed,
        binance_open_ms=parse_open_time_ms(ann.body) or parse_open_time_ms(title),
    )


_STOPWORDS = {"token", "tokens", "coin", "protocol", "network", "finance", "the", "labs",
              "foundation", "dao", "chain", "ai", "app", "official", "new"}


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _STOPWORDS}


def names_match(announced: str, exchange_name: str | None) -> bool | None:
    """True/False hvis vi kan avgjøre, None hvis børsen ikke oppgir navn.

    Beskytter mot ticker-forveksling: samme ticker kan være en helt annen mynt
    på en annen børs.
    """
    if not exchange_name:
        return None
    a_compact = re.sub(r"[^a-z0-9]", "", announced.lower())
    b_compact = re.sub(r"[^a-z0-9]", "", exchange_name.lower())
    if a_compact and b_compact and (a_compact in b_compact or b_compact in a_compact):
        return True
    a, b = _words(announced), _words(exchange_name)
    if not a or not b:
        return False
    overlap = len(a & b) / min(len(a), len(b))
    return overlap >= 0.5
