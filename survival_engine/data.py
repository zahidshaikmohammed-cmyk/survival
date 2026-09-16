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
    started = time.perf_counter()
    last_error = "unknown error"
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache, no-store", "User-Agent": "PSYGRID-SURVIVAL/1.0"})
            with urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("endpoint JSON root is not an object")
            return FetchResult(name, url, payload, None, (time.perf_counter() - started) * 1000, status)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(0.25 * (attempt + 1))
    return FetchResult(name, url, None, last_error, (time.perf_counter() - started) * 1000, None)


def fetch_endpoints(config: Config) -> tuple[dict[str, FetchResult], dict[str, FetchResult]]:
    stock_results: dict[str, FetchResult] = {}
    index_results: dict[str, FetchResult] = {}
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = {pool.submit(_request_json, name, url, config.request_timeout_seconds, config.request_retries): ("stock", name) for name, url in STOCK_ENDPOINTS.items()}
        futures.update({pool.submit(_request_json, name, url, config.request_timeout_seconds, config.request_retries): ("index", name) for name, url in INDEX_ENDPOINTS.items()})
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
    candles: list[Candle] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            candles.append(Candle(ts=_parse_ts(row.get("timestamp", row.get("ts", row.get("time")))), open=_num(row, "open", "o"), high=_num(row, "high", "h"), low=_num(row, "low", "l"), close=_num(row, "close", "c"), volume=_num(row, "volume", "v")))
        except (ValueError, TypeError, KeyError):
            continue
    candles.sort(key=lambda c: c.ts)
    return candles


def validate_candles(candles: list[Candle], cutoff: datetime, min_bars: int) -> tuple[bool, str]:
    if len(candles) < min_bars:
        return False, f"only {len(candles)} valid candles"
    seen: set[datetime] = set()
    prev: datetime | None = None
    for c in candles:
        if c.ts > cutoff:
            continue
        if c.ts in seen:
            return False, "duplicate candle timestamp"
        seen.add(c.ts)
        if prev is not None and c.ts <= prev:
            return False, "non-increasing timestamps"
        prev = c.ts
        if c.low > c.high or c.low > c.open or c.low > c.close or c.high < c.open or c.high < c.close:
            return False, "impossible OHLC"
        if c.volume < 0:
            return False, "negative volume"
        if min(c.open, c.high, c.low, c.close) <= 0:
            return False, "non-positive price"
    return True, "ok"


def parse_stock_payload(result: FetchResult, config: Config, cutoff: datetime) -> tuple[list[Stock], list[str]]:
    if result.payload is None:
        return [], [f"{result.name}: {result.error or 'no payload'}"]
    p = result.payload
    stocks_obj = p.get("stocks")
    if not isinstance(stocks_obj, dict):
        return [], [f"{result.name}: missing stocks object"]
    if p.get("service") not in (None, "PSYGRID"):
        return [], [f"{result.name}: unexpected service={p.get('service')!r}"]
    if p.get("status") not in (None, "OK"):
        return [], [f"{result.name}: endpoint status={p.get('status')!r}"]
    declared = p.get("stock_count")
    if declared is not None and int(declared) != config.expected_stocks_per_shard:
        return [], [f"{result.name}: declared stock_count={declared}, expected {config.expected_stocks_per_shard}"]
    if len(stocks_obj) != config.expected_stocks_per_shard:
        return [], [f"{result.name}: actual stock count={len(stocks_obj)}, expected {config.expected_stocks_per_shard}"]
    out: list[Stock] = []
    errors: list[str] = []
    for symbol, item in stocks_obj.items():
        if not isinstance(item, dict):
            errors.append(f"{result.name}/{symbol}: item is not object")
            continue
        try:
            candles = [c for c in parse_candles(_extract_rows(item)) if c.ts <= cutoff]
            ok, why = validate_candles(candles, cutoff, config.min_bars)
            if not ok:
                errors.append(f"{result.name}/{symbol}: {why}")
                continue
            if not candles:
                errors.append(f"{result.name}/{symbol}: no candles through cutoff")
                continue
            stale_minutes = (cutoff - candles[-1].ts).total_seconds() / 60.0
            if stale_minutes < 0 or stale_minutes > config.max_staleness_minutes:
                errors.append(f"{result.name}/{symbol}: stale by {stale_minutes:.1f} minutes")
                continue
            previous_close = float(item.get("previous_close"))
            today_open = float(item.get("today_open"))
            security_id = str(item.get("security_id", ""))
            if not security_id:
                raise ValueError("missing security_id")
            if previous_close <= 0 or today_open <= 0:
                raise ValueError("invalid previous_close/today_open")
            out.append(Stock(str(item.get("symbol", symbol)), security_id, previous_close, today_open, candles, result.name))
        except (TypeError, ValueError) as exc:
            errors.append(f"{result.name}/{symbol}: {exc}")
    return out, errors


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


def assemble_universe(stock_results: dict[str, FetchResult], index_results: dict[str, FetchResult], config: Config, cutoff: datetime) -> tuple[list[Stock], dict[str, IndexSeries], list[str]]:
    all_stocks: list[Stock] = []
    errors: list[str] = []
    for name in sorted(STOCK_ENDPOINTS):
        result = stock_results.get(name)
        if result is None:
            errors.append(f"{name}: missing fetch result")
            continue
        stocks, errs = parse_stock_payload(result, config, cutoff)
        all_stocks.extend(stocks)
        errors.extend(errs)

    by_symbol: dict[str, Stock] = {}
    duplicate_symbols: set[str] = set()
    for stock in all_stocks:
        if stock.symbol in by_symbol:
            duplicate_symbols.add(stock.symbol)
        else:
            by_symbol[stock.symbol] = stock
    if duplicate_symbols:
        errors.append("duplicate symbols across shards: " + ", ".join(sorted(duplicate_symbols)[:20]))
    if len(by_symbol) != config.expected_universe:
        errors.append(f"validated universe has {len(by_symbol)} unique stocks; expected {config.expected_universe}")

    indices: dict[str, IndexSeries] = {}
    for name, result in index_results.items():
        series = parse_index_payload(result, cutoff)
        if series:
            indices[name] = series
    for required in config.index_required:
        if required not in indices:
            errors.append(f"required index context unavailable: {required}")
    return list(by_symbol.values()), indices, errors
