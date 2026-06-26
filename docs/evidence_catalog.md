# Evidence Catalog

Phase 2 adds an executable evidence rule registry at `config/evidence_rule_registry.yaml`.

Enabled rule count: 13.

Initial event types used:

- `threshold_cross`
- `material_change`

Supported event types in validation:

- `threshold_cross`
- `material_change`
- `new_extreme`
- `trend_state_change`
- `data_quality_warning`

Evidence events are generated from stored metric observations, not directly from provider payloads. Each event stores the metric observation id, prior observation where relevant, threshold, rule version, headline, detail, and source lineage copied from the triggering metric observation.

Events are idempotent on `(event_code, metric_definition_id, as_of_date, rule_version)`.
