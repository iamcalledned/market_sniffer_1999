# Data Foundation Live Verification

## Verification Date and Environment

- Date/time: 2026-06-26 11:35:26 EDT -0400
- OS: Linux ned-builder-iron 6.17.0-35-generic x86_64 GNU/Linux
- Python: 3.12.3
- Package install command used: `python -m pip install -e ".[dev,yahoo]"`
- Verification database path type: `/tmp/...`
- Secrets: no API keys were printed or recorded.

## Repository and Commit

- Branch: `main`
- Starting commit: `7029b2e4c5c2c8499d42bf0c1c2db5858b7a411d`
- Expected commits present: `55a91c7 Remediate data foundation contracts`, `7029b2e Finalize data phase validation`
- Starting `git status --short`: clean before edits.
- Ending `git status --short`: documentation/config/code/test changes pending before this report commit.

## Commands Run

```bash
git status --short
git log --oneline -5
python -m market_sniffer.cli registry validate
python -m market_sniffer.cli validate-sources --allow-missing
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli validate-sources --live
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli verify-foundation --days 5 --db-path /tmp/market_sniffer_verify_live_20260626.sqlite3
python -m pytest
python -m ruff check .
python -m mypy market_sniffer
```

## Source Capability Results

| Source | Operation | Result | Count/Response Summary | Notes |
|---|---|---|---|---|
| FRED | `series/observations DGS10` | PASS | 21 rows | Live source check succeeded. |
| Massive/Polygon | `daily_bars SPY` | PASS | 22 rows, status `OK` | Live source check succeeded. |
| Yahoo | `historical_daily_bars SPY` | PASS | 22 rows, status `ok` | Required `YAHOO_ENABLED=true` and `YAHOO_HISTORICAL_VALIDATION_ENABLED=true`. |

## Verification Date Range

The five completed U.S. equity sessions covered 2026-06-18 through 2026-06-25. Completed trading dates in the range were 2026-06-18, 2026-06-22, 2026-06-23, 2026-06-24, and 2026-06-25.

## FRED Results

| Series | Fetched | Inserted | Skipped | Failed |
|---|---:|---:|---:|---:|
| DGS10 | 4 | 4 | 0 | 0 |
| BAMLH0A0HYM2 | 6 | 6 | 0 | 0 |

FRED observations preserved raw observation lineage and latest-vintage flags. The sample canonical observation had `is_latest_vintage=true`, a raw observation id, and a raw payload id.

## Massive / Polygon Results

| Instrument | Source-Specific Daily Bars | Corporate Actions | Failed |
|---|---:|---:|---:|
| SPY | 5 | 0 | 0 |
| QQQ | 5 | 0 | 0 |

## Yahoo Validation Results

| Instrument | Yahoo Source-Specific Daily Bars | Failed |
|---|---:|---:|
| SPY | 5 | 0 |
| QQQ | 5 | 0 |

Discrepancy breakdown:

| Status | Count |
|---|---:|
| match | 0 |
| minor_difference | 0 |
| material_difference | 0 |
| not_comparable | 10 |
| validation_unavailable | 0 |

## Canonical Daily Bar Results

Canonical daily bars were selected from Massive/Polygon when valid:

| Source | Instrument | Canonical Bars |
|---|---|---:|
| massive | SPY | 5 |
| massive | QQQ | 5 |

The verification database ended with 10 canonical daily bars and 20 source-specific daily bars.

## Data Quality Results

Unresolved quality events: 0.

Verification database counts after first run:

| Table | Count |
|---|---:|
| canonical_daily_bars | 10 |
| canonical_observations | 10 |
| collector_runs | 9 |
| daily_bars | 20 |
| raw_payloads | 8 |
| source_discrepancies | 10 |
| quality_events | 0 |

## Idempotency Rerun Results

The same verification command performed an internal resume rerun for the same date range. It skipped completed FRED, Massive/Polygon, corporate action, and Yahoo validation target/range work.

Counts after the rerun stayed stable for normalized data:

| Table | First Run | Rerun |
|---|---:|---:|
| canonical_observations | 10 | 10 |
| daily_bars | 20 | 20 |
| canonical_daily_bars | 10 | 10 |
| source_discrepancies | 10 | 10 |
| raw_payloads | 8 | 8 |
| collector_runs | 9 | 10 |

The collector run count increased because the parent rerun audit record is retained.

## Known Provider Limitations

The sandboxed Yahoo-enabled preflight initially hit DNS/network failures. The same command succeeded when run with normal network access. No provider entitlement limitation was observed in the final live verification.

## Decision

PASS: Safe to run the 24-month production seed.

## Next Production Command

```bash
python -m market_sniffer.cli backfill --profile core --months 24
```
