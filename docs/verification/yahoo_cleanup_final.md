# Yahoo Cleanup Final Verification

## Date and Environment

- Date/time: 2026-06-26 12:13:38 EDT -0400
- OS: Linux ned-builder-iron 6.17.0-35-generic x86_64 GNU/Linux
- Python: 3.12.3
- Production database: `/home/ned/data/market_sniffer_1999/market_sniffer.sqlite3`
- Secrets: no API keys, raw payload bodies, logs, or database files are included.

## Repository and Commit

- Branch: `main`
- Starting commit: `7d684fe5531f2e736817a95180979949e0ec0309`
- Cleanup commit: this report is committed with the Yahoo cleanup change.

## What Was Cleaned Up

- Replaced overconfident Yahoo `split_adjusted` language with bounded provider-native terminology.
- Kept Yahoo historical validation source-specific and non-canonical.
- Added active-vs-legacy validation summary reporting.
- Added corporate-action validation review guardrail.
- Tightened quote safety language without enabling quote polling.

## Yahoo Field and Adjustment Semantics

Yahoo historical validation requests:

```text
history(..., auto_adjust=False, actions=True)
```

Yahoo `Close` is stored as provider-native `provider_adjusted_unknown`. Yahoo `Adj Close` is retained separately in `adjusted_close`. The system does not claim universal Yahoo corporate-action adjustment semantics.

Massive/Polygon remains the canonical daily-bar source and uses provider aggregates requested with `adjusted=true`, stored as `split_adjusted`.

## Comparison Eligibility Policy

Validation eligibility is policy-controlled in `config/collection_profiles.yaml`.

The active policy approves Massive/Polygon vs Yahoo `close` and `volume` comparisons for the tested provider-native Yahoo `Close` behavior because SPY/QQQ compatibility was observed. The policy says to revalidate after major provider/library changes or corporate-action events.

## Active Rule Version

```text
daily_bar_validation_v3
```

## Legacy Audit Handling

Routine summaries default to the active rule only:

```bash
python -m market_sniffer.cli validation summary --current
```

Audit summaries include all rule versions:

```bash
python -m market_sniffer.cli validation summary --all-rules
```

Legacy `validation_v1` and `daily_bar_validation_v2` rows remain queryable. They do not pollute the current v3 summary.

## Corporate-Action Guardrail

`validate-history` checks existing corporate-action records for the requested symbol/date range. If known actions exist, it records a `validation_adjustment_review` quality event with the message that adjustment compatibility should be reviewed.

No broad adjustment engine was added. If no corporate-action records exist, the guardrail is limited to available records and material discrepancy detection.

## Quote Safety Confirmation

Loaded settings during cleanup:

```text
{'yahoo_enabled': False, 'yahoo_historical_validation_enabled': False, 'yahoo_quotes_enabled': False}
```

Yahoo quote capability remains future-only. Quote polling is disabled by default. Normal backfills do not collect quote snapshots, and quote quality is not treated as live unless provider metadata proves it.

## Commands Run

```bash
git status --short
git log --oneline -8
python -m market_sniffer.cli registry validate
python -m pytest
python -m ruff check .
python -m mypy market_sniffer
MARKET_SNIFFER_DB_PATH=/tmp/market_sniffer_cleanup_fixture.sqlite3 python -m market_sniffer.cli verify-foundation --days 5 --fixture --db-path /tmp/market_sniffer_cleanup_fixture.sqlite3
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli validate-sources --live
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli verify-foundation --days 5 --db-path /tmp/market_sniffer_cleanup_live.sqlite3
YAHOO_ENABLED=true YAHOO_HISTORICAL_VALIDATION_ENABLED=true YAHOO_QUOTES_ENABLED=false python -m market_sniffer.cli validate-history --symbols SPY --symbols QQQ --from 2026-06-18 --to 2026-06-25
python -m market_sniffer.cli validation summary --current --symbols SPY --symbols QQQ --from 2026-06-18 --to 2026-06-25
python -m market_sniffer.cli validation summary --all-rules --symbols SPY --symbols QQQ --from 2026-06-18 --to 2026-06-25
python -m market_sniffer.cli data-health
```

## Validation Results

Live source check:

| Source | Operation | Result | Rows |
|---|---|---:|---:|
| FRED | DGS10 observations | PASS | 21 |
| Massive/Polygon | SPY daily bars | PASS | 22 |
| Yahoo | SPY historical daily bars | PASS | 22 |

Five-day live verification range: 2026-06-18 through 2026-06-25.

Production v3 revalidation:

| Symbol | match | minor_difference | material_difference | not_comparable | validation_unavailable |
|---|---:|---:|---:|---:|---:|
| SPY | 5 | 5 | 0 | 0 | 0 |
| QQQ | 5 | 5 | 0 | 0 | 0 |

Current summary for SPY/QQQ over the same range:

| Field | Status | Count |
|---|---|---:|
| close | match | 10 |
| volume | minor_difference | 10 |

All-rules audit summary for SPY/QQQ over the same range:

| Rule Version | match | minor_difference | material_difference | not_comparable | validation_unavailable |
|---|---:|---:|---:|---:|---:|
| validation_v1 | 0 | 0 | 0 | 10 | 0 |
| daily_bar_validation_v2 | 10 | 10 | 0 | 0 | 0 |
| daily_bar_validation_v3 | 10 | 10 | 0 | 0 | 0 |

Canonical source confirmation:

| Source | Symbol | Price Basis | Count |
|---|---|---|---:|
| massive | QQQ | split_adjusted | 5 |
| massive | SPY | split_adjusted | 5 |

## Data Health

```text
new_quote_freshness_events=0
unresolved_quality_events=0
```

Active validation in data-health reports only `daily_bar_validation_v3` rows:

| Status | Count |
|---|---:|
| match | 10 |
| minor_difference | 10 |
| material_difference | 0 |
| not_comparable | 0 |
| validation_unavailable | 0 |

Total `source_discrepancies` remains 2048 because legacy audit rows are retained.

## Known Limitations

Yahoo provider-native `Close` behavior is bounded by observed compatibility, not a universal provider contract. Corporate-action guardrail coverage depends on available corporate-action records. Volume comparisons remain minor differences for SPY/QQQ and are preserved as evidence.

## Decision

PASS: Yahoo validation is cleanly bounded and data phase remains complete.
