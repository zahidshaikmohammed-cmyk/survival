from __future__ import annotations

from statistics import median

from .config import Config
from .mathx import atr, clamp, mean, pct, rolling_vwap, stdev
from .models import Candle, Features, IndexSeries, Stock


def _closes(stock: Stock) -> list[float]:
    return [c.close for c in stock.candles]


def _returns(closes: list[float], minutes: int) -> float:
    return pct(closes[-1], closes[-1 - minutes]) if len(closes) > minutes else 0.0


def _persistence(closes: list[float], direction: int, window: int) -> float:
    if len(closes) <= window:
        return 0.0
    diffs = [closes[i] - closes[i - 1] for i in range(len(closes) - window, len(closes))]
    return sum(1 for d in diffs if d * direction > 0) / len(diffs)


def _trend_quality(closes: list[float], direction: int, window: int) -> float:
    if len(closes) < window + 1:
        return 0.0
    segment = closes[-window:]
    span = max(segment) - min(segment)
    if span <= 0:
        return 0.0
    net = (segment[-1] - segment[0]) * direction
    dispersion = stdev([segment[i] - segment[i - 1] for i in range(1, len(segment))])
    raw = net / span
    stability = 1.0 / (1.0 + dispersion / max(span / window, 1e-9))
    return clamp(0.5 * raw + 0.5 * stability, 0.0, 1.0)


def _structure_quality(candles: list[Candle], direction: int, window: int = 20) -> float:
    seg = candles[-window:]
    if len(seg) < 10:
        return 0.0
    mid = len(seg) // 2
    first_high, second_high = max(c.high for c in seg[:mid]), max(c.high for c in seg[mid:])
    first_low, second_low = min(c.low for c in seg[:mid]), min(c.low for c in seg[mid:])
    if direction > 0:
        higher_high = second_high >= first_high * 0.998
        higher_low = second_low >= first_low * 0.998
        return (int(higher_high) + int(higher_low)) / 2.0
    lower_high = second_high <= first_high * 1.002
    lower_low = second_low <= first_low * 1.002
    return (int(lower_high) + int(lower_low)) / 2.0


def _exhaustion(candles: list[Candle], direction: int) -> float:
    seg = candles[-8:]
    if len(seg) < 5:
        return 0.0
    ranges = [c.high - c.low for c in seg]
    avg_range = mean(ranges[:-1]) or 1e-9
    last = seg[-1]
    body = abs(last.close - last.open)
    against_wick = last.high - max(last.open, last.close) if direction > 0 else min(last.open, last.close) - last.low
    penalty = 0.45 if ranges[-1] / avg_range > 2.0 else 0.0
    if body > 0 and against_wick / body > 1.8:
        penalty += 0.35
    return clamp(penalty, 0.0, 1.0)


def _noise(candles: list[Candle], window: int = 20) -> float:
    seg = candles[-window:]
    if len(seg) < 5:
        return 1.0
    closes = [c.close for c in seg]
    gross = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    net = abs(closes[-1] - closes[0])
    return clamp(1.0 - (net / gross if gross else 0.0), 0.0, 1.0)


def _volume_ratio(candles: list[Candle], window: int) -> float:
    if len(candles) <= window:
        return 1.0
    baseline = mean([c.volume for c in candles[-window - 1:-1]])
    return candles[-1].volume / baseline if baseline > 0 else 1.0


def _index_return(series: IndexSeries | None, minutes: int) -> float:
    if not series or len(series.candles) <= minutes:
        return 0.0
    closes = [c.close for c in series.candles]
    return _returns(closes, minutes)


def _market_alignment(stock_return: float, indices: dict[str, IndexSeries], direction: int) -> float:
    names = ("nifty", "nifty500", "sensex", "banknifty")
    observed = [_index_return(indices[name], 30) for name in names if name in indices]
    if not observed:
        return 0.5
    aligned = sum(1 for x in observed if x * direction >= 0)
    broad = aligned / len(observed)
    relative = clamp(0.5 + ((stock_return - median(observed)) * direction) / 0.01, 0.0, 1.0)
    return 0.55 * broad + 0.45 * relative


def _vix_noise_penalty(indices: dict[str, IndexSeries]) -> float:
    vix = indices.get("indiavix")
    if not vix or len(vix.candles) <= 30:
        return 0.0
    closes = [c.close for c in vix.candles]
    return clamp(abs(_returns(closes, 30)) / 0.08, 0.0, 1.0)


def _build_candidate(stock: Stock, indices: dict[str, IndexSeries], config: Config, universe_r15: float, universe_r30: float, universe_r60: float) -> Features | None:
    candles = stock.candles
    closes = _closes(stock)
    last = closes[-1]
    if last < config.minimum_price:
        return None
    avg_vol = mean([c.volume for c in candles[-config.volume_window:]])
    if avg_vol < config.minimum_avg_volume:
        return None

    r5, r15, r30, r60 = (_returns(closes, w) for w in (5, 15, 30, 60))
    rs15 = (r15 - universe_r15) * 10000
    rs30 = (r30 - universe_r30) * 10000
    rs60 = (r60 - universe_r60) * 10000
    direction = 1 if (0.45 * rs30 + 0.30 * rs15 + 0.25 * rs60) >= 0 else -1

    atr_value = atr([c.high for c in candles], [c.low for c in candles], closes, config.atr_window)
    if atr_value <= 0:
        return None
    atr_pct = atr_value / last
    vwap = rolling_vwap(closes, [c.volume for c in candles])
    dist_vwap = pct(last, vwap)
    intraday_high = max(c.high for c in candles)
    intraday_low = min(c.low for c in candles)
    distance_high = pct(last, intraday_high)
    distance_low = pct(last, intraday_low)
    persistence = _persistence(closes, direction, config.mid_window)
    trend = _trend_quality(closes, direction, config.long_window)
    structure = _structure_quality(candles, direction)
    exhaustion = _exhaustion(candles, direction)
    noise = _noise(candles)
    vol_ratio = _volume_ratio(candles, config.volume_window)
    liquidity = clamp((avg_vol / config.minimum_avg_volume - 1.0) / 4.0 + 0.5, 0.0, 1.0)
    market_align = _market_alignment(r30, indices, direction)
    vix_penalty = _vix_noise_penalty(indices)

    continuation = 0.24 * clamp(abs(rs30) / 35.0, 0.0, 1.0) + 0.18 * persistence + 0.18 * trend + 0.16 * structure + 0.10 * clamp(vol_ratio / 2.5, 0.0, 1.0) + 0.08 * (1.0 if dist_vwap * direction >= 0 else 0.0) + 0.06 * market_align
    range_edge = min(abs(distance_high), abs(distance_low)) < max(0.02, 2.0 * atr_pct)
    rejection_quality = 0.0
    if range_edge:
        rejection_quality = 0.35 * (1.0 - exhaustion) + 0.35 * (1.0 - noise) + 0.30 * market_align
    setup = "CONTINUATION" if continuation >= rejection_quality else "RANGE_REJECTION"

    raw_score = (0.18 * clamp(abs(rs15) / 35.0, 0.0, 1.0) + 0.22 * clamp(abs(rs30) / 50.0, 0.0, 1.0) + 0.10 * clamp(abs(rs60) / 70.0, 0.0, 1.0) + 0.15 * persistence + 0.12 * trend + 0.10 * structure + 0.07 * clamp(vol_ratio / 2.5, 0.0, 1.0) + 0.04 * liquidity + 0.02 * market_align) * 100.0
    raw_score -= 10.0 * exhaustion + 8.0 * noise + 4.0 * vix_penalty
    if setup == "RANGE_REJECTION":
        raw_score += 2.0 * rejection_quality
    score = clamp(raw_score, 0.0, 100.0)
    if score < config.min_entry_score:
        return None

    entry = last
    risk_unit = max(atr_value * config.stop_atr_multiple, last * 0.0015)
    stop = entry - risk_unit if direction > 0 else entry + risk_unit
    target = entry + config.target_r_multiple * risk_unit if direction > 0 else entry - config.target_r_multiple * risk_unit
    reward_risk = abs(target - entry) / abs(entry - stop)
    if reward_risk < config.risk_reward_floor:
        return None

    reasons: list[str] = []
    if abs(rs30) > 3.0:
        reasons.append("strong 30m cross-sectional relative strength")
    if persistence >= 0.60:
        reasons.append("persistent directional closes")
    if trend >= 0.60:
        reasons.append("clean directional structure")
    if vol_ratio >= 1.25:
        reasons.append("volume participation above recent baseline")
    if dist_vwap * direction > 0:
        reasons.append("price aligned with VWAP direction")
    if market_align >= 0.55:
        reasons.append("broad-market context supports direction")

    rejection_reasons: list[str] = []
    if exhaustion > 0.60:
        rejection_reasons.append("late-candle exhaustion")
    if noise > 0.65:
        rejection_reasons.append("high intraday noise")
    if vol_ratio < 0.80:
        rejection_reasons.append("weak volume participation")
    if vix_penalty > 0.70:
        rejection_reasons.append("elevated broad-market volatility")

    band = "A" if score >= 75 else "B+" if score >= 66 else "B"
    return Features(symbol=stock.symbol, direction="LONG" if direction > 0 else "SHORT", score=score, confidence_band=band, last_price=last, return_5m=r5, return_15m=r15, return_30m=r30, return_60m=r60, relative_15m=rs15, relative_30m=rs30, relative_60m=rs60, opening_gap=pct(stock.today_open, stock.previous_close), distance_vwap=dist_vwap, distance_high=distance_high, distance_low=distance_low, atr=atr_value, atr_pct=atr_pct, volume_ratio=vol_ratio, persistence=persistence, trend_quality=trend, structure_quality=structure, exhaustion=exhaustion, noise=noise, liquidity_quality=liquidity, market_alignment=market_align, setup=setup, reasons=reasons, rejection_reasons=rejection_reasons, risk_unit=risk_unit, entry=entry, stop=stop, target=target, reward_risk=reward_risk, hard_exit="13:15 IST")


def _universe_returns(stocks: list[Stock], minutes: int) -> list[float]:
    return [_returns(_closes(s), minutes) for s in stocks if len(s.candles) > minutes]


def score_universe(stocks: list[Stock], indices: dict[str, IndexSeries], config: Config) -> list[Features]:
    universe_r15 = median(_universe_returns(stocks, 15))
    universe_r30 = median(_universe_returns(stocks, 30))
    universe_r60 = median(_universe_returns(stocks, 60))
    candidates = []
    for stock in stocks:
        candidate = _build_candidate(stock, indices, config, universe_r15, universe_r30, universe_r60)
        if candidate:
            candidates.append(candidate)
    return sorted(candidates, key=lambda x: (-x.score, x.symbol))
