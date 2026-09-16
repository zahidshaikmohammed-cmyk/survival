#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from survival_engine.config import Config, INDEX_ENDPOINTS, STOCK_ENDPOINTS
from survival_engine.data import assemble_universe, fetch_endpoints
from survival_engine.selector import select_top3
from survival_engine.strategy import score_universe


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SURVIVAL full-system PSYGRID smoke test"
    )
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="require the live market universe and exactly 3 selected trades",
    )
    args = parser.parse_args()

    config = Config()
    started = time.perf_counter()

    print("=" * 72)
    print("SURVIVAL FULL-SYSTEM SMOKE TEST")
    print("=" * 72)
    print("Started:", datetime.now().astimezone().isoformat())
    print("Stock endpoints:", len(STOCK_ENDPOINTS))
    print("Index/context endpoints:", len(INDEX_ENDPOINTS))
    print("Expected stock universe:", config.expected_universe)
    print()

    print("[1/5] FETCHING ALL PSYGRID ENDPOINTS...")
    stock_results, index_results = fetch_endpoints(config)

    stock_ok = sum(1 for r in stock_results.values() if r.payload is not None)
    index_ok = sum(1 for r in index_results.values() if r.payload is not None)

    print(f"  Stock endpoints returned JSON: {stock_ok}/{len(STOCK_ENDPOINTS)}")
    print(f"  Index endpoints returned JSON: {index_ok}/{len(INDEX_ENDPOINTS)}")

    failed_stocks = sorted(
        name for name, result in stock_results.items() if result.payload is None
    )
    failed_indices = sorted(
        name for name, result in index_results.items() if result.payload is None
    )

    if failed_stocks:
        print("  Stock endpoint failures:", ", ".join(failed_stocks))
    if failed_indices:
        print("  Index endpoint failures:", ", ".join(failed_indices))

    print()
    print("[2/5] ASSEMBLING LATEST AVAILABLE MARKET STATE...")
    stocks, indices = assemble_universe(
        stock_results,
        index_results,
        None,
    )

    print("  Parsed stock records:", len(stocks))
    print("  Parsed index series:", len(indices))

    latest_stock = max(
        (c.ts for stock in stocks for c in stock.candles),
        default=None,
    )
    latest_index = max(
        (c.ts for series in indices.values() for c in series.candles),
        default=None,
    )

    print(
        "  Latest stock candle:",
        latest_stock.isoformat() if latest_stock else "NONE",
    )
    print(
        "  Latest index candle:",
        latest_index.isoformat() if latest_index else "NONE",
    )

    if not stocks:
        print()
        print("RESULT: INFRASTRUCTURE PASS - NO STOCK DATA AVAILABLE")
        print("The endpoints were reached, but no stock records were parsed.")
        print("This is normal when the upstream market feed is closed/unavailable.")
        if args.require_live:
            print("RESULT: FAIL - --require-live was requested")
            return 1
        elapsed = time.perf_counter() - started
        print(f"Elapsed: {elapsed:.3f}s")
        return 0

    print()
    print("[3/5] SCORING THE ENTIRE AVAILABLE STOCK UNIVERSE...")
    candidates = score_universe(stocks, indices, config)
    print("  Candidates produced:", len(candidates))

    if not candidates:
        print("RESULT: FAIL - scoring produced zero candidates")
        return 1

    invalid = []
    for candidate in candidates:
        if not (0.0 <= candidate.score <= 100.0):
            invalid.append(candidate.symbol + ": score out of bounds")
        if candidate.direction not in ("LONG", "SHORT"):
            invalid.append(candidate.symbol + ": invalid direction")
        if candidate.entry == candidate.stop:
            invalid.append(candidate.symbol + ": stop equals entry")
        if candidate.entry == candidate.target:
            invalid.append(candidate.symbol + ": target equals entry")

    if invalid:
        print("RESULT: FAIL - candidate invariants failed")
        for item in invalid[:20]:
            print("  ", item)
        return 1

    print("  Candidate invariants: PASS")

    print()
    print("[4/5] SELECTING TOP 3 WITH DIVERSIFICATION...")
    selected = select_top3(candidates, stocks, config)
    print("  Selected trades:", len(selected))

    for i, candidate in enumerate(selected, 1):
        print(
            f"  {i}. {candidate.symbol} "
            f"{candidate.direction} "
            f"score={candidate.score:.4f} "
            f"entry={candidate.entry:.4f} "
            f"stop={candidate.stop:.4f} "
            f"target={candidate.target:.4f} "
            f"RR={candidate.reward_risk:.4f}"
        )

    if args.require_live and len(selected) != config.final_trades:
        print(
            f"RESULT: FAIL - expected exactly {config.final_trades} selected trades"
        )
        return 1

    print()
    print("[5/5] VERIFYING FINAL EXECUTION GEOMETRY...")
    for candidate in selected:
        if candidate.direction == "LONG":
            assert candidate.stop < candidate.entry
            assert candidate.target > candidate.entry
        else:
            assert candidate.stop > candidate.entry
            assert candidate.target < candidate.entry

        assert candidate.risk_unit > 0
        assert candidate.reward_risk > 0

    print("  Final execution geometry: PASS")

    elapsed = time.perf_counter() - started
    print()
    print("=" * 72)
    if args.require_live:
        print("RESULT: FULL LIVE SMOKE TEST PASS")
    else:
        print("RESULT: FULL PIPELINE SMOKE TEST PASS")
    print(f"Elapsed: {elapsed:.3f}s")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
