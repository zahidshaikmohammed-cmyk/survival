from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Stock:
    symbol: str
    security_id: str
    previous_close: float
    today_open: float
    candles: list[Candle]
    source: str


@dataclass
class IndexSeries:
    name: str
    candles: list[Candle]
    source: str


@dataclass
class Features:
    symbol: str
    direction: str
    score: float
    confidence_band: str
    last_price: float
    return_5m: float
    return_15m: float
    return_30m: float
    return_60m: float
    relative_15m: float
    relative_30m: float
    relative_60m: float
    opening_gap: float
    distance_vwap: float
    distance_high: float
    distance_low: float
    atr: float
    atr_pct: float
    volume_ratio: float
    persistence: float
    trend_quality: float
    structure_quality: float
    exhaustion: float
    noise: float
    liquidity_quality: float
    market_alignment: float
    sector_alignment: float
    setup: str
    reasons: list[str]
    rejection_reasons: list[str]
    risk_unit: float
    entry: float
    stop: float
    target: float
    reward_risk: float
    hard_exit: str
    correlation_penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
