# Decision Log

## 2026-06-26

- SQLite is the durable system of record for Data Foundation v1.
- Massive / Polygon is primary for market data where the user's plan permits.
- FRED is canonical for macro data.
- Yahoo is validation/enrichment now and an explicitly planned future real-time quote option.
- Raw payloads/observations and canonical observations are separate.
- Initial seed is 24 calendar months ending on the command execution date.
- Intraday is scoped to a future watchlist and planned retention control; no broad tick archive is added.
- Real-time quote polling is deferred.
- Redis is intentionally not used for persistent Market Sniffer data in this milestone.
