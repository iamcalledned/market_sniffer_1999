from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_sniffer.db import models as m
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.dashboard.evidence_curation import curate_evidence
from market_sniffer.services.dashboard.formatters import format_value
from market_sniffer.services.dashboard.view_models import (
    DashboardViewModel,
    DataConfidenceViewModel,
    HeaderViewModel,
    KPITile,
    MarketBriefViewModel,
    MetricRow,
    PanelViewModel,
    QualityGroup,
    TechnicalAppendixViewModel,
)
from market_sniffer.services.metric_registry import load_metric_registry
from market_sniffer.web.app import (
    CanonicalDataMissing,
    EmptyDatabase,
    MetricsNotCalculated,
)


class DashboardService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = WarehouseRepository(session)

    def validate_database_state(self) -> None:
        """Validates that the database has been initialized, backfilled, and metrics calculated."""
        counts = self.repo.counts()

        if counts.get("sources", 0) == 0 or counts.get("instruments", 0) == 0:
            raise EmptyDatabase(
                "No data sources or instruments bootstrapped. Please run db initialization."
            )

        if (
            counts.get("daily_bars", 0) == 0
            and counts.get("canonical_observations", 0) == 0
        ):
            raise CanonicalDataMissing(
                "No daily bar or observation data found in the database. Please run historical backfill."
            )

        latest_run = self.session.scalar(
            select(m.MetricCalculationRun)
            .order_by(m.MetricCalculationRun.started_at_utc.desc())
            .limit(1)
        )
        if not latest_run:
            raise MetricsNotCalculated(
                "No metric calculation run found. Please calculate derived metrics."
            )

    def get_source_label(self, metric_code: str) -> str:
        """Determines the data source label for a given metric code."""
        if metric_code.startswith(("rates.", "credit.", "volatility.", "macro.")):
            return "FRED"
        return "Massive"

    def build_dashboard_view_model(self) -> DashboardViewModel:
        """Assembles the complete DashboardViewModel by querying the database."""
        # 1. Validate state first
        self.validate_database_state()

        registry = load_metric_registry()

        # 2. Query all observations for enabled metrics
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
        all_rows = self.session.execute(stmt).all()

        # Group and select only the latest observation for each metric code
        latest_obs: dict[str, tuple[m.MetricObservation, str, str, str]] = {}
        for obs, code, unit, display_name, category in all_rows:
            if code not in latest_obs:
                latest_obs[code] = (obs, unit, display_name, category)

        # 3. Determine overall evidence and generation timestamps
        latest_evidence = self.session.scalar(
            select(m.EvidenceEvent).order_by(m.EvidenceEvent.as_of_date.desc()).limit(1)
        )
        evidence_date_str = (
            latest_evidence.as_of_date.strftime("%b %d, %Y")
            if latest_evidence
            else "No calculated evidence"
        )
        generated_time_str = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")

        # 4. Unresolved Data Quality Events
        unresolved_events = self.session.scalars(
            select(m.DataQualityEvent).where(m.DataQualityEvent.resolved.is_(False))
        ).all()
        quality_count = len(unresolved_events)

        # Determine collection & calculation run statuses
        latest_collect_run = self.session.scalar(
            select(m.CollectorRun).order_by(m.CollectorRun.started_at_utc.desc()).limit(1)
        )
        latest_calc_run = self.session.scalar(
            select(m.MetricCalculationRun)
            .order_by(m.MetricCalculationRun.started_at_utc.desc())
            .limit(1)
        )

        data_status = (
            latest_collect_run.status.capitalize() if latest_collect_run else "Unknown"
        )
        metrics_status = (
            latest_calc_run.status.capitalize() if latest_calc_run else "Unknown"
        )

        header = HeaderViewModel(
            evidence_date=evidence_date_str,
            generated_time=generated_time_str,
            data_status=data_status,
            metrics_status=metrics_status,
            quality_count=quality_count,
        )

        # 5. Extract values for Market Brief
        def _get_val(k: str) -> Decimal | None:
            return latest_obs[k][0].value_numeric if k in latest_obs else None

        spy_dist_val = _get_val("market.spy_distance_200d")
        spy_ret_val = _get_val("market.spy_return_21d")
        breadth_50d = _get_val("breadth.tracked_above_50d_pct")
        breadth_200d = _get_val("breadth.tracked_above_200d_pct")
        vix_level = _get_val("volatility.vix_level")
        vix_change = _get_val("volatility.vix_change_5d")
        hy_oas = _get_val("credit.hy_oas")
        hy_oas_change = _get_val("credit.hy_oas_change_21d")

        # Calculate evidence in last 7 days
        days_7_ago = timedelta_days(7)
        evidence_count_7d = len(
            self.session.scalars(
                select(m.EvidenceEvent).where(m.EvidenceEvent.as_of_date >= days_7_ago)
            ).all()
        )

        # Construct deterministic plain text brief (No recommendations, no AI words)
        # SPY Trend Distance Description
        if spy_dist_val is not None:
            spy_dist_pct = float(spy_dist_val) * 100.0
            spy_dist_rel = "above" if spy_dist_pct >= 0 else "below"
            spy_dist_str = f"SPY remains {abs(spy_dist_pct):.2f}% {spy_dist_rel} its 200-day average"
        else:
            spy_dist_str = "SPY 200-day trend relation is unknown"

        # SPY 21d Return Description
        if spy_ret_val is not None:
            spy_ret_pct = float(spy_ret_val) * 100.0
            spy_ret_str = f"its 21-day return is {spy_ret_pct:.2f}%"
        else:
            spy_ret_str = "its 21-day return is unavailable"

        # Breadth Description
        if breadth_50d is not None and breadth_200d is not None:
            b50 = float(breadth_50d) * 100.0
            b200 = float(breadth_200d) * 100.0
            if b50 > 70.0 and b200 > 70.0:
                desc = "broad"
            elif b50 < 30.0 and b200 < 30.0:
                desc = "narrow"
            else:
                desc = "mixed"
            breadth_str = f"Breadth is {desc}: {b50:.2f}% above 50d and {b200:.2f}% above 200d"
        else:
            breadth_str = "Breadth indicators are unavailable"

        # VIX Description
        if vix_level is not None:
            vix_f = float(vix_level)
            if vix_change is not None:
                vix_c_f = float(vix_change)
                vix_change_dir = "up" if vix_c_f >= 0 else "down"
                vix_str = f"VIX is {vix_f:.2f}, {vix_change_dir} {abs(vix_c_f):.2f} over five observations"
            else:
                vix_str = f"VIX is {vix_f:.2f}"
        else:
            vix_str = "VIX level is unavailable"

        # Credit Spreads Description
        if hy_oas is not None:
            hy_f = float(hy_oas)
            if hy_oas_change is not None:
                hy_c_f = float(hy_oas_change)
                if abs(hy_c_f) < 0.1:
                    hy_change_str = "changed little from the prior observation"
                else:
                    hy_change_dir = "up" if hy_c_f >= 0 else "down"
                    hy_change_str = f"{hy_change_dir} {abs(hy_c_f):.2f} percentage points from the prior observation"
                hy_str = f"High-yield OAS is {hy_f:.2f} pp and {hy_change_str}"
            else:
                hy_str = f"High-yield OAS is {hy_f:.2f} pp"
        else:
            hy_str = "High-yield OAS is unavailable"

        # Significant Evidence Events
        if evidence_count_7d == 0:
            ev_str = "No significant evidence triggered in the last 7 days."
        else:
            ev_str = (
                f"There were {evidence_count_7d} evidence events triggered in the last 7 days."
            )

        brief_text = (
            f"{spy_dist_str}, but {spy_ret_str}. {breadth_str}. {vix_str}. {hy_str}. {ev_str}"
        )
        market_brief = MarketBriefViewModel(brief_text=brief_text)

        # 6. Key Market Strip
        # Tile 1: SPY Close
        spy_close = _get_val("market.spy_close")
        tile1 = KPITile(
            label="SPY",
            value=f"{float(spy_close):.2f}" if spy_close else "N/A",
            detail=f"21d: {format_value(spy_ret_val, 'ratio', show_sign=True)}",
        )

        # Tile 2: Trend
        spy_dist_200d = _get_val("market.spy_distance_200d")
        spy_ret_63d = _get_val("market.spy_return_63d")
        tile2 = KPITile(
            label="Trend",
            value=format_value(spy_dist_200d, "ratio", show_sign=True),
            detail=f"63d: {format_value(spy_ret_63d, 'ratio', show_sign=True)}",
        )

        # Tile 3: Breadth
        tile3 = KPITile(
            label="Breadth",
            value=f"50d: {format_value(breadth_50d, 'ratio')}",
            detail=f"200d: {format_value(breadth_200d, 'ratio')}",
        )

        # Tile 4: Volatility
        tile4 = KPITile(
            label="Volatility",
            value=f"{float(vix_level):.2f}" if vix_level else "N/A",
            detail=f"5-obs: {format_value(vix_change, 'index_point', show_sign=True)}",
            status="warning" if (vix_level and vix_level > 25) else "normal",
        )

        # Tile 5: Credit
        tile5 = KPITile(
            label="Credit",
            value=f"{float(hy_oas):.2f}%" if hy_oas else "N/A",
            detail=f"21-obs: {format_value(hy_oas_change, 'percent_point', show_sign=True)}",
            status="warning" if (hy_oas and hy_oas > 5.0) else "normal",
        )

        # Tile 6: Rates (2s10s & 3m10y)
        ust_2s10s = _get_val("rates.ust_2s10s_spread")
        ust_3m10y = _get_val("rates.ust_3m10y_spread")
        tile6 = KPITile(
            label="Rates",
            value=f"2s10s: {format_value(ust_2s10s, 'percent')}",
            detail=f"3m10y: {format_value(ust_3m10y, 'percent')}",
            status="warning" if (ust_2s10s and ust_2s10s < 0) else "normal",
        )

        # Tile 7: Leadership
        leaders = {
            "XLK": _get_val("leadership.xlk_vs_spy_21d"),
            "XLF": _get_val("leadership.xlf_vs_spy_21d"),
            "XLE": _get_val("leadership.xle_vs_spy_21d"),
            "AI Infra": _get_val("leadership.ai_infra_vs_spy_21d"),
        }
        valid_leaders = {k: v for k, v in leaders.items() if v is not None}
        if valid_leaders:
            top_leader = max(valid_leaders, key=lambda k: valid_leaders[k])
            top_val = valid_leaders[top_leader]
            tile7 = KPITile(
                label="Leadership",
                value=f"{top_leader}",
                detail=f"{format_value(top_val, 'ratio', show_sign=True)} vs SPY",
            )
        else:
            tile7 = KPITile(label="Leadership", value="N/A", detail="vs SPY (21d)")

        # Tile 8: Evidence
        tile8 = KPITile(
            label="Evidence",
            value=f"{evidence_count_7d} Events" if evidence_count_7d > 0 else "No Events",
            detail="Last 7 days",
            status="warning" if evidence_count_7d > 0 else "normal",
        )

        key_market_strip = [tile1, tile2, tile3, tile4, tile5, tile6, tile7, tile8]

        # 7. What Changed: Curate evidence events from the last 14 days
        days_14_ago = timedelta_days(14)
        evidence_stmt = (
            select(m.EvidenceEvent, m.MetricDefinition.metric_code, m.MetricDefinition.unit)
            .join(
                m.MetricDefinition,
                m.EvidenceEvent.metric_definition_id == m.MetricDefinition.id,
            )
            .where(m.EvidenceEvent.as_of_date >= days_14_ago)
            .order_by(m.EvidenceEvent.as_of_date.desc())
        )
        recent_evs_rows = [(r[0], r[1], r[2]) for r in self.session.execute(evidence_stmt).all()]
        # curate_evidence takes list of tuples (EvidenceEvent, metric_code, metric_unit)
        what_changed = curate_evidence(recent_evs_rows, registry.rules)

        # 8. Market Map (2x2 Panel Grid)
        def _build_row(k: str) -> MetricRow:
            if k not in latest_obs:
                return MetricRow(
                    metric_code=k,
                    display_name=k.split(".")[-1].replace("_", " ").title(),
                    value="N/A",
                    unit="unknown",
                    source="Unknown",
                    as_of="N/A",
                    chart_link=f"/charts/{k}",
                )
            obs, unit, disp_name, _cat = latest_obs[k]
            return MetricRow(
                metric_code=k,
                display_name=disp_name,
                value=format_value(obs.value_numeric, unit),
                unit=unit,
                source=self.get_source_label(k),
                as_of=obs.as_of_date.strftime("%Y-%m-%d"),
                chart_link=f"/charts/{k}",
            )

        # Panel 1: Trend & Structure
        trend_above = "above" if (spy_dist_200d and spy_dist_200d >= 0) else "below"
        panel1 = PanelViewModel(
            title="Trend & Structure",
            summary=f"SPY is currently {trend_above} its 200-day moving average.",
            metrics=[
                _build_row("market.spy_close"),
                _build_row("market.spy_return_5d"),
                _build_row("market.spy_return_21d"),
                _build_row("market.spy_return_63d"),
                _build_row("market.spy_distance_200d"),
            ],
            chart_link="/charts/market.spy_distance_200d",
        )

        # Panel 2: Breadth & Leadership
        lead_name = top_leader if valid_leaders else "N/A"
        panel2 = PanelViewModel(
            title="Breadth & Leadership",
            summary=f"Market breadth is {desc} with {lead_name} leading over the last 21 days.",
            metrics=[
                _build_row("breadth.tracked_above_50d_pct"),
                _build_row("breadth.tracked_above_200d_pct"),
                _build_row("leadership.xlk_vs_spy_21d"),
                _build_row("leadership.ai_infra_vs_spy_21d"),
                _build_row("leadership.xlf_vs_spy_21d"),
                _build_row("leadership.xle_vs_spy_21d"),
            ],
            chart_link="/charts/breadth.tracked_above_50d_pct",
        )

        # Panel 3: Rates & Credit
        curve_state = "inverted" if (ust_2s10s and ust_2s10s < 0) else "positive"
        credit_val = float(hy_oas_change) if hy_oas_change else 0.0
        credit_state = (
            "widened"
            if credit_val >= 0.1
            else ("narrowed" if credit_val <= -0.1 else "changed little")
        )
        panel3 = PanelViewModel(
            title="Rates & Credit",
            summary=f"The yield curve is {curve_state} while credit spreads have {credit_state} recently.",
            metrics=[
                _build_row("rates.ust_2s10s_spread"),
                _build_row("rates.ust_3m10y_spread"),
                _build_row("credit.hy_oas"),
                _build_row("credit.hy_oas_change_21d"),
            ],
            chart_link="/charts/rates.ust_2s10s_spread",
        )

        # Panel 4: Volatility & Cross-Asset
        vix_val = float(vix_level) if vix_level else 15.0
        vix_state = (
            "elevated"
            if vix_val >= 20.0
            else ("subdued" if vix_val <= 14.0 else "moderate")
        )
        nfci_level = _get_val("macro.nfci_level")
        nfci_val = float(nfci_level) if nfci_level else -0.5
        nfci_state = "tight" if nfci_val >= 0.0 else "loose"
        panel4 = PanelViewModel(
            title="Volatility & Cross-Asset",
            summary=f"Volatility remains {vix_state} and financial conditions are {nfci_state}.",
            metrics=[
                _build_row("volatility.vix_level"),
                _build_row("volatility.vix_change_5d"),
                _build_row("cross_asset.gold_vs_spy_21d"),
                _build_row("macro.nfci_level"),
                _build_row("macro.nfci_change_21d"),
            ],
            chart_link="/charts/volatility.vix_level",
        )

        market_map = [panel1, panel2, panel3, panel4]

        # 9. Data Confidence
        blocking_count = 0
        unavailable_count = 0
        stale_count = 0

        # Loop through all enabled metrics to check for anomalies
        for code, item in registry.enabled_metrics.items():
            if code not in latest_obs:
                unavailable_count += 1
            else:
                obs, _unit, _disp, _cat = latest_obs[code]
                if obs.quality_status in ("error", "blocking"):
                    blocking_count += 1
                elif obs.quality_status == "stale":
                    stale_count += 1
                elif obs.quality_status == "unavailable":
                    unavailable_count += 1

        # Determine confidence status
        if blocking_count > 0 or quality_count > 10:
            confidence_status = "Stale"
        elif stale_count > 0 or unavailable_count > 0 or quality_count > 0:
            confidence_status = "Attention"
        else:
            confidence_status = "Current"

        # Impact statement
        if blocking_count == 0 and unavailable_count == 0 and stale_count == 0:
            impact_statement = "Displayed core metrics are usable."
        else:
            impact_statement = "Some displayed metrics are stale or unavailable."

        # Group unresolved quality events by event_type
        type_counts: dict[str, int] = {}
        for qev in unresolved_events:
            label = qev.event_type.replace("_", " ")
            type_counts[label] = type_counts.get(label, 0) + 1

        quality_groups = [
            QualityGroup(name=name, count=count) for name, count in type_counts.items()
        ]
        # Sort by count desc
        quality_groups.sort(key=lambda x: x.count, reverse=True)

        data_confidence = DataConfidenceViewModel(
            status=confidence_status,
            unresolved_count=quality_count,
            blocking_count=blocking_count,
            unavailable_count=unavailable_count,
            stale_count=stale_count,
            quality_groups=quality_groups,
            impact_statement=impact_statement,
        )

        # 10. Technical Appendix
        enabled_metrics_count = len(registry.enabled_metrics)
        enabled_rules_count = len(registry.enabled_rules)
        metric_codes = sorted(list(registry.enabled_metrics.keys()))

        formula_versions = {
            code: item["formula_version"] for code, item in registry.enabled_metrics.items()
        }

        # Gather brief summaries of data sources
        sources_stmt = select(m.DataSource)
        db_sources = self.session.scalars(sources_stmt).all()
        source_summaries = [
            {
                "code": src.code,
                "name": src.display_name,
                "description": src.notes,
            }
            for src in db_sources
        ]

        latest_runs = {
            "collection": {
                "started_at": (
                    latest_collect_run.started_at_utc.strftime("%Y-%m-%d %H:%M UTC")
                    if latest_collect_run
                    else "None"
                ),
                "status": latest_collect_run.status if latest_collect_run else "N/A",
            },
            "metrics": {
                "started_at": (
                    latest_calc_run.started_at_utc.strftime("%Y-%m-%d %H:%M UTC")
                    if latest_calc_run
                    else "None"
                ),
                "status": latest_calc_run.status if latest_calc_run else "N/A",
            },
        }

        technical_appendix = TechnicalAppendixViewModel(
            enabled_metrics_count=enabled_metrics_count,
            enabled_rules_count=enabled_rules_count,
            metric_codes=metric_codes,
            formula_versions=formula_versions,
            source_summaries=source_summaries,
            latest_runs=latest_runs,
            db_type="SQLite (Local File)",
            readonly_note="GET / renders using local read-only queries; no live provider APIs are requested during dashboard render.",
            yahoo_note="Yahoo quotes are used strictly for manual, explicit user-triggered symbol lookups and are not polled or used as the source of truth for the dashboard.",
        )

        return DashboardViewModel(
            header=header,
            market_brief=market_brief,
            key_market_strip=key_market_strip,
            what_changed=what_changed,
            market_map=market_map,
            data_confidence=data_confidence,
            technical_appendix=technical_appendix,
        )


def timedelta_days(days: int) -> datetime:
    """Helper returning a timezone-aware datetime offset."""
    # To keep date objects compatible, return date directly or timezone-aware
    return datetime.now(timezone.utc).date() - timedelta_days_inner(days)


def timedelta_days_inner(days: int) -> Any:
    from datetime import timedelta

    return timedelta(days=days)
