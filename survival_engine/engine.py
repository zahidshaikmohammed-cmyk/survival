from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import Config
from .data import IST, assemble_universe, fetch_endpoints
from .report import print_report, write_report
from .selector import select_top3
from .strategy import score_universe


def now_ist() -> datetime:
    return datetime.now(IST)


def _payload_status(result: Any) -> str | None:
    payload = getattr(result, "payload", None)
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if isinstance(status, str):
        return status.upper()
    session = payload.get("session")
    if isinstance(session, dict) and isinstance(session.get("status"), str):
        return session["status"].upper()
    return None


def run_once(config: Config, allow_before_decision: bool = False) -> int:
    """Run SURVIVAL against the newest market state available right now.

    The upstream PSYGRID snapshot is authoritative. There is no local
    timestamp/staleness/completeness gate. A closed upstream session is
    reported explicitly as NO SIGNAL rather than being rendered as an
    apparently valid empty Top-3 decision.
    """
    decision_now = now_ist()

    print("\n[1/4] FETCHING LATEST PSYGRID: 10 STOCK SHARDS + INDEX CONTEXT...")
    stock_results, index_results = fetch_endpoints(config)

    print("[2/4] BUILDING THE LATEST AVAILABLE STRATEGY UNIVERSE...")
    stocks, indices = assemble_universe(stock_results, index_results, None)

    latest_stock_ts = max(
        (c.ts for stock in stocks for c in stock.candles),
        default=None,
    )
    latest_index_ts = max(
        (c.ts for series in indices.values() for c in series.candles),
        default=None,
    )

    stock_statuses = {
        name: _payload_status(result)
        for name, result in stock_results.items()
    }
    closed_stock_shards = sorted(
        name for name, status in stock_statuses.items() if status == "CLOSED"
    )
    failed_stock_shards = sorted(
        name for name, result in stock_results.items() if result.error
    )
    failed_index_endpoints = sorted(
        name for name, result in index_results.items() if result.error
    )

    print(f"    STOCKS RECEIVED: {len(stocks)}")
    print(f"    LATEST STOCK CANDLE: {latest_stock_ts.isoformat() if latest_stock_ts else 'N/A'}")
    print(f"    INDEX SERIES AVAILABLE: {len(indices)}")
    print(f"    LATEST INDEX CANDLE: {latest_index_ts.isoformat() if latest_index_ts else 'N/A'}")

    # If every stock shard explicitly reports CLOSED, there is no live
    # universe to rank. Do not fabricate a Top-3 from an empty input.
    all_stock_shards_closed = (
        len(stock_results) == config.expected_shards
        and len(closed_stock_shards) == config.expected_shards
    )

    if all_stock_shards_closed or not stocks:
        status = "UPSTREAM_SESSION_CLOSED" if all_stock_shards_closed else "NO_STOCK_DATA"
        reason = (
            "All ten PSYGRID stock shards report CLOSED; no live stock universe is available."
            if all_stock_shards_closed
            else "No stock records were parsed from the configured PSYGRID stock shards."
        )
        metadata: dict[str, Any] = {
            "decision_time": decision_now.isoformat(),
            "data_cutoff": None,
            "latest_stock_candle": None,
            "latest_index_candle": latest_index_ts.isoformat() if latest_index_ts else None,
            "received_stock_records": len(stocks),
            "index_series_available": len(indices),
            "index_context_available": sorted(indices),
            "candidate_count": 0,
            "final_count": 0,
            "stock_endpoints": config.expected_shards,
            "hard_exit": "13:15 IST",
            "engine_mode": "LATEST_AVAILABLE_DATA",
            "data_quality_layer": "UPSTREAM_AUTHORITY",
            "run_status": status,
            "run_reason": reason,
            "closed_stock_shards": closed_stock_shards,
            "failed_stock_shards": failed_stock_shards,
            "failed_index_endpoints": failed_index_endpoints,
        }
        print("[3/4] NO TRADE — NO LIVE STOCK UNIVERSE AVAILABLE")
        print("[4/4] WRITING NO-SIGNAL REPORT")
        print_report([], metadata)
        json_path, latest_path = write_report([], metadata, config.output_dir)
        print(f"Saved: {json_path}")
        print(f"Latest: {latest_path}")
        return 0

    print("[3/4] RUNNING SURVIVAL ACROSS THE ENTIRE AVAILABLE UNIVERSE...")
    candidates = score_universe(stocks, indices, config)
    selected = select_top3(candidates, stocks, config)

    metadata = {
        "decision_time": decision_now.isoformat(),
        "data_cutoff": None,
        "latest_stock_candle": latest_stock_ts.isoformat() if latest_stock_ts else None,
        "latest_index_candle": latest_index_ts.isoformat() if latest_index_ts else None,
        "received_stock_records": len(stocks),
        "index_series_available": len(indices),
        "index_context_available": sorted(indices),
        "candidate_count": len(candidates),
        "final_count": len(selected),
        "stock_endpoints": config.expected_shards,
        "hard_exit": "13:15 IST",
        "engine_mode": "LATEST_AVAILABLE_DATA",
        "data_quality_layer": "UPSTREAM_AUTHORITY",
        "run_status": "SIGNALS_GENERATED" if selected else "NO_CANDIDATES",
        "run_reason": "Strategy ranking completed on the available upstream stock universe.",
        "closed_stock_shards": closed_stock_shards,
        "failed_stock_shards": failed_stock_shards,
        "failed_index_endpoints": failed_index_endpoints,
    }

    print("[4/4] SURVIVAL SIGNAL — TOP 3")
    print_report(selected, metadata)
    json_path, latest_path = write_report(selected, metadata, config.output_dir)
    print(f"Saved: {json_path}")
    print(f"Latest: {latest_path}")
    return 0
