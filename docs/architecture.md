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
