from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON}


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    credential_env: Mapped[str | None] = mapped_column(String(80))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    canonical_responsibilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_responsibilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    future_quote_capability: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class DataSeries(Base):
    __tablename__ = "data_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_identifier: Mapped[str] = mapped_column(String(120), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), index=True)
    frequency: Mapped[str] = mapped_column(String(40))
    unit: Mapped[str] = mapped_column(String(80))
    native_unit: Mapped[str] = mapped_column(String(120))
    canonical_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    description: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    vintage_tracking: Mapped[bool] = mapped_column(Boolean, default=False)
    collection_profile: Mapped[str] = mapped_column(String(80), index=True)


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    asset_class: Mapped[str] = mapped_column(String(60), index=True)
    exchange: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(12), default="USD")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    collection_profiles: Mapped[list[str]] = mapped_column(JSON, default=list)
    daily_collection_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    future_intraday_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    future_quote_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    why_tracked: Mapped[str] = mapped_column(Text)


class InstrumentAlias(Base):
    __tablename__ = "instrument_aliases"
    __table_args__ = (UniqueConstraint("instrument_id", "source_id", "alias", name="uq_instrument_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    alias: Mapped[str] = mapped_column(String(80), index=True)


class SourceSeriesMapping(Base):
    __tablename__ = "source_series_mappings"
    __table_args__ = (UniqueConstraint("series_id", "source_id", "source_identifier", name="uq_source_series_mapping"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("data_series.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_identifier: Mapped[str] = mapped_column(String(120), index=True)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False)


class RawPayload(Base):
    __tablename__ = "raw_payloads"
    __table_args__ = (UniqueConstraint("source_id", "endpoint", "payload_hash", name="uq_raw_payload_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(160), index=True)
    request_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieved_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status_code: Mapped[int | None] = mapped_column(Integer)
    result_status: Mapped[str] = mapped_column(String(40), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    compressed_reference: Mapped[str | None] = mapped_column(Text)
    error_context: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    retention_class: Mapped[str] = mapped_column(String(40), default="indefinite", index=True)
    source_record_identifier: Mapped[str | None] = mapped_column(String(160), index=True)
    protected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pruned_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class RawObservation(Base):
    __tablename__ = "raw_observations"
    __table_args__ = (UniqueConstraint("source_id", "series_id", "instrument_id", "observation_key", "raw_payload_id", name="uq_raw_observation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    raw_payload_id: Mapped[int] = mapped_column(ForeignKey("raw_payloads.id"), index=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("data_series.id"), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    observation_key: Mapped[str] = mapped_column(String(180), index=True)
    observed_date: Mapped[date | None] = mapped_column(Date, index=True)
    observed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    value_text: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    realtime_start: Mapped[date | None] = mapped_column(Date)
    realtime_end: Mapped[date | None] = mapped_column(Date)
    retrieved_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    quality_status: Mapped[str] = mapped_column(String(40), default="ok", index=True)
    is_latest_vintage: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class CanonicalObservation(Base):
    __tablename__ = "canonical_observations"
    __table_args__ = (UniqueConstraint("series_id", "observation_date", "realtime_start", "source_id", name="uq_canonical_observation_vintage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("data_series.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    raw_observation_id: Mapped[int] = mapped_column(ForeignKey("raw_observations.id"), index=True)
    raw_payload_id: Mapped[int] = mapped_column(ForeignKey("raw_payloads.id"), index=True)
    observation_date: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    unit: Mapped[str] = mapped_column(String(80))
    quality_status: Mapped[str] = mapped_column(String(40), default="ok", index=True)
    transform_notes: Mapped[str] = mapped_column(Text, default="identity")
    realtime_start: Mapped[date | None] = mapped_column(Date)
    realtime_end: Mapped[date | None] = mapped_column(Date)
    retrieved_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_latest_vintage: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class MarketBarDaily(Base):
    __tablename__ = "market_bars_daily"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trade_date", "source_id", "price_basis", name="uq_market_bar_daily_basis"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    high: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    low: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    close: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    volume: Mapped[int | None] = mapped_column(Integer)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    transaction_count: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    raw_payload_id: Mapped[int] = mapped_column(ForeignKey("raw_payloads.id"), index=True)
    adjusted: Mapped[bool] = mapped_column(Boolean, default=True)
    price_basis: Mapped[str] = mapped_column(String(40), default="split_adjusted", index=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    quality_status: Mapped[str] = mapped_column(String(40), default="ok", index=True)


class CanonicalMarketBarDaily(Base):
    __tablename__ = "canonical_market_bars_daily"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trade_date", "price_basis", name="uq_canonical_market_bar_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    price_basis: Mapped[str] = mapped_column(String(40), default="split_adjusted", index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    high: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    low: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    close: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    volume: Mapped[int | None] = mapped_column(Integer)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    transactions: Mapped[int | None] = mapped_column(Integer)
    canonical_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_market_bar_id: Mapped[int] = mapped_column(ForeignKey("market_bars_daily.id"), index=True)
    raw_payload_id: Mapped[int] = mapped_column(ForeignKey("raw_payloads.id"), index=True)
    quality_status: Mapped[str] = mapped_column(String(40), default="ok", index=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    canonicalization_rule_version: Mapped[str] = mapped_column(String(40), index=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MarketBarIntraday(Base):
    __tablename__ = "market_bars_intraday"
    __table_args__ = (UniqueConstraint("instrument_id", "bar_start_utc", "interval", "source_id", "adjusted", name="uq_market_bar_intraday"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    bar_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    interval: Mapped[str] = mapped_column(String(12), index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    high: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    low: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    close: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    volume: Mapped[int | None] = mapped_column(Integer)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    raw_payload_id: Mapped[int] = mapped_column(ForeignKey("raw_payloads.id"), index=True)
    adjusted: Mapped[bool] = mapped_column(Boolean, default=True)
    quality_status: Mapped[str] = mapped_column(String(40), default="ok", index=True)


class QuoteSnapshot(Base):
    __tablename__ = "quote_snapshots"
    __table_args__ = (UniqueConstraint("instrument_id", "quote_timestamp_utc", "source_id", name="uq_quote_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    quote_timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    bid: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    prior_close: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    volume: Mapped[int | None] = mapped_column(Integer)
    market_state: Mapped[str | None] = mapped_column(String(40))
    quote_delay_seconds: Mapped[int | None] = mapped_column(Integer)
    quote_quality: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    is_tradeable_quote: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_payload_id: Mapped[int] = mapped_column(ForeignKey("raw_payloads.id"), index=True)
    received_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    quality_status: Mapped[str] = mapped_column(String(40), default="ok", index=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("instrument_id", "snapshot_date", "source_id", name="uq_market_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    raw_payload_id: Mapped[int] = mapped_column(ForeignKey("raw_payloads.id"), index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (UniqueConstraint("instrument_id", "source_id", "action_type", "ex_date", "source_action_id", name="uq_corporate_action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    raw_payload_id: Mapped[int] = mapped_column(ForeignKey("raw_payloads.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    ex_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    ratio: Mapped[str | None] = mapped_column(String(80))
    source_action_id: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CollectorDefinition(Base):
    __tablename__ = "collector_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    profile: Mapped[str] = mapped_column(String(80), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule_hint: Mapped[str | None] = mapped_column(String(120))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("collector_runs.id"), index=True)
    collector_name: Mapped[str] = mapped_column(String(120), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"), index=True)
    profile: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), index=True)
    target_key: Mapped[str | None] = mapped_column(String(120), index=True)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), index=True)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_context: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    retry_context: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resume_token: Mapped[str | None] = mapped_column(String(200), index=True)

    parent: Mapped["CollectorRun | None"] = relationship(remote_side=[id])


class CollectorRunItem(Base):
    __tablename__ = "collector_run_items"
    __table_args__ = (UniqueConstraint("collector_run_id", "target_type", "target_key", "date_from", "date_to", name="uq_collector_run_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(40), index=True)
    target_key: Mapped[str] = mapped_column(String(120), index=True)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), index=True)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_context: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"), index=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("data_series.id"), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    collector_run_id: Mapped[int | None] = mapped_column(ForeignKey("collector_runs.id"), index=True)
    observed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observation_date: Mapped[date | None] = mapped_column(Date, index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class SourceDiscrepancy(Base):
    __tablename__ = "source_discrepancies"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "trade_date",
            "primary_source_id",
            "validation_source_id",
            "field_name",
            "comparison_rule_version",
            name="uq_source_discrepancy_rule",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    primary_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    validation_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(40), index=True)
    primary_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    validation_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    absolute_difference: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    relative_difference: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    status: Mapped[str] = mapped_column(String(40), index=True)
    comparison_rule_version: Mapped[str] = mapped_column(String(40), default="validation_v1", index=True)
    raw_payload_id: Mapped[int | None] = mapped_column(ForeignKey("raw_payloads.id"))
    observed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    superseded_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), index=True)
    formula_version: Mapped[str] = mapped_column(String(40), index=True)
    frequency: Mapped[str] = mapped_column(String(40), default="market_daily", index=True)
    unit: Mapped[str] = mapped_column(String(40))
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MetricCalculationRun(Base):
    __tablename__ = "metric_calculation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(80), index=True)
    as_of_start: Mapped[date | None] = mapped_column(Date, index=True)
    as_of_end: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    metrics_attempted: Mapped[int] = mapped_column(Integer, default=0)
    metrics_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    metrics_skipped: Mapped[int] = mapped_column(Integer, default=0)
    metrics_failed: Mapped[int] = mapped_column(Integer, default=0)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MetricObservation(Base):
    __tablename__ = "metric_observations"
    __table_args__ = (
        UniqueConstraint(
            "metric_definition_id",
            "as_of_date",
            "formula_version",
            name="uq_metric_observation_formula",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_definition_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), index=True)
    calculation_run_id: Mapped[int | None] = mapped_column(ForeignKey("metric_calculation_runs.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(40))
    quality_status: Mapped[str] = mapped_column(String(40), default="ok", index=True)
    quality_details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    formula_version: Mapped[str] = mapped_column(String(40), index=True)
    source_lineage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_window_start: Mapped[date | None] = mapped_column(Date, index=True)
    input_window_end: Mapped[date | None] = mapped_column(Date, index=True)
    effective_source_date: Mapped[date | None] = mapped_column(Date, index=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class EvidenceEvent(Base):
    __tablename__ = "evidence_events"
    __table_args__ = (
        UniqueConstraint(
            "event_code",
            "metric_definition_id",
            "as_of_date",
            "rule_version",
            name="uq_evidence_event_rule",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_code: Mapped[str] = mapped_column(String(160), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    metric_definition_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), index=True)
    metric_observation_id: Mapped[int | None] = mapped_column(ForeignKey("metric_observations.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    rule_version: Mapped[str] = mapped_column(String(40), index=True)
    headline: Mapped[str] = mapped_column(String(240))
    detail: Mapped[str] = mapped_column(Text)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    prior_value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    threshold_numeric: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
