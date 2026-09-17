import unittest

from survival_engine.adaptive import _regime_adjustment
from survival_engine.models import Features


def candidate(direction: str, setup: str = "CONTINUATION") -> Features:
    return Features(
        symbol="X", direction=direction, score=80.0, confidence_band="A",
        last_price=100.0, return_5m=0.01, return_15m=0.02, return_30m=0.03, return_60m=0.04,
        relative_15m=10, relative_30m=20, relative_60m=15, opening_gap=0.0,
        distance_vwap=0.01, distance_high=0.02, distance_low=0.03, atr=1.0, atr_pct=0.01,
        volume_ratio=1.5, persistence=0.8, trend_quality=0.8, structure_quality=0.8,
        exhaustion=0.1, noise=0.1, liquidity_quality=0.8, market_alignment=0.5,
        setup=setup, reasons=[], rejection_reasons=[], risk_unit=1.0,
        entry=100.0, stop=99.0, target=101.55, reward_risk=1.55, hard_exit="13:15 IST",
    )


class MarketRegimeTests(unittest.TestCase):
    def test_bullish_regime_penalizes_short(self):
        bullish = (1, 1.0, 0.004, 0.70)
        long_adj, _, long_rej = _regime_adjustment(candidate("LONG"), bullish)
        short_adj, _, short_rej = _regime_adjustment(candidate("SHORT"), bullish)
        self.assertGreater(long_adj, 0.0)
        self.assertLess(short_adj, 0.0)
        self.assertFalse(long_rej)
        self.assertIn("counter-trend versus dominant market regime", short_rej)

    def test_bearish_regime_penalizes_long(self):
        bearish = (-1, 1.0, -0.004, 0.30)
        long_adj, _, long_rej = _regime_adjustment(candidate("LONG"), bearish)
        short_adj, _, short_rej = _regime_adjustment(candidate("SHORT"), bearish)
        self.assertLess(long_adj, 0.0)
        self.assertGreater(short_adj, 0.0)
        self.assertIn("counter-trend versus dominant market regime", long_rej)
        self.assertFalse(short_rej)

    def test_countertrend_reversion_gets_extra_penalty(self):
        bullish = (1, 1.0, 0.004, 0.70)
        continuation_adj, _, _ = _regime_adjustment(candidate("SHORT", "CONTINUATION"), bullish)
        reversion_adj, _, _ = _regime_adjustment(candidate("SHORT", "RANGE_REJECTION"), bullish)
        self.assertLess(reversion_adj, continuation_adj)


if __name__ == "__main__":
    unittest.main()
