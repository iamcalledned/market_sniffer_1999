# Metric Catalog

Phase 2 adds an executable metric registry at `config/metric_registry.yaml`.

Enabled catalog size: 25 metrics.

Categories:

- `market_structure`: SPY close, returns, moving averages, distance to 200-day average, realized volatility.
- `leadership_breadth`: tracked universe breadth, sector relative returns, AI infrastructure relative return.
- `rates_credit`: Treasury curve spreads, high-yield OAS level and change.
- `macro_momentum`: NFCI level and change.
- `volatility_cross_asset`: VIX level/change and GLD relative return.

All enabled metrics consume only canonical daily market bars and canonical FRED observations. The metric engine does not call collectors, quote clients, or Yahoo validation paths.

Each stored metric observation includes:

- `metric_definition_id`
- `as_of_date`
- `formula_version`
- numeric value or an explicit quality status
- source lineage JSON with canonical row ids and raw payload ids
- input window dates and effective source date

Formula versioning is part of the observation uniqueness key, so later formula revisions can coexist with historical values.
