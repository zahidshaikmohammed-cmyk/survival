from __future__ import annotations

from dataclasses import replace

from .config import Config
from .mathx import pearson
from .models import Features, Stock


def _return_vector(stock: Stock, window: int) -> list[float]:
    closes = [c.close for c in stock.candles]
    start = max(1, len(closes) - window)
    return [closes[i] / closes[i - 1] - 1.0 for i in range(start, len(closes))]


def select_top3(candidates: list[Features], stocks: list[Stock], config: Config) -> list[Features]:
    by_symbol = {s.symbol: s for s in stocks}
    selected: list[Features] = []
    vectors = {c.symbol: _return_vector(by_symbol[c.symbol], config.correlation_window) for c in candidates if c.symbol in by_symbol}
    for candidate in candidates:
        penalty = 0.0
        for chosen in selected:
            corr = abs(pearson(vectors.get(candidate.symbol, []), vectors.get(chosen.symbol, [])))
            if corr > config.max_pair_correlation:
                penalty = max(penalty, config.correlation_penalty * (corr - config.max_pair_correlation) / (1.0 - config.max_pair_correlation))
        adjusted = replace(candidate, correlation_penalty=penalty, score=max(0.0, candidate.score - penalty))
        selected = sorted(selected + [adjusted], key=lambda x: (-x.score, x.symbol))[: config.final_trades]
    return sorted(selected, key=lambda x: (-x.score, x.symbol))
