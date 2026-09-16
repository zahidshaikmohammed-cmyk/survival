# PSYGRID SURVIVAL

A cross-sectional intraday stock-selection engine for the PSYGRID 450-stock universe.

## Source architecture

- 10 stock endpoints: `live-a.json` through `live-j.json`
- The intended universe is 450 stocks across those ten shards
- Market/context endpoints are fetched separately and are treated as optional context
- The PSYGRID stock schema uses `stocks`, `security_id`, `previous_close`, `today_open`, and `candles_1m`

## Execution model

SURVIVAL uses the **latest market state returned by the upstream PSYGRID service at the moment it runs**. There is no local stale-data, timestamp, shard-size, completeness, minimum-bars, duplicate-symbol, or data-quality rejection gate.

The upstream service is authoritative for whether a live market snapshot is available.

When the stock endpoints are live, SURVIVAL:

1. Fetches all ten stock shards concurrently plus configured market/context endpoints.
2. Builds the latest available stock universe.
3. Calculates cross-sectional relative returns, persistence, trend quality, structure, volume participation, VWAP relationship, volatility, noise, exhaustion and market alignment.
4. Generates LONG/SHORT direction from the cross-sectional evidence.
5. Ranks candidates and applies the correlation-diversification penalty.
6. Produces up to three execution plans.
7. Uses a 13:15 IST hard exit.

## Closed market behavior

If all ten stock shards explicitly report `CLOSED`, SURVIVAL does **not** fabricate a Top-3. It writes a `NO TRADE SIGNAL` report with `UPSTREAM_SESSION_CLOSED` status and records which shards were closed.

This is expected behavior when the upstream server has no live stock snapshot available.

## Output

Each run writes:

- `outputs/survival_YYYYMMDD_HHMMSS.json`
- `outputs/survival_latest.json`

The report records the run status, received stock count, available context, endpoint failures, selected trades, entry reference, stop, target and hard exit.

## Run locally

From the repository directory:

```powershell
py -3 survival.py
```

or:

```powershell
python survival.py
```

`--test-now` is retained for compatibility; the current engine already uses the latest upstream state immediately.

## Tests

The production app uses Python standard-library modules.

```powershell
py -3 -m unittest discover -s tests -p "test_*.py" -v
```

## Setup

1. Install Python 3.11+.
2. Clone this repository.
3. Ensure the machine can reach `140.245.226.102:10000`.
4. Run `py -3 survival.py` when the upstream PSYGRID stock endpoints are live.
5. Review `outputs/survival_latest.json` after the run.

No API key or broker credentials are required by this version because it only reads the public PSYGRID endpoints.

## Important

This is a deterministic research/execution-support engine. A signal is not a guarantee of profit, and actual fills can differ from the reference price.
