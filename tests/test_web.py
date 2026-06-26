from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest.mock as mock

import pytest
from flask import Flask
from sqlalchemy import select

from market_sniffer.db import models as m
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.web.app import create_app


@pytest.fixture()
def app(session):
    """Creates a configured Flask app using the database from the session fixture."""
    # Build app with fixture mode enabled
    app = create_app({"fixture": True})
    app.config["TESTING"] = True

    # Override get_db_session to return the test session
    import market_sniffer.web.extensions as ext

    orig_get = ext.get_db_session
    ext.get_db_session = lambda: session

    yield app

    ext.get_db_session = orig_get


@pytest.fixture()
def client(app):
    return app.test_client()


def test_app_factory(app):
    """Verify that create_app configures Flask correctly."""
    assert isinstance(app, Flask)
    assert app.config["FIXTURE"] is True
    # Verify blueprints
    blueprints = list(app.blueprints.keys())
    assert "dashboard" in blueprints
    assert "quotes" in blueprints
    assert "charts" in blueprints
    assert "api" in blueprints


def test_static_css_route(client):
    """Verify that static assets (CSS) are served correctly."""
    res = client.get("/static/css/dashboard.css")
    assert res.status_code == 200
    assert b"Market Sniffer 2000" in res.data


def test_empty_database_setup_renders(session, client):
    """Verify that GET / handles an empty database by rendering a troubleshooting setup screen."""
    # Delete sources to trigger the empty database state
    session.query(m.DataSource).delete()
    session.commit()

    res = client.get("/")
    assert res.status_code == 500
    assert b"Database is Empty" in res.data
    assert b"python -m market_sniffer.cli backfill" in res.data


def test_missing_canonical_data_renders(session, client):
    """Verify that missing canonical bars/FRED obs renders missing data state."""
    # Database is bootstrapped, but has no market bars or observations
    res = client.get("/")
    assert res.status_code == 500
    assert b"Canonical Data Missing" in res.data
    assert b"python -m market_sniffer.cli backfill" in res.data


def test_metrics_missing_state_renders(session, client):
    """Verify that missing calculation run / metrics renders the setup screen."""
    repo = WarehouseRepository(session)
    # Insert raw market bar to clear CanonicalDataMissing, but keep MetricCalculationRun empty
    source = repo.source("massive")
    inst = repo.instrument("SPY")
    raw = repo.raw_payload("massive", "daily_bar", {"symbol": "SPY"}, {})
    bar = m.MarketBarDaily(
        instrument_id=inst.id,
        trade_date=date(2026, 6, 25),
        source_id=source.id,
        open=Decimal("400"),
        high=Decimal("405"),
        low=Decimal("398"),
        close=Decimal("402"),
        raw_payload_id=raw.id,
    )
    session.add(bar)
    # also insert canonical daily bar
    cbar = m.CanonicalMarketBarDaily(
        instrument_id=inst.id,
        trade_date=date(2026, 6, 25),
        open=Decimal("400"),
        high=Decimal("405"),
        low=Decimal("398"),
        close=Decimal("402"),
        canonical_source_id=source.id,
        source_market_bar_id=1,  # dummy id since session.flush will handle it or not needed for test
        raw_payload_id=raw.id,
        canonicalization_rule_version="v1",
    )
    session.add(cbar)
    session.commit()

    res = client.get("/")
    assert res.status_code == 500
    assert b"Metrics Not Calculated" in res.data
    assert b"python -m market_sniffer.cli metrics backfill" in res.data


def test_dashboard_renders_read_only_boundaries(session, client):
    """Verify that GET / is read-only, makes no provider calls, and performs no database commits."""
    # Seed DB with completed metrics and run metadata so the page loads successfully
    _seed_test_database(session)

    # Wrap session methods to track changes
    session.commit = mock.Mock(side_effect=AssertionError("Database mutation attempted during GET /"))
    session.flush = mock.Mock(side_effect=AssertionError("Database mutation attempted during GET /"))

    # Also mock provider calls
    with mock.patch("market_sniffer.collectors.yahoo.YahooQuoteClient.quote_snapshot") as mock_yahoo:
        res = client.get("/")
        assert res.status_code == 200
        mock_yahoo.assert_not_called()


def test_dashboard_content_and_styling(session, client):
    """Verify that all main dashboard visual sections and constraints are satisfied."""
    _seed_test_database(session)

    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Section 1: Header
    assert "Evidence through Jun 25, 2026" in html
    assert "Generated" in html
    assert "Quality Issues: 1" in html

    # Section 2: Market Brief
    assert "SPY remains 10.00% above its 200-day average" in html
    assert "its 21-day return is 5.00%" in html
    assert "Breadth is broad: 80.00% above 50d" in html
    assert "VIX is 15.00, up 2.00 over five observations" in html
    assert "High-yield OAS is 3.50 pp and changed little" in html

    # Forbidden words checks
    forbidden = ["buy", "sell", "bullish", "bearish", "risk-on", "risk-off", "market will", "should outperform"]
    for word in forbidden:
        assert word not in html.lower()

    # Section 3: Key Market Strip
    assert "SPY" in html
    assert "Trend" in html
    assert "Breadth" in html
    assert "Volatility" in html
    assert "Credit" in html
    assert "Rates" in html
    assert "Leadership" in html

    # Section 4: What Changed
    assert "XLK relative performance became material" in html
    assert "Latest +4.00% vs SPY" in html
    assert "Triggered 1 times" in html

    # Section 5: Market Map (2x2 Panel grid)
    assert "Trend &amp; Structure" in html
    assert "Breadth &amp; Leadership" in html
    assert "Rates &amp; Credit" in html
    assert "Volatility &amp; Cross-Asset" in html
    assert "View Key Chart" in html

    # Section 6: Data Confidence
    assert "Confidence Status" in html
    assert "Unresolved Issues" in html
    assert "Top Quality Event Groups" in html
    assert "quote freshness problem" in html

    # Section 7: Technical Appendix is collapsed
    assert "<details class=\"technical-appendix\">" in html
    assert "Technical Appendix" in html


def test_chart_data_endpoints(session, client):
    """Verify that chart JSON endpoints return persisted database history."""
    _seed_test_database(session)

    # 1. Metric chart JSON
    res = client.get("/api/charts/metric/market.spy_close")
    assert res.status_code == 200
    data = res.json
    assert len(data) > 0
    assert data[-1]["value"] == 440.0

    # 2. Instrument chart JSON
    res = client.get("/api/charts/instrument/SPY")
    assert res.status_code == 200
    data = res.json
    assert len(data) > 0
    assert data[-1]["value"] == 440.0

    # 3. FRED chart JSON
    res = client.get("/api/charts/series/VIXCLS")
    assert res.status_code == 200
    data = res.json
    assert len(data) > 0
    assert data[-1]["value"] == 15.0


def test_yahoo_quote_lookup(session, client):
    """Verify Yahoo quote route behavior, input validation, and explicit lookup."""
    # 1. Symbol validation (should fail for invalid inputs)
    res = client.post("/quotes/lookup", data={"symbol": "INVALID$$$"})
    assert b"Invalid symbol format" in res.data

    # 2. Fetch works in fixture mode
    res = client.post("/quotes/lookup", data={"symbol": "AAPL", "persist": "false"})
    assert res.status_code == 200
    assert b"Quote Details: AAPL" in res.data
    assert b"Provider:</b> Yahoo" in res.data
    assert b"Live" not in res.data  # delayed is fixture delay

    # 3. Requesting persistence saves to DB
    res = client.post("/quotes/lookup", data={"symbol": "MSFT", "persist": "true"})
    assert res.status_code == 200
    assert b"Persisted to DB" in res.data


def _seed_test_database(session):
    """Populates the database with valid metrics, runs, observations and quality issues."""
    repo = WarehouseRepository(session)
    source = repo.source("massive")
    source_fred = repo.source("fred")

    inst_spy = repo.instrument("SPY")
    repo.instrument("XLK")
    repo.instrument("XLF")
    repo.instrument("XLE")

    series_vix = session.scalar(select(m.DataSeries).where(m.DataSeries.series_code == "VIXCLS"))
    if not series_vix:
        series_vix = m.DataSeries(
            series_code="VIXCLS",
            source_id=source_fred.id,
            source_identifier="VIXCLS",
            display_name="VIX Index",
            category="volatility_cross_asset",
            frequency="daily",
            unit="index",
            native_unit="index",
            canonical_source_id=source_fred.id,
            why_it_matters="Volatility",
        )
        session.add(series_vix)
        session.flush()

    raw = repo.raw_payload("massive", "daily_bar", {"symbol": "SPY"}, {})
    raw_fred = repo.raw_payload("fred", "series", {"series": "VIXCLS"}, {})

    # Seed observations
    bar = m.CanonicalMarketBarDaily(
        instrument_id=inst_spy.id,
        trade_date=date(2026, 6, 25),
        open=Decimal("400"),
        high=Decimal("440"),
        low=Decimal("398"),
        close=Decimal("440"),
        canonical_source_id=source.id,
        source_market_bar_id=1,
        raw_payload_id=raw.id,
        canonicalization_rule_version="v1",
    )
    session.add(bar)

    fred_obs = m.CanonicalObservation(
        series_id=series_vix.id,
        source_id=source_fred.id,
        raw_observation_id=1,
        raw_payload_id=raw_fred.id,
        observation_date=date(2026, 6, 25),
        value=Decimal("15"),
        unit="index",
        is_latest_vintage=True,
        retrieved_at_utc=datetime.now(timezone.utc),
    )
    session.add(fred_obs)

    # Seed Runs
    col_run = m.CollectorRun(
        profile="core",
        started_at_utc=datetime.now(timezone.utc),
        finished_at_utc=datetime.now(timezone.utc),
        status="succeeded",
    )
    session.add(col_run)
    session.flush()

    calc_run = m.MetricCalculationRun(
        profile="core",
        status="succeeded",
        started_at_utc=datetime.now(timezone.utc),
        finished_at_utc=datetime.now(timezone.utc),
        metrics_attempted=10,
        metrics_succeeded=10,
    )
    session.add(calc_run)
    session.flush()

    # Seed definition and observations for all core metrics
    metrics_to_seed = [
        ("market.spy_close", "price", Decimal("440.0")),
        ("market.spy_distance_200d", "ratio", Decimal("0.10")),
        ("market.spy_return_21d", "ratio", Decimal("0.05")),
        ("market.spy_return_63d", "ratio", Decimal("0.12")),
        ("breadth.tracked_above_50d_pct", "ratio", Decimal("0.80")),
        ("breadth.tracked_above_200d_pct", "ratio", Decimal("0.85")),
        ("volatility.vix_level", "index", Decimal("15.0")),
        ("volatility.vix_change_5d", "index_point", Decimal("2.0")),
        ("credit.hy_oas", "percent", Decimal("3.50")),
        ("credit.hy_oas_change_21d", "percent_point", Decimal("0.05")),
        ("rates.ust_2s10s_spread", "percent", Decimal("-0.25")),
        ("rates.ust_3m10y_spread", "percent", Decimal("-0.15")),
        ("leadership.xlk_vs_spy_21d", "ratio", Decimal("0.04")),
        ("leadership.xlf_vs_spy_21d", "ratio", Decimal("0.01")),
        ("leadership.xle_vs_spy_21d", "ratio", Decimal("-0.02")),
        ("leadership.ai_infra_vs_spy_21d", "ratio", Decimal("0.03")),
        ("cross_asset.gold_vs_spy_21d", "ratio", Decimal("0.02")),
        ("macro.nfci_level", "index", Decimal("-0.45")),
        ("macro.nfci_change_21d", "index_point", Decimal("0.01")),
    ]

    for code, unit, val in metrics_to_seed:
        mdef = session.scalar(select(m.MetricDefinition).where(m.MetricDefinition.metric_code == code))
        if not mdef:
            mdef = m.MetricDefinition(
                metric_code=code,
                display_name=code.split(".")[-1].replace("_", " ").title(),
                category="market_structure" if "spy" in code else "rates_credit",
                formula_version="metric_v1",
                frequency="daily",
                unit=unit,
            )
            session.add(mdef)
            session.flush()

        obs = m.MetricObservation(
            metric_definition_id=mdef.id,
            calculation_run_id=calc_run.id,
            as_of_date=date(2026, 6, 25),
            value_numeric=val,
            unit=unit,
            quality_status="ok",
            formula_version="metric_v1",
            created_at_utc=datetime.now(timezone.utc),
            updated_at_utc=datetime.now(timezone.utc),
        )
        session.add(obs)
        session.flush()

        # Seed an evidence event for xlk
        if code == "leadership.xlk_vs_spy_21d":
            event = m.EvidenceEvent(
                event_code="ev.xlk_vs_spy_material",
                event_type="material_change",
                severity="info",
                metric_definition_id=mdef.id,
                metric_observation_id=obs.id,
                as_of_date=date(2026, 6, 25),
                rule_version="evidence_v1",
                headline="XLK relative performance became material",
                detail="XLK 21-day return versus SPY is 0.04.",
                value_numeric=val,
                prior_value_numeric=Decimal("0.01"),
                threshold_numeric=Decimal("0.03"),
                created_at_utc=datetime.now(timezone.utc),
                updated_at_utc=datetime.now(timezone.utc),
            )
            session.add(event)

    # Seed one unresolved quality event
    q_event = m.DataQualityEvent(
        event_type="quote_freshness_problem",
        severity="warning",
        observed_at_utc=datetime.now(timezone.utc),
        message="Quote is stale",
        resolved=False,
    )
    session.add(q_event)
    session.commit()
