"""price basis validation

Revision ID: 0004_price_basis_validation
Revises: 0003_validation_rule_version
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_price_basis_validation"
down_revision = "0003_validation_rule_version"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table) if idx["name"] is not None}


def _unique_constraints(table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table)
        if constraint["name"] is not None
    }


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index_if_missing(index_name: str, table: str, columns: list[str]) -> None:
    if index_name not in _indexes(table):
        op.create_index(index_name, table, columns)


def upgrade() -> None:
    _add_column_if_missing(
        "source_discrepancies",
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    _add_column_if_missing(
        "source_discrepancies",
        sa.Column("superseded_at_utc", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index_if_missing(
        "ix_source_discrepancies_superseded_at_utc",
        "source_discrepancies",
        ["superseded_at_utc"],
    )

    op.execute("UPDATE market_bars_daily SET price_basis = 'split_adjusted' WHERE price_basis = 'adjusted'")
    op.execute("UPDATE market_bars_daily SET price_basis = 'raw' WHERE price_basis = 'unadjusted'")
    op.execute(
        "UPDATE canonical_market_bars_daily SET price_basis = 'split_adjusted' WHERE price_basis = 'adjusted'"
    )
    op.execute("UPDATE canonical_market_bars_daily SET price_basis = 'raw' WHERE price_basis = 'unadjusted'")

    constraints = _unique_constraints("market_bars_daily")
    with op.batch_alter_table("market_bars_daily") as batch:
        if "uq_market_bar_daily" in constraints:
            batch.drop_constraint("uq_market_bar_daily", type_="unique")
        if "uq_market_bar_daily_basis" not in constraints:
            batch.create_unique_constraint(
                "uq_market_bar_daily_basis",
                ["instrument_id", "trade_date", "source_id", "price_basis"],
            )

    constraints = _unique_constraints("source_discrepancies")
    with op.batch_alter_table("source_discrepancies") as batch:
        if "uq_source_discrepancy" in constraints:
            batch.drop_constraint("uq_source_discrepancy", type_="unique")
        if "uq_source_discrepancy_rule" not in constraints:
            batch.create_unique_constraint(
                "uq_source_discrepancy_rule",
                [
                    "instrument_id",
                    "trade_date",
                    "primary_source_id",
                    "validation_source_id",
                    "field_name",
                    "comparison_rule_version",
                ],
            )


def downgrade() -> None:
    constraints = _unique_constraints("source_discrepancies")
    with op.batch_alter_table("source_discrepancies") as batch:
        if "uq_source_discrepancy_rule" in constraints:
            batch.drop_constraint("uq_source_discrepancy_rule", type_="unique")
        if "uq_source_discrepancy" not in constraints:
            batch.create_unique_constraint(
                "uq_source_discrepancy",
                ["instrument_id", "trade_date", "primary_source_id", "validation_source_id", "field_name"],
            )
        if "superseded_at_utc" in _columns("source_discrepancies"):
            batch.drop_index("ix_source_discrepancies_superseded_at_utc")
            batch.drop_column("superseded_at_utc")
        if "details" in _columns("source_discrepancies"):
            batch.drop_column("details")

    constraints = _unique_constraints("market_bars_daily")
    with op.batch_alter_table("market_bars_daily") as batch:
        if "uq_market_bar_daily_basis" in constraints:
            batch.drop_constraint("uq_market_bar_daily_basis", type_="unique")
        if "uq_market_bar_daily" not in constraints:
            batch.create_unique_constraint(
                "uq_market_bar_daily",
                ["instrument_id", "trade_date", "source_id", "adjusted"],
            )
