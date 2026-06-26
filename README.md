# Market Sniffer 2000

Market Sniffer 2000 Data Foundation v1 is a durable local market-data warehouse. It is not a dashboard, prediction engine, stock picker, portfolio tool, alerting system, or trading system.

SQLite is the system of record for this milestone. Redis is intentionally not used for Market Sniffer persistent state.

## First Run

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev,yahoo]"
cp .env.example .env
python -m market_sniffer.cli db init
python -m market_sniffer.cli registry validate
python -m market_sniffer.cli validate-sources --allow-missing
python -m market_sniffer.cli verify-foundation --days 5
python -m market_sniffer.cli backfill --profile core --months 24
```

For a local smoke test without external APIs:

```bash
MARKET_SNIFFER_DB_PATH=/tmp/market_sniffer_smoke.sqlite3 \
python -m market_sniffer.cli backfill --profile core --from 2026-01-02 --to 2026-01-06 --only DGS10 --only SPY --fixture
```

## Core Commands

```bash
python -m market_sniffer.cli db init
python -m market_sniffer.cli db summary
python -m market_sniffer.cli registry validate
python -m market_sniffer.cli registry show FRED:DGS10
python -m market_sniffer.cli validate-sources
python -m market_sniffer.cli verify-foundation --days 5
python -m market_sniffer.cli backfill --profile core --months 24
python -m market_sniffer.cli collect --profile daily_market
python -m market_sniffer.cli status
python -m market_sniffer.cli data-health
python -m market_sniffer.cli retention prune-raw-payloads --scope quote --dry-run
python -m market_sniffer.cli inspect series FRED:DGS10 --from 2024-01-01 --to 2026-01-01
python -m market_sniffer.cli inspect instrument MASSIVE:SPY --from 2024-01-01 --to 2026-01-01
```

## Source Roles

Massive / Polygon is primary and canonical for daily equity and ETF bars, future scoped intraday bars, available snapshots, and corporate actions where the user's plan permits.

FRED is canonical for macroeconomic, rates, credit, inflation, labor, housing, growth, liquidity, financial-condition, dollar, commodity, volatility, and recession series.

Yahoo Finance is validation and enrichment now, plus an explicit future quote option. Yahoo is not silently promoted over Massive/Polygon or FRED.

Daily market bars are stored twice by design: `market_bars_daily` keeps source-specific bars, while `canonical_market_bars_daily` stores one downstream bar per instrument, trade date, and price basis. Registry source precedence selects Massive/Polygon first. Yahoo fallback requires explicit configuration, records quality/discrepancy evidence, and preserves source lineage.

Default market backfills end at the most recent completed U.S. equity session using an exchange calendar. Explicit `--to` overrides this and warns when it may include incomplete daily market data. FRED collection can independently include observations through the current date.

Run `verify-foundation --days 5` successfully before the full 24-month production seed.

## Configuration

Configuration comes from environment variables or an untracked `.env` file:

- `MARKET_SNIFFER_DB_PATH`
- `MASSIVE_API_KEY` or `POLYGON_API_KEY`
- `FRED_API_KEY`
- `YAHOO_ENABLED`
- `YAHOO_QUOTES_ENABLED`
- `MARKET_SNIFFER_LOG_LEVEL`

The default database path is `runtime/market_sniffer.sqlite3`, which is ignored by Git along with WAL/SHM files, logs, `.env`, caches, and raw payload directories.
