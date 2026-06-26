from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HeaderViewModel:
    evidence_date: str
    generated_time: str
    data_status: str
    metrics_status: str
    quality_count: int


@dataclass
class MarketBriefViewModel:
    brief_text: str


@dataclass
class KPITile:
    label: str
    value: str
    detail: str
    status: str = "normal"  # normal, warning, critical


@dataclass
class MetricRow:
    metric_code: str
    display_name: str
    value: str
    unit: str
    source: str
    as_of: str
    chart_link: str


@dataclass
class PanelViewModel:
    title: str
    summary: str
    metrics: list[MetricRow] = field(default_factory=list)
    chart_link: str = ""


@dataclass
class QualityGroup:
    name: str
    count: int


@dataclass
class DataConfidenceViewModel:
    status: str  # Current / Attention / Stale
    unresolved_count: int
    blocking_count: int
    unavailable_count: int
    stale_count: int
    impact_statement: str
    quality_groups: list[QualityGroup] = field(default_factory=list)


@dataclass
class TechnicalAppendixViewModel:
    enabled_metrics_count: int
    enabled_rules_count: int
    metric_codes: list[str]
    formula_versions: dict[str, str]
    source_summaries: list[dict[str, Any]]
    latest_runs: dict[str, Any]
    db_type: str
    readonly_note: str
    yahoo_note: str


@dataclass
class DashboardViewModel:
    header: HeaderViewModel
    market_brief: MarketBriefViewModel
    key_market_strip: list[KPITile]
    what_changed: list[dict[str, Any]]
    market_map: list[PanelViewModel]
    data_confidence: DataConfidenceViewModel
    technical_appendix: TechnicalAppendixViewModel
