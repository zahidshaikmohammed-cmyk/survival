from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .config import Config
from .data import IST, assemble_universe, fetch_endpoints
from .report import print_report, write_report
from .selector import select_top3
from .strategy import score_universe


def now_ist() -> datetime:
    return datetime.now(IST)


def wait_until_decision(config: Config) -> datetime:
    now = now_ist()
    target = datetime.combine(now.date(), config.decision_time, tzinfo=IST)
    if now < target:
        seconds = (target - now).total_seconds()
        print(f"SURVIVAL armed. Waiting {seconds:.0f}s until {target.strftime('%H:%M:%S')} IST...")
        time.sleep(seconds)
        now = now_ist()
    return now


def _cutoff_for_day(now: datetime, config: Config) -> datetime:
    return datetime.combine(now.date(), config.data_cutoff_time, tzinfo=IST)


def run_once(config: Config, allow_before_decision: bool = False) -> int:
    decision_now = now_ist() if allow_before_decision else wait_until_decision(config)
    cutoff = _cutoff_for_day(decision_now, config)

    print("\n[1/4] FETCHING PSYGRID: 10 STOCK SHARDS + INDEX CONTEXT...")
    stock_results, index_results = fetch_endpoints(config)

    print("[2/4] BUILDING THE 450-STOCK STRATEGY UNIVERSE...")
    # Upstream acquisition is authoritative by design. No stale-data,
    # malformed-data, shard-count, duplicate, or completeness gate lives here.
    stocks, indices = assemble_universe(stock_results, index_results, cutoff)

    print(f"    STOCKS RECEIVED: {len(stocks)}")
    print(f"    INDEX SERIES AVAILABLE: {len(indices)}")
    print("[3/4] RUNNING STRATEGY ACROSS THE ENTIRE UNIVERSE...")
    candidates = score_universe(stocks, indices, config)

    # Strategy is responsible for ranking. We do not abort merely because a
    # candidate score is below a threshold; the selector chooses the three
    # strongest opportunities produced by the model.
    selected = select_top3(candidates, stocks, config)

    metadata: dict[str, Any] = {
        "decision_time": decision_now.isoformat(),
        "data_cutoff": cutoff.isoformat(),
        "received_stock_records": len(stocks),
        "index_context_available": sorted(indices),
        "candidate_count": len(candidates),
        "final_count": len(selected),
        "stock_endpoints": 10,
        "hard_exit": "13:15 IST",
        "engine_mode": "STRATEGY_ONLY",
        "data_quality_layer": "UPSTREAM_AUTHORITY",
    }

    print("[4/4] FINAL 3-STOCK EXECUTION PLAN")
    print_report(selected, metadata)
    json_path, latest_path = write_report(selected, metadata, config.output_dir)
    print(f"Saved: {json_path}")
    print(f"Latest: {latest_path}")
    return 0
