# Yahoo and Massive Historical Validation Finalization

## Date and Environment

- Date/time: 2026-06-26 11:54:29 EDT -0400
- OS: Linux ned-builder-iron 6.17.0-35-generic x86_64 GNU/Linux
- Python: 3.12.3
- Production database: `/home/ned/data/market_sniffer_1999/market_sniffer.sqlite3`
- Verification database: `/tmp/market_sniffer_verify_finalization_20260626.sqlite3`
- Secrets: no API keys, raw payload bodies, or database files are included.

## Repository and Commit

- Branch: `main`
- Starting commit: `4179580189e56c1473095cfc266e672f06565cb6`
- Finalization commit: the Git commit containing this report, titled `Finalize Yahoo Massive validation basis`.

## Problem Being Fixed

The 24-month seed produced `close | not_comparable | 2008` because Yahoo historical bars and Massive/Polygon bars were not being compared with explicit compatible price-basis semantics. The old logic used the Boolean `adjusted` interpretation and could label a basis mismatch without enough detail.

## Source Price-Basis Semantics

Controlled vocabulary:

```text
raw
split_adjusted
total_return_adjusted
provider_adjusted_unknown
unknown
```

Massive/Polygon daily aggregates are requested with `adjusted=true` and stored as `split_adjusted`.

Yahoo historical validation now calls:

```text
yfinance.Ticker(symbol).history(..., auto_adjust=False, actions=True)
```

Yahoo Close/OHLCV from that call is stored as `split_adjusted`, and Yahoo `Adj Close` is preserved separately. Legacy Yahoo rows collected before this explicit call are labeled `total_return_adjusted`.

## Comparison Policy

Comparison rule version: `daily_bar_validation_v2`.

Policy lives in `config/collection_profiles.yaml`. Current allowed basis pairs are:

```text
split_adjusted -> split_adjusted
raw -> raw
```

The validation compares close and volume for compatible pairs. Incompatible basis pairs become `not_comparable` with structured reason details. Missing source rows or failed provider calls become `validation_unavailable`.

## Commands Run

```bash
git status --short
git log --oneline -8
python -m market_sniffer.cli registry validate
python -m pytest
python -m ruff check .
python -m mypy market_sniffer
MARKET_SNIFFER_DB_PATH=/tmp/market_sniffer_migration_finalization_2.sqlite3 python -m market_sniffer.cli db init
MARKET_SNIFFER_DB_PATH=/tmp/market_sniffer_fixture_finalization.sqlite3 python -m market_sniffer.cli verify-foundation --days 5 --fixture
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli validate-sources --live
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli verify-foundation --days 5 --db-path /tmp/market_sniffer_verify_finalization_20260626.sqlite3
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli validate-history --symbols SPY --symbols QQQ --from 2026-06-18 --to 2026-06-25
python -m market_sniffer.cli db init
python -m market_sniffer.cli data-health
```

## Live Verification Date Range

Five completed U.S. equity sessions: 2026-06-18 through 2026-06-25.

Completed trading dates: 2026-06-18, 2026-06-22, 2026-06-23, 2026-06-24, 2026-06-25.

## SPY Results

Production `validate-history` result for SPY:

| Status | Count |
|---|---:|
| match | 5 |
| minor_difference | 5 |
| material_difference | 0 |
| not_comparable | 0 |
| validation_unavailable | 0 |

The five matches were close comparisons. The five minor differences were volume comparisons.

## QQQ Results

Production `validate-history` result for QQQ:

| Status | Count |
|---|---:|
| match | 5 |
| minor_difference | 5 |
| material_difference | 0 |
| not_comparable | 0 |
| validation_unavailable | 0 |

The five matches were close comparisons. The five minor differences were volume comparisons.

## Discrepancy Summary

Current rule-version production summary for SPY and QQQ over the live range:

| Field | Status | Count |
|---|---|---:|
| close | match | 10 |
| volume | minor_difference | 10 |

Rule-version audit summary:

| Rule Version | Field | Status | Count |
|---|---|---|---:|
| daily_bar_validation_v2 | close | match | 10 |
| daily_bar_validation_v2 | volume | minor_difference | 10 |
| validation_v1 | close | not_comparable | 2008 |

Old `validation_v1` rows remain for audit; normal current reporting should use `daily_bar_validation_v2`.

## Canonical Source Confirmation

Canonical SPY and QQQ bars remained Massive/Polygon:

| Source | Symbol | Price Basis | Count |
|---|---|---|---:|
| massive | QQQ | split_adjusted | 5 |
| massive | SPY | split_adjusted | 5 |

Yahoo remained source-specific validation data only.

## Existing Data Revalidation

The production revalidation command was run twice for idempotency:

```bash
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli validate-history --symbols SPY --symbols QQQ --from 2026-06-18 --to 2026-06-25
```

Both runs returned the same status counts:

| Symbol | match | minor_difference | material_difference | not_comparable | validation_unavailable |
|---|---:|---:|---:|---:|---:|
| SPY | 5 | 5 | 0 | 0 | 0 |
| QQQ | 5 | 5 | 0 | 0 | 0 |

Production basis labels for the same range:

| Source | Symbol | Price Basis | Count |
|---|---|---|---:|
| massive | QQQ | split_adjusted | 5 |
| massive | SPY | split_adjusted | 5 |
| yahoo | QQQ | split_adjusted | 5 |
| yahoo | QQQ | total_return_adjusted | 5 |
| yahoo | SPY | split_adjusted | 5 |
| yahoo | SPY | total_return_adjusted | 5 |

The `total_return_adjusted` Yahoo rows are legacy validation records retained for audit. The current comparable rows are `split_adjusted`.

## Data Health

```text
new_quote_freshness_events=0
unresolved_quality_events=0
```

Post-revalidation counts:

| Table | Count |
|---|---:|
| canonical_daily_bars | 33132 |
| canonical_observations | 11674 |
| daily_bars | 35150 |
| source_discrepancies | 2028 |
| quote_snapshots | 0 |

## Known Limitations

Volume comparisons are currently minor differences for SPY and QQQ over the tested range. They are retained as evidence, not forced into match status.

Yahoo legacy `validation_v1` rows remain in the database for audit and are separated by comparison rule version.

Quote polling remains disabled.

## Decision

PASS: Data phase complete.
