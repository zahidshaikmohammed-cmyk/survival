import unittest
from datetime import datetime, timedelta, timezone

from survival_engine.config import Config
from survival_engine.data import parse_candles, validate_candles
from survival_engine.mathx import pearson
from survival_engine.models import Candle, Features, Stock
from survival_engine.selector import select_top3

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


class SurvivalTests(unittest.TestCase):
    def test_candle_validation_accepts_valid_series(self):
        candles = make_candles(100)
        ok, reason = validate_candles(candles, datetime(2026, 9, 16, 11, 0, tzinfo=IST), 70)
        self.assertTrue(ok, reason)

    def test_candle_validation_rejects_duplicate_timestamp(self):
        candles = make_candles(100)
        candles[50] = candles[49]
        ok, reason = validate_candles(candles, datetime(2026, 9, 16, 11, 0, tzinfo=IST), 70)
        self.assertFalse(ok)
        self.assertIn("duplicate", reason)

    def test_pearson_identical_vectors_is_one(self):
        self.assertAlmostEqual(pearson([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]), 1.0, places=9)

    def test_parse_candles_accepts_psygrid_schema(self):
        rows = [{"timestamp": "2026-09-16 09:16:00 IST", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10}]
        parsed = parse_candles(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].close, 100.5)

    def test_selector_returns_three(self):
        candles = make_candles(100)
        stocks = [Stock(f"S{i}", str(i), 100, 100, candles, "a") for i in range(4)]
        fs = []
        for i in range(4):
            fs.append(Features(f"S{i}", "LONG", 80-i, "A", 100, .01, .02, .03, .04, 10, 20, 30, 0, .01, 0, 0, .01, .001, 1.5, .8, .8, .1, .1, .8, .5, "CONTINUATION", [], [], 1, 101, 99, 102, 1.0, 2.0, "13:15 IST"))
        selected = select_top3(fs, stocks, Config())
        self.assertEqual(len(selected), 3)


if __name__ == "__main__":
    unittest.main()
