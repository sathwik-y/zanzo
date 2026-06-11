"""record the DM sender on items so verified users can claim history

Revision ID: 9c3e1f6a4b23
Revises: 8b2d0e5f3a12
Create Date: 2026-06-11

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '9c3e1f6a4b23'
down_revision: str | None = '8b2d0e5f3a12'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('saved_items', sa.Column('dm_sender_pk', sa.Text(), nullable=True))
    op.create_index(
        op.f('ix_saved_items_dm_sender_pk'), 'saved_items', ['dm_sender_pk'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_saved_items_dm_sender_pk'), table_name='saved_items')
    op.drop_column('saved_items', 'dm_sender_pk')
