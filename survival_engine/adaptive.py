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


def _market_regime(stocks: list[Stock]) -> tuple[int, float, float, float]:
    """Infer broad intraday direction from the stock cross-section itself.

    The live SURVIVAL engine currently receives the 450-stock snapshot without
    index series. The median cross-section therefore becomes the market proxy.
    The regime combines 15m/30m/60m median returns with breadth, so one stock
    cannot dictate the direction. The result is used as a strong prior, not as
    a data-quality gate.
    """
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
    med15 = median(r15)
    med30 = median(r30)
    med60 = median(r60)

    composite = 0.20 * med15 + 0.50 * med30 + 0.30 * med60
    breadth30 = sum(1 for value in r30 if value > 0) / len(r30)
    breadth_strength = abs(breadth30 - 0.5) * 2.0
    return_strength = min(abs(composite) / 0.0035, 1.0)
    strength = min(1.0, 0.60 * return_strength + 0.40 * breadth_strength)

    if composite > 0:
        direction = 1
    elif composite < 0:
        direction = -1
    else:
        direction = 0
    return direction, strength, composite, breadth30


def _regime_adjustment(candidate: Features, regime: tuple[int, float, float, float]) -> tuple[float, list[str], list[str]]:
    """Prefer trades aligned with the dominant cross-sectional market direction."""
    regime_direction, strength, composite, breadth30 = regime
    if regime_direction == 0 or strength < 0.20:
        return 0.0, [], []

    candidate_direction = 1 if candidate.direction == "LONG" else -1
    aligned = candidate_direction == regime_direction
    label = "bullish" if regime_direction > 0 else "bearish"
    adjustment = 0.0
    reasons: list[str] = [
        f"cross-sectional market regime is {label}",
        f"30m market breadth={breadth30:.0%}",
    ]
    rejection: list[str] = []

    if aligned:
        adjustment += 8.0 * strength
        reasons.append("trade direction aligns with the dominant market regime")
    else:
        # Counter-trend trades are allowed to remain in the universe, but they
        # must overcome a meaningful regime penalty. Reversion trades receive
        # an additional penalty because the prior engine was selecting them
        # too freely against a persistent market move.
        adjustment -= 22.0 * strength
        if candidate.setup == "RANGE_REJECTION":
            adjustment -= 8.0 * strength
        rejection.append("counter-trend versus dominant market regime")

    return adjustment, reasons, rejection


def _adaptive_geometry(stock: Stock, candidate: Features) -> tuple[float, float, float, float, list[str]]:
    """Derive stop/target from the current price structure, not a fixed R multiple."""
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
    buffer = median_range * (0.35 + 0.35 * min(range_ratio, 1.5))
    buffer = max(buffer, atr * 0.12)

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
        risk = entry - stop
        if risk <= 0:
            stop = entry - max(median_range, atr * 0.8)
            risk = entry - stop
    else:
        for objective in objectives:
            if entry - objective >= minimum_objective_distance:
                target = objective
                break
        risk = stop - entry
        if risk <= 0:
            stop = entry + max(median_range, atr * 0.8)
            risk = stop - entry

    if direction > 0 and target <= entry:
        target = recent_high if recent_high > entry else entry + max(atr, median_range)
    if direction < 0 and target >= entry:
        target = recent_low if recent_low < entry else entry - max(atr, median_range)

    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = reward / max(risk, 1e-9)
    notes = [
        "stop anchored to current structural invalidation",
        "target anchored to nearest meaningful opposing structure",
        f"adaptive structural R:R={rr:.2f}",
    ]
    return risk, entry, stop, target, notes


def _opportunity_adjustment(candidate: Features, risk: float, target: float) -> float:
    """Convert current structural opportunity into a relative score adjustment."""
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
    """Score the universe with adaptive geometry and a market-regime prior."""
    base = _base_score_universe(stocks, indices, config)
    by_symbol = {stock.symbol: stock for stock in stocks}
    regime = _market_regime(stocks)
    out: list[Features] = []

    for candidate in base:
        stock = by_symbol.get(candidate.symbol)
        if stock is None:
            out.append(candidate)
            continue

        risk, entry, stop, target, notes = _adaptive_geometry(stock, candidate)
        adjustment = _opportunity_adjustment(candidate, risk, target)
        regime_adjustment, regime_reasons, regime_rejections = _regime_adjustment(candidate, regime)
        score = max(0.0, min(100.0, candidate.score + adjustment + regime_adjustment))

        reasons = [r for r in candidate.reasons if not r.startswith("sufficient remaining range")]
        reasons.extend(notes)
        reasons.extend(regime_reasons)

        rejection = list(candidate.rejection_reasons)
        rejection.extend(regime_rejections)
        if abs(target - entry) < max(candidate.atr * 0.65, 1e-9):
            rejection.append("structural objective too close to current price")

        return_candidate = replace(
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
        )
        out.append(return_candidate)

    return sorted(out, key=lambda x: (-x.score, x.symbol))
