from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import Config, STOCK_ENDPOINT
from .data import IST, assemble_universe, fetch_universe
from .report import print_report, write_report
from .selector import select_top3
from .adaptive import score_universe


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
    """Run SURVIVAL against the single latest 450-stock PSYGRID snapshot."""
    decision_now = now_ist()

    print("\n[1/4] FETCHING PSYGRID: SINGLE 450-STOCK ENDPOINT...")
    result = fetch_universe(config)

    print("[2/4] BUILDING THE LATEST AVAILABLE 450-STOCK UNIVERSE...")
    stocks = assemble_universe(result, None)

    latest_stock_ts = max(
        (c.ts for stock in stocks for c in stock.candles),
        default=None,
    )
    status = _payload_status(result)

    print(f"    ENDPOINT: {STOCK_ENDPOINT}")
    print(f"    JSON RECEIVED: {'YES' if result.payload is not None else 'NO'}")
    print(f"    UPSTREAM STATUS: {status or 'UNKNOWN'}")
    print(f"    STOCKS RECEIVED: {len(stocks)}")
    print(
        f"    LATEST STOCK CANDLE: "
        f"{latest_stock_ts.isoformat() if latest_stock_ts else 'N/A'}"
    )

    if status == "CLOSED" or not stocks:
        run_status = "UPSTREAM_SESSION_CLOSED" if status == "CLOSED" else "NO_STOCK_DATA"
        reason = (
            "The single PSYGRID stock endpoint reports CLOSED; no live stock decision is generated."
            if status == "CLOSED"
            else "No stock records were parsed from the single PSYGRID stock endpoint."
        )
        metadata: dict[str, Any] = {
            "decision_time": decision_now.isoformat(),
            "data_cutoff": None,
            "latest_stock_candle": latest_stock_ts.isoformat() if latest_stock_ts else None,
            "received_stock_records": len(stocks),
            "expected_universe": config.expected_universe,
            "candidate_count": 0,
            "final_count": 0,
            "stock_endpoint": STOCK_ENDPOINT,
            "hard_exit": "13:15 IST",
            "engine_mode": "LATEST_AVAILABLE_DATA",
            "data_quality_layer": "UPSTREAM_AUTHORITY",
            "run_status": run_status,
            "run_reason": reason,
            "endpoint_error": result.error,
            "upstream_status": status,
        }
        print("[3/4] NO TRADE — NO LIVE 450-STOCK UNIVERSE AVAILABLE")
        print("[4/4] WRITING NO-SIGNAL REPORT")
        print_report([], metadata)
        json_path, latest_path = write_report([], metadata, config.output_dir)
        print(f"Saved: {json_path}")
        print(f"Latest: {latest_path}")
        return 0

    print("[3/4] RUNNING SURVIVAL ACROSS ALL AVAILABLE STOCKS...")
    candidates = score_universe(stocks, {}, config)
    selected = select_top3(candidates, stocks, config)

    metadata = {
        "decision_time": decision_now.isoformat(),
        "data_cutoff": None,
        "latest_stock_candle": latest_stock_ts.isoformat() if latest_stock_ts else None,
        "received_stock_records": len(stocks),
        "expected_universe": config.expected_universe,
        "candidate_count": len(candidates),
        "final_count": len(selected),
        "stock_endpoint": STOCK_ENDPOINT,
        "hard_exit": "13:15 IST",
        "engine_mode": "LATEST_AVAILABLE_DATA",
        "data_quality_layer": "UPSTREAM_AUTHORITY",
        "run_status": "SIGNALS_GENERATED" if selected else "NO_CANDIDATES",
        "run_reason": "Adaptive structural ranking completed on the single upstream 450-stock snapshot.",
        "endpoint_error": result.error,
        "upstream_status": status,
    }

    print("[4/4] SURVIVAL SIGNAL — TOP 3")
    print_report(selected, metadata)
    json_path, latest_path = write_report(selected, metadata, config.output_dir)
    print(f"Saved: {json_path}")
    print(f"Latest: {latest_path}")
    return 0
