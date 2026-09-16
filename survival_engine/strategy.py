from __future__ import annotations

from statistics import median

from .config import Config
from .mathx import atr, clamp, mean, pct, rolling_vwap, stdev
from .models import Candle, Features, IndexSeries, Stock


# SURVIVAL strategy principle:
# At 11:01 the engine is not trying to predict the whole market. It is trying
# to find cross-sectional dispersion: stocks behaving materially better or
# worse than their peers, while distinguishing continuation from reversion.
# The upstream acquisition layer is authoritative; this module contains no
# data-quality eligibility gates.


def _closes(stock: Stock) -> list[float]:
    return [c.close for c in stock.candles]


def _returns(closes: list[float], minutes: int) -> float:
    if minutes <= 0 or len(closes) <= minutes:
        return 0.0
    return pct(closes[-1], closes[-1 - minutes])


def _slope(values: list[float], window: int) -> float:
    if len(values) < max(3, window):
        return 0.0
    y = values[-window:]
    n = len(y)
    x_mean = (n - 1) / 2.0
    y_mean = mean(y)
    den = sum((i - x_mean) ** 2 for i in range(n))
    return sum((i - x_mean) * (v - y_mean) for i, v in enumerate(y)) / den if den else 0.0


def _persistence(closes: list[float], direction: int, window: int) -> float:
    if len(closes) < 2:
        return 0.0
    n = min(window, len(closes) - 1)
    diffs = [closes[i] - closes[i - 1] for i in range(len(closes) - n, len(closes))]
    return sum(1 for d in diffs if d * direction > 0) / len(diffs) if diffs else 0.0


def _trend_quality(closes: list[float], direction: int, window: int) -> float:
    if len(closes) < 5:
        return 0.0
    n = min(window, len(closes))
    segment = closes[-n:]
    span = max(segment) - min(segment)
    if span <= 0:
        return 0.0
    net = (segment[-1] - segment[0]) * direction
    dispersion = stdev([segment[i] - segment[i - 1] for i in range(1, len(segment))])
    path = sum(abs(segment[i] - segment[i - 1]) for i in range(1, len(segment)))
    efficiency = abs(segment[-1] - segment[0]) / path if path else 0.0
    directional = clamp(net / span, 0.0, 1.0)
    stability = 1.0 / (1.0 + dispersion / max(span / max(n, 1), 1e-9))
    return clamp(0.50 * directional + 0.30 * efficiency + 0.20 * stability, 0.0, 1.0)


def _structure_quality(candles: list[Candle], direction: int, window: int = 20) -> float:
    if len(candles) < 8:
        return 0.0
    seg = candles[-min(window, len(candles)):]
    mid = max(1, len(seg) // 2)
    first, second = seg[:mid], seg[mid:]
    if not first or not second:
        return 0.0
    first_high, second_high = max(c.high for c in first), max(c.high for c in second)
    first_low, second_low = min(c.low for c in first), min(c.low for c in second)
    if direction > 0:
        hh = clamp((second_high - first_high) / max(abs(first_high), 1e-9) / 0.01, -1.0, 1.0)
        hl = clamp((second_low - first_low) / max(abs(first_low), 1e-9) / 0.01, -1.0, 1.0)
    else:
        hh = clamp((first_high - second_high) / max(abs(first_high), 1e-9) / 0.01, -1.0, 1.0)
        hl = clamp((first_low - second_low) / max(abs(first_low), 1e-9) / 0.01, -1.0, 1.0)
    return clamp(0.5 + 0.25 * hh + 0.25 * hl, 0.0, 1.0)


def _range_location(candles: list[Candle], lookback: int = 30) -> tuple[float, float, float]:
    if not candles:
        return 0.5, 0.0, 0.0
    seg = candles[-min(lookback, len(candles)):]
    high = max(c.high for c in seg)
    low = min(c.low for c in seg)
    last = seg[-1].close
    span = max(high - low, 1e-9)
    location = clamp((last - low) / span, 0.0, 1.0)
    return location, high, low


def _wick_rejection(candles: list[Candle], direction: int, window: int = 3) -> float:
    seg = candles[-min(window, len(candles)):]
    if not seg:
        return 0.0
    values: list[float] = []
    for c in seg:
        rng = max(c.high - c.low, 1e-9)
        body = abs(c.close - c.open)
        if direction > 0:
            lower = min(c.open, c.close) - c.low
            close_position = (c.close - c.low) / rng
            values.append(clamp(lower / rng, 0.0, 1.0) * 0.6 + close_position * 0.4 if body >= 0 else 0.0)
        else:
            upper = c.high - max(c.open, c.close)
            close_position = (c.high - c.close) / rng
            values.append(clamp(upper / rng, 0.0, 1.0) * 0.6 + close_position * 0.4 if body >= 0 else 0.0)
    return mean(values)


def _exhaustion(candles: list[Candle], direction: int) -> float:
    if len(candles) < 4:
        return 0.0
    seg = candles[-min(8, len(candles)):]
    ranges = [max(c.high - c.low, 0.0) for c in seg]
    baseline = mean(ranges[:-1]) or 1e-9
    last = seg[-1]
    body = abs(last.close - last.open)
    against_wick = (last.high - max(last.open, last.close)) if direction > 0 else (min(last.open, last.close) - last.low)
    score = 0.0
    if ranges[-1] / baseline > 2.0:
        score += 0.45
    if body > 0 and against_wick / body > 1.8:
        score += 0.35
    # A very large directional extension over the recent range is also risky.
    recent = [c.close for c in seg]
    extension = abs(recent[-1] - recent[0]) / max(mean(ranges), 1e-9)
    if extension > 4.0:
        score += 0.25
    return clamp(score, 0.0, 1.0)


def _noise(candles: list[Candle], window: int = 20) -> float:
    if len(candles) < 3:
        return 1.0
    seg = candles[-min(window, len(candles)):]
    closes = [c.close for c in seg]
    gross = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    net = abs(closes[-1] - closes[0])
    return clamp(1.0 - (net / gross if gross else 0.0), 0.0, 1.0)


def _volume_ratio(candles: list[Candle], window: int) -> float:
    if len(candles) < 2:
        return 1.0
    n = min(window, len(candles) - 1)
    baseline = mean([max(c.volume, 0.0) for c in candles[-n - 1:-1]])
    return candles[-1].volume / baseline if baseline > 0 else 1.0


def _volume_trend(candles: list[Candle], direction: int, window: int = 10) -> float:
    if len(candles) < 4:
        return 0.5
    seg = candles[-min(window, len(candles)):]
    signed = [((c.close - c.open) * direction) * max(c.volume, 0.0) for c in seg]
    denom = sum(abs((c.close - c.open) * max(c.volume, 0.0)) for c in seg)
    return clamp(0.5 + 0.5 * (sum(signed) / denom if denom else 0.0), 0.0, 1.0)


def _compression_expansion(candles: list[Candle], atr_value: float) -> float:
    if len(candles) < 10 or atr_value <= 0:
        return 0.5
    seg = candles[-10:]
    early = mean([c.high - c.low for c in seg[:5]])
    late = mean([c.high - c.low for c in seg[-3:]])
    ratio = late / max(early, 1e-9)
    last_range = seg[-1].high - seg[-1].low
    expansion = clamp((ratio - 0.8) / 1.2, 0.0, 1.0)
    impulse = clamp(last_range / atr_value / 2.0, 0.0, 1.0)
    return 0.55 * expansion + 0.45 * impulse


def _index_return(series: IndexSeries | None, minutes: int) -> float:
    if not series:
        return 0.0
    return _returns([c.close for c in series.candles], minutes)


def _market_alignment(stock_return: float, indices: dict[str, IndexSeries], direction: int) -> float:
    names = ("nifty", "nifty500", "sensex", "banknifty")
    observed = [_index_return(indices[name], 30) for name in names if name in indices]
    if not observed:
        return 0.5
    broad = sum(1 for value in observed if value * direction >= 0) / len(observed)
    relative = clamp(0.5 + ((stock_return - median(observed)) * direction) / 0.01, 0.0, 1.0)
    return clamp(0.45 * broad + 0.55 * relative, 0.0, 1.0)


def _vix_noise_penalty(indices: dict[str, IndexSeries]) -> float:
    vix = indices.get("indiavix")
    if not vix:
        return 0.0
    closes = [c.close for c in vix.candles]
    return clamp(abs(_returns(closes, 30)) / 0.08, 0.0, 1.0)


def _median_return(stocks: list[Stock], minutes: int) -> float:
    values = [_returns(_closes(s), minutes) for s in stocks]
    return median(values) if values else 0.0


def _residual_strength(r5: float, r15: float, r30: float, r60: float,
                       u5: float, u15: float, u30: float, u60: float) -> tuple[float, float, float, float]:
    # Basis points make horizons comparable and avoid a single raw return
    # dominating the composite.  Short horizon gets the smallest weight so a
    # single noisy bar cannot decide the direction.
    rs5 = (r5 - u5) * 10000.0
    rs15 = (r15 - u15) * 10000.0
    rs30 = (r30 - u30) * 10000.0
    rs60 = (r60 - u60) * 10000.0
    return rs5, rs15, rs30, rs60


def _directional_pressure(rs5: float, rs15: float, rs30: float, rs60: float,
                          trend: float, vwap_side: float) -> float:
    # Positive = bullish, negative = bearish. 30m/15m carry most weight;
    # 5m is confirmation, not the driver. VWAP/trend are small tie-breakers.
    momentum = 0.10 * rs5 + 0.30 * rs15 + 0.38 * rs30 + 0.22 * rs60
    return momentum + 10.0 * (trend - 0.5) + 5.0 * vwap_side


def _remaining_opportunity(distance_vwap: float, atr_pct: float, risk_unit: float,
                           entry: float, direction: int, target_r: float,
                           range_high: float, range_low: float) -> float:
    if entry <= 0 or risk_unit <= 0 or atr_pct <= 0:
        return 0.5
    target_distance = target_r * risk_unit
    if direction > 0:
        room = max(range_high - entry, 0.0)
    else:
        room = max(entry - range_low, 0.0)
    room_score = clamp(room / max(target_distance, 1e-9), 0.0, 1.5) / 1.5
    # A large VWAP displacement consumes more of the likely intraday move.
    stretch = clamp(abs(distance_vwap) / max(2.5 * atr_pct, 1e-9), 0.0, 1.0)
    return clamp(0.70 * room_score + 0.30 * (1.0 - stretch), 0.0, 1.0)


def _build_candidate(stock: Stock, indices: dict[str, IndexSeries], config: Config,
                     universe: tuple[float, float, float, float]) -> Features:
    """Score one stock using continuation/reversion logic; no eligibility gate."""
    candles = stock.candles
    closes = _closes(stock)
    last = closes[-1] if closes else 0.0

    u5, u15, u30, u60 = universe
    r5 = _returns(closes, 5)
    r15 = _returns(closes, 15)
    r30 = _returns(closes, 30)
    r60 = _returns(closes, 60)
    rs5, rs15, rs30, rs60 = _residual_strength(r5, r15, r30, r60, u5, u15, u30, u60)

    atr_value = atr([c.high for c in candles], [c.low for c in candles], closes, config.atr_window) if candles and closes else 0.0
    atr_value = max(atr_value, abs(last) * 0.0001, 1e-9)
    atr_pct = atr_value / max(abs(last), 1e-9)
    vwap = rolling_vwap(closes, [c.volume for c in candles]) if closes else 0.0
    dist_vwap = pct(last, vwap) if vwap > 0 else 0.0

    location, range_high, range_low = _range_location(candles, config.long_window)
    extension_atr = abs(last - vwap) / atr_value if vwap > 0 else 0.0
    trend_sign = 1 if (0.30 * rs15 + 0.45 * rs30 + 0.25 * rs60) >= 0 else -1
    trend = _trend_quality(closes, trend_sign, config.long_window)
    persistence = _persistence(closes, trend_sign, config.mid_window)
    structure = _structure_quality(candles, trend_sign, config.long_window)
    exhaustion = _exhaustion(candles, trend_sign)
    noise = _noise(candles, config.long_window)
    vol_ratio = _volume_ratio(candles, config.volume_window)
    avg_vol = mean([max(c.volume, 0.0) for c in candles[-config.volume_window:]]) if candles else 0.0
    liquidity = clamp(0.5 + (avg_vol / max(config.minimum_avg_volume, 1.0) - 1.0) / 4.0, 0.0, 1.0)
    volume_direction = _volume_trend(candles, trend_sign)
    expansion = _compression_expansion(candles, atr_value)
    market_align = _market_alignment(r30, indices, trend_sign)
    vix_penalty = _vix_noise_penalty(indices)

    # Continuation requires persistence, directional structure and a fresh
    # expansion. It is deliberately penalized when the stock is already far
    # from VWAP/range equilibrium or showing exhaustion.
    continuation_core = (
        0.25 * clamp(abs(rs30) / 50.0, 0.0, 1.0)
        + 0.18 * clamp(abs(rs15) / 40.0, 0.0, 1.0)
        + 0.10 * clamp(abs(rs60) / 70.0, 0.0, 1.0)
        + 0.14 * persistence
        + 0.12 * trend
        + 0.10 * structure
        + 0.06 * expansion
        + 0.05 * clamp(vol_ratio / 2.0, 0.0, 1.0)
    )
    continuation_penalty = (
        0.20 * clamp(extension_atr / 3.0, 0.0, 1.0)
        + 0.18 * exhaustion
        + 0.12 * noise
    )
    continuation_quality = clamp(continuation_core - continuation_penalty, 0.0, 1.0)

    # Reversion is only attractive at a meaningful range edge / VWAP stretch.
    # Direction is explicitly toward equilibrium, not merely the opposite of
    # the latest candle.
    edge_strength = max(location, 1.0 - location)
    if location >= 0.65:
        reversion_direction = -1
    elif location <= 0.35:
        reversion_direction = 1
    else:
        reversion_direction = -1 if dist_vwap > 0 else 1
    vwap_stretch = clamp(extension_atr / 2.5, 0.0, 1.0)
    rejection = _wick_rejection(candles, reversion_direction)
    reversion_quality = clamp(
        0.30 * edge_strength
        + 0.25 * vwap_stretch
        + 0.20 * rejection
        + 0.15 * (1.0 - exhaustion)
        + 0.10 * (1.0 - noise),
        0.0,
        1.0,
    )

    # Choose setup first, then choose direction according to that setup.
    # This prevents a strong bullish stock that is visibly overextended from
    # automatically becoming a LONG continuation trade.
    if reversion_quality > continuation_quality and reversion_quality >= 0.35:
        setup = "RANGE_REJECTION"
        direction = reversion_direction
        setup_quality = reversion_quality
    else:
        setup = "CONTINUATION"
        direction = trend_sign
        setup_quality = continuation_quality

    directional_rs = (0.20 * rs5 + 0.30 * rs15 + 0.35 * rs30 + 0.15 * rs60) * direction
    vwap_side = (dist_vwap * direction) / max(2.5 * atr_pct, 1e-9)
    pressure = _directional_pressure(rs5, rs15, rs30, rs60, trend, clamp(vwap_side, -1.0, 1.0)) * direction
    directional_confirmation = clamp(0.5 + pressure / 120.0, 0.0, 1.0)

    # For a reversion trade, the sign of raw momentum can be contrary by
    # design, so confirmation comes from stretch + rejection rather than trend.
    if setup == "RANGE_REJECTION":
        directional_confirmation = clamp(
            0.55 * (0.5 + vwap_stretch / 2.0)
            + 0.45 * rejection,
            0.0,
            1.0,
        )

    market_score = market_align if setup == "CONTINUATION" else (1.0 - market_align * 0.35)
    remaining = _remaining_opportunity(
        dist_vwap, atr_pct, max(atr_value * config.stop_atr_multiple, abs(last) * 0.0015, 1e-9),
        last, direction, config.target_r_multiple, range_high, range_low,
    )

    score = 100.0 * (
        0.24 * setup_quality
        + 0.18 * clamp(abs(directional_rs) / 55.0, 0.0, 1.0)
        + 0.13 * directional_confirmation
        + 0.10 * persistence
        + 0.08 * structure
        + 0.08 * volume_direction
        + 0.07 * clamp(vol_ratio / 2.0, 0.0, 1.0)
        + 0.07 * remaining
        + 0.05 * market_score
    )
    score -= 10.0 * exhaustion + 7.0 * noise + 4.0 * vix_penalty
    score = clamp(score, 0.0, 100.0)

    entry = last
    risk_unit = max(atr_value * config.stop_atr_multiple, abs(last) * 0.0015, 1e-9)
    if setup == "RANGE_REJECTION":
        # Give a rejection trade slightly more room than a clean continuation,
        # while never allowing the stop to become smaller than the configured
        # minimum volatility/price distance.
        risk_unit = max(risk_unit, atr_value * 0.95)
    stop = entry - risk_unit if direction > 0 else entry + risk_unit
    target = entry + config.target_r_multiple * risk_unit if direction > 0 else entry - config.target_r_multiple * risk_unit
    reward_risk = abs(target - entry) / max(abs(entry - stop), 1e-9)

    reasons: list[str] = []
    if abs(rs30) >= 5.0:
        reasons.append("strong 30m cross-sectional alpha")
    if abs(rs15) >= 4.0:
        reasons.append("15m relative strength confirms the move")
    if persistence >= 0.60:
        reasons.append("directional persistence is established")
    if structure >= 0.60:
        reasons.append("intraday price structure supports direction")
    if expansion >= 0.60:
        reasons.append("recent range expansion supports movement")
    if vol_ratio >= 1.20:
        reasons.append("volume participation is above recent baseline")
    if setup == "RANGE_REJECTION":
        reasons.append("range/VWAP stretch with rejection supports mean reversion")
    if remaining >= 0.60:
        reasons.append("sufficient remaining range for the engineered target")
    if market_score >= 0.55:
        reasons.append("broad-market context is not strongly adverse")

    rejection_reasons: list[str] = []
    if exhaustion >= 0.60:
        rejection_reasons.append("late-stage exhaustion")
    if noise >= 0.65:
        rejection_reasons.append("choppy intraday path")
    if extension_atr >= 2.5:
        rejection_reasons.append("large VWAP displacement")
    if remaining < 0.35:
        rejection_reasons.append("limited remaining range")
    if vol_ratio < 0.80:
        rejection_reasons.append("weak current-bar participation")
    if vix_penalty > 0.70:
        rejection_reasons.append("elevated broad-market volatility")

    band = "A+" if score >= 82 else "A" if score >= 74 else "B+" if score >= 66 else "B"
    return Features(
        symbol=stock.symbol,
        direction="LONG" if direction > 0 else "SHORT",
        score=score,
        confidence_band=band,
        last_price=last,
        return_5m=r5,
        return_15m=r15,
        return_30m=r30,
        return_60m=r60,
        relative_15m=rs15,
        relative_30m=rs30,
        relative_60m=rs60,
        opening_gap=pct(stock.today_open, stock.previous_close),
        distance_vwap=dist_vwap,
        distance_high=pct(last, range_high) if range_high else 0.0,
        distance_low=pct(last, range_low) if range_low else 0.0,
        atr=atr_value,
        atr_pct=atr_pct,
        volume_ratio=vol_ratio,
        persistence=persistence,
        trend_quality=trend,
        structure_quality=structure,
        exhaustion=exhaustion,
        noise=noise,
        liquidity_quality=liquidity,
        market_alignment=market_align,
        setup=setup,
        reasons=reasons,
        rejection_reasons=rejection_reasons,
        risk_unit=risk_unit,
        entry=entry,
        stop=stop,
        target=target,
        reward_risk=reward_risk,
        hard_exit="13:15 IST",
    )


def score_universe(stocks: list[Stock], indices: dict[str, IndexSeries], config: Config) -> list[Features]:
    universe = (
        _median_return(stocks, 5),
        _median_return(stocks, 15),
        _median_return(stocks, 30),
        _median_return(stocks, 60),
    )
    candidates = [_build_candidate(stock, indices, config, universe) for stock in stocks]
    return sorted(candidates, key=lambda x: (-x.score, x.symbol))
