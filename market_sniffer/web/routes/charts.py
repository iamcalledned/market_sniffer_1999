from __future__ import annotations

from flask import Blueprint, render_template, abort
from sqlalchemy import select

from market_sniffer.db import models as m
from market_sniffer.services.dashboard.chart_service import (
    generate_svg_chart,
    get_metric_history,
    get_instrument_history,
    get_series_history,
)
from market_sniffer.services.dashboard.formatters import format_value
from market_sniffer.services.dashboard.explanations import MetricExplanationService
from market_sniffer.services.metric_registry import load_metric_registry, METRIC_CATEGORIES
from market_sniffer.web.app import ChartMetricNotFound
from market_sniffer.web.extensions import get_db_session

charts_bp = Blueprint("charts", __name__, url_prefix="/charts")


@charts_bp.route("")
@charts_bp.route("/")
def index():
    """Lists all active chartable metrics grouped by category, plus instruments and FRED series."""
    registry = load_metric_registry()
    session = get_db_session()
    explanation_service = MetricExplanationService()

    stmt = (
        select(
            m.MetricObservation,
            m.MetricDefinition.metric_code,
            m.MetricDefinition.unit,
            m.MetricDefinition.display_name,
            m.MetricDefinition.category,
        )
        .join(
            m.MetricDefinition,
            m.MetricObservation.metric_definition_id == m.MetricDefinition.id,
        )
        .where(
            m.MetricObservation.formula_version == m.MetricDefinition.formula_version,
            m.MetricDefinition.enabled.is_(True),
        )
        .order_by(m.MetricObservation.as_of_date.desc())
    )
    all_rows = session.execute(stmt).all()

    latest_obs: dict[str, tuple[float, any]] = {}
    for obs, code, unit, display_name, category in all_rows:
        if code not in latest_obs:
            latest_obs[code] = (float(obs.value_numeric) if obs.value_numeric is not None else None, obs.as_of_date)

    # Group metrics by category
    grouped_metrics: dict[str, list] = {}
    for category in METRIC_CATEGORIES:
        grouped_metrics[category] = []

    for code, mdef in registry.enabled_metrics.items():
        cat = mdef.get("category", "market_structure")
        if cat not in grouped_metrics:
            grouped_metrics[cat] = []
        expl = explanation_service.get_explanation(code)
        val, as_of = latest_obs.get(code, (None, None))
        val_str = format_value(val, mdef.get("unit", "unknown")) if val is not None else "N/A"
        
        grouped_metrics[cat].append({
            "code": code,
            "display_name": mdef.get("display_name", code),
            "plain_label": expl.get("plain_label", mdef.get("display_name", code)),
            "short_description": expl.get("short_description", ""),
            "latest_value": val_str,
            "as_of": as_of.strftime("%Y-%m-%d") if as_of else "N/A",
        })

    # Sort each category alphabetically by plain_label/display_name
    for cat in grouped_metrics:
        grouped_metrics[cat].sort(key=lambda x: x["plain_label"].lower())

    instruments = session.scalars(select(m.Instrument).order_by(m.Instrument.symbol)).all()
    series = session.scalars(select(m.DataSeries).order_by(m.DataSeries.series_code)).all()

    category_labels = {
        "market_structure": "Market Structure & Trends",
        "leadership_breadth": "Breadth & Leadership",
        "rates_credit": "Interest Rates & Credit",
        "volatility_cross_asset": "Volatility & Cross-Asset",
        "macro_momentum": "Macroeconomic & Liquidity",
    }

    return render_template(
        "charts/index.html",
        grouped_metrics=grouped_metrics,
        category_labels=category_labels,
        instruments=instruments,
        series=series,
    )


@charts_bp.route("/metric/<metric_code>")
def show_metric(metric_code: str):
    """Renders a chart page for a specific metric using a server-rendered SVG and explanations."""
    registry = load_metric_registry()
    if metric_code not in registry.metrics:
        raise ChartMetricNotFound(f"Metric code '{metric_code}' is not registered.")

    session = get_db_session()
    data = get_metric_history(session, metric_code, limit=120)

    metric_def = registry.metrics[metric_code]
    display_name = metric_def.get("display_name", metric_code)
    unit = metric_def.get("unit", "unknown")

    # Generate the SVG string
    svg_chart = generate_svg_chart(data, display_name, unit)

    # Calculate ranges and details
    if data:
        min_date = data[0][0].strftime("%b %d, %Y")
        max_date = data[-1][0].strftime("%b %d, %Y")
        date_range = f"{min_date} to {max_date}"
        current_val = format_value(data[-1][1], unit)
    else:
        date_range = "No data range"
        current_val = "N/A"

    source = "FRED" if metric_code.startswith(("rates.", "credit.", "volatility.", "macro.")) else "Massive"
    
    explanation_service = MetricExplanationService()
    expl = explanation_service.get_explanation(metric_code)

    return render_template(
        "charts/metric.html",
        metric_code=metric_code,
        display_name=display_name,
        plain_label=expl.get("plain_label", display_name),
        short_description=expl.get("short_description", ""),
        why_it_matters=expl.get("why_it_matters", ""),
        what_it_does_not_mean=expl.get("what_it_does_not_mean", ""),
        good_to_know=expl.get("good_to_know", ""),
        date_range=date_range,
        current_value=current_val,
        source=source,
        quality_note="Canonical persisted historical calculations",
        svg_chart=svg_chart,
        interpretation_limits="This briefing page displays historical calculations for observation purposes only. No buy or sell signals are generated. Past indicators are not predictive of future market results.",
    )


@charts_bp.route("/instrument/<symbol>")
def show_instrument(symbol: str):
    """Renders a close price chart page for a specific instrument."""
    session = get_db_session()
    symbol_upper = symbol.upper()
    
    inst = session.scalar(select(m.Instrument).where(m.Instrument.symbol == symbol_upper))
    if not inst:
        abort(404, description=f"Instrument '{symbol}' not found in database.")

    data = get_instrument_history(session, symbol_upper, limit=120)

    # Generate the SVG string
    svg_chart = generate_svg_chart(data, f"{symbol_upper} Close Price", "price")

    if data:
        min_date = data[0][0].strftime("%b %d, %Y")
        max_date = data[-1][0].strftime("%b %d, %Y")
        date_range = f"{min_date} to {max_date}"
        current_val = f"${data[-1][1]:.2f}"
    else:
        date_range = "No data range"
        current_val = "N/A"

    return render_template(
        "charts/instrument.html",
        symbol=symbol_upper,
        display_name=inst.name,
        date_range=date_range,
        current_value=current_val,
        quality_note="Canonical trade session close prices",
        svg_chart=svg_chart,
        interpretation_limits="This briefing page displays historical asset close prices. Past performance is no guarantee of future results.",
    )


@charts_bp.route("/series/<series_code>")
def show_series(series_code: str):
    """Renders a chart page for a specific FRED series."""
    session = get_db_session()
    series_code_upper = series_code.upper()
    
    ser = session.scalar(select(m.DataSeries).where(m.DataSeries.series_code == series_code_upper))
    if not ser:
        abort(404, description=f"FRED series '{series_code}' not found in database.")

    data = get_series_history(session, series_code_upper, limit=120)

    # Generate the SVG string
    svg_chart = generate_svg_chart(data, f"{series_code_upper} Level", ser.unit or "level")

    if data:
        min_date = data[0][0].strftime("%b %d, %Y")
        max_date = data[-1][0].strftime("%b %d, %Y")
        date_range = f"{min_date} to {max_date}"
        current_val = format_value(data[-1][1], ser.unit or "level")
    else:
        date_range = "No data range"
        current_val = "N/A"

    return render_template(
        "charts/series.html",
        series_code=series_code_upper,
        display_name=ser.display_name,
        date_range=date_range,
        current_value=current_val,
        quality_note="Point-in-time canonical series observations",
        svg_chart=svg_chart,
        interpretation_limits="This briefing page displays Federal Reserve Economic Data series observations. Economic indices are subject to historical revisions.",
    )
