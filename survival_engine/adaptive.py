from __future__ import annotations

from dataclasses import replace
from statistics import median

from .config import Config
from .models import Candle, Features, IndexSeries, Stock
from .strategy import score_universe as _base_score_universe


def _median_true_range(candles: list[Candle], window: int = 12) -> float:
    seg = candles[-min(window, len(candles)):]
    if not seg:
        return 0.0
    ranges = [max(c.high - c.low, 0.0) for c in seg]
    return median(ranges) if ranges else 0.0


def _pivot_levels(candles: list[Candle], direction: int, window: int = 30) -> tuple[list[float], list[float]]:
    """Return nearby structural supports and resistances from confirmed local pivots."""
    seg = candles[-min(window, len(candles)):]
    if len(seg) < 5:
        return [], []
    supports: list[float] = []
    resistances: list[float] = []
    for i in range(2, len(seg) - 2):
        c = seg[i]
        if c.low <= seg[i - 1].low and c.low <= seg[i + 1].low and c.low <= seg[i - 2].low and c.low <= seg[i + 2].low:
            supports.append(c.low)
        if c.high >= seg[i - 1].high and c.high >= seg[i + 1].high and c.high >= seg[i - 2].high and c.high >= seg[i + 2].high:
            resistances.append(c.high)
    return supports, resistances


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def _stock_context(stock: Stock, direction: int) -> tuple[float, dict[str, float]]:
    """Audit the stock itself before relative strength is allowed to rank it."""
    candles = stock.candles
    closes = [c.close for c in candles]
    if len(closes) < 12:
        return 0.0, {"agreement": 0.0, "ema": 0.0, "ema_slope": 0.0, "vwap": 0.0, "candles": 0.0, "structure": 0.0, "opening_range": 0.0, "gap": 0.5, "reversal": 0.0}

    def ret(minutes: int) -> float:
        return closes[-1] / closes[-1 - minutes] - 1.0 if len(closes) > minutes else 0.0

    r5, r15, r30, r60 = ret(5), ret(15), ret(30), ret(60)
    weighted = ((0.10, r5), (0.20, r15), (0.40, r30), (0.30, r60))
    agreement = sum(weight for weight, value in weighted if value * direction > 0)

    ema9 = _ema(closes, 9)
    ema20 = _ema(closes, 20)
    ema9_slope = ema9[-1] - ema9[-min(6, len(ema9))]
    ema20_slope = ema20[-1] - ema20[-min(6, len(ema20))]
    ema_alignment = 1.0 if (ema9[-1] - ema20[-1]) * direction > 0 else 0.0
    ema_slope_alignment = 1.0 if ema9_slope * direction > 0 and ema20_slope * direction > 0 else 0.5 if ema9_slope * direction > 0 or ema20_slope * direction > 0 else 0.0

    volume = [max(c.volume, 0.0) for c in candles]
    total_volume = sum(volume)
    vwap = sum(c.close * v for c, v in zip(candles, volume)) / total_volume if total_volume > 0 else closes[-1]
    atr_proxy = max(median([max(c.high - c.low, 0.0) for c in candles[-min(20, len(candles)):]]), abs(closes[-1]) * 0.0001, 1e-9)
    vwap_distance = (closes[-1] - vwap) * direction / atr_proxy
    vwap_alignment = 1.0 if vwap_distance >= 0 else max(0.0, 1.0 + vwap_distance)

    recent = candles[-3:]
    candle_alignment = sum(1 for c in recent if (c.close - c.open) * direction > 0) / max(len(recent), 1)
    structure_seg = candles[-min(20, len(candles)):]
    half = len(structure_seg) // 2
    first, second = structure_seg[:half], structure_seg[half:]
    if first and second:
        fh, sh = max(c.high for c in first), max(c.high for c in second)
        fl, sl = min(c.low for c in first), min(c.low for c in second)
        structure = (int(sh > fh) + int(sl > fl)) / 2.0 if direction > 0 else (int(sh < fh) + int(sl < fl)) / 2.0
    else:
        structure = 0.5

    # Opening range is a real session reference. By 11:01, a continuation trade
    # should normally respect the direction of the first 15 minutes rather than
    # ignoring it because relative strength is attractive.
    opening = candles[:15]
    if opening:
        or_high = max(c.high for c in opening)
        or_low = min(c.low for c in opening)
        if direction > 0:
            opening_range = 1.0 if closes[-1] > or_high else 0.5 if closes[-1] >= or_low else 0.0
        else:
            opening_range = 1.0 if closes[-1] < or_low else 0.5 if closes[-1] <= or_high else 0.0
    else:
        opening_range = 0.5

    # Gap behaviour: a gap in one direction that is already failing is a warning
    # against continuation in that same direction and can support the opposite
    # direction only when the rest of the tape agrees.
    prev = stock.previous_close
    gap = (stock.today_open / prev - 1.0) if prev else 0.0
    move_from_open = closes[-1] / stock.today_open - 1.0 if stock.today_open else 0.0
    gap_score = 0.5
    if gap > 0.002:
        gap_score = 1.0 if move_from_open > 0 else 0.0
        if direction < 0:
            gap_score = 1.0 if move_from_open < -0.001 else 0.5
    elif gap < -0.002:
        gap_score = 1.0 if move_from_open < 0 else 0.0
        if direction > 0:
            gap_score = 1.0 if move_from_open > 0.001 else 0.5

    old_direction = 1 if 0.40 * r30 + 0.60 * r60 >= 0 else -1
    short_direction = 1 if 0.40 * r5 + 0.60 * r15 >= 0 else -1
    reversal_shift = 1.0 if short_direction == direction and old_direction != direction else 0.0
    reversal_vwap = 1.0 if vwap_distance >= 0 else 0.0
    reversal_structure = structure
    reversal = 0.50 * reversal_shift + 0.25 * reversal_vwap + 0.25 * reversal_structure

    integrity = (
        0.25 * agreement
        + 0.18 * ema_alignment
        + 0.12 * ema_slope_alignment
        + 0.15 * vwap_alignment
        + 0.10 * candle_alignment
        + 0.10 * structure
        + 0.06 * opening_range
        + 0.04 * gap_score
    )
    return integrity, {
        "agreement": agreement,
        "ema": ema_alignment,
        "ema_slope": ema_slope_alignment,
        "vwap": vwap_alignment,
        "candles": candle_alignment,
        "structure": structure,
        "opening_range": opening_range,
        "gap": gap_score,
        "reversal": reversal,
        "r5": r5,
        "r15": r15,
        "r30": r30,
        "r60": r60,
        "vwap_distance": vwap_distance,
    }


def _market_regime(stocks: list[Stock]) -> tuple[int, float, float, float]:
    """Infer broad intraday direction from the 450-stock cross-section."""
    if not stocks:
        return 0, 0.0, 0.0, 0.0

    def ret(stock: Stock, minutes: int) -> float:
        closes = [c.close for c in stock.candles]
        if len(closes) <= minutes:
            return 0.0
        return closes[-1] / closes[-1 - minutes] - 1.0

    r15 = [ret(stock, 15) for stock in stocks]
    r30 = [ret(stock, 30) for stock in stocks]
    r60 = [ret(stock, 60) for stock in stocks]
    med15, med30, med60 = median(r15), median(r30), median(r60)
    composite = 0.20 * med15 + 0.50 * med30 + 0.30 * med60
    breadth30 = sum(1 for value in r30 if value > 0) / len(r30)
    breadth_strength = abs(breadth30 - 0.5) * 2.0
    return_strength = min(abs(composite) / 0.0035, 1.0)
    strength = min(1.0, 0.60 * return_strength + 0.40 * breadth_strength)
    direction = 1 if composite > 0 else -1 if composite < 0 else 0
    return direction, strength, composite, breadth30


def _regime_adjustment(candidate: Features, regime: tuple[int, float, float, float]) -> tuple[float, list[str], list[str]]:
    regime_direction, strength, composite, breadth30 = regime
    if regime_direction == 0 or strength < 0.20:
        return 0.0, [], []
    candidate_direction = 1 if candidate.direction == "LONG" else -1
    aligned = candidate_direction == regime_direction
    label = "bullish" if regime_direction > 0 else "bearish"
    adjustment = 8.0 * strength if aligned else -22.0 * strength
    rejection: list[str] = []
    reasons = [f"cross-sectional market regime is {label}", f"30m market breadth={breadth30:.0%}"]
    if aligned:
        reasons.append("trade direction aligns with the dominant market regime")
    else:
        rejection.append("counter-trend versus dominant market regime")
        if candidate.setup == "RANGE_REJECTION":
            adjustment -= 8.0 * strength
    return adjustment, reasons, rejection


def _adaptive_geometry(stock: Stock, candidate: Features) -> tuple[float, float, float, float, list[str]]:
    """Derive stop/target from current structure, not a fixed R multiple."""
    candles = stock.candles
    entry = candidate.last_price
    direction = 1 if candidate.direction == "LONG" else -1
    if not candles or entry <= 0:
        return candidate.risk_unit, candidate.entry, candidate.stop, candidate.target, []

    supports, resistances = _pivot_levels(candles, direction, 30)
    recent = candles[-min(30, len(candles)):]
    recent_high = max(c.high for c in recent)
    recent_low = min(c.low for c in recent)
    median_range = _median_true_range(candles, 12)
    atr = max(candidate.atr, 1e-9)
    range_ratio = median_range / atr
    buffer = max(median_range * (0.35 + 0.35 * min(range_ratio, 1.5)), atr * 0.12)

    if direction > 0:
        below = [level for level in supports if level < entry]
        structural_stop = max(below) if below else recent_low
        stop = structural_stop - buffer
        above = sorted(level for level in resistances if level > entry)
        objectives = above + ([recent_high] if recent_high > entry else [])
        target = objectives[0] if objectives else entry + max(atr, median_range)
    else:
        above = [level for level in resistances if level > entry]
        structural_stop = min(above) if above else recent_high
        stop = structural_stop + buffer
        below = sorted((level for level in supports if level < entry), reverse=True)
        objectives = below + ([recent_low] if recent_low < entry else [])
        target = objectives[0] if objectives else entry - max(atr, median_range)

    minimum_objective_distance = max(median_range, atr * 0.65)
    if direction > 0:
        for objective in objectives:
            if objective - entry >= minimum_objective_distance:
                target = objective
                break
        if entry - stop <= 0:
            stop = entry - max(median_range, atr * 0.8)
    else:
        for objective in objectives:
            if entry - objective >= minimum_objective_distance:
                target = objective
                break
        if stop - entry <= 0:
            stop = entry + max(median_range, atr * 0.8)

    if direction > 0 and target <= entry:
        target = recent_high if recent_high > entry else entry + max(atr, median_range)
    if direction < 0 and target >= entry:
        target = recent_low if recent_low < entry else entry - max(atr, median_range)

    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = reward / max(risk, 1e-9)
    return risk, entry, stop, target, [
        "stop anchored to current structural invalidation",
        "target anchored to nearest meaningful opposing structure",
        f"adaptive structural R:R={rr:.2f}",
    ]


def _opportunity_adjustment(candidate: Features, risk: float, target: float) -> float:
    if risk <= 0:
        return -20.0
    reward = abs(target - candidate.last_price)
    rr = reward / risk
    room_factor = min(reward / max(candidate.atr, 1e-9), 4.0) / 4.0
    structure_factor = candidate.structure_quality
    noise_factor = 1.0 - candidate.noise
    raw = 50.0 * min(rr / max(1.0 + candidate.noise, 0.5), 3.0) / 3.0
    raw += 25.0 * room_factor + 25.0 * structure_factor * noise_factor
    return raw - 50.0


def score_universe(stocks: list[Stock], indices: dict[str, IndexSeries], config: Config) -> list[Features]:
    """Score with structure, market regime, stock direction and reversal intelligence."""
    base = _base_score_universe(stocks, indices, config)
    by_symbol = {stock.symbol: stock for stock in stocks}
    regime = _market_regime(stocks)
    out: list[Features] = []

    for candidate in base:
        stock = by_symbol.get(candidate.symbol)
        if stock is None:
            out.append(candidate)
            continue

        direction = 1 if candidate.direction == "LONG" else -1
        integrity, context = _stock_context(stock, direction)
        risk, entry, stop, target, notes = _adaptive_geometry(stock, candidate)
        adjustment = _opportunity_adjustment(candidate, risk, target)
        regime_adjustment, regime_reasons, regime_rejections = _regime_adjustment(candidate, regime)

        # Relative strength ranks stocks. It is not allowed to overrule the
        # stock's own directional tape. This directly addresses the old failure
        # where a strong relative performer could still be emitted as a SHORT.
        integrity_adjustment = (integrity - 0.55) * 55.0
        old_direction = 1 if 0.40 * context["r30"] + 0.60 * context["r60"] >= 0 else -1
        short_direction = 1 if 0.40 * context["r5"] + 0.60 * context["r15"] >= 0 else -1

        if candidate.setup == "CONTINUATION" and old_direction != direction:
            integrity_adjustment -= 20.0
            regime_rejections.append("continuation direction conflicts with 30m/60m stock trend")
        if context["agreement"] <= 0.25 and context["ema"] == 0.0 and context["vwap"] == 0.0:
            # Obvious three-layer contradiction: price horizons, EMA structure,
            # and VWAP all disagree. Do not let relative strength rescue it.
            integrity_adjustment -= 35.0
            regime_rejections.append("hard stock-direction contradiction: momentum + EMA + VWAP")

        if candidate.setup == "RANGE_REJECTION" and old_direction != direction:
            # Counter-trend mean reversion is permitted only when the short
            # horizon has actually turned and price has also changed context.
            reversal = context["reversal"]
            if short_direction == direction and reversal >= 0.65:
                integrity_adjustment += 4.0
                regime_reasons.append("counter-trend reversal has multi-factor confirmation")
            else:
                integrity_adjustment -= 30.0
                regime_rejections.append("counter-trend reversion lacks confirmed reversal")

        score = max(0.0, min(100.0, candidate.score + adjustment + regime_adjustment + integrity_adjustment))
        reasons = [r for r in candidate.reasons if not r.startswith("sufficient remaining range")]
        reasons.extend(notes)
        reasons.extend(regime_reasons)
        if context["agreement"] >= 0.75:
            reasons.append("stock direction agrees across most intraday horizons")
        if context["ema"] >= 1.0 and context["ema_slope"] >= 0.5:
            reasons.append("9/20 EMA structure confirms direction")
        if context["vwap"] >= 1.0:
            reasons.append("price is on the directional side of VWAP")
        if context["opening_range"] >= 1.0:
            reasons.append("price respects the opening-range direction")

        rejection = list(candidate.rejection_reasons)
        rejection.extend(regime_rejections)
        if context["ema"] == 0.0:
            rejection.append("9/20 EMA alignment contradicts proposed direction")
        if context["vwap"] < 0.50:
            rejection.append("price is materially on the opposite side of VWAP")
        if context["structure"] < 0.50:
            rejection.append("higher-high/lower-low structure does not confirm direction")
        if context["opening_range"] == 0.0:
            rejection.append("price is on the wrong side of the opening range")
        if abs(target - entry) < max(candidate.atr * 0.65, 1e-9):
            rejection.append("structural objective too close to current price")

        out.append(replace(
            candidate,
            score=score,
            confidence_band="A+" if score >= 82 else "A" if score >= 74 else "B+" if score >= 66 else "B",
            risk_unit=risk,
            entry=entry,
            stop=stop,
            target=target,
            reward_risk=abs(target - entry) / max(risk, 1e-9),
            reasons=reasons,
            rejection_reasons=rejection,
        ))

    return sorted(out, key=lambda x: (-x.score, x.symbol))
