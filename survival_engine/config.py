from __future__ import annotations

from dataclasses import dataclass
from datetime import time

# Single authoritative PSYGRID endpoint containing the complete 450-stock universe.
BASE_URL = "http://140.245.226.102:10000/public"
STOCK_ENDPOINT = f"{BASE_URL}/live.json"


@dataclass(frozen=True)
class Config:
    decision_time: time = time(11, 1)
    data_cutoff_time: time = time(11, 0)
    hard_exit_time: time = time(13, 15)
    market_open_time: time = time(9, 15)

    # Runtime only; these are not strategy/data gates.
    request_timeout_seconds: float = 8.0
    request_retries: int = 2
    max_workers: int = 4

    # Universe definition.
    expected_universe: int = 450
    final_trades: int = 3

    # Strategy windows.
    atr_window: int = 20
    volume_window: int = 20
    mid_window: int = 15
    long_window: int = 30
    correlation_window: int = 30

    # Cross-sectional portfolio construction.
    max_pair_correlation: float = 0.82
    correlation_penalty: float = 8.0

    # Execution engineering.
    target_r_multiple: float = 1.55
    stop_atr_multiple: float = 0.85

    # Tradability constraints are strategy rules, not data-quality checks.
    minimum_price: float = 20.0
    minimum_avg_volume: float = 1000.0

    output_dir: str = "outputs"
    log_dir: str = "logs"
    snapshot_dir: str = "snapshots"
