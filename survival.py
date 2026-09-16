#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys

from survival_engine.config import Config
from survival_engine.engine import run_once


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PSYGRID SURVIVAL — latest available market-state decision engine"
    )
    parser.add_argument(
        "--test-now",
        action="store_true",
        help="kept for CLI compatibility; execution already uses the latest available upstream state",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        return run_once(Config(), allow_before_decision=args.test_now)
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except Exception as exc:
        logging.exception("SURVIVAL ENGINE FAILED")
        print(f"FATAL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
