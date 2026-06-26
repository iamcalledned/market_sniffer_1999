# Data Dictionary

All tables are migration-managed by Alembic and use SQLite as the durable store.

| Table | Purpose | Key Constraints and Relationships | Retention |
| --- | --- | --- | --- |
| `data_sources` | Source identity, capabilities, credentials, source role notes. | Unique `code`. Referenced by all source-owned data. | Indefinite. |
| `data_series` | Canonical registry of tracked economic/market context series. | Unique `series_code`; source and canonical source FKs. | Indefinite. |
| `instruments` | Financial instruments independent from series. | Unique `symbol`; quote/intraday eligibility flags. | Indefinite. |
| `instrument_aliases` | Source-specific aliases for instruments. | Unique instrument/source/alias. | Indefinite. |
| `source_series_mappings` | Maps internal series to source identifiers. | Unique series/source/source identifier. | Indefinite. |
| `raw_payloads` | Redacted request metadata, response payloads, hashes, status, error context. | Unique source/endpoint/payload hash avoids duplicate payload storage. | Indefinite unless raw archival policy changes. |
| `raw_observations` | Source observations before canonicalization. | Unique source/series/instrument/key/payload. | Indefinite lineage. |
| `canonical_observations` | Normalized series values for future evidence and metrics. | Unique series/date/vintage/source. Links raw observation and payload. | Indefinite. |
| `market_bars_daily` | Source-specific daily market OHLCV bars. | Unique instrument/trade date/source/adjusted. Links raw payload; includes price basis and finality. | Indefinite. |
| `canonical_market_bars_daily` | Single downstream daily bar per instrument/date/price basis. | Unique instrument/trade date/price basis. Links canonical source, source bar, and raw payload. | Indefinite. |
| `market_bars_intraday` | Future selected intraday bars. | Unique instrument/start/interval/source/adjusted. | Planned rolling 90 days by policy; pruning not active. |
| `quote_snapshots` | Future quote snapshots from Yahoo and/or Massive. | Unique instrument/timestamp/source. Links raw payload and quality status. | Policy deferred before activation. |
| `market_snapshots` | Future daily market snapshot payloads. | Unique instrument/snapshot date/source. | Indefinite initially. |
| `corporate_actions` | Splits, dividends, and similar source actions. | Unique instrument/source/type/ex-date/source action id. | Indefinite. |
| `collector_definitions` | Registry-backed collector/profile definitions. | Unique `name`. | Indefinite. |
| `collector_runs` | Parent and child run state, counts, failures, resumability. | Indexed source/profile/target/date/status. | Indefinite operational audit. |
| `collector_run_items` | Per-target run items for retries/resume. | Unique run/target/date range. | Indefinite operational audit. |
| `data_quality_events` | Visible data quality, freshness, entitlement, rate-limit, and malformed-data events. | Indexed type/severity/source/series/instrument/date. | Indefinite until resolved/archived policy exists. |
| `source_discrepancies` | Primary-vs-validation comparisons. | Unique instrument/date/source pair/field. Status is match/minor/material/not comparable/unavailable. | Indefinite validation audit. |
| `system_settings` | Small local system metadata. | Primary key `key`. | Indefinite. |

Missing data is never stored as zero. Canonical records retain source, raw observation or payload lineage, quality status, observation date/timestamp, retrieval timestamp, and unit.

FRED vintages use `series_id`, `observation_date`, `realtime_start`, and `source_id` as the revision identity. `is_latest_vintage` marks the latest known vintage for current reports. Point-in-time reads select the newest `realtime_start` not after the requested historical date.

Raw payload retention classes are `indefinite`, `quote`, `intraday`, and `validation`. Pruning clears eligible payload bodies only; redacted request metadata, payload hash, retrieval timestamp, status, source record identifier, and downstream lineage remain.
