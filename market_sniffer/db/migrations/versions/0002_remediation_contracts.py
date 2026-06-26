"""remediation contracts

Revision ID: 0002_remediation_contracts
Revises: 0001_data_foundation
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_remediation_contracts"
down_revision = "0001_data_foundation"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table)}


def _tables() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index_if_missing(index_name: str, table: str, columns: list[str]) -> None:
    bind = op.get_bind()
    existing = {idx["name"] for idx in sa.inspect(bind).get_indexes(table)}
    if index_name not in existing:
        op.create_index(index_name, table, columns)


def upgrade() -> None:
    _add_column_if_missing("raw_payloads", sa.Column("retention_class", sa.String(length=40), nullable=False, server_default="indefinite"))
    _add_column_if_missing("raw_payloads", sa.Column("source_record_identifier", sa.String(length=160), nullable=True))
    _add_column_if_missing("raw_payloads", sa.Column("protected", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("raw_payloads", sa.Column("pruned_at_utc", sa.DateTime(timezone=True), nullable=True))
    _create_index_if_missing("ix_raw_payloads_retention_class", "raw_payloads", ["retention_class"])
    _create_index_if_missing("ix_raw_payloads_source_record_identifier", "raw_payloads", ["source_record_identifier"])
    _create_index_if_missing("ix_raw_payloads_protected", "raw_payloads", ["protected"])
    _create_index_if_missing("ix_raw_payloads_pruned_at_utc", "raw_payloads", ["pruned_at_utc"])

    _add_column_if_missing("raw_observations", sa.Column("quality_status", sa.String(length=40), nullable=False, server_default="ok"))
    _add_column_if_missing("raw_observations", sa.Column("is_latest_vintage", sa.Boolean(), nullable=False, server_default=sa.true()))
    _create_index_if_missing("ix_raw_observations_quality_status", "raw_observations", ["quality_status"])
    _create_index_if_missing("ix_raw_observations_is_latest_vintage", "raw_observations", ["is_latest_vintage"])

    _add_column_if_missing("canonical_observations", sa.Column("is_latest_vintage", sa.Boolean(), nullable=False, server_default=sa.true()))
    _create_index_if_missing("ix_canonical_observations_is_latest_vintage", "canonical_observations", ["is_latest_vintage"])

    _add_column_if_missing("market_bars_daily", sa.Column("price_basis", sa.String(length=40), nullable=False, server_default="adjusted"))
    _add_column_if_missing("market_bars_daily", sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.true()))
    _create_index_if_missing("ix_market_bars_daily_price_basis", "market_bars_daily", ["price_basis"])
    _create_index_if_missing("ix_market_bars_daily_is_final", "market_bars_daily", ["is_final"])

    if "canonical_market_bars_daily" not in _tables():
        op.create_table(
            "canonical_market_bars_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
            sa.Column("trade_date", sa.Date(), nullable=False),
            sa.Column("price_basis", sa.String(length=40), nullable=False),
            sa.Column("open", sa.Numeric(28, 10), nullable=False),
            sa.Column("high", sa.Numeric(28, 10), nullable=False),
            sa.Column("low", sa.Numeric(28, 10), nullable=False),
            sa.Column("close", sa.Numeric(28, 10), nullable=False),
            sa.Column("adjusted_close", sa.Numeric(28, 10), nullable=True),
            sa.Column("volume", sa.Integer(), nullable=True),
            sa.Column("vwap", sa.Numeric(28, 10), nullable=True),
            sa.Column("transactions", sa.Integer(), nullable=True),
            sa.Column("canonical_source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
            sa.Column("source_market_bar_id", sa.Integer(), sa.ForeignKey("market_bars_daily.id"), nullable=False),
            sa.Column("raw_payload_id", sa.Integer(), sa.ForeignKey("raw_payloads.id"), nullable=False),
            sa.Column("quality_status", sa.String(length=40), nullable=False),
            sa.Column("is_final", sa.Boolean(), nullable=False),
            sa.Column("canonicalization_rule_version", sa.String(length=40), nullable=False),
            sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("instrument_id", "trade_date", "price_basis", name="uq_canonical_market_bar_daily"),
        )
    _create_index_if_missing("ix_canonical_market_bars_daily_instrument_id", "canonical_market_bars_daily", ["instrument_id"])
    _create_index_if_missing("ix_canonical_market_bars_daily_trade_date", "canonical_market_bars_daily", ["trade_date"])
    _create_index_if_missing("ix_canonical_market_bars_daily_price_basis", "canonical_market_bars_daily", ["price_basis"])
    _create_index_if_missing("ix_canonical_market_bars_daily_canonical_source_id", "canonical_market_bars_daily", ["canonical_source_id"])
    _create_index_if_missing("ix_canonical_market_bars_daily_source_market_bar_id", "canonical_market_bars_daily", ["source_market_bar_id"])
    _create_index_if_missing("ix_canonical_market_bars_daily_raw_payload_id", "canonical_market_bars_daily", ["raw_payload_id"])

    _add_column_if_missing("quote_snapshots", sa.Column("quote_delay_seconds", sa.Integer(), nullable=True))
    _add_column_if_missing("quote_snapshots", sa.Column("is_tradeable_quote", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("quote_snapshots", sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("quote_snapshots", sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=True))
    _create_index_if_missing("ix_quote_snapshots_is_tradeable_quote", "quote_snapshots", ["is_tradeable_quote"])
    _create_index_if_missing("ix_quote_snapshots_is_stale", "quote_snapshots", ["is_stale"])


def downgrade() -> None:
    op.drop_table("canonical_market_bars_daily")
    with op.batch_alter_table("quote_snapshots") as batch:
        batch.drop_index("ix_quote_snapshots_is_stale")
        batch.drop_index("ix_quote_snapshots_is_tradeable_quote")
        batch.drop_column("created_at_utc")
        batch.drop_column("is_stale")
        batch.drop_column("is_tradeable_quote")
        batch.drop_column("quote_delay_seconds")
    with op.batch_alter_table("market_bars_daily") as batch:
        batch.drop_index("ix_market_bars_daily_is_final")
        batch.drop_index("ix_market_bars_daily_price_basis")
        batch.drop_column("is_final")
        batch.drop_column("price_basis")
    with op.batch_alter_table("canonical_observations") as batch:
        batch.drop_index("ix_canonical_observations_is_latest_vintage")
        batch.drop_column("is_latest_vintage")
    with op.batch_alter_table("raw_observations") as batch:
        batch.drop_index("ix_raw_observations_is_latest_vintage")
        batch.drop_index("ix_raw_observations_quality_status")
        batch.drop_column("is_latest_vintage")
        batch.drop_column("quality_status")
    with op.batch_alter_table("raw_payloads") as batch:
        batch.drop_index("ix_raw_payloads_pruned_at_utc")
        batch.drop_index("ix_raw_payloads_protected")
        batch.drop_index("ix_raw_payloads_source_record_identifier")
        batch.drop_index("ix_raw_payloads_retention_class")
        batch.drop_column("pruned_at_utc")
        batch.drop_column("protected")
        batch.drop_column("source_record_identifier")
        batch.drop_column("retention_class")
