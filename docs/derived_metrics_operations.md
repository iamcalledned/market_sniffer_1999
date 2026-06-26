# Derived Metrics Operations

Validate registries:

```bash
python -m market_sniffer.cli metrics validate
```

List the enabled catalog:

```bash
python -m market_sniffer.cli metrics list
```

Calculate one completed market date:

```bash
python -m market_sniffer.cli metrics calculate --as-of 2026-06-25
```

Backfill the core metric profile:

```bash
python -m market_sniffer.cli metrics backfill --profile core
```

Bounded backfill:

```bash
python -m market_sniffer.cli metrics backfill --profile core --from 2026-04-01 --to 2026-06-25
```

Inspect one metric:

```bash
python -m market_sniffer.cli metrics inspect market.spy_return_21d --limit 20
```

Metric health:

```bash
python -m market_sniffer.cli metrics health
```

Recent evidence:

```bash
python -m market_sniffer.cli evidence recent --days 7
```

Evidence detail:

```bash
python -m market_sniffer.cli evidence inspect 1
```

Evidence summary:

```bash
python -m market_sniffer.cli evidence summary --from 2026-06-19 --to 2026-06-25
```

Operational boundaries:

- Metrics read `canonical_market_bars_daily` and `canonical_observations`.
- Metrics do not poll quotes.
- Metrics do not use Yahoo rows for core derived values.
- Reruns are safe; observations and events are upserted on formula and rule uniqueness keys.
