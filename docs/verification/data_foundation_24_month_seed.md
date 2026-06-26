# Data Foundation 24-Month Seed

## Seed Date and Environment

- Date/time: 2026-06-26 11:35:26 EDT -0400
- OS: Linux ned-builder-iron 6.17.0-35-generic x86_64 GNU/Linux
- Python: 3.12.3
- Package install command used: `python -m pip install -e ".[dev,yahoo]"`
- Production database path: `/home/ned/data/market_sniffer_1999/market_sniffer.sqlite3`
- Secrets: no API keys were printed or recorded.

## Repository and Commit

- Branch: `main`
- Starting commit: `7029b2e4c5c2c8499d42bf0c1c2db5858b7a411d`
- Expected commits present: `55a91c7 Remediate data foundation contracts`, `7029b2e Finalize data phase validation`
- Starting `git status --short`: clean before edits.
- Ending `git status --short`: documentation/config/code/test changes pending before this report commit.

## Command Run

Production seed command:

```bash
python -m market_sniffer.cli backfill --profile core --months 24
```

Post-seed validation commands:

```bash
python -m market_sniffer.cli db init
python -m market_sniffer.cli data-health
python -m market_sniffer.cli db summary
python -m market_sniffer.cli status
python -m market_sniffer.cli inspect series FRED:DGS10 --from 2024-01-01 --to 2026-12-31 --limit 5
python -m market_sniffer.cli inspect series FRED:BAMLH0A0HYM2 --from 2024-01-01 --to 2026-12-31 --limit 5
python -m market_sniffer.cli inspect instrument MASSIVE:SPY --from 2024-01-01 --to 2026-12-31 --limit 5
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli backfill --profile core --from 2026-06-18 --to 2026-06-25 --only DGS10 --only BAMLH0A0HYM2 --only SPY --only QQQ
```

## Effective Date Window

- Effective market end date: 2026-06-25, the most recent completed U.S. equity session.
- Effective FRED end date: 2026-06-26.
- Observed canonical market bar range after seed: 2024-06-25 through 2026-06-25.
- Observed canonical FRED observation range after seed: 2024-04-01 through 2026-06-25. Some lower-frequency macro series have observation dates before the calculated collection start because their current period began earlier.

## Source and Profile Scope

The seed used the `core` profile:

- `fred_macro`: FRED macro, rates, and credit series.
- `daily_market`: Massive/Polygon daily market bars and corporate action checks.
- `validation`: Yahoo historical validation sample when Yahoo validation is enabled.

Quote polling remained disabled. Future intraday collection was not enabled.

## Result Summary

PASS. The production database contains real, source-traceable data from FRED, Massive/Polygon, and Yahoo validation rows. The post-seed health check reported zero unresolved quality events.

One transient Massive/Polygon timeout for IWD occurred during the seed, was recorded as a resolved quality event, and the resumed run completed successfully.

## Database Counts

Final production counts after the idempotency slice:

| Table | Count |
|---|---:|
| canonical_daily_bars | 33132 |
| canonical_observations | 11674 |
| collector_runs | 201 |
| corporate_actions | 0 |
| daily_bars | 35140 |
| instruments | 66 |
| quality_events | 1 |
| quote_snapshots | 0 |
| raw_payloads | 191 |
| series | 45 |
| source_discrepancies | 2008 |
| sources | 3 |

Collector run summary:

| Collector | Status | Count |
|---|---|---:|
| backfill | failed | 1 |
| backfill | succeeded | 5 |
| fred_observations | succeeded | 48 |
| massive_corporate_actions | succeeded | 69 |
| massive_daily_bars | failed | 1 |
| massive_daily_bars | succeeded | 70 |
| yahoo_validation_history | succeeded | 7 |

## Data Health Results

```text
new_quote_freshness_events=0
unresolved_quality_events=0
```

Quality event summary:

| Event Type | Severity | Resolved | Source | Symbol | Count |
|---|---|---:|---|---|---:|
| collector_failure | error | 1 | massive | IWD | 1 |

Discrepancy summary:

| Field | Status | Count |
|---|---|---:|
| close | not_comparable | 2008 |

## Sample Lineage Checks

FRED DGS10 inspection returned canonical observations with source id and raw observation lineage, beginning:

```text
DGS10 2024-06-25 value=4.2300000000 unit=percent source_id=2 raw_observation_id=2995
```

FRED BAMLH0A0HYM2 inspection returned canonical observations with source id and raw observation lineage, beginning:

```text
BAMLH0A0HYM2 2024-06-25 value=3.1900000000 unit=percent source_id=2 raw_observation_id=6724
```

SPY inspection returned both Massive/Polygon and Yahoo source-specific rows. Canonical selection for the five-day idempotency slice stayed on Massive/Polygon:

| Source | Instrument | Source-Specific Bars |
|---|---|---:|
| massive | SPY | 5 |
| massive | QQQ | 5 |
| yahoo | SPY | 5 |
| yahoo | QQQ | 5 |

| Canonical Source | Instrument | Canonical Bars |
|---|---|---:|
| massive | SPY | 5 |
| massive | QQQ | 5 |

## Idempotency Check

The production idempotency command used the verified five-session range:

```bash
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli backfill --profile core --from 2026-06-18 --to 2026-06-25 --only DGS10 --only BAMLH0A0HYM2 --only SPY --only QQQ
```

Results:

| Target | Fetched | Inserted | Skipped | Failed |
|---|---:|---:|---:|---:|
| FRED DGS10 | 4 | 0 | 4 | 0 |
| FRED BAMLH0A0HYM2 | 6 | 0 | 6 | 0 |
| Massive SPY | 5 | 0 | 5 | 0 |
| Massive QQQ | 5 | 0 | 5 | 0 |
| Massive corporate actions SPY | 0 | 0 | 0 | 0 |
| Massive corporate actions QQQ | 0 | 0 | 0 | 0 |
| Yahoo validation SPY | 5 | 0 | 5 | 0 |
| Yahoo validation QQQ | 5 | 0 | 5 | 0 |

No duplicate canonical observations, source bars, or canonical daily bars were inserted.

## Failures or Limitations

- A transient Massive/Polygon read timeout for IWD was observed during the 24-month seed. It was captured as a resolved quality event and did not block final completion.
- Yahoo validation discrepancies are currently `close/not_comparable`, reflecting basis comparability rather than canonical source failure.
- Quote snapshots remain disabled and were not collected.

## Decision

PASS
