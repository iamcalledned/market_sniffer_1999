# Derived Metrics and Evidence Phase 2 Verification

Verification checklist:

- Apply a clean migration with `python -m market_sniffer.cli db init`.
- Validate registries with `python -m market_sniffer.cli metrics validate`.
- Run the test suite with `python -m pytest`.
- Run lint and type checks with `ruff` and `mypy`.
- Backfill a bounded production window before a full metric backfill.
- Run `metrics health`.
- Run `evidence recent --days 7` and `evidence summary`.
- Rerun the bounded backfill to confirm idempotency.
- Confirm canonical source row counts do not change during metrics-only runs.
- Confirm no Yahoo quote polling is invoked by metrics commands.

Current implementation scope:

- Derived metrics and evidence persistence only.
- No dashboard, UI, AI layer, portfolio logic, alerts, schedulers, quote polling, Redis, or warehouse replacement.
