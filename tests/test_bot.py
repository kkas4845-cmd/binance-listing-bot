"""Tester som kjører uten nett og uten ccxt:  python -m pytest  (eller python -m unittest)"""
import asyncio
import json
import os
import tempfile
import unittest

from listing_bot import config as C
from listing_bot import exits, risk
from listing_bot.app import App
from listing_bot.detector import parse_list_response, parse_ws_message, signed_ws_url, ws_query_string
from listing_bot.market import Fill, PreTradeResult, spread_pct, walk_book
from listing_bot.parser import Announcement, names_match, parse, parse_open_time_ms
from listing_bot.store import Store, now_ms

D = C.DetectorConfig()


def P(title, body=""):
    return parse(Announcement(id="x", title=title, body=body), must_start_with=D.title_must_start_with,
                 blocked_words=D.blocked_title_words, include_seed_tag=True)


class TestParser(unittest.TestCase):
    def test_single(self):
        s = P("Binance Will List Magic Eden (ME)")
        self.assertEqual([(t.name, t.ticker) for t in s.tokens], [("Magic Eden", "ME")])
        self.assertFalse(s.seed_tag)

    def test_seed_tag(self):
        s = P("Binance Will List Movement (MOVE) with Seed Tag Applied")
        self.assertEqual(s.tokens[0].ticker, "MOVE")
        self.assertTrue(s.seed_tag)

    def test_multiple(self):
        s = P("Binance Will List Foo Protocol (FOO), Bar (BAR) and Baz Network (BAZ)")
        self.assertEqual([t.ticker for t in s.tokens], ["FOO", "BAR", "BAZ"])
        self.assertEqual(s.tokens[2].name, "Baz Network")

    def test_ignored(self):
        for t in ["Binance Futures Will Launch USDⓈ-Margined FOO Perpetual Contract",
                  "Binance Will Delist FOO (FOO) on 2026-10-20",
                  "Binance Will Add FOO (FOO) on Earn, Convert & Margin",
                  "Binance Will List FOO (FOO) on Binance Alpha",
                  "Binance Will List USDT (USDT) Margin Pairs",
                  "Binance Will List FOO (FOO) Perpetual Contract",
                  "Introducing Foo (FOO) on Binance HODLer Airdrops!"]:
            self.assertIsNone(P(t), t)

    def test_no_stablecoin(self):
        self.assertIsNone(P("Binance Will List First Digital USD (FDUSD)"))

    def test_open_time(self):
        body = "Binance will list Foo (FOO) and open trading for FOO/USDT at 2026-10-13 10:00 (UTC)."
        ms = parse_open_time_ms(body)
        self.assertEqual(ms, 1791885600000)
        self.assertEqual(P("Binance Will List Foo (FOO)", body).binance_open_ms, ms)

    def test_name_match(self):
        self.assertTrue(names_match("Magic Eden", "MagicEden"))
        self.assertTrue(names_match("Movement", "Movement Network"))
        self.assertFalse(names_match("Magic Eden", "Mecha Engine Token"))
        self.assertIsNone(names_match("Foo", None))


class TestExits(unittest.TestCase):
    X = C.ExitConfig(stop_loss_pct=10, trailing_activation_pct=8, trailing_distance_pct=6,
                     max_hold_minutes=60, sell_after_binance_open_minutes=10)

    def d(self, bid, peak=100.0, opened=0, now=1000, open_ms=None):
        return exits.decide(entry_price=100, peak_price=peak, bid=bid, opened_ms=opened, now_ms=now,
                            binance_open_ms=open_ms, cfg=self.X)

    def test_hold(self):
        self.assertIsNone(self.d(95).reason)

    def test_stop_loss(self):
        self.assertEqual(self.d(89.9).reason, "stop_loss")

    def test_trailing_not_active_below_activation(self):
        r = self.d(101, peak=107)  # topp +7 % < 8 %
        self.assertIsNone(r.reason)

    def test_trailing(self):
        r = self.d(112, peak=120)  # stopp = 120*0.94 = 112.8
        self.assertEqual(r.reason, "trailing_stop")
        self.assertGreater(r.stop_price, 100)

    def test_peak_updates(self):
        self.assertEqual(self.d(130, peak=120).new_peak, 130)

    def test_max_hold(self):
        self.assertEqual(self.d(101, now=61 * 60_000).reason, "max_hold_time")

    def test_binance_open(self):
        self.assertEqual(self.d(101, now=20 * 60_000, open_ms=5 * 60_000).reason, "binance_open")
        self.assertIsNone(self.d(101, now=10 * 60_000, open_ms=5 * 60_000).reason)


class TestBook(unittest.TestCase):
    asks = [[1.00, 10], [1.02, 10], [1.05, 100]]

    def test_walk_buy_limit(self):
        amt, cost = walk_book(self.asks, limit_price=1.03, side="buy")
        self.assertAlmostEqual(amt, 20)
        self.assertAlmostEqual(cost, 20.2)

    def test_walk_buy_max_cost(self):
        amt, cost = walk_book(self.asks, limit_price=1.03, side="buy", max_cost=15)
        self.assertAlmostEqual(cost, 15)

    def test_walk_sell(self):
        bids = [[0.99, 5], [0.95, 5], [0.80, 100]]
        amt, cost = walk_book(bids, limit_price=0.94, side="sell", max_amount=8)
        self.assertAlmostEqual(amt, 8)
        self.assertAlmostEqual(cost, 5 * 0.99 + 3 * 0.95)

    def test_spread(self):
        self.assertAlmostEqual(spread_pct(99, 101), 2.0)


class TestConfig(unittest.TestCase):
    def test_defaults_ok(self):
        C.validate(C.Config())

    def test_rejects_huge_amount(self):
        with self.assertRaises(C.ConfigError):
            C.from_dict({"entry": {"buy_amount_usdt": 2000}})

    def test_rejects_tight_stop(self):
        with self.assertRaises(C.ConfigError):
            C.from_dict({"exit": {"stop_loss_pct": 1}})

    def test_live_needs_confirmation(self):
        with self.assertRaises(C.ConfigError):
            C.from_dict({"mode": "live"})
        cfg = C.from_dict({"mode": "live", "live_trading_confirmed": True})
        self.assertTrue(cfg.is_live)

    def test_unknown_key(self):
        with self.assertRaises(C.ConfigError):
            C.from_dict({"entry": {"buyamount": 5}})

    def test_fast_polling_rejected(self):
        with self.assertRaises(C.ConfigError):
            C.from_dict({"detector": {"poll_interval_sec": 1}})


class TestDetector(unittest.TestCase):
    def test_ws_message(self):
        inner = {"catalogId": 48, "catalogName": "New Cryptocurrency Listing", "publishDate": 1700000000000,
                 "title": "Binance Will List Foo (FOO)", "body": "...", "disclaimer": ""}
        raw = json.dumps({"type": "DATA", "topic": "com_announcement_en", "data": json.dumps(inner)})
        a = parse_ws_message(raw)
        self.assertEqual(a.title, "Binance Will List Foo (FOO)")
        self.assertEqual(a.publish_ms, 1700000000000)
        self.assertIsNone(parse_ws_message('{"type":"COMMAND","data":"SUCCESS"}'))

    def test_same_id_from_both_sources(self):
        inner = {"title": "Binance Will List Foo (FOO)", "publishDate": 1}
        ws = parse_ws_message(json.dumps({"type": "DATA", "topic": "com_announcement_en", "data": json.dumps(inner)}))
        poll = parse_list_response({"data": {"catalogs": [{"catalogName": "New Cryptocurrency Listing",
                                                            "articles": [{"title": "Binance Will List Foo (FOO) ",
                                                                          "releaseDate": 1}]}]}})
        self.assertEqual(ws.id, poll[0].id)

    def test_signature(self):
        url = signed_ws_url("k", "s", ts_ms=1, rnd="abc")
        q = ws_query_string(url)
        self.assertEqual(q["topic"], "com_announcement_en")
        self.assertEqual(len(q["signature"]), 64)


# ---------------------------------------------------------------- ende-til-ende med falsk børs
class FakeMarket:
    def __init__(self, bid=1.0, ask=1.01, ok=True, reason=""):
        self.bid, self.ask, self.ok, self.reason = bid, ask, ok, reason
        self.buys = []
        self.sells = []

    async def connect(self): pass
    async def close(self): pass

    async def pre_trade_checks(self, ticker, name, amount, announce_ms):
        if not self.ok:
            return PreTradeResult(False, self.reason)
        return PreTradeResult(True, "", f"{ticker}/USDT", self.ask * 1.03, amount / (self.ask * 1.03), self.ask)

    async def buy(self, pre, amount):
        self.buys.append((pre.symbol, amount))
        amt = amount / self.ask
        return Fill(amt, self.ask, amount, amount * 0.002)

    async def best_bid_ask(self, symbol):
        return self.bid, self.ask, {"bids": [[self.bid, 1e9]], "asks": [[self.ask, 1e9]]}

    async def sell(self, symbol, amount):
        self.sells.append((symbol, amount))
        return Fill(amount, self.bid, amount * self.bid, amount * self.bid * 0.002)


class TestApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.cfg = C.from_dict({"database": "t.db"})
        self.app = App(self.cfg)
        self.fm = FakeMarket()
        self.app.market = self.fm

    def tearDown(self):
        self.app.store.db.close()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def ann(self, title, age_s=1, aid=None):
        return Announcement(id=aid or title, title=title, publish_ms=now_ms() - age_s * 1000, source="websocket")

    def run_(self, coro):
        return asyncio.run(coro)

    def test_buys_fresh_listing_once(self):
        a = self.ann("Binance Will List Foo (FOO)")
        self.run_(self.app.handle_announcement(a))
        self.run_(self.app.handle_announcement(a))  # duplikat
        self.assertEqual(len(self.fm.buys), 1)
        self.assertEqual(len(self.app.store.open_positions("paper")), 1)

    def test_ignores_old(self):
        self.run_(self.app.handle_announcement(self.ann("Binance Will List Foo (FOO)", age_s=600)))
        self.assertEqual(self.fm.buys, [])

    def test_seed_tag_half_size(self):
        self.run_(self.app.handle_announcement(self.ann("Binance Will List Foo (FOO) with Seed Tag Applied")))
        self.assertAlmostEqual(self.fm.buys[0][1], 10.0)

    def test_max_open_positions(self):
        self.cfg.risk.max_daily_spend_usdt = 200
        for i, t in enumerate(["AAA", "BBB", "CCC", "DDD"]):
            self.run_(self.app.handle_announcement(self.ann(f"Binance Will List Coin{i} ({t})")))
        self.assertEqual(len(self.fm.buys), 3)

    def test_kill_switch(self):
        open("STOP", "w").close()
        self.run_(self.app.handle_announcement(self.ann("Binance Will List Foo (FOO)")))
        self.assertEqual(self.fm.buys, [])

    def test_pretrade_reject(self):
        self.app.market = FakeMarket(ok=False, reason="For tynn orderbok")
        self.run_(self.app.handle_announcement(self.ann("Binance Will List Foo (FOO)")))
        self.assertEqual(self.app.store.open_positions("paper"), [])

    def test_stop_loss_closes_and_daily_loss_limit(self):
        cfg = C.from_dict({"database": "t2.db", "risk": {"daily_loss_limit_usdt": 1.5, "max_daily_spend_usdt": 200}})
        app = App(cfg)
        fm = FakeMarket(bid=1.0, ask=1.0)
        app.market = fm
        self.run_(app.handle_announcement(self.ann("Binance Will List Foo (FOO)")))
        fm.bid = 0.85  # -15 % -> stop loss
        pos = app.store.open_positions("paper")[0]
        self.run_(app.check_exit(pos))
        self.assertEqual(app.store.open_positions("paper"), [])
        closed = app.store.all_positions()[0]
        self.assertEqual(closed.exit_reason, "stop_loss")
        self.assertLess(closed.pnl, -2.9)
        # Tapsgrensen (1.5) er nådd -> neste listing kjøpes ikke
        self.assertIsNotNone(risk.check_can_buy(cfg, app.store, "BAR", 20))
        app.store.db.close()

    def test_daily_spend_limit(self):
        cfg = C.from_dict({"database": "t3.db", "risk": {"max_daily_spend_usdt": 30}})
        app = App(cfg)
        app.market = FakeMarket()
        self.run_(app.handle_announcement(self.ann("Binance Will List Foo (FOO)")))
        self.run_(app.handle_announcement(self.ann("Binance Will List Bar (BAR)")))
        self.assertEqual(len(app.market.buys), 1)
        app.store.db.close()

    def test_export(self):
        self.run_(self.app.handle_announcement(self.ann("Binance Will List Foo (FOO)")))
        n = self.app.store.export_csv("x.csv")
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
