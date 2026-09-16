from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config, INDEX_ENDPOINTS, STOCK_ENDPOINTS
from .models import Candle, IndexSeries, Stock

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
    """Fetch one authoritative PSYGRID endpoint.

    SURVIVAL assumes the upstream acquisition layer is authoritative. This
    function therefore does transport/JSON decoding only; it does not make
    trading decisions and does not apply data-quality gates.
    """
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


def fetch_endpoints(config: Config) -> tuple[dict[str, FetchResult], dict[str, FetchResult]]:
    """Fetch the ten stock shards and all configured index/context endpoints."""
    stock_results: dict[str, FetchResult] = {}
    index_results: dict[str, FetchResult] = {}
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = {
            pool.submit(
                _request_json,
                name,
                url,
                config.request_timeout_seconds,
                config.request_retries,
            ): ("stock", name)
            for name, url in STOCK_ENDPOINTS.items()
        }
        futures.update(
            {
                pool.submit(
                    _request_json,
                    name,
                    url,
                    config.request_timeout_seconds,
                    config.request_retries,
                ): ("index", name)
                for name, url in INDEX_ENDPOINTS.items()
            }
        )
        for future in as_completed(futures):
            kind, name = futures[future]
            result = future.result()
            (stock_results if kind == "stock" else index_results)[name] = result
    return stock_results, index_results


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


def parse_stock_payload(
    result: FetchResult,
    cutoff: datetime,
) -> list[Stock]:
    """Turn one live shard into Stock objects.

    No shard-count gate, no stale gate, no minimum-bar gate and no OHLC gate
    are applied here. The upstream PSYGRID acquisition layer is authoritative;
    SURVIVAL's job starts after ingestion.
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
            candles = [c for c in parse_candles(_extract_rows(item)) if c.ts <= cutoff]
            previous_close = float(item.get("previous_close"))
            today_open = float(item.get("today_open"))
            security_id = str(item.get("security_id", ""))
            out.append(
                Stock(
                    str(item.get("symbol", symbol)),
                    security_id,
                    previous_close,
                    today_open,
                    candles,
                    result.name,
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _index_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("candles_1m", "1m", "candles", "5m", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return rows
    for key in ("index", "indices"):
        obj = payload.get(key)
        if isinstance(obj, dict):
            for subkey in ("candles_1m", "1m", "candles", "5m", "data"):
                rows = obj.get(subkey)
                if isinstance(rows, list):
                    return rows
    return []


def parse_index_payload(result: FetchResult, cutoff: datetime) -> IndexSeries | None:
    if result.payload is None:
        return None
    rows = [c for c in parse_candles(_index_rows(result.payload)) if c.ts <= cutoff]
    return IndexSeries(result.name, rows, result.name) if rows else None


def assemble_universe(
    stock_results: dict[str, FetchResult],
    index_results: dict[str, FetchResult],
    cutoff: datetime,
) -> tuple[list[Stock], dict[str, IndexSeries]]:
    """Assemble the authoritative universe for the strategy.

    There are deliberately no data-quality gates here. The function does not
    reject stale candles, reject shard sizes, reject duplicate symbols, reject
    missing bars, or abort because a data-quality rule was triggered.
    """
    all_stocks: list[Stock] = []
    for name in sorted(STOCK_ENDPOINTS):
        result = stock_results.get(name)
        if result is not None:
            all_stocks.extend(parse_stock_payload(result, cutoff))

    indices: dict[str, IndexSeries] = {}
    for name, result in index_results.items():
        series = parse_index_payload(result, cutoff)
        if series:
            indices[name] = series

    return all_stocks, indices
