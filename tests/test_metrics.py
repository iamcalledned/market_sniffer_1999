from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from market_sniffer.db import models as m
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.metric_registry import load_metric_registry
from market_sniffer.services.metrics import MetricCalculationService


def _seed_bar(repo: WarehouseRepository, symbol: str, trade_date: date, close: Decimal) -> None:
    payload = repo.raw_payload("massive", "fixture", {"symbol": symbol, "date": trade_date.isoformat()}, {"close": str(close)})
    repo.insert_daily_bar(
        symbol,
        "massive",
        payload,
        {
            "trade_date": trade_date,
            "open": close,
            "high": close + Decimal("1"),
            "low": close - Decimal("1"),
            "close": close,
            "adjusted_close": close,
            "volume": 1000,
            "adjusted": True,
            "price_basis": "split_adjusted",
        },
    )
    repo.canonicalize_daily_bar(symbol, trade_date, ["massive"])


def _seed_fred(repo: WarehouseRepository, series_code: str, obs_date: date, value: Decimal) -> None:
    payload = repo.raw_payload("fred", "fixture", {"series_id": series_code, "date": obs_date.isoformat()}, {"value": str(value)})
    repo.insert_fred_observation(series_code, payload, obs_date, value, obs_date, obs_date, {"value": str(value)})


def _seed_metric_inputs(session, days: int = 230) -> list[date]:
    registry = load_metric_registry()
    repo = WarehouseRepository(session)
    symbols = {"SPY", "XLK", "XLF", "XLE", "GLD"}
    symbols.update(registry.baskets["breadth_core"]["symbols"])
    symbols.update(registry.baskets["ai_infrastructure"]["symbols"])
    start = date(2025, 1, 2)
    dates = [start + timedelta(days=i) for i in range(days)]
    for i, trade_date in enumerate(dates):
        for offset, symbol in enumerate(sorted(symbols)):
            base = Decimal("100") + Decimal(offset)
            slope = Decimal("0.10") if symbol != "SPY" else Decimal("0.08")
            if symbol in {"XLF", "XLE", "GLD"}:
                slope = Decimal("0.04")
            _seed_bar(repo, symbol, trade_date, base + (Decimal(i) * slope))
        _seed_fred(repo, "DGS10", trade_date, Decimal("4.00") + Decimal(i) / Decimal("1000"))
        _seed_fred(repo, "DGS2", trade_date, Decimal("3.50") + Decimal(i) / Decimal("2000"))
        _seed_fred(repo, "T10Y3M", trade_date, Decimal("1.20") - Decimal(i) / Decimal("2000"))
        _seed_fred(repo, "BAMLH0A0HYM2", trade_date, Decimal("3.00") + Decimal(i) / Decimal("100"))
        _seed_fred(repo, "NFCI", trade_date, Decimal("-0.50") + Decimal(i) / Decimal("1000"))
        _seed_fred(repo, "VIXCLS", trade_date, Decimal("20.00") + Decimal(i) / Decimal("10"))
    session.commit()
    return dates


def test_metric_registry_validation_and_count():
    registry = load_metric_registry()
    assert len(registry.enabled_metrics) == 25
    assert len(registry.enabled_rules) == 13
    assert {
        "market_structure",
        "leadership_breadth",
        "rates_credit",
        "volatility_cross_asset",
        "macro_momentum",
    } <= {item["category"] for item in registry.enabled_metrics.values()}


def test_metric_formulas_lineage_and_idempotency(session):
    dates = _seed_metric_inputs(session)
    as_of = dates[-1]
    service = MetricCalculationService(session)
    summary = service.calculate_date(as_of)
    assert summary["failed"] == 0
    assert summary["succeeded"] == 25
    first_count = len(session.scalars(select(m.MetricObservation)).all())
    assert service.calculate_date(as_of)["failed"] == 0
    second_count = len(session.scalars(select(m.MetricObservation)).all())
    assert second_count == first_count

    spy_return = session.scalar(
        select(m.MetricObservation)
        .join(m.MetricDefinition, m.MetricObservation.metric_definition_id == m.MetricDefinition.id)
        .where(m.MetricDefinition.metric_code == "market.spy_return_5d")
    )
    assert spy_return is not None
    assert spy_return.value_numeric is not None
    assert spy_return.source_lineage_json["source_type"] == "canonical_market_bars_daily"
    assert spy_return.source_lineage_json["formula_version"] == "metric_v1"
    assert spy_return.source_lineage_json["canonical_bar_ids"]

    spread = session.scalar(
        select(m.MetricObservation)
        .join(m.MetricDefinition, m.MetricObservation.metric_definition_id == m.MetricDefinition.id)
        .where(m.MetricDefinition.metric_code == "rates.ust_2s10s_spread")
    )
    assert spread is not None
    assert spread.value_numeric == Decimal("0.6145000000")
    assert spread.source_lineage_json["long"]["source_type"] == "canonical_observations"


def test_evidence_events_are_generated_and_idempotent(session):
    dates = _seed_metric_inputs(session)
    service = MetricCalculationService(session)
    summary = service.backfill(start=dates[-3], end=dates[-1])
    assert summary["failed"] == 0
    events = session.scalars(select(m.EvidenceEvent)).all()
    assert events
    first_count = len(events)
    service.backfill(start=dates[-3], end=dates[-1])
    assert len(session.scalars(select(m.EvidenceEvent)).all()) == first_count
    event = events[0]
    assert event.evidence_json["source_lineage"]
    assert event.event_type in {"threshold_cross", "material_change"}


def test_metrics_do_not_use_yahoo_or_quote_polling(session):
    dates = _seed_metric_inputs(session)
    repo = WarehouseRepository(session)
    counts_before = repo.counts()
    service = MetricCalculationService(session)
    assert service.calculate_date(dates[-1])["failed"] == 0
    counts_after = repo.counts()
    assert counts_after["quote_snapshots"] == counts_before["quote_snapshots"]
    assert counts_after["daily_bars"] == counts_before["daily_bars"]
    assert counts_after["canonical_daily_bars"] == counts_before["canonical_daily_bars"]
    yahoo = repo.source("yahoo")
    yahoo_bars = session.scalars(select(m.MarketBarDaily).where(m.MarketBarDaily.source_id == yahoo.id)).all()
    assert yahoo_bars == []
