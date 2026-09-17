import unittest
from datetime import datetime, timedelta, timezone

from survival_engine.adaptive import _stock_context
from survival_engine.models import Candle, Stock

IST = timezone(timedelta(hours=5, minutes=30))


def make_stock(direction: int) -> Stock:
    start = datetime(2026, 9, 17, 9, 15, tzinfo=IST)
    candles = []
    price = 100.0
    for i in range(70):
        step = 0.18 if direction > 0 else -0.18
        close = price + step
        candles.append(Candle(start + timedelta(minutes=i), price, max(price, close) + 0.04, min(price, close) - 0.04, close, 5000 + i * 10))
        price = close
    return Stock("TEST", "1", 100.0, 100.0, candles, "stocks")


class DirectionalIntelligenceTests(unittest.TestCase):
    def test_uptrend_supports_long(self):
        integrity, context = _stock_context(make_stock(1), 1)
        self.assertGreater(integrity, 0.70)
        self.assertGreaterEqual(context["agreement"], 0.75)
        self.assertGreaterEqual(context["ema"], 1.0)
        self.assertGreaterEqual(context["vwap"], 1.0)

    def test_uptrend_disagrees_with_short(self):
        integrity, context = _stock_context(make_stock(1), -1)
        self.assertLess(integrity, 0.35)
        self.assertLessEqual(context["agreement"], 0.25)
        self.assertEqual(context["ema"], 0.0)
        self.assertEqual(context["vwap"], 0.0)

    def test_downtrend_supports_short(self):
        integrity, context = _stock_context(make_stock(-1), -1)
        self.assertGreater(integrity, 0.70)
        self.assertGreaterEqual(context["agreement"], 0.75)

    def test_opening_range_is_directional_context(self):
        integrity, context = _stock_context(make_stock(1), 1)
        self.assertEqual(context["opening_range"], 1.0)


if __name__ == "__main__":
    unittest.main()
