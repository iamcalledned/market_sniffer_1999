# Source Registry

The source registry lives in `config/source_registry.yaml`.

## Massive / Polygon

Use cases: daily OHLCV bars, available corporate actions, future selected intraday bars, future quote/snapshot support where plan permits.

Role: canonical for daily equity and ETF market data. Credential: `MASSIVE_API_KEY` or `POLYGON_API_KEY`. Known limits: endpoint access and history are plan-dependent. Failure behavior: entitlement, rate-limit, malformed response, and outage events are recorded; values are not fabricated.

## FRED

Use cases: macroeconomic, rates, credit, inflation, labor, housing, growth, liquidity, financial-condition, dollar, commodity, volatility, and recession series.

Role: canonical for configured macro series. Credential: `FRED_API_KEY`. Known limits: series can be unavailable, retired, delayed, or revised. Failure behavior: unavailable or malformed series create data-quality events; realtime vintage fields are preserved when supplied.

## Yahoo Finance

Use cases: selected validation, enrichment, and future quote snapshots.

Role: validation/enrichment now; future quote option only when explicitly enabled. Credential: none by default. Known limits: terms, delay, market state, and field availability vary. Failure behavior: validation unavailable or discrepancy events are recorded. Yahoo is never silently promoted to canonical.
