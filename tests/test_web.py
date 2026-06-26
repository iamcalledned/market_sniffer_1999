from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest.mock as mock
import os

import pytest
from flask import Flask
from sqlalchemy import select

from market_sniffer.db import models as m
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.registry_service import load_registry
from market_sniffer.web.app import create_app


@pytest.fixture()
def app(session):
    """Creates a configured Flask app using the database from the session fixture."""
    # Ensure all required test instruments are bootstrapped in the test database
    for sym, name in [
        ("SPY", "SPY ETF"),
        ("AAPL", "Apple Inc."),
        ("MSFT", "Microsoft Corp."),
        ("XLK", "Tech ETF"),
        ("XLF", "Financial ETF"),
        ("XLE", "Energy ETF")
    ]:
        inst = session.scalar(select(m.Instrument).where(m.Instrument.symbol == sym))
        if not inst:
            inst = m.Instrument(
                symbol=sym,
                name=name,
                asset_class="equity",
                why_tracked="Test benchmark",
            )
            session.add(inst)
    session.commit()

    # Prevent Flask teardown from closing our test session
    session.close = lambda: None

    # Build app with fixture mode enabled
    app = create_app({"fixture": True})
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True

    # Inject our active test session into Flask request context globals g
    @app.before_request
    def inject_test_session():
        from flask import g
        g.db_session = session

    yield app


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
    # Delete database contents in dependency order to prevent foreign key errors
    session.query(m.EvidenceEvent).delete()
    session.query(m.MetricObservation).delete()
    session.query(m.MetricDefinition).delete()
    session.query(m.MetricCalculationRun).delete()
    session.query(m.SourceDiscrepancy).delete()
    session.query(m.CorporateAction).delete()
    session.query(m.MarketSnapshot).delete()
    session.query(m.QuoteSnapshot).delete()
    session.query(m.MarketBarIntraday).delete()
    session.query(m.CanonicalObservation).delete()
    session.query(m.RawObservation).delete()
    session.query(m.CanonicalMarketBarDaily).delete()
    session.query(m.MarketBarDaily).delete()
    session.query(m.DataQualityEvent).delete()
    session.query(m.CollectorRunItem).delete()
    session.query(m.CollectorRun).delete()
    session.query(m.CollectorDefinition).delete()
    session.query(m.SourceSeriesMapping).delete()
    session.query(m.DataSeries).delete()
    session.query(m.InstrumentAlias).delete()
    session.query(m.Instrument).delete()
    session.query(m.RawPayload).delete()
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
    
    now_utc = datetime.now(timezone.utc)
    
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
    session.flush() # populate bar.id
    
    # also insert canonical daily bar
    cbar = m.CanonicalMarketBarDaily(
        instrument_id=inst.id,
        trade_date=date(2026, 6, 25),
        open=Decimal("400"),
        high=Decimal("405"),
        low=Decimal("398"),
        close=Decimal("402"),
        canonical_source_id=source.id,
        source_market_bar_id=bar.id,  # Use actual bar ID
        raw_payload_id=raw.id,
        canonicalization_rule_version="v1",
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
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

    # Wrap session methods to track changes without triggering on empty autoflushes
    def mock_flush(*args, **kwargs):
        if session.dirty or session.new or session.deleted:
            raise AssertionError("Database mutation attempted during GET /")
    
    session.flush = mock.Mock(side_effect=mock_flush)
    session.commit = mock.Mock(side_effect=AssertionError("Database mutation attempted during GET /"))

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

    # Section 2: Start Here
    assert "Start Here" in html
    assert "Welcome to Market Sniffer 2000" in html
    assert "Read-only dashboard rendering" in html

    # Section 3: Market Brief
    assert "SPY remains 10.00% above its 200-day average" in html
    assert "its 21-day return is 5.00%" in html
    assert "Breadth is broad: 80.00% above 50d" in html
    assert "VIX is 15.00, up 2.00 over five observations" in html
    assert "High-yield OAS is 3.50 pp and changed little" in html

    # Forbidden words checks
    forbidden = ["buy", "sell", "bullish", "bearish", "risk-on", "risk-off", "market will", "should outperform"]
    for word in forbidden:
        assert word not in html.lower()

    # Section 4: Key Market Strip
    assert "SPY" in html
    assert "Trend" in html
    assert "Breadth" in html
    assert "Volatility" in html
    assert "Credit" in html
    assert "Rates" in html
    assert "Leadership" in html

    # Section 5: What Changed
    assert "XLK relative performance became material" in html
    assert "Latest +4.00% vs SPY" in html
    assert "Triggered 1 times" in html

    # Section 6: Market Map (2x2 Panel grid)
    assert "Trend &amp; Structure" in html
    assert "Breadth &amp; Leadership" in html
    assert "Rates &amp; Credit" in html
    assert "Volatility &amp; Cross-Asset" in html
    assert "View Key Chart" in html

    # Section 7: Data Confidence
    assert "Confidence Status" in html
    assert "Unresolved Issues" in html
    assert "Top Quality Event Groups" in html
    assert "quote freshness problem" in html

    # Section 8: Technical Appendix is collapsed
    assert "<details class=\"technical-appendix\">" in html
    assert "Technical Appendix" in html


def test_chart_data_endpoints(session, client):
    """Verify that chart JSON endpoints return enveloped persisted database history."""
    _seed_test_database(session)

    # 1. Metric chart JSON
    res = client.get("/api/charts/metric/market.spy_close")
    assert res.status_code == 200
    res_json = res.json
    assert res_json["ok"] is True
    data = res_json["data"]
    assert len(data) > 0
    assert data[-1]["value"] == 440.0

    # 2. Instrument chart JSON
    res = client.get("/api/charts/instrument/SPY")
    assert res.status_code == 200
    res_json = res.json
    assert res_json["ok"] is True
    data = res_json["data"]
    assert len(data) > 0
    assert data[-1]["value"] == 440.0

    # 3. FRED chart JSON
    res = client.get("/api/charts/series/VIXCLS")
    assert res.status_code == 200
    res_json = res.json
    assert res_json["ok"] is True
    data = res_json["data"]
    assert len(data) > 0
    assert data[-1]["value"] == 15.0


def test_yahoo_quote_lookup(client):
    """Verify Yahoo quote route behavior, input validation, and explicit lookup."""
    # 1. Symbol validation (should fail for invalid inputs)
    res = client.post("/quotes/lookup", data={"symbol": "INVALID$$$"})
    assert b"Invalid symbol format" in res.data

    # 2. Fetch works in fixture mode
    res = client.post("/quotes/lookup", data={"symbol": "AAPL", "persist": "false"})
    assert res.status_code == 200
    assert b"Quote Details: AAPL" in res.data
    assert b"Provider:</strong> Yahoo" in res.data
    assert b"Live" not in res.data  # delayed is fixture delay

    # 3. Requesting persistence saves to DB
    res = client.post("/quotes/lookup", data={"symbol": "MSFT", "persist": "true"})
    assert res.status_code == 200
    assert b"Persisted to DB" in res.data


def test_navigation_and_charts_index(session, client):
    """Verify navigation links exist and the /charts index renders grouped active metrics."""
    _seed_test_database(session)

    res = client.get("/charts")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Assert categories exist
    assert "Market Structure &amp; Trends" in html
    assert "Breadth &amp; Leadership" in html
    assert "Interest Rates &amp; Credit" in html
    assert "Volatility &amp; Cross-Asset" in html

    # Assert plain labels are present
    assert "SPY Close Price" in html
    assert "Breadth Above 50-Day Average" in html

    # Assert listed instruments and FRED series are present
    assert "SPY" in html
    assert "VIXCLS" in html


def test_panel_view_key_charts_links(session, client):
    """Verify that each dashboard grid panel contains its expected View Key Chart link."""
    _seed_test_database(session)

    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Verify Trend & Structure -> market.spy_distance_200d
    assert '/charts/metric/market.spy_distance_200d' in html

    # Verify Breadth & Leadership -> breadth.tracked_above_50d_pct
    assert '/charts/metric/breadth.tracked_above_50d_pct' in html

    # Verify Rates & Credit -> credit.hy_oas
    assert '/charts/metric/credit.hy_oas' in html

    # Verify Volatility & Cross-Asset -> volatility.vix_level
    assert '/charts/metric/volatility.vix_level' in html


def test_detailed_chart_pages(session, client):
    """Verify that metric, instrument, and series detailed chart pages render successfully."""
    _seed_test_database(session)

    # 1. Metric page
    res = client.get("/charts/metric/market.spy_distance_200d")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "SPY Distance from 200-Day Average" in html
    assert "Why It Matters" in html
    assert "What It Does Not Mean" in html
    assert "<svg" in html
    assert "This briefing page displays historical calculations" in html

    # 2. Instrument page
    res = client.get("/charts/instrument/SPY")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "SPY Close Price" in html
    assert "<svg" in html
    assert "Past performance is no guarantee of future results" in html

    # 3. FRED series page
    res = client.get("/charts/series/VIXCLS")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "VIXCLS Level" in html
    assert "<svg" in html
    assert "Economic indices are subject to historical revisions" in html


def test_api_response_formatting_envelopes(client):
    """Verify that all JSON API responses wrap results in ok: true/false envelopes."""
    # Health
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json["ok"] is True
    assert "status" in res.json["data"]

    # Dashboard summary
    res = client.get("/api/dashboard/summary")
    # This might return 500 or 200 depending on DB state, but it should have correct ok/error structure
    assert "ok" in res.json

    # Recent evidence
    res = client.get("/api/evidence/recent")
    assert res.status_code == 200
    assert res.json["ok"] is True
    assert isinstance(res.json["data"], list)

    # Single-symbol Yahoo lookup (valid)
    res = client.get("/api/quotes/AAPL")
    assert res.status_code == 200
    assert res.json["ok"] is True
    assert res.json["data"]["symbol"] == "AAPL"

    # Single-symbol Yahoo lookup (invalid symbol formatting)
    res = client.get("/api/quotes/INVALID$$$")
    assert res.status_code == 400
    assert res.json["ok"] is False
    assert "error" in res.json
    assert res.json["code"] == "INVALID_SYMBOL"


def test_future_intelligence_boundaries_isolation(app):
    """Assert recommendations/forecasting are decoupled and prediction routes do not exist."""
    # Check that placeholders exist on disk
    assert os.path.exists("market_sniffer/services/recommendations/__init__.py")
    assert os.path.exists("market_sniffer/services/forecasting/__init__.py")

    # Assert no active recommendations/predictions routes are registered in the Flask app
    rules = [rule.rule for rule in app.url_map.iter_rules()]
    for rule in rules:
        assert "predict" not in rule
        assert "recommend" not in rule
        assert "forecast" not in rule


def _seed_test_database(session):
    """Populates the database with valid metrics, runs, observations and quality issues."""
    repo = WarehouseRepository(session)
    source = repo.source("massive")
    source_fred = repo.source("fred")

    inst_spy = repo.instrument("SPY")

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

    now_utc = datetime.now(timezone.utc)

    # Seed at least TWO raw market bars for SPY to allow line charting (len >= 2)
    mb_bar1 = m.MarketBarDaily(
        instrument_id=inst_spy.id,
        trade_date=date(2026, 6, 24),
        source_id=source.id,
        open=Decimal("395"),
        high=Decimal("402"),
        low=Decimal("394"),
        close=Decimal("400"),
        raw_payload_id=raw.id,
    )
    mb_bar2 = m.MarketBarDaily(
        instrument_id=inst_spy.id,
        trade_date=date(2026, 6, 25),
        source_id=source.id,
        open=Decimal("400"),
        high=Decimal("440"),
        low=Decimal("398"),
        close=Decimal("440"),
        raw_payload_id=raw.id,
    )
    session.add(mb_bar1)
    session.add(mb_bar2)
    session.flush()

    # Seed canonical daily bars matching
    bar1 = m.CanonicalMarketBarDaily(
        instrument_id=inst_spy.id,
        trade_date=date(2026, 6, 24),
        open=Decimal("395"),
        high=Decimal("402"),
        low=Decimal("394"),
        close=Decimal("400"),
        canonical_source_id=source.id,
        source_market_bar_id=mb_bar1.id,
        raw_payload_id=raw.id,
        canonicalization_rule_version="v1",
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
    )
    bar2 = m.CanonicalMarketBarDaily(
        instrument_id=inst_spy.id,
        trade_date=date(2026, 6, 25),
        open=Decimal("400"),
        high=Decimal("440"),
        low=Decimal("398"),
        close=Decimal("440"),
        canonical_source_id=source.id,
        source_market_bar_id=mb_bar2.id,
        raw_payload_id=raw.id,
        canonicalization_rule_version="v1",
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
    )
    session.add(bar1)
    session.add(bar2)

    # Seed raw observations to avoid FOREIGN KEY errors (at least two)
    raw_obs1 = m.RawObservation(
        source_id=source_fred.id,
        raw_payload_id=raw_fred.id,
        series_id=series_vix.id,
        observation_key="VIXCLS_2026-06-24",
        observed_date=date(2026, 6, 24),
        retrieved_at_utc=now_utc,
        value_text="14.0",
    )
    raw_obs2 = m.RawObservation(
        source_id=source_fred.id,
        raw_payload_id=raw_fred.id,
        series_id=series_vix.id,
        observation_key="VIXCLS_2026-06-25",
        observed_date=date(2026, 6, 25),
        retrieved_at_utc=now_utc,
        value_text="15.0",
    )
    session.add(raw_obs1)
    session.add(raw_obs2)
    session.flush()

    fred_obs1 = m.CanonicalObservation(
        series_id=series_vix.id,
        source_id=source_fred.id,
        raw_observation_id=raw_obs1.id,
        raw_payload_id=raw_fred.id,
        observation_date=date(2026, 6, 24),
        value=Decimal("14"),
        unit="index",
        is_latest_vintage=True,
        retrieved_at_utc=now_utc,
    )
    fred_obs2 = m.CanonicalObservation(
        series_id=series_vix.id,
        source_id=source_fred.id,
        raw_observation_id=raw_obs2.id,
        raw_payload_id=raw_fred.id,
        observation_date=date(2026, 6, 25),
        value=Decimal("15"),
        unit="index",
        is_latest_vintage=True,
        retrieved_at_utc=now_utc,
    )
    session.add(fred_obs1)
    session.add(fred_obs2)

    # Seed Runs
    col_run = m.CollectorRun(
        collector_name="massive",
        profile="core",
        started_at_utc=now_utc,
        finished_at_utc=now_utc,
        status="succeeded",
    )
    session.add(col_run)
    session.flush()

    calc_run = m.MetricCalculationRun(
        profile="core",
        status="succeeded",
        started_at_utc=now_utc,
        finished_at_utc=now_utc,
        metrics_attempted=10,
        metrics_succeeded=10,
    )
    session.add(calc_run)
    session.flush()

    # Seed definition and observations for all core metrics (two observations per metric to allow charting)
    metrics_to_seed = [
        ("market.spy_close", "price", Decimal("400.0"), Decimal("440.0")),
        ("market.spy_distance_200d", "ratio", Decimal("0.08"), Decimal("0.10")),
        ("market.spy_return_21d", "ratio", Decimal("0.04"), Decimal("0.05")),
        ("market.spy_return_63d", "ratio", Decimal("0.10"), Decimal("0.12")),
        ("breadth.tracked_above_50d_pct", "ratio", Decimal("0.75"), Decimal("0.80")),
        ("breadth.tracked_above_200d_pct", "ratio", Decimal("0.82"), Decimal("0.85")),
        ("volatility.vix_level", "index", Decimal("14.0"), Decimal("15.0")),
        ("volatility.vix_change_5d", "index_point", Decimal("1.5"), Decimal("2.0")),
        ("credit.hy_oas", "percent", Decimal("3.40"), Decimal("3.50")),
        ("credit.hy_oas_change_21d", "percent_point", Decimal("0.04"), Decimal("0.05")),
        ("rates.ust_2s10s_spread", "percent", Decimal("-0.22"), Decimal("-0.25")),
        ("rates.ust_3m10y_spread", "percent", Decimal("-0.12"), Decimal("-0.15")),
        ("leadership.xlk_vs_spy_21d", "ratio", Decimal("0.03"), Decimal("0.04")),
        ("leadership.xlf_vs_spy_21d", "ratio", Decimal("0.005"), Decimal("0.01")),
        ("leadership.xle_vs_spy_21d", "ratio", Decimal("-0.01"), Decimal("-0.02")),
        ("leadership.ai_infra_vs_spy_21d", "ratio", Decimal("0.025"), Decimal("0.03")),
        ("cross_asset.gold_vs_spy_21d", "ratio", Decimal("0.015"), Decimal("0.02")),
        ("macro.nfci_level", "index", Decimal("-0.44"), Decimal("-0.45")),
        ("macro.nfci_change_21d", "index_point", Decimal("0.005"), Decimal("0.01")),
    ]

    for code, unit, val1, val2 in metrics_to_seed:
        mdef = session.scalar(select(m.MetricDefinition).where(m.MetricDefinition.metric_code == code))
        if not mdef:
            mdef = m.MetricDefinition(
                metric_code=code,
                display_name=code.split(".")[-1].replace("_", " ").title(),
                category="market_structure" if "spy" in code else "rates_credit",
                formula_version="metric_v1",
                frequency="daily",
                unit=unit,
                created_at_utc=now_utc,
                updated_at_utc=now_utc,
            )
            session.add(mdef)
            session.flush()

        obs1 = m.MetricObservation(
            metric_definition_id=mdef.id,
            calculation_run_id=calc_run.id,
            as_of_date=date(2026, 6, 24),
            value_numeric=val1,
            unit=unit,
            quality_status="ok",
            formula_version="metric_v1",
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
        )
        obs2 = m.MetricObservation(
            metric_definition_id=mdef.id,
            calculation_run_id=calc_run.id,
            as_of_date=date(2026, 6, 25),
            value_numeric=val2,
            unit=unit,
            quality_status="ok",
            formula_version="metric_v1",
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
        )
        session.add(obs1)
        session.add(obs2)
        session.flush()

        # Seed an evidence event for xlk
        if code == "leadership.xlk_vs_spy_21d":
            event = m.EvidenceEvent(
                event_code="ev.xlk_vs_spy_material",
                event_type="material_change",
                severity="info",
                metric_definition_id=mdef.id,
                metric_observation_id=obs2.id,
                as_of_date=date(2026, 6, 25),
                rule_version="evidence_v1",
                headline="XLK relative performance became material",
                detail="XLK 21-day return versus SPY is 0.04.",
                value_numeric=val2,
                prior_value_numeric=val1,
                threshold_numeric=Decimal("0.03"),
                created_at_utc=now_utc,
                updated_at_utc=now_utc,
            )
            session.add(event)

    # Seed one unresolved quality event
    q_event = m.DataQualityEvent(
        event_type="quote_freshness_problem",
        severity="warning",
        observed_at_utc=now_utc,
        message="Quote is stale",
        resolved=False,
    )
    session.add(q_event)
    session.commit()
