from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from market_sniffer.settings import PROJECT_ROOT


METRIC_REGISTRY_PATH = PROJECT_ROOT / "config" / "metric_registry.yaml"
EVIDENCE_RULE_REGISTRY_PATH = PROJECT_ROOT / "config" / "evidence_rule_registry.yaml"

METRIC_CATEGORIES = {
    "market_structure",
    "leadership_breadth",
    "rates_credit",
    "volatility_cross_asset",
    "macro_momentum",
}
EVENT_TYPES = {
    "threshold_cross",
    "material_change",
    "new_extreme",
    "trend_state_change",
    "data_quality_warning",
}


class MetricRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class MetricRegistry:
    profiles: dict[str, Any]
    baskets: dict[str, Any]
    metrics: dict[str, dict[str, Any]]
    rules: dict[str, dict[str, Any]]

    @property
    def enabled_metrics(self) -> dict[str, dict[str, Any]]:
        return {code: item for code, item in self.metrics.items() if item.get("enabled", True)}

    @property
    def enabled_rules(self) -> dict[str, dict[str, Any]]:
        return {code: item for code, item in self.rules.items() if item.get("enabled", True)}


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise MetricRegistryError(f"{path} must contain a YAML mapping")
    return data


def load_metric_registry(
    metric_path: Path = METRIC_REGISTRY_PATH,
    evidence_path: Path = EVIDENCE_RULE_REGISTRY_PATH,
) -> MetricRegistry:
    metric_data = _load_yaml(metric_path)
    evidence_data = _load_yaml(evidence_path)
    registry = MetricRegistry(
        profiles=metric_data.get("profiles", {}),
        baskets=metric_data.get("baskets", {}),
        metrics=metric_data.get("metrics", {}),
        rules=evidence_data.get("rules", {}),
    )
    validate_metric_registry(registry)
    return registry


def validate_metric_registry(registry: MetricRegistry) -> None:
    if not registry.metrics:
        raise MetricRegistryError("metric registry has no metrics")
    enabled = registry.enabled_metrics
    if len(enabled) > 25:
        raise MetricRegistryError(f"too many enabled metrics: {len(enabled)} > 25")
    categories = {item.get("category") for item in enabled.values()}
    missing_categories = METRIC_CATEGORIES - categories
    if missing_categories:
        raise MetricRegistryError(f"enabled metrics missing categories: {sorted(missing_categories)}")
    for code, item in registry.metrics.items():
        if not isinstance(item, dict):
            raise MetricRegistryError(f"metric {code} must be a mapping")
        required = ["display_name", "category", "formula", "formula_version", "frequency", "unit", "inputs"]
        missing = [field for field in required if field not in item]
        if missing:
            raise MetricRegistryError(f"metric {code} missing required fields: {missing}")
        if item["category"] not in METRIC_CATEGORIES:
            raise MetricRegistryError(f"metric {code} has invalid category {item['category']}")
        if not str(item["formula_version"]).strip():
            raise MetricRegistryError(f"metric {code} has blank formula_version")
    for code, item in registry.rules.items():
        required = ["metric_code", "event_type", "severity", "rule_version", "threshold", "direction", "headline"]
        missing = [field for field in required if field not in item]
        if missing:
            raise MetricRegistryError(f"evidence rule {code} missing required fields: {missing}")
        metric_code = item["metric_code"]
        if metric_code not in registry.metrics:
            raise MetricRegistryError(f"evidence rule {code} references missing metric {metric_code}")
        if registry.rules[code].get("enabled", True) and not registry.metrics[metric_code].get("enabled", True):
            raise MetricRegistryError(f"evidence rule {code} references disabled metric {metric_code}")
        if item["event_type"] not in EVENT_TYPES:
            raise MetricRegistryError(f"evidence rule {code} has invalid event_type {item['event_type']}")
