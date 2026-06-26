from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import select

from market_sniffer.db import models as m
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.dashboard.chart_service import (
    get_instrument_history,
    get_metric_history,
    get_series_history,
)
from market_sniffer.services.dashboard.service import DashboardService
from market_sniffer.services.quotes.yahoo_quote_service import YahooQuoteService
from market_sniffer.web.extensions import get_db_session

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/health")
def health():
    """System health check endpoint."""
    try:
        session = get_db_session()
        repo = WarehouseRepository(session)
        counts = repo.counts()
        return jsonify({"status": "healthy", "database": "online", "counts": counts})
    except Exception as e:
        return jsonify({"status": "unhealthy", "database": "offline", "error": str(e)}), 500


@api_bp.route("/dashboard/summary")
def dashboard_summary():
    """Returns a serialized JSON representation of the dashboard view model."""
    try:
        session = get_db_session()
        service = DashboardService(session)
        vm = service.build_dashboard_view_model()
        return jsonify(asdict(vm))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/evidence/recent")
def recent_evidence():
    """Returns recent evidence events within a configurable number of days."""
    days = request.args.get("days", default=7, type=int)
    limit = request.args.get("limit", default=50, type=int)

    session = get_db_session()
    start_date = date.today() - timedelta(days=days)

    stmt = (
        select(m.EvidenceEvent, m.MetricDefinition.metric_code)
        .join(m.MetricDefinition, m.EvidenceEvent.metric_definition_id == m.MetricDefinition.id)
        .where(m.EvidenceEvent.as_of_date >= start_date)
        .order_by(m.EvidenceEvent.as_of_date.desc(), m.EvidenceEvent.id.desc())
        .limit(limit)
    )

    rows = session.execute(stmt).all()
    results = []
    for ev, metric_code in rows:
        results.append(
            {
                "id": ev.id,
                "event_code": ev.event_code,
                "event_type": ev.event_type,
                "severity": ev.severity,
                "metric_code": metric_code,
                "as_of_date": ev.as_of_date.isoformat(),
                "headline": ev.headline,
                "detail": ev.detail,
                "value": float(ev.value_numeric) if ev.value_numeric is not None else None,
                "prior_value": float(ev.prior_value_numeric) if ev.prior_value_numeric is not None else None,
                "threshold": float(ev.threshold_numeric) if ev.threshold_numeric is not None else None,
            }
        )

    return jsonify(results)


@api_bp.route("/metrics/<metric_code>")
def get_metric(metric_code: str):
    """Returns raw historical values for a metric."""
    session = get_db_session()
    stmt = (
        select(m.MetricObservation)
        .join(m.MetricDefinition)
        .where(m.MetricDefinition.metric_code == metric_code)
        .order_by(m.MetricObservation.as_of_date.asc())
    )
    observations = session.scalars(stmt).all()
    results = [
        {
            "as_of_date": obs.as_of_date.isoformat(),
            "value": float(obs.value_numeric) if obs.value_numeric is not None else None,
            "quality_status": obs.quality_status,
        }
        for obs in observations
    ]
    return jsonify(results)


@api_bp.route("/charts/metric/<metric_code>")
def chart_metric(metric_code: str):
    """JSON historical observations list for metrics charting."""
    session = get_db_session()
    data = get_metric_history(session, metric_code, limit=120)
    return jsonify([{"date": d.isoformat(), "value": v} for d, v in data])


@api_bp.route("/charts/instrument/<symbol>")
def chart_instrument(symbol: str):
    """JSON historical close prices for instrument charting."""
    session = get_db_session()
    data = get_instrument_history(session, symbol.upper(), limit=120)
    return jsonify([{"date": d.isoformat(), "value": v} for d, v in data])


@api_bp.route("/charts/series/<series_code>")
def chart_series(series_code: str):
    """JSON historical observations for FRED series charting."""
    session = get_db_session()
    data = get_series_history(session, series_code, limit=120)
    return jsonify([{"date": d.isoformat(), "value": v} for d, v in data])


@api_bp.route("/quotes/<symbol>")
def get_quote(symbol: str):
    """Yahoo quote endpoint for explicit manual lookup of one symbol."""
    persist = request.args.get("persist", default="false").lower() == "true"
    session = get_db_session()
    fixture_mode = current_app.config.get("FIXTURE", False)
    service = YahooQuoteService(session, fixture=fixture_mode)

    try:
        quote_vm = service.lookup_quote(symbol, persist=persist)
        return jsonify(asdict(quote_vm))
    except ValueError as val_err:
        return jsonify({"error": str(val_err), "code": "INVALID_SYMBOL"}), 400
    except Exception as exc:
        return jsonify({"error": str(exc), "code": "PROVIDER_UNAVAILABLE"}), 500
