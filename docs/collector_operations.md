# Collector Operations

## Database Initialization

```bash
python -m market_sniffer.cli db init
```

This runs Alembic migrations, creates the SQLite database, enables WAL/foreign keys/busy timeout, and bootstraps registry records.

## First-Run 24-Month Seed

```bash
python -m market_sniffer.cli backfill --profile core --months 24
```

The command dynamically calculates a 24-calendar-month window ending on the execution date. Use `--from` and `--to` to override the window.

## Incremental Collection

```bash
python -m market_sniffer.cli collect --profile daily_market
```

Incremental collection defaults to the current date unless overridden.

## Fixture Smoke Backfill

```bash
MARKET_SNIFFER_DB_PATH=/tmp/market_sniffer_smoke.sqlite3 \
python -m market_sniffer.cli backfill --profile core --from 2026-01-02 --to 2026-01-06 --only DGS10 --only SPY --fixture
```

## Resume and Retry

Daily bars and FRED observations use uniqueness constraints, so rerunning an interrupted date range skips completed rows. `collector_runs` and child runs preserve fetched, inserted, skipped, and failed counts plus error context. `--continue-on-error` records source failures and keeps moving.

## Health and Inspection

```bash
python -m market_sniffer.cli status
python -m market_sniffer.cli data-health
python -m market_sniffer.cli registry show FRED:DGS10
python -m market_sniffer.cli inspect series FRED:DGS10 --from 2024-01-01 --to 2026-01-01
python -m market_sniffer.cli inspect instrument MASSIVE:SPY --from 2024-01-01 --to 2026-01-01
```

## Troubleshooting

Missing credentials: run `python -m market_sniffer.cli validate-sources`. Provider entitlement or rate-limit errors become `data_quality_events`.

Schema changes: add a SQLAlchemy model change and a new Alembic revision. Do not hand-edit a live SQLite schema.

Adding a series or instrument: update the registry YAML, run `registry validate`, then `db init` to sync registry records.

Future quote support: set `YAHOO_ENABLED=true` and `YAHOO_QUOTES_ENABLED=true` only when a quote collector command is implemented and source delay/quality metadata is documented. Normal backfills do not poll quotes.
