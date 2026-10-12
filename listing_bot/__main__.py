"""Kommandolinje.

  python -m listing_bot run                 # start boten
  python -m listing_bot check               # test oppsett og børstilkobling
  python -m listing_bot simulate "Binance Will List Foo (FOO)"   # øv i paper mode
  python -m listing_bot status              # åpne posisjoner og resultat
  python -m listing_bot export trades.csv   # alle handler til CSV (skattemeldingen)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from . import config as config_mod
from .parser import Announcement, parse
from .store import Store, now_ms


def setup_logging(verbose: bool) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    os.makedirs("logs", exist_ok=True)
    fh = RotatingFileHandler("logs/bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    for noisy in ("websockets", "aiohttp", "ccxt"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def cmd_check(cfg) -> int:
    from .market import Market
    print(f"Modus: {'LIVE' if cfg.is_live else 'paper'} | Børs: {cfg.exchange} | Kvote: {cfg.quote}")
    print(f"Binance WebSocket-nøkkel: {'ja' if cfg.binance_api_key else 'nei (bruker bare polling)'}")
    print(f"Børs-nøkkel: {'ja' if cfg.exchange_api_key else 'nei'}")
    print(f"Telegram: {'ja' if os.getenv('TELEGRAM_BOT_TOKEN') else 'nei'}")
    m = Market(cfg)
    try:
        await m.connect()
        sym = f"BTC/{cfg.quote}"
        bid, ask, _ = await m.best_bid_ask(sym)
        print(f"✅ Tilkobling OK – {sym} bid {bid} / ask {ask}")
        if cfg.exchange_api_key:
            print(f"✅ Saldo {cfg.quote}: {await m.free_quote_balance():.2f}")
        named = sum(1 for c in (m.ex.currencies or {}) if m.exchange_name_of(c))
        print(f"Fulle myntnavn tilgjengelig for {named} av {len(m.ex.currencies or {})} mynter "
              f"(brukes mot ticker-forveksling)")
    finally:
        await m.close()
    return 0


async def cmd_run(cfg) -> int:
    from .app import App
    await App(cfg).run()
    return 0


async def cmd_simulate(cfg, title: str, body: str, watch_minutes: float) -> int:
    from .app import App
    if cfg.is_live:
        print("simulate er bare tillatt i paper mode.")
        return 2
    cfg.database = "simulate.db"  # egen database, så øving ikke blandes med ekte drift
    app = App(cfg)
    await app.market.connect()
    try:
        ann = Announcement(id=f"sim:{now_ms()}", title=title, body=body, publish_ms=now_ms(), source="simulate")
        await app.handle_announcement(ann, force_fresh=True)
        end = now_ms() + watch_minutes * 60_000
        while now_ms() < end and app.store.open_positions(cfg.mode):
            for pos in app.store.open_positions(cfg.mode):
                await app.check_exit(pos)
            await asyncio.sleep(cfg.exit.check_interval_sec)
    finally:
        await app.market.close()
    return 0


def cmd_status(cfg) -> int:
    st = Store(cfg.database)
    rows = st.all_positions()
    if not rows:
        print("Ingen handler ennå.")
        return 0
    total = 0.0
    for p in rows:
        pnl = p.pnl
        total += pnl or 0
        state = f"{p.exit_reason} {pnl:+.2f}" if p.status == "closed" else "ÅPEN"
        print(f"#{p.id:<4} {p.mode:<5} {p.ticker:<8} kost {p.cost:8.2f}  inn {p.entry_price:.6g}  {state}")
    print(f"Realisert resultat totalt: {total:+.2f} {cfg.quote}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="listing_bot")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("check")
    sub.add_parser("status")
    pe = sub.add_parser("export")
    pe.add_argument("path", nargs="?", default="trades.csv")
    ps = sub.add_parser("simulate")
    ps.add_argument("title")
    ps.add_argument("--body", default="")
    ps.add_argument("--watch-minutes", type=float, default=0)
    pp = sub.add_parser("parse", help="Test hvordan en tittel tolkes (ingen nett)")
    pp.add_argument("title")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as e:
        print(e)
        return 2

    if args.cmd == "parse":
        d = cfg.detector
        sig = parse(Announcement(id="x", title=args.title, publish_ms=now_ms()),
                    must_start_with=d.title_must_start_with, blocked_words=d.blocked_title_words,
                    include_seed_tag=d.include_seed_tag)
        print("Ikke en ny spot-listing (ignoreres)" if not sig else
              f"Tokens: {[(t.name, t.ticker) for t in sig.tokens]}  Seed Tag: {sig.seed_tag}")
        return 0
    if args.cmd == "status":
        return cmd_status(cfg)
    if args.cmd == "export":
        n = Store(cfg.database).export_csv(args.path)
        print(f"Skrev {n} handler til {args.path}")
        return 0
    try:
        if args.cmd == "check":
            return asyncio.run(cmd_check(cfg))
        if args.cmd == "simulate":
            return asyncio.run(cmd_simulate(cfg, args.title, args.body, args.watch_minutes))
        if args.cmd == "run":
            return asyncio.run(cmd_run(cfg))
    except KeyboardInterrupt:
        print("\nStoppet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
