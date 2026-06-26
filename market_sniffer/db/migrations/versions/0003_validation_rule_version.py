"""validation rule version

Revision ID: 0003_validation_rule_version
Revises: 0002_remediation_contracts
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_validation_rule_version"
down_revision = "0002_remediation_contracts"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table) if idx["name"] is not None}


def upgrade() -> None:
    if "comparison_rule_version" not in _columns("source_discrepancies"):
        op.add_column(
            "source_discrepancies",
            sa.Column("comparison_rule_version", sa.String(length=40), nullable=False, server_default="validation_v1"),
        )
    if "ix_source_discrepancies_comparison_rule_version" not in _indexes("source_discrepancies"):
        op.create_index(
            "ix_source_discrepancies_comparison_rule_version",
            "source_discrepancies",
            ["comparison_rule_version"],
        )


def downgrade() -> None:
    with op.batch_alter_table("source_discrepancies") as batch:
        batch.drop_index("ix_source_discrepancies_comparison_rule_version")
        batch.drop_column("comparison_rule_version")
