from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Features


def write_report(features: list[Features], metadata: dict[str, Any], output_dir: str) -> tuple[Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "engine": "PSYGRID SURVIVAL",
        "version": "1.0.0",
        "metadata": metadata,
        "trade_count": len(features),
        "trades": [asdict(x) for x in features],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    json_path = path / f"survival_{stamp}.json"
    latest_path = path / "survival_latest.json"
    json_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    return json_path, latest_path


def print_report(features: list[Features], metadata: dict[str, Any]) -> None:
    print("\n" + "=" * 100)
    print("PSYGRID SURVIVAL — LATEST DECISION")
    print("=" * 100)
    print(
        f"Stocks received: {metadata.get('received_stock_records', 0)} | "
        f"Index series: {metadata.get('index_series_available', 0)} | "
        f"Decision: {metadata.get('decision_time')}"
    )
    print(f"Run status: {metadata.get('run_status', 'UNKNOWN')}")
    print(f"Reason: {metadata.get('run_reason', '')}")

    closed = metadata.get("closed_stock_shards") or []
    failed_stocks = metadata.get("failed_stock_shards") or []
    failed_indices = metadata.get("failed_index_endpoints") or []
    if closed:
        print(f"Closed stock shards: {', '.join(closed)}")
    if failed_stocks:
        print(f"Failed stock shards: {', '.join(failed_stocks)}")
    if failed_indices:
        print(f"Unavailable index/context endpoints: {', '.join(failed_indices)}")

    if features:
        print("\nFINAL 3")
        print("-" * 100)
        for i, f in enumerate(features, 1):
            print(
                f"#{i} {f.symbol:<16} {f.direction:<5} score={f.score:5.1f} "
                f"setup={f.setup:<15} entry={f.entry:.2f} stop={f.stop:.2f} "
                f"target={f.target:.2f} R:R={f.reward_risk:.2f}"
            )
            if f.reasons:
                print("   + " + "; ".join(f.reasons))
            if f.rejection_reasons:
                print("   - " + "; ".join(f.rejection_reasons))
    else:
        print("\nNO TRADE SIGNAL")
        print("-" * 100)
        print("SURVIVAL did not generate a Top-3 because no usable stock universe was available for ranking.")

    print("\nHard exit: 13:15 IST")
    print("Entry is the latest available reference price at signal time; live fill can differ. No software can guarantee profit.")
    print("=" * 100 + "\n")
