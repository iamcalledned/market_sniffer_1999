from __future__ import annotations

from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_sniffer.db import models as m


def get_metric_history(session: Session, metric_code: str, limit: int = 120) -> list[tuple[date, float]]:
    """Retrieves the history of a specific metric from the database."""
    stmt = (
        select(m.MetricObservation)
        .join(m.MetricDefinition)
        .where(
            m.MetricDefinition.metric_code == metric_code,
            m.MetricObservation.value_numeric.is_not(None),
        )
        .order_by(m.MetricObservation.as_of_date.asc())
    )
    obs = session.scalars(stmt).all()
    # Apply limit to the end of the history
    if limit > 0:
        obs = obs[-limit:]
    return [(o.as_of_date, float(o.value_numeric)) for o in obs if o.value_numeric is not None]


def get_instrument_history(session: Session, symbol: str, limit: int = 120) -> list[tuple[date, float]]:
    """Retrieves the close price history of an instrument from the database."""
    stmt = (
        select(m.CanonicalMarketBarDaily)
        .join(m.Instrument)
        .where(
            m.Instrument.symbol == symbol,
            m.CanonicalMarketBarDaily.close.is_not(None),
        )
        .order_by(m.CanonicalMarketBarDaily.trade_date.asc())
    )
    bars = session.scalars(stmt).all()
    if limit > 0:
        bars = bars[-limit:]
    return [(b.trade_date, float(b.close)) for b in bars]


def get_series_history(session: Session, series_code: str, limit: int = 120) -> list[tuple[date, float]]:
    """Retrieves the history of a FRED series from the database."""
    stmt = (
        select(m.CanonicalObservation)
        .join(m.DataSeries)
        .where(
            m.DataSeries.series_code == series_code,
            m.CanonicalObservation.value.is_not(None),
        )
        .order_by(m.CanonicalObservation.observation_date.asc())
    )
    obs = session.scalars(stmt).all()
    if limit > 0:
        obs = obs[-limit:]
    return [(o.observation_date, float(o.value)) for o in obs]


def generate_svg_chart(data: Sequence[tuple[date, float]], title: str, unit: str) -> str:
    """Generates a beautiful, responsive SVG line chart with a dark financial theme."""
    width = 800
    height = 350
    padding_top = 40
    padding_bottom = 50
    padding_left = 70
    padding_right = 30

    if len(data) < 2:
        # Render empty state placeholder SVG
        return (
            f'<svg viewBox="0 0 {width} {height}" class="chart-svg" xmlns="http://www.w3.org/2000/svg">'
            f'<rect width="100%" height="100%" fill="#161b22" rx="6"/>'
            f'<text x="{width // 2}" y="{height // 2}" fill="#8b949e" font-family="system-ui" '
            f'font-size="16" text-anchor="middle">Insufficient historical data to render chart</text>'
            f"</svg>"
        )

    # Calculate ranges
    dates = [d[0] for d in data]
    values = [d[1] for d in data]

    min_val = min(values)
    max_val = max(values)
    # Add a small padding to Y range to prevent hugging boundaries
    val_range = max_val - min_val
    if val_range == 0:
        min_val -= 1.0
        max_val += 1.0
        val_range = 2.0
    else:
        min_val -= val_range * 0.08
        max_val += val_range * 0.08
        val_range = max_val - min_val

    min_ord = min(dates).toordinal()
    max_ord = max(dates).toordinal()
    ord_range = max_ord - min_ord
    if ord_range == 0:
        ord_range = 1

    chart_w = width - padding_left - padding_right
    chart_h = height - padding_top - padding_bottom

    # Map data to SVG coordinates
    coords: list[tuple[float, float]] = []
    for d, val in data:
        x = padding_left + ((d.toordinal() - min_ord) / ord_range) * chart_w
        y = height - padding_bottom - ((val - min_val) / val_range) * chart_h
        coords.append((x, y))

    # Build chart line path
    line_path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)

    # Build gradient fill path (area under the curve)
    fill_path = (
        f"{line_path} L {coords[-1][0]:.1f} {height - padding_bottom:.1f} "
        f"L {coords[0][0]:.1f} {height - padding_bottom:.1f} Z"
    )

    # Generate Y gridlines and labels (4 lines)
    grid_lines = []
    for i in range(4):
        y_val = min_val + (val_range * i / 3.0)
        y_coord = height - padding_bottom - (i / 3.0) * chart_h

        # Format label based on unit
        if unit == "ratio":
            label = f"{y_val * 100.0:.1f}%"
        elif unit == "percent":
            label = f"{y_val:.1f}%"
        elif unit == "percent_point":
            label = f"{y_val:.1f} pp"
        else:
            label = f"{y_val:.2f}"

        grid_lines.append(
            f'<line x1="{padding_left}" y1="{y_coord:.1f}" x2="{width - padding_right}" y2="{y_coord:.1f}" '
            f'stroke="#30363d" stroke-dasharray="4,4" />'
            f'<text x="{padding_left - 10}" y="{y_coord + 4:.1f}" fill="#8b949e" font-family="system-ui" '
            f'font-size="11" text-anchor="end">{label}</text>'
        )

    # Generate X axis date labels (3 labels: start, middle, end)
    indices = [0, len(data) // 2, len(data) - 1]
    x_labels = []
    for idx in indices:
        d, val = data[idx]
        x_coord = coords[idx][0]
        date_label = d.strftime("%b %d, %Y")
        x_labels.append(
            f'<text x="{x_coord:.1f}" y="{height - padding_bottom + 20}" fill="#8b949e" font-family="system-ui" '
            f'font-size="11" text-anchor="middle">{date_label}</text>'
        )

    # Assemble the final SVG
    svg_parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" xmlns="http://www.w3.org/2000/svg">',
        '<defs>',
        '  <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">',
        '    <stop offset="0%" stop-color="#58a6ff" stop-opacity="0.25"/>',
        '    <stop offset="100%" stop-color="#58a6ff" stop-opacity="0.00"/>',
        '  </linearGradient>',
        '</defs>',
        '<rect width="100%" height="100%" fill="#161b22" rx="6" stroke="#30363d" stroke-width="1"/>',
        # Title
        f'<text x="{padding_left}" y="25" fill="#c9d1d9" font-family="system-ui" font-weight="600" font-size="14">{title}</text>',
        # Grid lines
        "".join(grid_lines),
        # Area fill
        f'<path d="{fill_path}" fill="url(#chartGrad)" />',
        # Outline path
        f'<path d="{line_path}" fill="none" stroke="#58a6ff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>',
        # Date labels
        "".join(x_labels),
        "</svg>",
    ]
    return "\n".join(svg_parts)
