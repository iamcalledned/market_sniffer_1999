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
- Source-specific daily bars and canonical daily bars are separate so downstream analytics never guess which price is authoritative.
- U.S. equity daily market backfills default to the most recent completed exchange session.
- FRED vintages are retained separately for current-view and point-in-time reconstruction.
- Raw payload bodies have retention classes; lineage metadata is retained after eligible pruning.
- Future quotes have explicit quality/freshness semantics and remain disabled by default.
- Yahoo historical validation is implemented as source-specific bars plus discrepancies, not as canonical promotion.
- `--force` is constrained to explicit target/range reload workflows; `--resume` skips previously succeeded target/range runs.
- Daily-bar validation uses explicit price-basis semantics plus comparison eligibility. Massive/Polygon remains `split_adjusted`; Yahoo `Close` is provider-native and labeled `provider_adjusted_unknown`. Current comparisons run only under `daily_bar_validation_v3`; older discrepancy rule versions remain auditable.
- The web dashboard is strictly read-only. Commits or external provider API requests are blocked during GET / rendering to ensure database integrity and eliminate side-effects.
- Yahoo quote lookups are manual-only and validated. Auto-polling of real-time quotes is disabled. Snapshot persistence to DB is user-requested only.
- Web charts are server-rendered as inline SVGs using a premium dark style. This keeps the application dependency-free, fast, and secure.
