import unittest
from datetime import datetime, timedelta, timezone

from survival_engine.adaptive import _adaptive_geometry, score_universe
from survival_engine.config import Config
from survival_engine.models import Candle, Features, Stock

IST = timezone(timedelta(hours=5, minutes=30))


def candles_with_structure(entry: float, support: float, resistance: float, n: int = 30):
    start = datetime(2026, 9, 17, 9, 15, tzinfo=IST)
    values = []
    base = entry - 1.0
    for i in range(n):
        price = base + (i * 0.05)
        values.append(Candle(start + timedelta(minutes=i), price, price + 0.20, price - 0.20, price + 0.05, 2000))
    # Build confirmed pivot low and high inside the lookback window.
    for i in range(8, 13):
        p = support + abs(i - 10) * 0.5
        values[i] = Candle(start + timedelta(minutes=i), p + 0.10, p + 0.20, p, p + 0.10, 2000)
    for i in range(16, 21):
        p = resistance - abs(i - 18) * 0.5
        values[i] = Candle(start + timedelta(minutes=i), p - 0.10, p, p - 0.20, p - 0.10, 2000)
    values[-1] = Candle(start + timedelta(minutes=n - 1), entry - 0.05, entry + 0.10, entry - 0.10, entry, 2500)
    return values


def feature(symbol: str, direction: str = "LONG"):
    return Features(
        symbol=symbol, direction=direction, score=80.0, confidence_band="A",
        last_price=100.0, return_5m=.01, return_15m=.02, return_30m=.03, return_60m=.04,
        relative_15m=10, relative_30m=20, relative_60m=15, opening_gap=0,
        distance_vwap=.01, distance_high=.02, distance_low=.03, atr=1.0, atr_pct=.01,
        volume_ratio=1.5, persistence=.8, trend_quality=.8, structure_quality=.8,
        exhaustion=.1, noise=.1, liquidity_quality=.8, market_alignment=.5,
        setup="CONTINUATION", reasons=[], rejection_reasons=[], risk_unit=1.0,
        entry=100.0, stop=99.0, target=101.55, reward_risk=1.55, hard_exit="13:15 IST",
    )


class AdaptiveTests(unittest.TestCase):
    def test_target_is_structural_not_fixed_155r(self):
        stock = Stock("TEST", "1", 100, 100, candles_with_structure(100, 96, 106), "stocks")
        risk, entry, stop, target, notes = _adaptive_geometry(stock, feature("TEST"))
        self.assertGreater(target, entry)
        self.assertNotAlmostEqual((target - entry) / risk, 1.55, places=2)
        self.assertTrue(any("structural" in note for note in notes))

    def test_current_structure_changes_geometry(self):
        near = Stock("NEAR", "1", 100, 100, candles_with_structure(100, 98, 103), "stocks")
        far = Stock("FAR", "2", 100, 100, candles_with_structure(100, 95, 110), "stocks")
        a = _adaptive_geometry(near, feature("NEAR"))
        b = _adaptive_geometry(far, feature("FAR"))
        self.assertNotEqual((round(a[2], 4), round(a[3], 4)), (round(b[2], 4), round(b[3], 4)))

    def test_adaptive_engine_scores_entire_universe(self):
        stocks = []
        for i in range(20):
            candles = candles_with_structure(100 + i, 96 + i, 106 + i)
            stocks.append(Stock(f"S{i:02d}", str(i), 100 + i, 100 + i, candles, "stocks"))
        scored = score_universe(stocks, {}, Config())
        self.assertEqual(len(scored), 20)
        self.assertTrue(all(0.0 <= item.score <= 100.0 for item in scored))
        self.assertTrue(all(item.stop != item.entry for item in scored))
        self.assertTrue(all(item.target != item.entry for item in scored))


if __name__ == "__main__":
    unittest.main()
