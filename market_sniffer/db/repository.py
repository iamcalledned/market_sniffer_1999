from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_sniffer.db import models as m
from market_sniffer.services.registry_service import Registry
from market_sniffer.settings import redact_secrets


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_payload(payload: dict[str, Any] | list[Any] | None) -> str:
    encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class WarehouseRepository:
    def __init__(self, session: Session):
        self.session = session

    def bootstrap_registry(self, registry: Registry) -> None:
        source_ids: dict[str, int] = {}
        for code, item in registry.sources.items():
            source = self.session.scalar(select(m.DataSource).where(m.DataSource.code == code))
            if source is None:
                source = m.DataSource(code=code, display_name=item["display_name"])
                self.session.add(source)
            source.enabled = bool(item.get("enabled", True))
            source.credential_env = item.get("credential_env")
            source.capabilities = {
                "update_expectations": item.get("update_expectations"),
                "known_plan_limits": item.get("known_plan_limits"),
            }
            source.canonical_responsibilities = item.get("canonical_responsibilities", [])
            source.validation_responsibilities = item.get("validation_responsibilities", [])
            source.future_quote_capability = bool(item.get("future_quote_capability", False))
            source.notes = item.get("failure_behavior")
            self.session.flush()
            source_ids[code] = source.id

        for code, item in registry.series.items():
            series = self.session.scalar(select(m.DataSeries).where(m.DataSeries.series_code == code))
            if series is None:
                series = m.DataSeries(series_code=code)
                self.session.add(series)
            series.source_id = source_ids[item["source"]]
            series.source_identifier = item["source_id"]
            series.display_name = item.get("display_name", code)
            series.category = item["category"]
            series.frequency = item["frequency"]
            series.unit = item["unit"]
            series.native_unit = item.get("native_unit", item["unit"])
            series.canonical_source_id = source_ids[item["canonical_source"]]
            series.description = item.get("description")
            series.why_it_matters = item["why"]
            series.active = bool(item.get("active", True))
            series.vintage_tracking = bool(item.get("vintage_tracking", False))
            series.collection_profile = item["collection_profile"]
            self.session.flush()
            self._ensure_source_series_mapping(series.id, series.source_id, series.source_identifier, True)

        for symbol, item in registry.instruments.items():
            inst = self.session.scalar(select(m.Instrument).where(m.Instrument.symbol == symbol))
            if inst is None:
                inst = m.Instrument(symbol=symbol)
                self.session.add(inst)
            inst.name = item.get("name")
            inst.asset_class = item["asset_class"]
            inst.exchange = item.get("exchange")
            inst.currency = item.get("currency", "USD")
            inst.active = bool(item.get("active", True))
            inst.groups = item.get("groups", [])
            inst.collection_profiles = item.get("collection_profiles", [])
            inst.daily_collection_eligible = bool(item.get("daily", True))
            inst.future_intraday_eligible = bool(item.get("future_intraday", False))
            inst.future_quote_eligible = bool(item.get("future_quote", False))
            inst.why_tracked = item["why"]
        for name, item in registry.profiles.items():
            source_code = item.get("source") or ("massive" if name == "core" else None)
            source_id = source_ids.get(source_code) if source_code else None
            if source_id is None and source_ids:
                source_id = next(iter(source_ids.values()))
            if source_id is not None:
                definition = self.session.scalar(
                    select(m.CollectorDefinition).where(m.CollectorDefinition.name == name)
                )
                if definition is None:
                    definition = m.CollectorDefinition(name=name, source_id=source_id, profile=name)
                    self.session.add(definition)
                definition.enabled = bool(item.get("enabled_by_default", item.get("runs_by_default", True)))
                definition.config = item
        self.session.commit()

    def _ensure_source_series_mapping(self, series_id: int, source_id: int, source_identifier: str, canonical: bool) -> None:
        mapping = self.session.scalar(
            select(m.SourceSeriesMapping).where(
                m.SourceSeriesMapping.series_id == series_id,
                m.SourceSeriesMapping.source_id == source_id,
                m.SourceSeriesMapping.source_identifier == source_identifier,
            )
        )
        if mapping is None:
            self.session.add(
                m.SourceSeriesMapping(
                    series_id=series_id,
                    source_id=source_id,
                    source_identifier=source_identifier,
                    is_canonical=canonical,
                )
            )

    def source(self, code: str) -> m.DataSource:
        source = self.session.scalar(select(m.DataSource).where(m.DataSource.code == code))
        if source is None:
            raise KeyError(f"source not bootstrapped: {code}")
        return source

    def series(self, code: str) -> m.DataSeries:
        series = self.session.scalar(select(m.DataSeries).where(m.DataSeries.series_code == code))
        if series is None:
            raise KeyError(f"series not bootstrapped: {code}")
        return series

    def instrument(self, symbol: str) -> m.Instrument:
        instrument = self.session.scalar(select(m.Instrument).where(m.Instrument.symbol == symbol))
        if instrument is None:
            raise KeyError(f"instrument not bootstrapped: {symbol}")
        return instrument

    def raw_payload(
        self,
        source_code: str,
        endpoint: str,
        request_metadata: dict[str, Any],
        response_payload: dict[str, Any] | None,
        status_code: int | None = 200,
        result_status: str = "ok",
        error_context: dict[str, Any] | None = None,
    ) -> m.RawPayload:
        source = self.source(source_code)
        payload_hash = _hash_payload(response_payload)
        existing = self.session.scalar(
            select(m.RawPayload).where(
                m.RawPayload.source_id == source.id,
                m.RawPayload.endpoint == endpoint,
                m.RawPayload.payload_hash == payload_hash,
            )
        )
        if existing:
            return existing
        payload = m.RawPayload(
            source_id=source.id,
            endpoint=endpoint,
            request_metadata=redact_secrets(request_metadata),
            retrieved_at_utc=utc_now(),
            status_code=status_code,
            result_status=result_status,
            payload_hash=payload_hash,
            response_payload=response_payload,
            error_context=error_context,
        )
        self.session.add(payload)
        self.session.flush()
        return payload

    def start_run(
        self,
        collector_name: str,
        profile: str,
        source_code: str | None = None,
        parent_run_id: int | None = None,
        target_type: str | None = None,
        target_key: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> m.CollectorRun:
        run = m.CollectorRun(
            parent_run_id=parent_run_id,
            collector_name=collector_name,
            source_id=self.source(source_code).id if source_code else None,
            profile=profile,
            target_type=target_type,
            target_key=target_key,
            date_from=date_from,
            date_to=date_to,
            started_at_utc=utc_now(),
            status="running",
        )
        self.session.add(run)
        self.session.commit()
        return run

    def finish_run(self, run: m.CollectorRun, status: str = "succeeded", error: dict[str, Any] | None = None) -> None:
        run.status = status
        run.finished_at_utc = utc_now()
        run.error_context = cast(dict[str, Any] | None, redact_secrets(error)) if isinstance(error, dict) else None
        self.session.commit()

    def record_event(
        self,
        event_type: str,
        message: str,
        severity: str = "warning",
        source_code: str | None = None,
        series_code: str | None = None,
        symbol: str | None = None,
        collector_run_id: int | None = None,
        observation_date: date | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            m.DataQualityEvent(
                event_type=event_type,
                severity=severity,
                source_id=self.source(source_code).id if source_code else None,
                series_id=self.series(series_code).id if series_code else None,
                instrument_id=self.instrument(symbol).id if symbol else None,
                collector_run_id=collector_run_id,
                observed_at_utc=utc_now(),
                observation_date=observation_date,
                message=message,
                details=redact_secrets(details or {}),
            )
        )
        self.session.flush()

    def insert_fred_observation(
        self,
        series_code: str,
        raw_payload: m.RawPayload,
        observation_date: date,
        value: Decimal,
        realtime_start: date | None,
        realtime_end: date | None,
        raw_data: dict[str, Any],
    ) -> tuple[bool, m.CanonicalObservation | None]:
        source = self.source("fred")
        series = self.series(series_code)
        key = f"{series_code}:{observation_date.isoformat()}:{realtime_start}:{realtime_end}"
        raw = self.session.scalar(
            select(m.RawObservation).where(
                m.RawObservation.source_id == source.id,
                m.RawObservation.series_id == series.id,
                m.RawObservation.observation_key == key,
                m.RawObservation.raw_payload_id == raw_payload.id,
            )
        )
        if raw is None:
            raw = m.RawObservation(
                source_id=source.id,
                raw_payload_id=raw_payload.id,
                series_id=series.id,
                instrument_id=None,
                observation_key=key,
                observed_date=observation_date,
                value_text=str(value),
                raw_data=raw_data,
                realtime_start=realtime_start,
                realtime_end=realtime_end,
                retrieved_at_utc=raw_payload.retrieved_at_utc,
            )
            self.session.add(raw)
            self.session.flush()
        existing = self.session.scalar(
            select(m.CanonicalObservation).where(
                m.CanonicalObservation.series_id == series.id,
                m.CanonicalObservation.observation_date == observation_date,
                m.CanonicalObservation.realtime_start == realtime_start,
                m.CanonicalObservation.realtime_end == realtime_end,
                m.CanonicalObservation.source_id == source.id,
            )
        )
        if existing:
            return False, existing
        canonical = m.CanonicalObservation(
            series_id=series.id,
            source_id=source.id,
            raw_observation_id=raw.id,
            raw_payload_id=raw_payload.id,
            observation_date=observation_date,
            value=value,
            unit=series.unit,
            quality_status="ok",
            transform_notes="identity parse from FRED observation value",
            realtime_start=realtime_start,
            realtime_end=realtime_end,
            retrieved_at_utc=raw_payload.retrieved_at_utc,
        )
        self.session.add(canonical)
        self.session.flush()
        return True, canonical

    def insert_daily_bar(self, symbol: str, source_code: str, raw_payload: m.RawPayload, bar: dict[str, Any]) -> bool:
        inst = self.instrument(symbol)
        source = self.source(source_code)
        trade_date = bar["trade_date"]
        if isinstance(trade_date, str):
            trade_date = date.fromisoformat(trade_date)
        existing = self.session.scalar(
            select(m.MarketBarDaily).where(
                m.MarketBarDaily.instrument_id == inst.id,
                m.MarketBarDaily.trade_date == trade_date,
                m.MarketBarDaily.source_id == source.id,
                m.MarketBarDaily.adjusted == bool(bar.get("adjusted", True)),
            )
        )
        if existing:
            return False
        self.session.add(
            m.MarketBarDaily(
                instrument_id=inst.id,
                trade_date=trade_date,
                open=Decimal(str(bar["open"])),
                high=Decimal(str(bar["high"])),
                low=Decimal(str(bar["low"])),
                close=Decimal(str(bar["close"])),
                adjusted_close=Decimal(str(bar["adjusted_close"])) if bar.get("adjusted_close") is not None else None,
                volume=bar.get("volume"),
                vwap=Decimal(str(bar["vwap"])) if bar.get("vwap") is not None else None,
                transaction_count=bar.get("transaction_count"),
                source_id=source.id,
                raw_payload_id=raw_payload.id,
                adjusted=bool(bar.get("adjusted", True)),
                quality_status="ok",
            )
        )
        self.session.flush()
        return True

    def insert_corporate_action(
        self, symbol: str, source_code: str, raw_payload: m.RawPayload, action: dict[str, Any]
    ) -> bool:
        inst = self.instrument(symbol)
        source = self.source(source_code)
        ex_date = action["ex_date"]
        if isinstance(ex_date, str):
            ex_date = date.fromisoformat(ex_date)
        source_action_id = action.get("source_action_id") or action.get("id")
        existing = self.session.scalar(
            select(m.CorporateAction).where(
                m.CorporateAction.instrument_id == inst.id,
                m.CorporateAction.source_id == source.id,
                m.CorporateAction.action_type == action["action_type"],
                m.CorporateAction.ex_date == ex_date,
                m.CorporateAction.source_action_id == source_action_id,
            )
        )
        if existing:
            return False
        self.session.add(
            m.CorporateAction(
                instrument_id=inst.id,
                source_id=source.id,
                raw_payload_id=raw_payload.id,
                action_type=action["action_type"],
                ex_date=ex_date,
                amount=Decimal(str(action["amount"])) if action.get("amount") is not None else None,
                ratio=action.get("ratio"),
                source_action_id=source_action_id,
                details=action,
            )
        )
        self.session.flush()
        return True

    def record_discrepancy(
        self,
        symbol: str,
        trade_date: date,
        primary_source_code: str,
        validation_source_code: str,
        field_name: str,
        status: str,
        primary_value: Decimal | None = None,
        validation_value: Decimal | None = None,
        raw_payload_id: int | None = None,
    ) -> bool:
        inst = self.instrument(symbol)
        primary = self.source(primary_source_code)
        validation = self.source(validation_source_code)
        existing = self.session.scalar(
            select(m.SourceDiscrepancy).where(
                m.SourceDiscrepancy.instrument_id == inst.id,
                m.SourceDiscrepancy.trade_date == trade_date,
                m.SourceDiscrepancy.primary_source_id == primary.id,
                m.SourceDiscrepancy.validation_source_id == validation.id,
                m.SourceDiscrepancy.field_name == field_name,
            )
        )
        if existing:
            existing.status = status
            existing.observed_at_utc = utc_now()
            return False
        difference = None
        relative = None
        if primary_value is not None and validation_value is not None:
            difference = abs(primary_value - validation_value)
            relative = difference / primary_value if primary_value != 0 else None
        self.session.add(
            m.SourceDiscrepancy(
                instrument_id=inst.id,
                trade_date=trade_date,
                primary_source_id=primary.id,
                validation_source_id=validation.id,
                field_name=field_name,
                primary_value=primary_value,
                validation_value=validation_value,
                absolute_difference=difference,
                relative_difference=relative,
                status=status,
                raw_payload_id=raw_payload_id,
                observed_at_utc=utc_now(),
            )
        )
        self.session.flush()
        return True

    def insert_quote_snapshot(self, symbol: str, source_code: str, raw_payload: m.RawPayload, quote: dict[str, Any]) -> bool:
        inst = self.instrument(symbol)
        source = self.source(source_code)
        quote_ts = quote["quote_timestamp_utc"]
        if isinstance(quote_ts, str):
            quote_ts = datetime.fromisoformat(quote_ts.replace("Z", "+00:00"))
        existing = self.session.scalar(
            select(m.QuoteSnapshot).where(
                m.QuoteSnapshot.instrument_id == inst.id,
                m.QuoteSnapshot.quote_timestamp_utc == quote_ts,
                m.QuoteSnapshot.source_id == source.id,
            )
        )
        if existing:
            return False
        self.session.add(
            m.QuoteSnapshot(
                instrument_id=inst.id,
                quote_timestamp_utc=quote_ts,
                source_id=source.id,
                last_price=Decimal(str(quote["last_price"])) if quote.get("last_price") is not None else None,
                bid=Decimal(str(quote["bid"])) if quote.get("bid") is not None else None,
                ask=Decimal(str(quote["ask"])) if quote.get("ask") is not None else None,
                prior_close=Decimal(str(quote["prior_close"])) if quote.get("prior_close") is not None else None,
                volume=quote.get("volume"),
                market_state=quote.get("market_state"),
                quote_quality=quote.get("quote_quality", "unknown"),
                raw_payload_id=raw_payload.id,
                received_at_utc=utc_now(),
                quality_status=quote.get("quality_status", "ok"),
            )
        )
        self.session.flush()
        return True

    def counts(self) -> dict[str, int]:
        tables = {
            "sources": m.DataSource,
            "series": m.DataSeries,
            "instruments": m.Instrument,
            "raw_payloads": m.RawPayload,
            "canonical_observations": m.CanonicalObservation,
            "daily_bars": m.MarketBarDaily,
            "quote_snapshots": m.QuoteSnapshot,
            "corporate_actions": m.CorporateAction,
            "source_discrepancies": m.SourceDiscrepancy,
            "collector_runs": m.CollectorRun,
            "quality_events": m.DataQualityEvent,
        }
        return {name: self.session.scalar(select(func.count()).select_from(model)) or 0 for name, model in tables.items()}
