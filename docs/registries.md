# Series and Instrument Registries

Registry files:

- `config/source_registry.yaml`
- `config/series_registry.yaml`
- `config/instrument_registry.yaml`
- `config/collection_profiles.yaml`

Every FRED series entry includes the internal code, source identifier, category, frequency, unit, native unit, canonical source, collection profile, backfill eligibility, update schedule, vintage tracking flag, Yahoo validation flag, and why it matters.

Every instrument entry includes symbol, display name, asset class, exchange, currency, active state, group metadata, collection profiles, daily eligibility, future intraday eligibility, future quote eligibility, and why it is tracked.

The configured FRED scope covers Treasury curve, yield curve, policy/liquidity, credit, inflation, labor, housing, growth/activity, financial conditions/stress, dollar/commodity context, volatility/risk, and recession context.

The configured instrument universe covers broad market/global ETFs, U.S. sectors, style/factor ETFs, fixed income/credit/inflation-protected ETFs, commodity and dollar proxies, volatility/tactical proxies, and AI infrastructure/semiconductor watchlist names.

Validate executable registry configuration with:

```bash
python -m market_sniffer.cli registry validate
```

Validation checks required fields, duplicate YAML keys, source references, canonical source references, collection profile references, future quote/intraday flags, and daily-market source precedence.

`config/collection_profiles.yaml` also defines batch size, validation sample symbols, canonical source precedence, fallback policy, and retention classes/days for validation, future intraday, and future quote payloads.
