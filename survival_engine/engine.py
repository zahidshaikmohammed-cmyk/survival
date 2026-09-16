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


def run_once(config: Config, allow_before_decision: bool = False) -> int:
    """Run SURVIVAL against the newest market state available right now.

    There is intentionally no 11:00/11:01 timestamp gate. The upstream
    PSYGRID snapshot is authoritative; whatever the newest candles are when
    fetched become the strategy state used for the signal.
    """
    decision_now = now_ist()

    print("\n[1/4] FETCHING LATEST PSYGRID: 10 STOCK SHARDS + INDEX CONTEXT...")
    stock_results, index_results = fetch_endpoints(config)

    print("[2/4] BUILDING THE LATEST AVAILABLE STRATEGY UNIVERSE...")
    # cutoff=None is deliberate: never discard a newer candle because of a
    # configured clock. No data-quality gate is introduced here.
    stocks, indices = assemble_universe(stock_results, index_results, None)

    latest_stock_ts = max(
        (c.ts for stock in stocks for c in stock.candles),
        default=None,
    )
    latest_index_ts = max(
        (c.ts for series in indices.values() for c in series.candles),
        default=None,
    )

    print(f"    STOCKS RECEIVED: {len(stocks)}")
    print(f"    LATEST STOCK CANDLE: {latest_stock_ts.isoformat() if latest_stock_ts else 'N/A'}")
    print(f"    INDEX SERIES AVAILABLE: {len(indices)}")
    print(f"    LATEST INDEX CANDLE: {latest_index_ts.isoformat() if latest_index_ts else 'N/A'}")

    print("[3/4] RUNNING SURVIVAL ACROSS THE ENTIRE AVAILABLE UNIVERSE...")
    candidates = score_universe(stocks, indices, config)
    selected = select_top3(candidates, stocks, config)

    metadata: dict[str, Any] = {
        "decision_time": decision_now.isoformat(),
        "data_cutoff": None,
        "latest_stock_candle": latest_stock_ts.isoformat() if latest_stock_ts else None,
        "latest_index_candle": latest_index_ts.isoformat() if latest_index_ts else None,
        "received_stock_records": len(stocks),
        "index_context_available": sorted(indices),
        "candidate_count": len(candidates),
        "final_count": len(selected),
        "stock_endpoints": 10,
        "hard_exit": "13:15 IST",
        "engine_mode": "LATEST_AVAILABLE_DATA",
        "data_quality_layer": "UPSTREAM_AUTHORITY",
    }

    print("[4/4] SURVIVAL SIGNAL — TOP 3")
    print_report(selected, metadata)
    json_path, latest_path = write_report(selected, metadata, config.output_dir)
    print(f"Saved: {json_path}")
    print(f"Latest: {latest_path}")
    return 0
