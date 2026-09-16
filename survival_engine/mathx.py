from __future__ import annotations

import math
from statistics import median


def pct(a: float, b: float) -> float:
    return (a / b - 1.0) if b else 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / (len(values) - 1))


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def pearson(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    xs, ys = xs[-n:], ys[-n:]
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else 0.0


def rolling_vwap(closes: list[float], volumes: list[float]) -> float:
    total_v = sum(max(v, 0.0) for v in volumes)
    return sum(p * max(v, 0.0) for p, v in zip(closes, volumes)) / total_v if total_v else closes[-1]


def true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    out = []
    for i, (h, l) in enumerate(zip(highs, lows)):
        prev = closes[i - 1] if i else closes[i]
        out.append(max(h - l, abs(h - prev), abs(l - prev)))
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], window: int) -> float:
    trs = true_ranges(highs, lows, closes)
    return mean(trs[-window:]) if trs else 0.0


def median_abs_deviation(values: list[float]) -> float:
    if not values:
        return 0.0
    m = median(values)
    return median([abs(x - m) for x in values])
