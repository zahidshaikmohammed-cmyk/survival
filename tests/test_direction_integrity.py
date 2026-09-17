import unittest
from datetime import datetime, timedelta, timezone

from survival_engine.adaptive import _stock_context
from survival_engine.models import Candle, Stock

IST = timezone(timedelta(hours=5, minutes=30))


def make_stock(up: bool) -> Stock:
    start = datetime(2026, 9, 17, 9, 15, tzinfo=IST)
    candles = []
    price = 100.0
    for i in range(80):
        drift = 0.18 if up else -0.18
        close = price + drift
        candles.append(Candle(
            start + timedelta(minutes=i),
            price,
            max(price, close) + 0.05,
            min(price, close) - 0.05,
            close,
            2000,
        ))
        price = close
    return Stock("TEST", "1", 100.0, 100.0, candles, "stocks")


class DirectionIntegrityTests(unittest.TestCase):
    def test_uptrend_agrees_with_long(self):
        integrity, context = _stock_context(make_stock(True), 1)
        self.assertGreater(integrity, 0.70)
        self.assertGreaterEqual(context["agreement"], 0.75)
        self.assertEqual(context["ema"], 1.0)
        self.assertEqual(context["vwap"], 1.0)

    def test_uptrend_disagrees_with_short(self):
        integrity, context = _stock_context(make_stock(True), -1)
        self.assertLess(integrity, 0.35)
        self.assertLessEqual(context["agreement"], 0.25)
        self.assertEqual(context["ema"], 0.0)
        self.assertEqual(context["vwap"], 0.0)

    def test_downtrend_agrees_with_short(self):
        integrity, context = _stock_context(make_stock(False), -1)
        self.assertGreater(integrity, 0.70)
        self.assertGreaterEqual(context["agreement"], 0.75)
        self.assertEqual(context["ema"], 1.0)
        self.assertEqual(context["vwap"], 1.0)


if __name__ == "__main__":
    unittest.main()
