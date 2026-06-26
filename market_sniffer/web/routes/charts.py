from __future__ import annotations

from flask import Blueprint, render_template

from market_sniffer.services.dashboard.chart_service import (
    generate_svg_chart,
    get_metric_history,
)
from market_sniffer.services.dashboard.formatters import format_value
from market_sniffer.services.metric_registry import load_metric_registry
from market_sniffer.web.app import ChartMetricNotFound
from market_sniffer.web.extensions import get_db_session

charts_bp = Blueprint("charts", __name__, url_prefix="/charts")


@charts_bp.route("/<metric_code>")
def show_chart(metric_code: str):
    """Renders a chart page for a specific metric using a server-rendered SVG."""
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

    return render_template(
        "charts/show.html",
        metric_code=metric_code,
        display_name=display_name,
        date_range=date_range,
        current_value=current_val,
        source=source,
        quality_note="Canonical persisted historical calculations",
        svg_chart=svg_chart,
        interpretation_limits="This briefing page displays historical calculations for observation purposes only. No buy or sell signals are generated. Past indicators are not predictive of future market results.",
    )
