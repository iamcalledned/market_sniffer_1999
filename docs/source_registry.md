# Source Registry

The source registry lives in `config/source_registry.yaml`.

## Massive / Polygon

Use cases: daily OHLCV bars, available corporate actions, future selected intraday bars, future quote/snapshot support where plan permits.

Role: canonical for daily equity and ETF market data. Credential: `MASSIVE_API_KEY` or `POLYGON_API_KEY`. Known limits: endpoint access and history are plan-dependent. Failure behavior: entitlement, rate-limit, malformed response, and outage events are recorded; values are not fabricated.

Daily market source precedence: first for canonical daily bars.

## FRED

Use cases: macroeconomic, rates, credit, inflation, labor, housing, growth, liquidity, financial-condition, dollar, commodity, volatility, and recession series.

Role: canonical for configured macro series. Credential: `FRED_API_KEY`. Known limits: series can be unavailable, retired, delayed, or revised. Failure behavior: unavailable or malformed series create data-quality events; realtime vintage fields are preserved when supplied.

## Yahoo Finance

Use cases: selected validation, enrichment, and future quote snapshots.

Role: validation/enrichment now; future quote option only when explicitly enabled. Historical validation uses `YAHOO_HISTORICAL_VALIDATION_ENABLED=true`; quote polling is not enabled by default. Credential: none by default. Known limits: terms, delay, market state, and field availability vary. Failure behavior: validation unavailable or discrepancy events are recorded. Yahoo is never silently promoted to canonical.

Daily market source precedence: validation/fallback only. Fallback is disabled unless a registry/profile explicitly allows it.

Historical validation uses `yfinance` when `YAHOO_ENABLED=true` and `YAHOO_HISTORICAL_VALIDATION_ENABLED=true`. Current Yahoo validation calls `history(..., auto_adjust=False, actions=True)`, stores `Close` as provider-native `provider_adjusted_unknown`, preserves `Adj Close` separately, compares only approved source/field pairs against Massive/Polygon, and classifies results as match, minor difference, material difference, not comparable, or validation unavailable.
