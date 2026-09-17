from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config, STOCK_ENDPOINT
from .models import Candle, Stock

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class FetchResult:
    name: str
    url: str
    payload: dict[str, Any] | None
    error: str | None
    elapsed_ms: float
    http_status: int | None = None


def _request_json(name: str, url: str, timeout: float, retries: int) -> FetchResult:
    """Fetch the authoritative PSYGRID endpoint without strategy/data gates."""
    started = time.perf_counter()
    last_error = "unknown error"
    for attempt in range(retries + 1):
        try:
            req = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-cache, no-store",
                    "User-Agent": "PSYGRID-SURVIVAL/1.0",
                },
            )
            with urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            return FetchResult(
                name,
                url,
                payload,
                None,
                (time.perf_counter() - started) * 1000,
                status,
            )
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(0.25 * (attempt + 1))
    return FetchResult(
        name,
        url,
        None,
        last_error,
        (time.perf_counter() - started) * 1000,
        None,
    )


def fetch_universe(config: Config) -> FetchResult:
    """Fetch the single PSYGRID endpoint containing the 450-stock universe."""
    return _request_json(
        "stocks",
        STOCK_ENDPOINT,
        config.request_timeout_seconds,
        config.request_retries,
    )


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        dt = datetime.fromtimestamp(raw, tz=timezone.utc)
    elif isinstance(value, str):
        s = value.strip().replace(" IST", "+05:30")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = parsedate_to_datetime(value)
    else:
        raise ValueError(f"unsupported timestamp type: {type(value).__name__}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def _num(item: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in item:
            value = float(item[key])
            if not math.isfinite(value):
                raise ValueError(f"non-finite {key}")
            return value
    raise ValueError(f"missing one of {keys}")


def _extract_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("candles_1m", "1m", "candles", "data"):
        rows = item.get(key)
        if isinstance(rows, list):
            return rows
    return []


def parse_candles(rows: list[dict[str, Any]]) -> list[Candle]:
    """Parse upstream candles without stale/quality/trading gates."""
    candles: list[Candle] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            candles.append(
                Candle(
                    ts=_parse_ts(row.get("timestamp", row.get("ts", row.get("time")))),
                    open=_num(row, "open", "o"),
                    high=_num(row, "high", "h"),
                    low=_num(row, "low", "l"),
                    close=_num(row, "close", "c"),
                    volume=_num(row, "volume", "v"),
                )
            )
        except (ValueError, TypeError, KeyError):
            continue
    candles.sort(key=lambda c: c.ts)
    return candles


def parse_stock_payload(result: FetchResult, cutoff: datetime | None = None) -> list[Stock]:
    """Build all stocks from the single PSYGRID universe payload.

    ``cutoff`` is retained only for historical replay compatibility. Live
    SURVIVAL execution passes None and therefore never imposes a clock cutoff.
    """
    if result.payload is None:
        return []
    stocks_obj = result.payload.get("stocks", {})
    if not isinstance(stocks_obj, dict):
        return []

    out: list[Stock] = []
    for symbol, item in stocks_obj.items():
        if not isinstance(item, dict):
            continue
        try:
            parsed = parse_candles(_extract_rows(item))
            candles = [c for c in parsed if cutoff is None or c.ts <= cutoff]
            out.append(
                Stock(
                    str(item.get("symbol", symbol)),
                    str(item.get("security_id", "")),
                    float(item.get("previous_close")),
                    float(item.get("today_open")),
                    candles,
                    result.name,
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def assemble_universe(
    result: FetchResult,
    cutoff: datetime | None = None,
) -> list[Stock]:
    """Assemble SURVIVAL from the single latest upstream stock snapshot.

    No timestamp, stale-data, completeness, minimum-bar, duplicate-symbol,
    shard-size, or trading-data quality gate is applied.
    """
    return parse_stock_payload(result, cutoff)
