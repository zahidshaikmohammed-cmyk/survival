from __future__ import annotations

from dataclasses import dataclass
from datetime import time

BASE_URL = "http://140.245.226.102:10000/public"

# Exactly ten stock shards: live-a through live-j = the 450-stock universe.
STOCK_ENDPOINTS = {letter: f"{BASE_URL}/live-{letter}.json" for letter in "abcdefghij"}

# Market/context series used by the strategy as reference information.
INDEX_ENDPOINTS = {
    "nifty": f"{BASE_URL}/nifty.json",
    "banknifty": f"{BASE_URL}/banknifty.json",
    "sensex": f"{BASE_URL}/sensex.json",
    "nifty500": f"{BASE_URL}/nifty500.json",
    "niftymidcap100": f"{BASE_URL}/niftymidcap100.json",
    "niftysmallcap100": f"{BASE_URL}/niftysmallcap100.json",
    "finnifty": f"{BASE_URL}/finnifty.json",
    "indiavix": f"{BASE_URL}/indiavix.json",
    "niftyit": f"{BASE_URL}/niftyit.json",
    "niftyauto": f"{BASE_URL}/niftyauto.json",
    "niftypharma": f"{BASE_URL}/niftypharma.json",
    "niftymetal": f"{BASE_URL}/niftymetal.json",
    "niftyfmcg": f"{BASE_URL}/niftyfmcg.json",
    "niftyrealty": f"{BASE_URL}/niftyrealty.json",
    "niftyenergy": f"{BASE_URL}/niftyenergy.json",
    "niftyinfra": f"{BASE_URL}/niftyinfra.json",
}


@dataclass(frozen=True)
class Config:
    decision_time: time = time(11, 1)
    data_cutoff_time: time = time(11, 0)
    hard_exit_time: time = time(13, 15)
    market_open_time: time = time(9, 15)

    # Runtime only; these are not strategy/data gates.
    request_timeout_seconds: float = 8.0
    request_retries: int = 2
    max_workers: int = 20

    # Universe definition.
    expected_shards: int = 10
    expected_stocks_per_shard: int = 45
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
