# Documentation Changelog

## 2026-06-26

- Added Flask-based web application with clean factory pattern and Blueprint routing architecture.
- Implemented professional dark-themed dashboard interface containing deterministic Market Brief, KPI strip, clustered evidence, 2x2 Market Map grid, and Data Confidence statistics.
- Added server-rendered inline SVG charts for metrics, instruments, and FRED series.
- Added explicit manual single-symbol Yahoo quote lookup with optional DB persistence.
- Configured setup state error screens displaying copyable troubleshooting commands.
- Documented canonical source precedence, web blueprints, and data boundaries.

- Documented canonical source-specific bar versus canonical daily-bar design.
- Documented FRED vintage insertion, latest-vintage selection, and point-in-time query semantics.
- Documented completed-market-session default date behavior.
- Documented raw-payload retention classes and manual pruning.
- Documented quote quality labels and disabled-by-default quote polling.
- Documented registry validation and constrained live verification workflow.
- Documented Yahoo historical validation, live source capability checks, and resume/force semantics.
- Added the simple operator runbook and committed live verification plus 24-month seed evidence.
- Split Yahoo historical validation configuration from future quote polling with `YAHOO_HISTORICAL_VALIDATION_ENABLED`.
- Added explicit daily-bar price-basis semantics, registry-driven validation thresholds, `validate-history`, and final Yahoo/Massive validation evidence.
- Bounded Yahoo semantics with `provider_adjusted_unknown`, added active-vs-legacy validation summaries, and added a corporate-action validation guardrail.
