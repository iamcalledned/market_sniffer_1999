# Architecture

Required flow:

```text
External APIs
  -> source-specific clients and collectors
  -> raw payload storage
  -> raw observation storage
  -> normalization and canonicalization
  -> SQLite warehouse
  -> future metrics, evidence engine, AI Sniffer, portfolio impact layer, dashboard, reports, alerts
```

SQLite is the durable system of record for Data Foundation v1. Redis is not used for Market Sniffer persistent state in this milestone.

The dashboard, metrics, signal scoring, AI Sniffer, portfolio impact analysis, alerts, recurring quote polling, and broad intraday archive are future boundaries. This milestone only prepares tables and registry fields needed to add those capabilities without changing source-of-truth rules.

## Source Boundaries

Massive / Polygon owns canonical daily equity and ETF bars, available corporate actions, future selected intraday bars, and available market snapshots where entitlement permits. Missing permissions, rate limits, source outages, and malformed data are recorded as quality events.

FRED owns canonical macro and financial-condition observations. Realtime vintage fields are retained when supplied.

Yahoo Finance has three roles: validation, enrichment, and future real-time or near-real-time quote snapshots. Quote polling is disabled by default. Yahoo cannot silently replace Massive/Polygon or FRED.

## Canonical Daily Bars

`market_bars_daily` stores source-specific bars from Massive/Polygon, Yahoo validation, or another future source. `canonical_market_bars_daily` stores exactly one selected downstream bar per instrument, trade date, and price basis. The canonical row points to the source bar and raw payload used to create it.

Source precedence lives in `config/collection_profiles.yaml`. The initial rule is Massive/Polygon first, Yahoo only as explicit fallback. If fallback is allowed, the warehouse records quality and discrepancy evidence and marks the canonical row as fallback.

Yahoo historical validation is a separate flow. It stores Yahoo source bars and discrepancy records but does not alter canonical selection while a valid Massive/Polygon bar exists.

## FRED Vintages

FRED observations retain `realtime_start`, `realtime_end`, retrieval timestamp, raw payload, raw observation, quality status, and `is_latest_vintage`. New vintages are inserted separately; older vintages are not overwritten.

Repository methods support current-view reads and point-in-time reads so future historical analysis can avoid revised values unavailable at the requested date.
