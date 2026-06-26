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

The command dynamically calculates a 24-calendar-month window. Market bars end at the most recent completed U.S. equity trading session. FRED can use the current date independently. Use `--from` and `--to` to override the window; market commands warn if the explicit end date may include incomplete bars.

Run the constrained live verification first:

```bash
python -m market_sniffer.cli verify-foundation --days 5
```

It loads DGS10, BAMLH0A0HYM2, SPY, QQQ, Yahoo validation records, canonicalizes bars, runs health checks, reruns the same range, and reports idempotency counts. Do not run the full production seed until this passes or provider limitations are explicitly accepted.

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
python -m market_sniffer.cli retention prune-raw-payloads --scope quote --dry-run
python -m market_sniffer.cli registry show FRED:DGS10
python -m market_sniffer.cli inspect series FRED:DGS10 --from 2024-01-01 --to 2026-01-01
python -m market_sniffer.cli inspect instrument MASSIVE:SPY --from 2024-01-01 --to 2026-01-01
```

## Troubleshooting

Missing credentials: run `python -m market_sniffer.cli validate-sources`. Provider entitlement or rate-limit errors become `data_quality_events`.

Schema changes: add a SQLAlchemy model change and a new Alembic revision. Do not hand-edit a live SQLite schema.

Adding a series or instrument: update the registry YAML, run `registry validate`, then `db init` to sync registry records.

Future quote support: set `YAHOO_ENABLED=true` and `YAHOO_QUOTES_ENABLED=true` only when a quote collector command is implemented and source delay/quality metadata is documented. Normal backfills do not poll quotes.

## FRED Current and Point-in-Time Reads

FRED revisions are inserted as separate vintages keyed by observation date and `realtime_start`. Normal current reports use `latest_fred_value`. Historical analysis can call `fred_value_as_of` to avoid using revised values unavailable at the requested date. If FRED omits vintage metadata, the collector records a quality event and uses the observation date as the vintage key.

## Retention

FRED, daily OHLCV, corporate action, canonical, collector-run, quality-event, and discrepancy lineage is retained indefinitely. Quote, intraday, repeated validation, and high-frequency snapshot raw payload bodies are eligible for configured pruning, initially 90 days. Pruning is manual and dry-run capable; incident-linked and canonical-linked payloads are protected.

## Quote Quality

Quote quality labels are `live`, `near_real_time`, `delayed`, `last_known`, `stale`, `market_closed`, `unavailable`, and `unknown`. The system labels a quote `live` only when provider metadata supports that claim. Normal backfills never invoke quote retrieval.
