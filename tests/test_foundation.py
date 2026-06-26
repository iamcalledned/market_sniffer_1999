from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from market_sniffer.collectors.base import DailyBar, MissingCredentialError
from market_sniffer.collectors.fred import FixtureFredClient, FredApiClient
from market_sniffer.collectors.massive import FixtureMassiveClient
from market_sniffer.collectors.yahoo import FixtureYahooQuoteClient, YahooQuoteClient
from market_sniffer.db import models as m
from market_sniffer.db.engine import assert_sqlite_pragmas, create_db_engine
from market_sniffer.db.models import Base
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.backfill import BackfillService
from market_sniffer.services.dates import default_backfill_window
from market_sniffer.services.quality import DataQualityService
from market_sniffer.services.registry_service import load_registry


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
    assert repo.insert_daily_bar("SPY", "massive", payload, bar.asdict()) is True
    assert repo.insert_daily_bar("SPY", "massive", payload, bar.asdict()) is False
    session.commit()
    assert repo.counts()["daily_bars"] == 1


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
    session.commit()
    assert repo.counts()["canonical_observations"] == 1


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
    service = BackfillService(session, registry, FixtureFredClient(), FixtureMassiveClient())
    kwargs = {"profile": "core", "start": date(2026, 1, 2), "end": date(2026, 1, 6), "only": ["DGS10", "SPY"]}
    assert service.backfill(**kwargs) == 0
    counts_first = WarehouseRepository(session).counts()
    assert service.backfill(**kwargs) == 0
    counts_second = WarehouseRepository(session).counts()
    assert counts_second["canonical_observations"] == counts_first["canonical_observations"]
    assert counts_second["daily_bars"] == counts_first["daily_bars"]


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


def test_no_credentials_in_payload_metadata(session):
    repo = WarehouseRepository(session)
    payload = repo.raw_payload("massive", "fixture", {"apiKey": "secret", "nested": {"token": "abc"}}, {"ok": True})
    assert payload.request_metadata["apiKey"] == "***REDACTED***"
    assert payload.request_metadata["nested"]["token"] == "***REDACTED***"


def test_future_quote_polling_disabled_by_default():
    registry = load_registry()
    assert registry.profiles["future_realtime_quote_watchlist"]["enabled_by_default"] is False
    assert registry.sources["yahoo"]["enabled"] is False
