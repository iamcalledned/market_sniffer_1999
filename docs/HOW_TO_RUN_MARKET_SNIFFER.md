# Market Sniffer 2000: How to Run It

## What This Does

Market Sniffer 2000 stores market and macro data in a local SQLite database.

Massive/Polygon is primary for market bars. FRED is primary for macro, rates, and credit data. Yahoo validates selected market history and is prepared for a later quote option, but Yahoo is not canonical in this data phase.

The dashboard and AI are not part of this operational runbook yet.

## One-Time Setup

```bash
git clone https://github.com/iamcalledned/market_sniffer_1999.git
cd market_sniffer_1999
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,yahoo]"
cp .env.example .env
```

## Add Your API Keys

Edit `.env` and set these fields:

```text
MASSIVE_API_KEY or POLYGON_API_KEY
FRED_API_KEY
YAHOO_ENABLED=true
YAHOO_HISTORICAL_VALIDATION_ENABLED=true
YAHOO_QUOTES_ENABLED=false
```

`YAHOO_ENABLED=true` allows Yahoo support. `YAHOO_HISTORICAL_VALIDATION_ENABLED=true` allows registry-driven historical validation. `YAHOO_QUOTES_ENABLED=false` keeps quote polling disabled.

Never commit `.env`.

## Check That Your Sources Work

```bash
python -m market_sniffer.cli registry validate
python -m market_sniffer.cli validate-sources --live
```

Expected result: the registry command reports counts for sources, series, instruments, and profiles. The live source check should report success for FRED, Massive/Polygon, and Yahoo historical validation when Yahoo validation is enabled.

If `.env` is missing keys, run:

```bash
python -m market_sniffer.cli validate-sources --allow-missing
```

## Run the Safe Five-Day Verification

```bash
python -m market_sniffer.cli verify-foundation --days 5
```

This uses a temporary verification database. It checks FRED, Massive/Polygon, Yahoo validation, canonical market bars, data quality, and a rerun to prove idempotency. It does not replace or seed the production database.

## Seed the Last 24 Months

```bash
python -m market_sniffer.cli backfill --profile core --months 24
```

Only run this after the five-day verification passes. It may take time. It is safe to rerun because the database uses uniqueness rules and idempotent inserts. It does not collect live quotes. Run it from the project virtual environment.

## Run a Normal Daily Update

```bash
python -m market_sniffer.cli collect --profile core
```

For daily market bars, this defaults to the last completed U.S. market session. FRED can use its own source update cadence.

## Check Data Health

```bash
python -m market_sniffer.cli status
python -m market_sniffer.cli data-health
python -m market_sniffer.cli db summary
```

Red flags are unresolved quality events, stale data, source failures, validation discrepancies that need review, missing credentials, entitlement failures, and rate-limit failures.

## See What Is in the Database

```bash
python -m market_sniffer.cli registry show FRED:DGS10
python -m market_sniffer.cli inspect series FRED:DGS10 --from 2024-01-01 --to 2026-01-01
python -m market_sniffer.cli inspect instrument MASSIVE:SPY --from 2024-01-01 --to 2026-01-01
```

The configured production database path verified on 2026-06-26 was `/home/ned/data/market_sniffer_1999/market_sniffer.sqlite3`. A SQLite shell check works with:

```bash
sqlite3 /home/ned/data/market_sniffer_1999/market_sniffer.sqlite3
.tables
.quit
```

## If Something Fails

| Problem | First Command to Run | What It Usually Means |
|---|---|---|
| Missing API key | `python -m market_sniffer.cli validate-sources` | `.env` is missing `FRED_API_KEY` or `MASSIVE_API_KEY`/`POLYGON_API_KEY`. |
| Massive entitlement or 403 | `python -m market_sniffer.cli validate-sources --live` | The key works, but the plan may not include the requested endpoint/history. |
| FRED failure | `python -m market_sniffer.cli validate-sources --live` | The key, FRED availability, or a series endpoint needs checking. |
| Yahoo validation failure | `python -m market_sniffer.cli validate-sources --live` | Yahoo support is disabled, `yfinance` is missing, or Yahoo/network access failed. |
| Rate-limit response | `python -m market_sniffer.cli data-health` | A provider throttled the run; wait and rerun safely. |
| Interrupted backfill | `python -m market_sniffer.cli backfill --profile core --months 24 --resume` | The prior run stopped; completed target/range work can be skipped. |
| Stale data-health warning | `python -m market_sniffer.cli status` | A source may not have refreshed or a daily update did not run. |
| Migration error | `python -m market_sniffer.cli db init` | The local database schema did not migrate cleanly. |
| Outside virtual environment | `which python` | The wrong Python environment is active. |

## Important Safety Rules

Do not commit `.env`. Do not commit database files. Do not run `--force` casually. Do not delete raw data casually. Do not treat Yahoo as canonical. Do not enable quote polling yet. Run safe verification before broad backfills after major source changes.
