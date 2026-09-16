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

    print("\n[1/5] FETCHING 10 STOCK SHARDS + INDEX CONTEXT...")
    stock_results, index_results = fetch_endpoints(config)
    print("[2/5] VALIDATING AND MERGING 10 × 45 STOCKS...")
    stocks, indices, validation_errors = assemble_universe(stock_results, index_results, config, cutoff)

    # Never issue a three-stock decision from an incomplete or duplicated universe.
    hard_errors = [e for e in validation_errors if "validated universe" in e or "duplicate symbols" in e]
    if hard_errors or len(stocks) != config.expected_universe:
        print("\nSURVIVAL ABORT — COMPLETE 450-STOCK UNIVERSE NOT VERIFIED.")
        for err in hard_errors[:20]:
            print("  ", err)
        if not hard_errors:
            print(f"  validated stocks={len(stocks)} expected={config.expected_universe}")
        print("No trade list was generated.")
        return 2
    if "nifty" not in indices:
        print("\nSURVIVAL ABORT — required NIFTY context unavailable.")
        return 2

    print("[3/5] BUILDING CROSS-SECTIONAL FEATURES FOR ALL 450 STOCKS...")
    candidates = score_universe(stocks, indices, config)
    print(f"[4/5] CANDIDATES AFTER HARD FILTERS: {len(candidates)}")
    selected = select_top3(candidates, stocks, config)
    if len(selected) != config.final_trades:
        print(f"\nSURVIVAL ABORT — only {len(selected)} executable candidates survived; required {config.final_trades}.")
        return 3

    metadata: dict[str, Any] = {
        "decision_time": decision_now.isoformat(),
        "data_cutoff": cutoff.isoformat(),
        "validated_universe": len(stocks),
        "data_quality": "PASS" if not validation_errors else "PASS_WITH_NONFATAL_STOCK_WARNINGS",
        "nonfatal_validation_warnings": validation_errors[:100],
        "stock_endpoints": 10,
        "index_endpoints": len(index_results),
        "index_context_available": sorted(indices),
        "candidate_count": len(candidates),
        "final_count": len(selected),
        "hard_exit": "13:15 IST",
    }
    print("[5/5] FINALIZING EXECUTION PLAN...")
    print_report(selected, metadata)
    json_path, latest_path = write_report(selected, metadata, config.output_dir)
    print(f"Saved: {json_path}")
    print(f"Latest: {latest_path}")
    return 0
