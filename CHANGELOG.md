# Changelog

## 0.2.0 - 2026-06-26

- Added executable metric and evidence registries.
- Added metric definition, observation, calculation run, and evidence event tables.
- Added metrics and evidence CLI commands for validation, list, backfill, calculation, inspection, health, and summaries.
- Added formula, lineage, idempotency, evidence, and no-Yahoo/quote-polling tests for derived metrics.

## 0.1.0 - 2026-06-26

- Added Data Foundation v1 SQLite warehouse schema.
- Added Alembic migration setup.
- Added registry-driven sources, series, instruments, and collection profiles.
- Added CLI for database init, registry validation/inspection, source validation, backfill, collect, status, health, and data inspection.
- Added Massive/Polygon, FRED, and Yahoo client abstractions with fixture clients for tests.
- Added quality events, lineage-preserving raw payload/observation storage, canonical observations, daily bars, and future quote snapshot schema.
- Added documentation for architecture, data dictionary, registries, collector operations, decisions, and first-run commands.

## 0.1.1 - 2026-06-26

- Added canonical daily market bar table and canonicalization service behavior.
- Added FRED latest-vintage flags and point-in-time repository queries.
- Added completed-session U.S. market date rules.
- Added raw-payload retention classes and manual prune command.
- Added quote delay, tradeability, stale status, and quality semantics.
- Strengthened registry validation and source precedence configuration.
- Added constrained `verify-foundation --days 5` workflow.
- Added Yahoo historical validation bars and Massive/Yahoo discrepancy classification.
- Added live source capability validation mode and `.env` loading.
- Made `--resume` and constrained `--force` operational.
