# PSYGRID SURVIVAL

A cross-sectional intraday stock-selection engine for the PSYGRID 450-stock universe.

## Source architecture

- One stock endpoint: `live.json`
- The endpoint contains the complete 450-stock universe under `stocks`
- No stock shards are used
- No NIFTY, BANK NIFTY, SENSEX, sector-index, or India VIX endpoint is used by SURVIVAL
- The PSYGRID stock schema uses `stocks`, `security_id`, `previous_close`, `today_open`, and `candles_1m`

## Execution model

SURVIVAL uses the **latest market state returned by the upstream PSYGRID service at the moment it runs**. There is no local stale-data, timestamp, completeness, minimum-bars, duplicate-symbol, or data-quality rejection gate.

The upstream service is authoritative for whether a live market snapshot is available.

When the stock endpoint is live, SURVIVAL:

1. Fetches the single `live.json` endpoint containing the 450-stock universe.
2. Builds the latest available stock universe.
3. Applies the existing strategy unchanged, using the stock cross-section as its available reference data and no external index/context series.
4. Calculates cross-sectional relative returns, persistence, trend quality, structure, volume participation, VWAP relationship, volatility, noise and exhaustion.
5. Generates LONG/SHORT direction from the existing cross-sectional evidence.
6. Ranks candidates and applies the existing correlation-diversification penalty.
7. Produces up to three execution plans.
8. Uses a 13:15 IST hard exit.

## Closed market behavior

If the single stock endpoint explicitly reports `CLOSED`, SURVIVAL does **not** fabricate a Top-3. It writes a `NO TRADE SIGNAL` report with `UPSTREAM_SESSION_CLOSED` status.

This is expected behavior when the upstream server has no live stock snapshot available.

## Output

Each run writes:

- `outputs/survival_YYYYMMDD_HHMMSS.json`
- `outputs/survival_latest.json`

The report records the run status, received stock count, selected trades, entry reference, stop, target and hard exit.

## Run locally

From the repository directory:

```powershell
py -3 survival.py
```

or:

```powershell
python survival.py
```

`--test-now` is retained for CLI compatibility; the current engine already uses the latest upstream state immediately.

## Live smoke test

To test the complete live pipeline against the single endpoint and require exactly three selected trades:

```powershell
py -3 smoke_test.py --require-live
```

Expected live path:

```text
Single endpoint → 450 stocks → 450 candidates → 3 selected trades
```

## Tests

The production app uses Python standard-library modules.

```powershell
py -3 -m unittest discover -s tests -p "test_*.py" -v
```

The unit suite includes explicit coverage that one PSYGRID payload can parse and score all 450 stock records.

## Setup

1. Install Python 3.11+.
2. Clone this repository.
3. Ensure the machine can reach `140.245.226.102:10000`.
4. Run `py -3 survival.py` when the upstream PSYGRID stock endpoint is live.
5. Review `outputs/survival_latest.json` after the run.

No API key or broker credentials are required by this version because it only reads the public PSYGRID endpoint.

## Important

This is a deterministic research/execution-support engine. A signal is not a guarantee of profit, and actual fills can differ from the reference price.
