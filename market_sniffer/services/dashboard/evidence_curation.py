from __future__ import annotations

from typing import Any

from market_sniffer.db import models as m
from market_sniffer.services.dashboard.formatters import format_value


def curate_evidence(
    events_with_metrics: list[tuple[m.EvidenceEvent, str, str]], registry_rules: dict[str, Any]
) -> list[dict[str, Any]]:
    """Clusters and curates raw evidence events to prevent duplicate event spam

    and displays a summary capping at 5 items.
    """
    clusters: dict[tuple[str, str, str, str], list[tuple[m.EvidenceEvent, str, str]]] = {}

    for event, metric_code, metric_unit in events_with_metrics:
        rule_def = registry_rules.get(event.event_code, {})
        direction = rule_def.get("direction", "unknown")
        key = (event.event_code, metric_code, event.event_type, direction)
        clusters.setdefault(key, []).append((event, metric_code, metric_unit))

    curated_items: list[dict[str, Any]] = []
    for key, group in clusters.items():
        # Sort group by date descending
        group.sort(key=lambda x: x[0].as_of_date, reverse=True)
        latest_event, metric_code, metric_unit = group[0]
        count = len(group)

        earliest_event = group[-1][0]
        earliest_date_str = earliest_event.as_of_date.strftime("%b %d")

        # Format numeric values
        latest_val = latest_event.value_numeric
        threshold_val = latest_event.threshold_numeric

        latest_str = format_value(latest_val, metric_unit, show_sign=True)
        threshold_str = format_value(threshold_val, metric_unit, show_sign=True)

        # Contextual label extension for relative performance rules
        if "_vs_spy" in metric_code:
            latest_str += " vs SPY"
            threshold_str += " vs SPY"

        detail_msg = (
            f"Latest {latest_str}. Triggered {count} times since "
            f"{earliest_date_str}. Threshold {threshold_str}."
        )

        curated_items.append(
            {
                "headline": latest_event.headline,
                "detail": detail_msg,
                "latest_date": latest_event.as_of_date,
                "severity": latest_event.severity,
                "event_code": latest_event.event_code,
            }
        )

    # Sort results by the latest date descending and limit to 5
    curated_items.sort(key=lambda x: x["latest_date"], reverse=True)
    return curated_items[:5]
