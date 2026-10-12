"""SQLite-lagring: sette annonseringer, posisjoner og hendelseslogg."""
from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
    id TEXT PRIMARY KEY,
    title TEXT,
    source TEXT,
    publish_ms INTEGER,
    received_ms INTEGER,
    result TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT,
    exchange TEXT,
    ticker TEXT,
    symbol TEXT,
    amount REAL,
    entry_price REAL,
    cost REAL,
    entry_fee REAL,
    opened_ms INTEGER,
    peak_price REAL,
    binance_open_ms INTEGER,
    announcement_id TEXT,
    status TEXT,            -- open | closed
    exit_price REAL,
    proceeds REAL,
    exit_fee REAL,
    closed_ms INTEGER,
    exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS events (
    ts_ms INTEGER,
    level TEXT,
    message TEXT
);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def utc_day_start_ms(ts_ms: int | None = None) -> int:
    ts = (ts_ms or now_ms()) / 1000
    d = datetime.fromtimestamp(ts, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


@dataclass
class Position:
    id: int
    mode: str
    exchange: str
    ticker: str
    symbol: str
    amount: float
    entry_price: float
    cost: float
    entry_fee: float
    opened_ms: int
    peak_price: float
    binance_open_ms: int | None
    announcement_id: str
    status: str
    exit_price: float | None = None
    proceeds: float | None = None
    exit_fee: float | None = None
    closed_ms: int | None = None
    exit_reason: str | None = None

    @property
    def pnl(self) -> float | None:
        if self.proceeds is None:
            return None
        return self.proceeds - (self.exit_fee or 0) - self.cost - self.entry_fee


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # --- annonseringer ---
    def seen(self, ann_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM announcements WHERE id=?", (ann_id,)).fetchone() is not None

    def mark_seen(self, ann_id: str, title: str, source: str, publish_ms: int, result: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO announcements VALUES (?,?,?,?,?,?)",
            (ann_id, title, source, publish_ms, now_ms(), result),
        )
        self.db.commit()

    # --- posisjoner ---
    def open_position(self, **kw) -> int:
        cols = ",".join(kw)
        q = ",".join("?" for _ in kw)
        cur = self.db.execute(f"INSERT INTO positions ({cols}, status) VALUES ({q}, 'open')", tuple(kw.values()))
        self.db.commit()
        return int(cur.lastrowid)

    def update_peak(self, pos_id: int, peak: float) -> None:
        self.db.execute("UPDATE positions SET peak_price=? WHERE id=?", (peak, pos_id))
        self.db.commit()

    def close_position(self, pos_id: int, exit_price: float, proceeds: float, exit_fee: float, reason: str) -> None:
        self.db.execute(
            "UPDATE positions SET status='closed', exit_price=?, proceeds=?, exit_fee=?, closed_ms=?, exit_reason=? WHERE id=?",
            (exit_price, proceeds, exit_fee, now_ms(), reason, pos_id),
        )
        self.db.commit()

    def reduce_position(self, pos_id: int, new_amount: float, new_cost: float, new_fee: float) -> None:
        self.db.execute("UPDATE positions SET amount=?, cost=?, entry_fee=? WHERE id=?",
                        (new_amount, new_cost, new_fee, pos_id))
        self.db.commit()

    def _rows(self, where: str = "", args: tuple = ()) -> list[Position]:
        rows = self.db.execute(f"SELECT * FROM positions {where} ORDER BY id", args).fetchall()
        return [Position(**{k: r[k] for k in r.keys()}) for r in rows]

    def open_positions(self, mode: str) -> list[Position]:
        return self._rows("WHERE status='open' AND mode=?", (mode,))

    def all_positions(self) -> list[Position]:
        return self._rows()

    def bought_ticker_since(self, ticker: str, since_ms: int, mode: str) -> bool:
        r = self.db.execute("SELECT 1 FROM positions WHERE ticker=? AND opened_ms>=? AND mode=?",
                            (ticker, since_ms, mode)).fetchone()
        return r is not None

    def spent_since(self, since_ms: int, mode: str) -> float:
        r = self.db.execute("SELECT COALESCE(SUM(cost+entry_fee),0) FROM positions WHERE opened_ms>=? AND mode=?",
                            (since_ms, mode)).fetchone()
        return float(r[0])

    def realized_pnl_since(self, since_ms: int, mode: str) -> float:
        return sum(p.pnl or 0 for p in self._rows("WHERE status='closed' AND closed_ms>=? AND mode=?", (since_ms, mode)))

    def recent_closed(self, mode: str, n: int) -> list[Position]:
        rows = self._rows("WHERE status='closed' AND mode=?", (mode,))
        rows.sort(key=lambda p: p.closed_ms or 0, reverse=True)
        return rows[:n]

    # --- logg ---
    def log(self, level: str, message: str) -> None:
        self.db.execute("INSERT INTO events VALUES (?,?,?)", (now_ms(), level, message))
        self.db.commit()

    def export_csv(self, path: str) -> int:
        rows = self.all_positions()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["id", "modus", "børs", "ticker", "åpnet (UTC)", "mengde", "kjøpspris", "kost USDT",
                        "kjøpsgebyr", "lukket (UTC)", "salgspris", "salgssum USDT", "salgsgebyr",
                        "resultat USDT", "grunn"])
            for p in rows:
                fmt = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ms else ""
                w.writerow([p.id, p.mode, p.exchange, p.ticker, fmt(p.opened_ms), p.amount, p.entry_price, p.cost,
                            p.entry_fee, fmt(p.closed_ms), p.exit_price, p.proceeds, p.exit_fee,
                            round(p.pnl, 4) if p.pnl is not None else "", p.exit_reason or ""])
        return len(rows)
