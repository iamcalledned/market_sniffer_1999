"""yahoo legacy price basis

Revision ID: 0005_yahoo_legacy_price_basis
Revises: 0004_price_basis_validation
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

revision = "0005_yahoo_legacy_price_basis"
down_revision = "0004_price_basis_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE market_bars_daily
        SET price_basis = 'total_return_adjusted'
        WHERE price_basis = 'raw'
          AND source_id IN (SELECT id FROM data_sources WHERE code = 'yahoo')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE market_bars_daily
        SET price_basis = 'raw'
        WHERE price_basis = 'total_return_adjusted'
          AND source_id IN (SELECT id FROM data_sources WHERE code = 'yahoo')
        """
    )
