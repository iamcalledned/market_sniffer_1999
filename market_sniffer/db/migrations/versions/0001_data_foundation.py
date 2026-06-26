"""data foundation v1

Revision ID: 0001_data_foundation
Revises:
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

revision = "0001_data_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from market_sniffer.db.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from market_sniffer.db.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
