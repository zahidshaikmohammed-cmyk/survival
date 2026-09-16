# PSYGRID SURVIVAL

A fail-safe 11:01 IST cross-sectional stock-selection engine for the PSYGRID 450-stock universe.

## Source architecture

- 10 stock endpoints: `live-a.json` through `live-j.json`
- Each stock endpoint is expected to contain 45 stocks
- Total required universe: exactly 450 unique stocks
- Index/context endpoints are fetched separately, with NIFTY required for a valid run
- The PSYGRID sample response schema uses `stocks`, `security_id`, `previous_close`, `today_open`, and `candles_1m`

## Decision protocol

1. Wait until 11:01 IST when run normally.
2. Fetch all 10 stock shards concurrently plus configured index endpoints.
3. Discard data after the 11:00 IST information cutoff.
4. Validate each candle and reject malformed or stale stock histories.
5. Refuse to issue trades if the 450-stock universe cannot be verified.
6. Calculate cross-sectional relative returns, persistence, trend quality, structure, volume participation, VWAP relationship, volatility, noise, exhaustion and market alignment.
7. Generate direction from the cross-sectional evidence.
8. Rank candidates and apply a correlation-diversification penalty.
9. Produce exactly three execution plans when three candidates satisfy the hard filters.
10. Output entry, stop, target, R:R, reasons and a 13:15 IST hard exit.

## Important

This is a deterministic trading research/execution engine. No software can guarantee that three stocks will be profitable. The engine therefore has a hard safety rule: **incomplete or corrupted market data means NO TRADE LIST**, rather than fabricating three signals.

## Run locally

```bash
python survival.py
```

For a smoke test without waiting for 11:01:

```bash
python survival.py --test-now
```

## Tests

The production app uses only Python standard-library modules.

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

## Manual setup

1. Install Python 3.11+ on the Windows machine that will run the engine.
2. Clone this repository.
3. Run `python survival.py` around 11:00; the program waits for 11:01 if started early.
4. Keep internet access available to `140.245.226.102:10000`.
5. The endpoint server must be live and have complete 1-minute data through 11:00 IST.
6. Review `outputs/survival_latest.json` after the decision.

No API key or broker credentials are required by this version because it only reads the public PSYGRID endpoints.
