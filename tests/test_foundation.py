from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from market_sniffer.collectors.base import DailyBar, MissingCredentialError
from market_sniffer.collectors.fred import FixtureFredClient, FredApiClient
from market_sniffer.collectors.massive import FixtureMassiveClient
from market_sniffer.collectors.yahoo import FixtureYahooQuoteClient, YahooQuoteClient
from market_sniffer.collectors.yahoo import FixtureYahooHistoricalClient
from market_sniffer.cli import validation_summary
from market_sniffer.db import models as m
from market_sniffer.db.engine import assert_sqlite_pragmas, create_db_engine
from market_sniffer.db.models import Base
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.backfill import BackfillService
from market_sniffer.services.dates import MarketCalendar, default_backfill_window
from market_sniffer.services.quality import DataQualityService
from market_sniffer.services.registry_service import Registry, RegistryError, load_registry, validate_registry
from market_sniffer.services.retention import RetentionService
from market_sniffer.settings import get_settings


def test_database_pragmas_and_tables(tmp_path):
    engine = create_db_engine(tmp_path / "clean.sqlite3")
    Base.metadata.create_all(engine)
    pragmas = assert_sqlite_pragmas(engine)
    assert pragmas["foreign_keys"] == 1
    assert str(pragmas["journal_mode"]).lower() == "wal"
    assert int(pragmas["busy_timeout"]) >= 5000


def test_registry_load_and_validate():
    registry = load_registry()
    assert {"massive", "fred", "yahoo"} <= set(registry.sources)
    assert "DGS10" in registry.series
    assert "NVDA" in registry.instruments
    assert registry.profiles["future_realtime_quote_watchlist"]["enabled_by_default"] is False


def test_duplicate_daily_bar_idempotency(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("massive", "fixture", {"symbol": "SPY"}, {"ok": True})
    bar = DailyBar(date(2026, 1, 2), Decimal("1"), Decimal("2"), Decimal("1"), Decimal("2"), Decimal("2"), 10)
    inserted, source_bar = repo.insert_daily_bar("SPY", "massive", payload, bar.asdict())
    assert inserted is True
    assert source_bar.price_basis == "split_adjusted"
    inserted_again, _ = repo.insert_daily_bar("SPY", "massive", payload, bar.asdict())
    assert inserted_again is False
    changed, canonical = repo.canonicalize_daily_bar("SPY", source_bar.trade_date, ["massive", "yahoo"])
    assert changed is True
    assert canonical is not None
    assert canonical.price_basis == "split_adjusted"
    assert canonical.source_market_bar_id == source_bar.id
    session.commit()
    assert repo.counts()["daily_bars"] == 1
    assert repo.counts()["canonical_daily_bars"] == 1


def test_source_bars_can_coexist_but_only_one_canonical(session):
    repo = WarehouseRepository(session)
    massive_payload = repo.raw_payload("massive", "fixture", {"symbol": "SPY"}, {"source": "massive"})
    yahoo_payload = repo.raw_payload("yahoo", "fixture", {"symbol": "SPY"}, {"source": "yahoo"})
    bar = DailyBar(date(2026, 1, 2), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10"), Decimal("10"), 1)
    inserted_massive, massive_bar = repo.insert_daily_bar("SPY", "massive", massive_payload, bar.asdict())
    yahoo_dict = bar.asdict()
    yahoo_dict["close"] = Decimal("10.50")
    inserted_yahoo, yahoo_bar = repo.insert_daily_bar("SPY", "yahoo", yahoo_payload, yahoo_dict)
    assert inserted_massive and inserted_yahoo
    changed, canonical = repo.canonicalize_daily_bar("SPY", date(2026, 1, 2), ["massive", "yahoo"])
    assert changed is True
    assert canonical is not None
    assert canonical.source_market_bar_id == massive_bar.id
    assert canonical.source_market_bar_id != yahoo_bar.id
    changed_again, canonical_again = repo.canonicalize_daily_bar("SPY", date(2026, 1, 2), ["massive", "yahoo"])
    assert changed_again is False
    assert canonical_again is not None
    assert repo.counts()["canonical_daily_bars"] == 1


def test_yahoo_fallback_requires_explicit_allowance(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("yahoo", "fixture", {"symbol": "SPY"}, {"source": "yahoo"})
    bar = DailyBar(date(2026, 1, 2), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10"), Decimal("10"), 1)
    inserted, _ = repo.insert_daily_bar("SPY", "yahoo", payload, bar.asdict())
    assert inserted is True
    changed, canonical = repo.canonicalize_daily_bar("SPY", date(2026, 1, 2), ["massive", "yahoo"])
    assert changed is False
    assert canonical is None
    changed, canonical = repo.canonicalize_daily_bar(
        "SPY",
        date(2026, 1, 2),
        ["massive", "yahoo"],
        allow_yahoo_fallback=True,
        primary_failure="fixture primary unavailable",
    )
    assert changed is True
    assert canonical is not None
    assert canonical.quality_status == "fallback"
    events = session.scalars(select(m.DataQualityEvent)).all()
    assert any(event.event_type == "source_discrepancy" for event in events)


def test_canonical_rule_version_change_is_auditable(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("massive", "fixture", {"symbol": "SPY"}, {"source": "massive"})
    bar = DailyBar(date(2026, 1, 2), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10"), Decimal("10"), 1)
    _, source_bar = repo.insert_daily_bar("SPY", "massive", payload, bar.asdict())
    repo.canonicalize_daily_bar("SPY", source_bar.trade_date, ["massive"], rule_version="daily_bar_v1")
    changed, canonical = repo.canonicalize_daily_bar("SPY", source_bar.trade_date, ["massive"], rule_version="daily_bar_v2")
    assert changed is True
    assert canonical is not None
    assert canonical.canonicalization_rule_version == "daily_bar_v2"


def test_duplicate_fred_observation_idempotency_and_lineage(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("fred", "fixture", {"series_id": "DGS10"}, {"observations": [1]})
    inserted, canonical = repo.insert_fred_observation(
        "DGS10", payload, date(2026, 1, 2), Decimal("4.25"), date(2026, 1, 2), date(2026, 1, 2), {"value": "4.25"}
    )
    assert inserted is True
    inserted_again, canonical_again = repo.insert_fred_observation(
        "DGS10", payload, date(2026, 1, 2), Decimal("4.25"), date(2026, 1, 2), date(2026, 1, 2), {"value": "4.25"}
    )
    assert inserted_again is False
    assert canonical is not None
    assert canonical_again is not None
    assert canonical.raw_payload_id == payload.id
    assert canonical.raw_observation_id is not None
    assert canonical.is_latest_vintage is True
    session.commit()
    assert repo.counts()["canonical_observations"] == 1


def test_fred_revisions_latest_and_point_in_time(session):
    repo = WarehouseRepository(session)
    payload1 = repo.raw_payload("fred", "fixture", {"series_id": "DGS10", "v": 1}, {"observations": [1]})
    payload2 = repo.raw_payload("fred", "fixture", {"series_id": "DGS10", "v": 2}, {"observations": [2]})
    obs_date = date(2025, 12, 1)
    inserted1, first = repo.insert_fred_observation(
        "DGS10", payload1, obs_date, Decimal("4.00"), date(2025, 12, 5), date(2025, 12, 31), {"value": "4.00"}
    )
    inserted2, second = repo.insert_fred_observation(
        "DGS10", payload2, obs_date, Decimal("4.25"), date(2026, 1, 10), date(2026, 1, 31), {"value": "4.25"}
    )
    inserted_dup, _ = repo.insert_fred_observation(
        "DGS10", payload2, obs_date, Decimal("4.25"), date(2026, 1, 10), date(2026, 1, 31), {"value": "4.25"}
    )
    assert inserted1 is True and inserted2 is True and inserted_dup is False
    assert first is not None and second is not None
    assert repo.latest_fred_value("DGS10", obs_date).value == Decimal("4.2500000000")
    assert repo.fred_value_as_of("DGS10", obs_date, date(2025, 12, 20)).value == Decimal("4.0000000000")
    assert repo.fred_value_as_of("DGS10", obs_date, date(2026, 1, 15)).value == Decimal("4.2500000000")


def test_yahoo_cannot_replace_canonical_series(session):
    registry = load_registry()
    assert all(item["canonical_source"] == "fred" for item in registry.series.values())
    assert registry.sources["yahoo"]["canonical_responsibilities"] == []


def test_missing_credentials_fail_safely():
    with pytest.raises(MissingCredentialError):
        FredApiClient(None).observations("DGS10", date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(MissingCredentialError):
        YahooQuoteClient(enabled=False, quotes_enabled=False).quote_snapshot("SPY")


def test_quality_event_for_malformed_market_data(session):
    class BadMarketClient(FixtureMassiveClient):
        def daily_bars(self, symbol, start, end):
            return {"bad": True}, [
                DailyBar(start, Decimal("-1"), Decimal("2"), Decimal("3"), Decimal("0"), None, None)
            ]

    service = BackfillService(session, load_registry(), FixtureFredClient(), BadMarketClient())
    failures = service.backfill("daily_market", date(2026, 1, 2), date(2026, 1, 2), only=["SPY"], continue_on_error=True)
    events = session.scalars(select(m.DataQualityEvent)).all()
    assert failures == 0
    assert any(event.event_type == "suspicious_value_jump" for event in events)


def test_fixture_backfill_resume_idempotent(session):
    registry = load_registry()
    service = BackfillService(
        session, registry, FixtureFredClient(), FixtureMassiveClient(), validation_client=FixtureYahooHistoricalClient()
    )
    kwargs = {"profile": "core", "start": date(2026, 1, 2), "end": date(2026, 1, 6), "only": ["DGS10", "SPY"]}
    assert service.backfill(**kwargs) == 0
    counts_first = WarehouseRepository(session).counts()
    assert service.backfill(**kwargs) == 0
    counts_second = WarehouseRepository(session).counts()
    assert counts_second["canonical_observations"] == counts_first["canonical_observations"]
    assert counts_second["daily_bars"] == counts_first["daily_bars"]
    assert counts_second["canonical_daily_bars"] == counts_first["canonical_daily_bars"]


def test_yahoo_historical_validation_stores_bars_and_does_not_change_canonical(session):
    registry = load_registry()
    service = BackfillService(
        session, registry, FixtureFredClient(), FixtureMassiveClient(), validation_client=FixtureYahooHistoricalClient()
    )
    assert service.backfill("core", date(2026, 1, 2), date(2026, 1, 6), only=["SPY"]) == 0
    repo = WarehouseRepository(session)
    massive_source = repo.source("massive")
    yahoo_source = repo.source("yahoo")
    instrument = repo.instrument("SPY")
    massive_bars = session.scalars(
        select(m.MarketBarDaily).where(
            m.MarketBarDaily.instrument_id == instrument.id,
            m.MarketBarDaily.source_id == massive_source.id,
        )
    ).all()
    yahoo_bars = session.scalars(
        select(m.MarketBarDaily).where(
            m.MarketBarDaily.instrument_id == instrument.id,
            m.MarketBarDaily.source_id == yahoo_source.id,
        )
    ).all()
    canonical = session.scalars(select(m.CanonicalMarketBarDaily)).all()
    discrepancies = session.scalars(select(m.SourceDiscrepancy)).all()
    assert len(massive_bars) == 3
    assert len(yahoo_bars) == 3
    assert len(canonical) == 3
    assert all(row.canonical_source_id == massive_source.id for row in canonical)
    assert {row.price_basis for row in massive_bars} == {"split_adjusted"}
    assert {row.price_basis for row in yahoo_bars} == {"provider_adjusted_unknown"}
    assert {row.price_basis for row in canonical} == {"split_adjusted"}
    assert {row.field_name for row in discrepancies} == {"close", "volume"}
    assert {row.status for row in discrepancies} == {"match"}
    counts = repo.counts()
    assert service.backfill("core", date(2026, 1, 2), date(2026, 1, 6), only=["SPY"]) == 0
    rerun_counts = repo.counts()
    assert rerun_counts["daily_bars"] == counts["daily_bars"]
    assert rerun_counts["canonical_daily_bars"] == counts["canonical_daily_bars"]
    assert rerun_counts["source_discrepancies"] == counts["source_discrepancies"]


def test_yahoo_discrepancy_classification_material_and_not_comparable(session):
    repo = WarehouseRepository(session)
    service = BackfillService(session, load_registry(), FixtureFredClient(), FixtureMassiveClient())
    assert service._classify_difference(Decimal("100"), Decimal("100.00000001"), Decimal("0.000001"), Decimal("0.002"), Decimal("0.01")) == "match"
    assert service._classify_difference(Decimal("100"), Decimal("100.10"), Decimal("0.000001"), Decimal("0.002"), Decimal("0.01")) == "minor_difference"
    assert service._classify_difference(Decimal("100"), Decimal("103"), Decimal("0.000001"), Decimal("0.002"), Decimal("0.01")) == "material_difference"
    assert service._classify_difference(Decimal("0"), Decimal("1"), Decimal("0.000001"), Decimal("0.002"), Decimal("0.01")) == "material_difference"
    payload = repo.raw_payload("massive", "fixture", {"symbol": "SPY"}, {"source": "massive"})
    _, massive_bar = repo.insert_daily_bar(
        "SPY",
        "massive",
        payload,
        {
            "trade_date": date(2026, 1, 2),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "adjusted_close": None,
            "volume": 100,
            "adjusted": False,
            "price_basis": "raw",
        },
    )
    registry = load_registry()
    incompatible_registry = Registry(
        sources=registry.sources,
        series=registry.series,
        instruments=registry.instruments,
        profiles=registry.profiles,
        validation={
            **registry.validation,
            "daily_bars": {
                **registry.validation["daily_bars"],
                "source_price_basis": {"massive": "raw", "yahoo": "provider_adjusted_unknown"},
                "approved_comparison_pairs": [],
            },
        },
    )
    service = BackfillService(session, incompatible_registry, FixtureFredClient(), FixtureMassiveClient())
    yahoo_bar = DailyBar(massive_bar.trade_date, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("100"), 100, price_basis="provider_adjusted_unknown")
    service._compare_yahoo_bar("SPY", massive_bar.trade_date, yahoo_bar, payload.id, collector_run_id=None)
    discrepancy = session.scalar(select(m.SourceDiscrepancy).where(m.SourceDiscrepancy.field_name == "close"))
    assert discrepancy.status == "not_comparable"
    assert discrepancy.details["primary_price_basis"] == "raw"
    assert discrepancy.details["validation_price_basis"] == "provider_adjusted_unknown"
    assert discrepancy.details["comparison_eligible"] is False


def test_rule_version_results_are_not_confused(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("massive", "fixture", {"symbol": "SPY"}, {"source": "massive"})
    repo.record_discrepancy(
        "SPY",
        date(2026, 1, 2),
        "massive",
        "yahoo",
        "close",
        "not_comparable",
        comparison_rule_version="validation_v1",
    )
    service = BackfillService(session, load_registry(), FixtureFredClient(), FixtureMassiveClient())
    repo.insert_daily_bar(
        "SPY",
        "massive",
        payload,
        DailyBar(date(2026, 1, 2), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("100"), 100).asdict(),
    )
    yahoo_bar = DailyBar(date(2026, 1, 2), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("100"), 100, price_basis="provider_adjusted_unknown")
    service._compare_yahoo_bar("SPY", date(2026, 1, 2), yahoo_bar, payload.id, collector_run_id=None)
    rows = session.scalars(select(m.SourceDiscrepancy).where(m.SourceDiscrepancy.field_name == "close")).all()
    assert {row.comparison_rule_version for row in rows} == {"validation_v1", "daily_bar_validation_v3"}
    assert {row.status for row in rows} == {"not_comparable", "match"}


def test_validate_history_idempotent_and_preserves_canonical(session):
    registry = load_registry()
    service = BackfillService(
        session, registry, FixtureFredClient(), FixtureMassiveClient(), validation_client=FixtureYahooHistoricalClient()
    )
    first = service.validate_history(["SPY", "QQQ"], date(2026, 1, 2), date(2026, 1, 6))
    repo = WarehouseRepository(session)
    massive_source = repo.source("massive")
    canonical = session.scalars(select(m.CanonicalMarketBarDaily)).all()
    assert all(row.canonical_source_id == massive_source.id for row in canonical)
    counts = repo.counts()
    second = service.validate_history(["SPY", "QQQ"], date(2026, 1, 2), date(2026, 1, 6))
    rerun_counts = repo.counts()
    assert first == second
    assert rerun_counts["daily_bars"] == counts["daily_bars"]
    assert rerun_counts["canonical_daily_bars"] == counts["canonical_daily_bars"]
    assert rerun_counts["source_discrepancies"] == counts["source_discrepancies"]
    assert first["SPY"]["match"] == 6
    assert first["QQQ"]["match"] == 6


def test_validation_summary_current_excludes_legacy_and_all_rules_labels_it(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("massive", "fixture", {"symbol": "SPY"}, {"source": "massive"})
    repo.record_discrepancy(
        "SPY",
        date(2026, 1, 2),
        "massive",
        "yahoo",
        "close",
        "not_comparable",
        comparison_rule_version="validation_v1",
    )
    service = BackfillService(session, load_registry(), FixtureFredClient(), FixtureMassiveClient())
    repo.insert_daily_bar(
        "SPY",
        "massive",
        payload,
        DailyBar(date(2026, 1, 2), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("100"), 100).asdict(),
    )
    yahoo_bar = DailyBar(date(2026, 1, 2), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("100"), 100, price_basis="provider_adjusted_unknown")
    service._compare_yahoo_bar("SPY", date(2026, 1, 2), yahoo_bar, payload.id, collector_run_id=None)
    current = validation_summary(session, load_registry(), current=True, symbols=["SPY"])
    all_rules = validation_summary(session, load_registry(), current=False, symbols=["SPY"])
    assert current["active_rule_version"] == "daily_bar_validation_v3"
    assert current["counts_by_status"]["not_comparable"] == 0
    assert current["legacy_audit_row_count"] == 1
    assert "validation_v1" not in current["counts_by_rule"]
    assert all_rules["counts_by_rule"]["validation_v1"]["not_comparable"] == 1
    assert all_rules["counts_by_rule"]["daily_bar_validation_v3"]["match"] == 2


def test_current_material_discrepancy_remains_visible(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("massive", "fixture", {"symbol": "SPY"}, {"source": "massive"})
    service = BackfillService(session, load_registry(), FixtureFredClient(), FixtureMassiveClient())
    repo.insert_daily_bar(
        "SPY",
        "massive",
        payload,
        DailyBar(date(2026, 1, 2), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("100"), 100).asdict(),
    )
    yahoo_bar = DailyBar(date(2026, 1, 2), Decimal("130"), Decimal("131"), Decimal("129"), Decimal("130"), Decimal("130"), 200, price_basis="provider_adjusted_unknown")
    service._compare_yahoo_bar("SPY", date(2026, 1, 2), yahoo_bar, payload.id, collector_run_id=None)
    current = validation_summary(session, load_registry(), current=True, symbols=["SPY"])
    assert current["counts_by_status"]["material_difference"] == 2


def test_corporate_action_guardrail_records_review_event(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("massive", "corporate_actions", {"symbol": "SPY"}, {"fixture": True})
    assert repo.insert_corporate_action(
        "SPY",
        "massive",
        payload,
        {"action_type": "split", "ex_date": "2026-01-03", "source_action_id": "split-1", "amount": None},
    )
    service = BackfillService(
        session, load_registry(), FixtureFredClient(), FixtureMassiveClient(), validation_client=FixtureYahooHistoricalClient()
    )
    service.validate_history(["SPY"], date(2026, 1, 2), date(2026, 1, 6))
    events = session.scalars(select(m.DataQualityEvent).where(m.DataQualityEvent.event_type == "validation_adjustment_review")).all()
    assert len(events) == 1
    assert events[0].details["corporate_action_count"] == 1


def test_dynamic_24_calendar_month_window():
    start, end = default_backfill_window(date(2026, 6, 26), months=24)
    assert start == date(2024, 6, 26)
    assert end == date(2026, 6, 26)


def test_quote_snapshot_schema_and_freshness(session):
    repo = WarehouseRepository(session)
    payload, quote = FixtureYahooQuoteClient().quote_snapshot("SPY")
    raw = repo.raw_payload("yahoo", "quote_snapshot", {"symbol": "SPY"}, payload)
    assert repo.insert_quote_snapshot("SPY", "yahoo", raw, quote) is True
    old_quote = dict(quote)
    old_quote["quote_timestamp_utc"] = datetime(2020, 1, 1, tzinfo=timezone.utc)
    raw2 = repo.raw_payload("yahoo", "quote_snapshot", {"symbol": "SPY", "old": True}, {"old": True})
    assert repo.insert_quote_snapshot("SPY", "yahoo", raw2, old_quote) is True
    session.commit()
    created = DataQualityService(session).check_quote_freshness(max_age_minutes=1)
    assert created >= 1


def test_quote_quality_does_not_claim_live_without_provider_metadata():
    received = datetime(2026, 1, 2, 15, 30, tzinfo=timezone.utc)
    quality, stale = DataQualityService.classify_quote(
        datetime(2026, 1, 2, 15, 29, tzinfo=timezone.utc), received, provider_quality=None
    )
    assert quality == "unknown"
    assert stale is False
    quality, stale = DataQualityService.classify_quote(
        datetime(2026, 1, 2, 15, 30, tzinfo=timezone.utc), received, provider_quality="live", provider_delay_seconds=0
    )
    assert quality == "live"
    assert stale is False


def test_no_credentials_in_payload_metadata(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("massive", "fixture", {"apiKey": "secret", "nested": {"token": "abc"}}, {"ok": True})
    assert payload.request_metadata["apiKey"] == "***REDACTED***"
    assert payload.request_metadata["nested"]["token"] == "***REDACTED***"


def test_future_quote_polling_disabled_by_default():
    registry = load_registry()
    assert registry.profiles["future_realtime_quote_watchlist"]["enabled_by_default"] is False
    assert registry.sources["yahoo"]["enabled"] is True
    assert registry.sources["yahoo"]["future_quote_capability"] is True
    assert registry.validation["daily_bars"]["comparison_rule_version"] == "daily_bar_validation_v3"
    assert registry.validation["daily_bars"]["source_price_basis"]["massive"] == "split_adjusted"
    assert registry.validation["daily_bars"]["source_price_basis"]["yahoo"] == "provider_adjusted_unknown"
    assert registry.validation["daily_bars"]["sources"]["yahoo"]["adjusted_close_field"] == "Adj Close"


def test_yahoo_historical_validation_flag_is_separate_from_quotes(monkeypatch):
    monkeypatch.setenv("YAHOO_ENABLED", "true")
    monkeypatch.setenv("YAHOO_HISTORICAL_VALIDATION_ENABLED", "true")
    monkeypatch.setenv("YAHOO_QUOTES_ENABLED", "false")
    settings = get_settings()
    assert settings.yahoo_enabled is True
    assert settings.yahoo_historical_validation_enabled is True
    assert settings.yahoo_quotes_enabled is False


def test_yahoo_historical_validation_defaults_to_yahoo_enabled(monkeypatch):
    monkeypatch.setenv("YAHOO_ENABLED", "true")
    monkeypatch.delenv("YAHOO_HISTORICAL_VALIDATION_ENABLED", raising=False)
    monkeypatch.setenv("YAHOO_QUOTES_ENABLED", "false")
    settings = get_settings()
    assert settings.yahoo_historical_validation_enabled is True
    assert settings.yahoo_quotes_enabled is False


def test_market_calendar_completed_session_rules():
    calendar = MarketCalendar()
    weekend = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    assert calendar.completed_session_end_date(weekend) == date(2026, 7, 2)
    holiday = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert calendar.completed_session_end_date(holiday) == date(2025, 12, 31)
    during_session = datetime(2026, 1, 2, 16, 0, tzinfo=timezone.utc)
    assert calendar.completed_session_end_date(during_session) == date(2025, 12, 31)
    after_close = datetime(2026, 1, 2, 22, 0, tzinfo=timezone.utc)
    assert calendar.completed_session_end_date(after_close) == date(2026, 1, 2)
    early_close_after = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)
    assert calendar.completed_session_end_date(early_close_after) == date(2026, 11, 27)


def test_retention_dry_run_and_prune_protects_incidents(session):
    repo = WarehouseRepository(session)
    old = datetime(2025, 1, 1, tzinfo=timezone.utc)
    payload = repo.raw_payload("yahoo", "quote_snapshot", {"symbol": "SPY"}, {"old": True}, retention_class="quote")
    payload.retrieved_at_utc = old
    protected = repo.raw_payload("yahoo", "quote_snapshot", {"symbol": "QQQ"}, {"old": "protected"}, retention_class="quote")
    protected.retrieved_at_utc = old
    repo.record_event("quote_source_unavailable", "incident", "warning", "yahoo", details={"raw_payload_id": protected.id})
    session.commit()
    dry = RetentionService(session).prune_raw_payloads("quote", dry_run=True, retention_days=90)
    assert dry.eligible == 1
    assert dry.protected == 1
    assert session.get(m.RawPayload, payload.id).response_payload is not None
    actual = RetentionService(session).prune_raw_payloads("quote", dry_run=False, retention_days=90)
    assert actual.pruned == 1
    assert session.get(m.RawPayload, payload.id).response_payload is None
    assert session.get(m.RawPayload, protected.id).response_payload is not None


def test_registry_validation_failures():
    registry = load_registry()
    bad_source = Registry(
        sources=registry.sources,
        series={"BAD": {**registry.series["DGS10"], "source": "missing"}},
        instruments=registry.instruments,
        profiles=registry.profiles,
        validation=registry.validation,
    )
    with pytest.raises(RegistryError):
        validate_registry(bad_source)
    bad_profile = Registry(
        sources=registry.sources,
        series={"BAD": {**registry.series["DGS10"], "collection_profile": "missing"}},
        instruments=registry.instruments,
        profiles=registry.profiles,
        validation=registry.validation,
    )
    with pytest.raises(RegistryError):
        validate_registry(bad_profile)
    bad_basis = Registry(
        sources=registry.sources,
        series=registry.series,
        instruments=registry.instruments,
        profiles={**registry.profiles, "daily_market": {**registry.profiles["daily_market"], "price_basis": "vague"}},
        validation=registry.validation,
    )
    with pytest.raises(RegistryError):
        validate_registry(bad_basis)
    bad_pair = Registry(
        sources=registry.sources,
        series=registry.series,
        instruments=registry.instruments,
        profiles=registry.profiles,
        validation={
            **registry.validation,
            "daily_bars": {
                **registry.validation["daily_bars"],
                "allowed_price_basis_pairs": [["split_adjusted", "mystery"]],
            },
        },
    )
    with pytest.raises(RegistryError):
        validate_registry(bad_pair)
    bad_approval = Registry(
        sources=registry.sources,
        series=registry.series,
        instruments=registry.instruments,
        profiles=registry.profiles,
        validation={
            **registry.validation,
            "daily_bars": {
                **registry.validation["daily_bars"],
                "approved_comparison_pairs": [
                    {**registry.validation["daily_bars"]["approved_comparison_pairs"][0], "status": "always_trust"}
                ],
            },
        },
    )
    with pytest.raises(RegistryError):
        validate_registry(bad_approval)
