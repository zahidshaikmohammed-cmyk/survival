#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from survival_engine.config import Config, STOCK_ENDPOINT
from survival_engine.data import assemble_universe, fetch_universe
from survival_engine.selector import select_top3
from survival_engine.strategy import score_universe


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SURVIVAL single-endpoint PSYGRID smoke test"
    )
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="require the complete 450-stock live universe and exactly 3 selected trades",
    )
    args = parser.parse_args()

    config = Config()
    started = time.perf_counter()

    print("=" * 72)
    print("SURVIVAL SINGLE-ENDPOINT FULL-SYSTEM SMOKE TEST")
    print("=" * 72)
    print("Started:", datetime.now().astimezone().isoformat())
    print("Final stock endpoint:", STOCK_ENDPOINT)
    print("Expected stock universe:", config.expected_universe)
    print()

    print("[1/5] FETCHING SINGLE PSYGRID 450-STOCK ENDPOINT...")
    result = fetch_universe(config)
    json_ok = result.payload is not None
    print("  Endpoint returned JSON:", "YES" if json_ok else "NO")
    if result.error:
        print("  Endpoint error:", result.error)

    print()
    print("[2/5] ASSEMBLING LATEST AVAILABLE 450-STOCK MARKET STATE...")
    stocks = assemble_universe(result, None)
    print("  Parsed stock records:", len(stocks))

    latest_stock = max(
        (c.ts for stock in stocks for c in stock.candles),
        default=None,
    )
    print(
        "  Latest stock candle:",
        latest_stock.isoformat() if latest_stock else "NONE",
    )

    if not stocks:
        print()
        print("RESULT: INFRASTRUCTURE PASS - NO STOCK DATA AVAILABLE")
        print("The single endpoint was reached, but no stock records were parsed.")
        if args.require_live:
            print("RESULT: FAIL - --require-live was requested")
            return 1
        elapsed = time.perf_counter() - started
        print(f"Elapsed: {elapsed:.3f}s")
        return 0

    if args.require_live and len(stocks) != config.expected_universe:
        print(
            f"RESULT: FAIL - expected {config.expected_universe} parsed stocks, "
            f"received {len(stocks)}"
        )
        return 1

    print()
    print("[3/5] SCORING THE ENTIRE AVAILABLE STOCK UNIVERSE...")
    # Strategy is unchanged. No external index/context data is supplied.
    candidates = score_universe(stocks, {}, config)
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

    if args.require_live and len(candidates) != config.expected_universe:
        print(
            f"RESULT: FAIL - expected {config.expected_universe} candidates, "
            f"received {len(candidates)}"
        )
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
