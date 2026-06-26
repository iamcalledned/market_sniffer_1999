from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_sniffer.db import models as m
from market_sniffer.db.repository import utc_now
from market_sniffer.services.metric_registry import MetricRegistry, load_metric_registry


@dataclass(frozen=True)
class MetricResult:
    value: Decimal | None
    quality_status: str
    quality_details: dict[str, Any]
    lineage: dict[str, Any]
    input_window_start: date | None
    input_window_end: date | None
    effective_source_date: date | None


class MetricCalculationService:
    def __init__(self, session: Session, registry: MetricRegistry | None = None):
        self.session = session
        self.registry = registry or load_metric_registry()

    def bootstrap_definitions(self) -> None:
        now = utc_now()
        for code, item in self.registry.metrics.items():
            definition = self.session.scalar(select(m.MetricDefinition).where(m.MetricDefinition.metric_code == code))
            if definition is None:
                definition = m.MetricDefinition(metric_code=code, created_at_utc=now)
                self.session.add(definition)
            definition.display_name = item["display_name"]
            definition.category = item["category"]
            definition.formula_version = item["formula_version"]
            definition.frequency = item["frequency"]
            definition.unit = item["unit"]
            definition.definition_json = item
            definition.enabled = bool(item.get("enabled", True))
            definition.updated_at_utc = now
        self.session.commit()

    def list_metrics(self) -> list[dict[str, Any]]:
        self.bootstrap_definitions()
        rows = self.session.scalars(select(m.MetricDefinition).order_by(m.MetricDefinition.metric_code)).all()
        return [
            {
                "metric_code": row.metric_code,
                "display_name": row.display_name,
                "category": row.category,
                "formula": row.definition_json.get("formula"),
                "formula_version": row.formula_version,
                "enabled": row.enabled,
            }
            for row in rows
        ]

    def calculate_date(self, as_of: date, profile: str = "core", run: m.MetricCalculationRun | None = None) -> dict[str, int]:
        self.bootstrap_definitions()
        own_run = run is None
        if run is None:
            run = self._start_run(profile, as_of, as_of)
        attempted = succeeded = skipped = failed = 0
        for code, item in self.registry.enabled_metrics.items():
            attempted += 1
            try:
                result = self._calculate_metric(code, item, as_of)
                observation = self._upsert_observation(code, item, result, as_of, run)
                self._evaluate_rules(code, observation)
                if result.quality_status == "ok":
                    succeeded += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                run.details_json = {**(run.details_json or {}), code: {"error": exc.__class__.__name__, "message": str(exc)}}
        run.metrics_attempted += attempted
        run.metrics_succeeded += succeeded
        run.metrics_skipped += skipped
        run.metrics_failed += failed
        if own_run:
            self._finish_run(run, failed)
        self.session.commit()
        return {"attempted": attempted, "succeeded": succeeded, "skipped": skipped, "failed": failed}

    def backfill(
        self,
        profile: str = "core",
        start: date | None = None,
        end: date | None = None,
        only: list[str] | None = None,
    ) -> dict[str, Any]:
        self.bootstrap_definitions()
        dates = self._market_dates(start, end)
        if not dates:
            return {"dates": 0, "attempted": 0, "succeeded": 0, "skipped": 0, "failed": 0}
        original_metrics = self.registry.metrics
        if only:
            allowed = set(only)
            self.registry = MetricRegistry(
                self.registry.profiles,
                self.registry.baskets,
                {code: item for code, item in self.registry.metrics.items() if code in allowed},
                self.registry.rules,
            )
        run = self._start_run(profile, dates[0], dates[-1])
        summary = {"dates": len(dates), "attempted": 0, "succeeded": 0, "skipped": 0, "failed": 0}
        for as_of in dates:
            result = self.calculate_date(as_of, profile, run)
            for key in ("attempted", "succeeded", "skipped", "failed"):
                summary[key] += result[key]
        self.registry = MetricRegistry(self.registry.profiles, self.registry.baskets, original_metrics, self.registry.rules)
        self._finish_run(run, summary["failed"])
        self.session.commit()
        return summary

    def health(self) -> dict[str, Any]:
        self.bootstrap_definitions()
        latest = self.session.scalar(select(func.max(m.MetricObservation.as_of_date)))
        quality_rows = self.session.execute(
            select(m.MetricObservation.quality_status, func.count()).group_by(m.MetricObservation.quality_status)
        ).all()
        category_rows = self.session.execute(
            select(m.MetricDefinition.category, func.count(m.MetricObservation.id))
            .join(m.MetricObservation, m.MetricObservation.metric_definition_id == m.MetricDefinition.id)
            .group_by(m.MetricDefinition.category)
        ).all()
        return {
            "enabled_metric_count": len(self.registry.enabled_metrics),
            "enabled_evidence_rule_count": len(self.registry.enabled_rules),
            "latest_as_of_date": latest,
            "observation_count": self.session.scalar(select(func.count(m.MetricObservation.id))),
            "evidence_event_count": self.session.scalar(select(func.count(m.EvidenceEvent.id))),
            "quality_status_counts": {status: count for status, count in quality_rows},
            "observation_counts_by_category": {category: count for category, count in category_rows},
        }

    def _start_run(self, profile: str, start: date | None, end: date | None) -> m.MetricCalculationRun:
        run = m.MetricCalculationRun(
            profile=profile,
            as_of_start=start,
            as_of_end=end,
            status="running",
            started_at_utc=utc_now(),
            metrics_attempted=0,
            metrics_succeeded=0,
            metrics_skipped=0,
            metrics_failed=0,
            details_json={},
        )
        self.session.add(run)
        self.session.flush()
        return run

    def _finish_run(self, run: m.MetricCalculationRun, failed: int) -> None:
        run.status = "failed" if failed else "succeeded"
        run.finished_at_utc = utc_now()

    def _definition(self, code: str) -> m.MetricDefinition:
        definition = self.session.scalar(select(m.MetricDefinition).where(m.MetricDefinition.metric_code == code))
        if definition is None:
            raise KeyError(f"metric definition not bootstrapped: {code}")
        return definition

    def _instrument_id(self, symbol: str) -> int:
        inst = self.session.scalar(select(m.Instrument).where(m.Instrument.symbol == symbol))
        if inst is None:
            raise KeyError(f"instrument not bootstrapped: {symbol}")
        return inst.id

    def _series_id(self, series_code: str) -> int:
        series = self.session.scalar(select(m.DataSeries).where(m.DataSeries.series_code == series_code))
        if series is None:
            raise KeyError(f"series not bootstrapped: {series_code}")
        return series.id

    def _bars(self, symbol: str, as_of: date, limit: int) -> list[m.CanonicalMarketBarDaily]:
        inst_id = self._instrument_id(symbol)
        rows = self.session.scalars(
            select(m.CanonicalMarketBarDaily)
            .where(
                m.CanonicalMarketBarDaily.instrument_id == inst_id,
                m.CanonicalMarketBarDaily.trade_date <= as_of,
                m.CanonicalMarketBarDaily.price_basis == "split_adjusted",
                m.CanonicalMarketBarDaily.is_final.is_(True),
            )
            .order_by(m.CanonicalMarketBarDaily.trade_date.desc())
            .limit(limit)
        ).all()
        return list(reversed(rows))

    def _fred_obs(self, series_code: str, as_of: date, limit: int) -> list[m.CanonicalObservation]:
        series_id = self._series_id(series_code)
        rows = self.session.scalars(
            select(m.CanonicalObservation)
            .where(
                m.CanonicalObservation.series_id == series_id,
                m.CanonicalObservation.observation_date <= as_of,
                m.CanonicalObservation.is_latest_vintage.is_(True),
            )
            .order_by(m.CanonicalObservation.observation_date.desc())
            .limit(limit)
        ).all()
        return list(reversed(rows))

    def _calculate_metric(self, code: str, item: dict[str, Any], as_of: date) -> MetricResult:
        formula = item["formula"]
        inputs = item["inputs"]
        lookback = int(item.get("lookback", 0))
        if formula == "close":
            return self._close(inputs["symbols"][0], as_of)
        if formula == "return":
            return self._return(inputs["symbols"][0], as_of, lookback)
        if formula == "moving_average":
            return self._moving_average(inputs["symbols"][0], as_of, lookback)
        if formula == "distance_to_ma":
            return self._distance_to_ma(inputs["symbols"][0], as_of, lookback)
        if formula == "realized_vol":
            return self._realized_vol(inputs["symbols"][0], as_of, lookback)
        if formula == "breadth_above_ma_pct":
            return self._breadth_above_ma_pct(inputs["basket"], as_of, lookback)
        if formula == "relative_return":
            return self._relative_return(inputs["symbol"], inputs["benchmark"], as_of, lookback)
        if formula == "basket_relative_return":
            return self._basket_relative_return(inputs["basket"], inputs["benchmark"], as_of, lookback)
        if formula == "fred_level":
            return self._fred_level(inputs["series"], as_of)
        if formula == "fred_change":
            return self._fred_change(inputs["series"], as_of, lookback)
        if formula == "fred_spread":
            return self._fred_spread(inputs["long_series"], inputs["short_series"], as_of)
        raise ValueError(f"unsupported metric formula {formula} for {code}")

    def _insufficient(self, reason: str, inputs: dict[str, Any]) -> MetricResult:
        return MetricResult(None, "insufficient_history", {"reason": reason}, {"inputs": inputs}, None, None, None)

    def _close(self, symbol: str, as_of: date) -> MetricResult:
        bars = self._bars(symbol, as_of, 1)
        if not bars:
            return self._insufficient("missing_canonical_bar", {"symbols": [symbol]})
        bar = bars[-1]
        return MetricResult(bar.close, "ok", {}, self._bar_lineage([bar], [symbol]), bar.trade_date, bar.trade_date, bar.trade_date)

    def _return(self, symbol: str, as_of: date, lookback: int) -> MetricResult:
        bars = self._bars(symbol, as_of, lookback + 1)
        if len(bars) < lookback + 1:
            return self._insufficient("not_enough_bars", {"symbols": [symbol], "lookback": lookback})
        value = (bars[-1].close / bars[0].close) - Decimal("1")
        return MetricResult(value, "ok", {}, self._bar_lineage([bars[0], bars[-1]], [symbol]), bars[0].trade_date, bars[-1].trade_date, bars[-1].trade_date)

    def _moving_average(self, symbol: str, as_of: date, lookback: int) -> MetricResult:
        bars = self._bars(symbol, as_of, lookback)
        if len(bars) < lookback:
            return self._insufficient("not_enough_bars", {"symbols": [symbol], "lookback": lookback})
        value = sum((bar.close for bar in bars), Decimal("0")) / Decimal(len(bars))
        return MetricResult(value, "ok", {}, self._bar_lineage(bars, [symbol]), bars[0].trade_date, bars[-1].trade_date, bars[-1].trade_date)

    def _distance_to_ma(self, symbol: str, as_of: date, lookback: int) -> MetricResult:
        bars = self._bars(symbol, as_of, lookback)
        if len(bars) < lookback:
            return self._insufficient("not_enough_bars", {"symbols": [symbol], "lookback": lookback})
        ma = sum((bar.close for bar in bars), Decimal("0")) / Decimal(len(bars))
        value = (bars[-1].close / ma) - Decimal("1")
        lineage = self._bar_lineage(bars, [symbol])
        lineage["moving_average"] = str(ma)
        return MetricResult(value, "ok", {}, lineage, bars[0].trade_date, bars[-1].trade_date, bars[-1].trade_date)

    def _realized_vol(self, symbol: str, as_of: date, lookback: int) -> MetricResult:
        bars = self._bars(symbol, as_of, lookback + 1)
        if len(bars) < lookback + 1:
            return self._insufficient("not_enough_bars", {"symbols": [symbol], "lookback": lookback})
        returns = [math.log(float(bars[i].close / bars[i - 1].close)) for i in range(1, len(bars))]
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / max(len(returns) - 1, 1)
        value = Decimal(str(math.sqrt(variance) * math.sqrt(252)))
        return MetricResult(value, "ok", {}, self._bar_lineage(bars, [symbol]), bars[0].trade_date, bars[-1].trade_date, bars[-1].trade_date)

    def _breadth_above_ma_pct(self, basket_code: str, as_of: date, lookback: int) -> MetricResult:
        basket = self.registry.baskets[basket_code]
        valid = above = 0
        bars_used: list[m.CanonicalMarketBarDaily] = []
        for symbol in basket["symbols"]:
            bars = self._bars(symbol, as_of, lookback)
            if len(bars) < lookback:
                continue
            valid += 1
            ma = sum((bar.close for bar in bars), Decimal("0")) / Decimal(len(bars))
            above += 1 if bars[-1].close > ma else 0
            bars_used.extend([bars[0], bars[-1]])
        min_ratio = Decimal(str(basket.get("min_valid_ratio", 0.8)))
        if not basket["symbols"] or Decimal(valid) / Decimal(len(basket["symbols"])) < min_ratio:
            return self._insufficient("not_enough_valid_basket_members", {"basket": basket_code, "valid": valid})
        value = Decimal(above) / Decimal(valid)
        return MetricResult(value, "ok", {"valid_members": valid}, self._bar_lineage(bars_used, basket["symbols"]), None, as_of, as_of)

    def _relative_return(self, symbol: str, benchmark: str, as_of: date, lookback: int) -> MetricResult:
        primary = self._return(symbol, as_of, lookback)
        bench = self._return(benchmark, as_of, lookback)
        if primary.value is None or bench.value is None:
            return self._insufficient("missing_relative_return_inputs", {"symbol": symbol, "benchmark": benchmark, "lookback": lookback})
        lineage = {"primary": primary.lineage, "benchmark": bench.lineage}
        return MetricResult(primary.value - bench.value, "ok", {}, lineage, primary.input_window_start, primary.input_window_end, primary.effective_source_date)

    def _basket_relative_return(self, basket_code: str, benchmark: str, as_of: date, lookback: int) -> MetricResult:
        basket = self.registry.baskets[basket_code]
        returns: list[Decimal] = []
        lineages: list[dict[str, Any]] = []
        for symbol in basket["symbols"]:
            result = self._return(symbol, as_of, lookback)
            if result.value is not None:
                returns.append(result.value)
                lineages.append(result.lineage)
        if len(returns) < int(basket.get("min_valid_count", 1)):
            return self._insufficient("not_enough_valid_basket_members", {"basket": basket_code, "valid": len(returns)})
        bench = self._return(benchmark, as_of, lookback)
        if bench.value is None:
            return self._insufficient("missing_benchmark", {"benchmark": benchmark})
        basket_return = sum(returns, Decimal("0")) / Decimal(len(returns))
        return MetricResult(
            basket_return - bench.value,
            "ok",
            {"valid_members": len(returns)},
            {"basket": basket_code, "members": lineages, "benchmark": bench.lineage},
            None,
            as_of,
            as_of,
        )

    def _fred_level(self, series_code: str, as_of: date) -> MetricResult:
        rows = self._fred_obs(series_code, as_of, 1)
        if not rows:
            return self._insufficient("missing_canonical_observation", {"series": series_code})
        obs = rows[-1]
        return MetricResult(obs.value, "ok", {}, self._fred_lineage([obs], [series_code]), obs.observation_date, obs.observation_date, obs.observation_date)

    def _fred_change(self, series_code: str, as_of: date, lookback: int) -> MetricResult:
        rows = self._fred_obs(series_code, as_of, lookback + 1)
        if len(rows) < lookback + 1:
            return self._insufficient("not_enough_observations", {"series": series_code, "lookback": lookback})
        return MetricResult(rows[-1].value - rows[0].value, "ok", {}, self._fred_lineage([rows[0], rows[-1]], [series_code]), rows[0].observation_date, rows[-1].observation_date, rows[-1].observation_date)

    def _fred_spread(self, long_series: str, short_series: str, as_of: date) -> MetricResult:
        long = self._fred_level(long_series, as_of)
        short = self._fred_level(short_series, as_of)
        if long.value is None or short.value is None:
            return self._insufficient("missing_spread_input", {"long_series": long_series, "short_series": short_series})
        if (
            long.input_window_start is None
            or short.input_window_start is None
            or long.input_window_end is None
            or short.input_window_end is None
            or long.effective_source_date is None
            or short.effective_source_date is None
        ):
            return self._insufficient("missing_spread_lineage_dates", {"long_series": long_series, "short_series": short_series})
        return MetricResult(
            long.value - short.value,
            "ok",
            {},
            {"long": long.lineage, "short": short.lineage},
            min(long.input_window_start, short.input_window_start),
            max(long.input_window_end, short.input_window_end),
            min(long.effective_source_date, short.effective_source_date),
        )

    def _bar_lineage(self, bars: list[m.CanonicalMarketBarDaily], symbols: list[str]) -> dict[str, Any]:
        return {
            "source_type": "canonical_market_bars_daily",
            "symbols": sorted(set(symbols)),
            "canonical_bar_ids": [bar.id for bar in bars],
            "source_market_bar_ids": [bar.source_market_bar_id for bar in bars],
            "raw_payload_ids": sorted({bar.raw_payload_id for bar in bars}),
            "canonical_source_ids": sorted({bar.canonical_source_id for bar in bars}),
            "date_range": [bars[0].trade_date.isoformat(), bars[-1].trade_date.isoformat()] if bars else None,
        }

    def _fred_lineage(self, rows: list[m.CanonicalObservation], series: list[str]) -> dict[str, Any]:
        return {
            "source_type": "canonical_observations",
            "series": sorted(set(series)),
            "canonical_observation_ids": [row.id for row in rows],
            "raw_observation_ids": [row.raw_observation_id for row in rows],
            "raw_payload_ids": sorted({row.raw_payload_id for row in rows}),
            "source_ids": sorted({row.source_id for row in rows}),
            "date_range": [rows[0].observation_date.isoformat(), rows[-1].observation_date.isoformat()] if rows else None,
        }

    def _upsert_observation(
        self,
        code: str,
        item: dict[str, Any],
        result: MetricResult,
        as_of: date,
        run: m.MetricCalculationRun,
    ) -> m.MetricObservation:
        definition = self._definition(code)
        now = utc_now()
        existing = self.session.scalar(
            select(m.MetricObservation).where(
                m.MetricObservation.metric_definition_id == definition.id,
                m.MetricObservation.as_of_date == as_of,
                m.MetricObservation.formula_version == item["formula_version"],
            )
        )
        if existing is None:
            existing = m.MetricObservation(
                metric_definition_id=definition.id,
                as_of_date=as_of,
                formula_version=item["formula_version"],
                created_at_utc=now,
            )
            self.session.add(existing)
        existing.calculation_run_id = run.id
        existing.value_numeric = result.value
        existing.value_text = None if result.value is None else str(result.value)
        existing.unit = item["unit"]
        existing.quality_status = result.quality_status
        existing.quality_details_json = result.quality_details
        existing.source_lineage_json = {**result.lineage, "formula_version": item["formula_version"], "metric_code": code}
        existing.input_window_start = result.input_window_start
        existing.input_window_end = result.input_window_end
        existing.effective_source_date = result.effective_source_date
        existing.updated_at_utc = now
        self.session.flush()
        return existing

    def _evaluate_rules(self, metric_code: str, observation: m.MetricObservation) -> None:
        if observation.value_numeric is None or observation.quality_status != "ok":
            return
        definition = self._definition(metric_code)
        for event_code, rule in self.registry.enabled_rules.items():
            if rule["metric_code"] != metric_code:
                continue
            threshold = Decimal(str(rule["threshold"]))
            prior = self._prior_observation(definition.id, observation.as_of_date, observation.formula_version)
            should_emit = self._rule_matches(rule, observation.value_numeric, prior.value_numeric if prior else None, threshold)
            if should_emit:
                self._upsert_event(event_code, rule, definition, observation, prior, threshold)

    def _prior_observation(self, metric_definition_id: int, as_of: date, formula_version: str) -> m.MetricObservation | None:
        return self.session.scalar(
            select(m.MetricObservation)
            .where(
                m.MetricObservation.metric_definition_id == metric_definition_id,
                m.MetricObservation.as_of_date < as_of,
                m.MetricObservation.formula_version == formula_version,
                m.MetricObservation.value_numeric.is_not(None),
                m.MetricObservation.quality_status == "ok",
            )
            .order_by(m.MetricObservation.as_of_date.desc())
            .limit(1)
        )

    def _rule_matches(
        self,
        rule: dict[str, Any],
        value: Decimal,
        prior: Decimal | None,
        threshold: Decimal,
    ) -> bool:
        direction = rule["direction"]
        if rule["event_type"] == "material_change":
            return abs(value) >= threshold if direction == "abs_above" else value >= threshold
        if rule["event_type"] == "threshold_cross":
            if direction == "abs_above":
                return abs(value) >= threshold and (prior is None or abs(prior) < threshold)
            if prior is None:
                return False
            if direction == "above":
                return prior <= threshold < value
            if direction == "below":
                return prior >= threshold > value
            if direction == "both":
                return (prior <= threshold < value) or (prior >= threshold > value)
        return False

    def _upsert_event(
        self,
        event_code: str,
        rule: dict[str, Any],
        definition: m.MetricDefinition,
        observation: m.MetricObservation,
        prior: m.MetricObservation | None,
        threshold: Decimal,
    ) -> None:
        now = utc_now()
        event = self.session.scalar(
            select(m.EvidenceEvent).where(
                m.EvidenceEvent.event_code == event_code,
                m.EvidenceEvent.metric_definition_id == definition.id,
                m.EvidenceEvent.as_of_date == observation.as_of_date,
                m.EvidenceEvent.rule_version == rule["rule_version"],
            )
        )
        if event is None:
            event = m.EvidenceEvent(
                event_code=event_code,
                metric_definition_id=definition.id,
                as_of_date=observation.as_of_date,
                rule_version=rule["rule_version"],
                created_at_utc=now,
            )
            self.session.add(event)
        value = observation.value_numeric
        prior_value = prior.value_numeric if prior else None
        event.event_type = rule["event_type"]
        event.severity = rule["severity"]
        event.metric_observation_id = observation.id
        event.headline = rule["headline"]
        event.detail = rule.get("detail_template", "{value}").format(value=value, prior_value=prior_value)
        event.value_numeric = value
        event.prior_value_numeric = prior_value
        event.threshold_numeric = threshold
        event.evidence_json = {
            "metric_code": definition.metric_code,
            "metric_observation_id": observation.id,
            "prior_metric_observation_id": prior.id if prior else None,
            "source_lineage": observation.source_lineage_json,
            "rule": {k: v for k, v in rule.items() if k != "detail_template"},
        }
        event.updated_at_utc = now
        self.session.flush()

    def _market_dates(self, start: date | None, end: date | None) -> list[date]:
        spy_id = self._instrument_id("SPY")
        stmt = (
            select(m.CanonicalMarketBarDaily.trade_date)
            .where(
                m.CanonicalMarketBarDaily.instrument_id == spy_id,
                m.CanonicalMarketBarDaily.price_basis == "split_adjusted",
                m.CanonicalMarketBarDaily.is_final.is_(True),
            )
            .order_by(m.CanonicalMarketBarDaily.trade_date)
        )
        if start:
            stmt = stmt.where(m.CanonicalMarketBarDaily.trade_date >= start)
        if end:
            stmt = stmt.where(m.CanonicalMarketBarDaily.trade_date <= end)
        return list(self.session.scalars(stmt).all())
