import unittest
from datetime import datetime, timedelta, timezone

from survival_engine.config import Config, STOCK_ENDPOINT
from survival_engine.data import FetchResult, assemble_universe, parse_candles, parse_stock_payload
from survival_engine.mathx import pearson
from survival_engine.models import Candle, Features, Stock
from survival_engine.selector import select_top3
from survival_engine.strategy import score_universe

IST = timezone(timedelta(hours=5, minutes=30))


def make_candles(start_price: float, direction: float = 1.0, n: int = 100):
    start = datetime(2026, 9, 16, 9, 16, tzinfo=IST)
    out = []
    price = start_price
    for i in range(n):
        o = price
        c = price + direction * 0.5
        h = max(o, c) + 0.1
        l = min(o, c) - 0.1
        out.append(Candle(start + timedelta(minutes=i), o, h, l, c, 2000 + i))
        price = c
    return out


def make_universe_payload(count: int = 450) -> dict:
    stocks = {}
    for i in range(count):
        symbol = f"S{i:03d}"
        stocks[symbol] = {
            "symbol": symbol,
            "security_id": str(i),
            "previous_close": 100.0 + i,
            "today_open": 100.0 + i,
            "candles_1m": [
                {
                    "timestamp": (datetime(2026, 9, 17, 9, 15, tzinfo=IST) + timedelta(minutes=j)).strftime("%Y-%m-%d %H:%M:%S IST"),
                    "open": 100.0 + i + j * 0.1,
                    "high": 100.2 + i + j * 0.1,
                    "low": 99.8 + i + j * 0.1,
                    "close": 100.1 + i + j * 0.1,
                    "volume": 2000 + j,
                }
                for j in range(40)
            ],
        }
    return {
        "service": "PSYGRID",
        "schema_version": "4.0",
        "status": "OK",
        "session": {
            "status": "LIVE",
            "date": "2026-09-17",
            "timezone": "Asia/Kolkata",
        },
        "universe_size": count,
        "stock_count": count,
        "data_policy": "1M_OHLCV_PLUS_PREVIOUS_CLOSE_AND_TODAY_OPEN",
        "synthetic_candles": False,
        "stocks": stocks,
    }


class SurvivalTests(unittest.TestCase):
    def test_single_endpoint_is_the_only_stock_source(self):
        self.assertEqual(STOCK_ENDPOINT, "http://140.245.226.102:10000/public/live.json")
        self.assertEqual(Config().expected_universe, 450)
        self.assertFalse(hasattr(Config(), "expected_shards"))
        self.assertFalse(hasattr(Config(), "expected_stocks_per_shard"))

    def test_parse_candles_accepts_psygrid_schema(self):
        rows = [{"timestamp": "2026-09-16 09:16:00 IST", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10}]
        parsed = parse_candles(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].close, 100.5)

    def test_parse_candles_keeps_old_candles_without_stale_gate(self):
        rows = [{"timestamp": "2026-09-16 09:16:00 IST", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10}]
        parsed = parse_candles(rows)
        self.assertEqual(len(parsed), 1)

    def test_single_payload_parses_all_450_stocks(self):
        result = FetchResult("stocks", STOCK_ENDPOINT, make_universe_payload(450), None, 1.0, 200)
        stocks = parse_stock_payload(result)
        self.assertEqual(len(stocks), 450)
        self.assertEqual(len(assemble_universe(result)), 450)

    def test_strategy_scores_full_450_stock_universe_without_exception(self):
        payload = make_universe_payload(450)
        result = FetchResult("stocks", STOCK_ENDPOINT, payload, None, 1.0, 200)
        stocks = assemble_universe(result)
        scored = score_universe(stocks, {}, Config())
        self.assertEqual(len(stocks), 450)
        self.assertEqual(len(scored), 450)
        self.assertTrue(all(0.0 <= item.score <= 100.0 for item in scored))
        self.assertTrue(all(item.direction in {"LONG", "SHORT"} for item in scored))
        self.assertTrue(all(item.setup in {"CONTINUATION", "RANGE_REJECTION"} for item in scored))
        self.assertTrue(all(item.stop != item.entry for item in scored))
        self.assertTrue(all(item.target != item.entry for item in scored))

    def test_strategy_scores_small_synthetic_universe_without_exception(self):
        stocks = [Stock(f"S{i}", str(i), 100, 100, make_candles(100 + i), "stocks") for i in range(10)]
        scored = score_universe(stocks, {}, Config())
        self.assertEqual(len(scored), 10)
        self.assertTrue(all(0.0 <= item.score <= 100.0 for item in scored))
        self.assertTrue(all(item.direction in {"LONG", "SHORT"} for item in scored))
        self.assertTrue(all(item.setup in {"CONTINUATION", "RANGE_REJECTION"} for item in scored))
        self.assertTrue(all(item.stop != item.entry for item in scored))
        self.assertTrue(all(item.target != item.entry for item in scored))

    def test_selector_returns_three(self):
        candles = make_candles(100)
        stocks = [Stock(f"S{i}", str(i), 100, 100, candles, "stocks") for i in range(4)]
        fs = []
        for i in range(4):
            fs.append(Features(f"S{i}", "LONG", 80-i, "A", 100, .01, .02, .03, .04, 10, 20, 30, 0, .01, 0, 0, .01, .001, 1.5, .8, .8, .1, .1, .8, .5, "CONTINUATION", [], [], 1, 101, 99, 102, 1.0, 2.0, "13:15 IST"))
        selected = select_top3(fs, stocks, Config())
        self.assertEqual(len(selected), 3)

    def test_selector_orders_by_adjusted_strategy_score(self):
        candles = make_candles(100)
        stocks = [Stock(f"S{i}", str(i), 100, 100, candles, "stocks") for i in range(4)]
        fs = []
        for i in range(4):
            fs.append(Features(f"S{i}", "LONG", 90-i*5, "A", 100, .01, .02, .03, .04, 10, 20, 30, 0, .01, 0, 0, .01, .001, 1.5, .8, .8, .1, .1, .8, .5, "CONTINUATION", [], [], 1, 101, 99, 102, 1.0, 2.0, "13:15 IST"))
        selected = select_top3(fs, stocks, Config())
        self.assertEqual([x.symbol for x in selected], ["S0", "S1", "S2"])


if __name__ == "__main__":
    unittest.main()
