"""bot accounts pool with per-user assignment

Revision ID: 8b2d0e5f3a12
Revises: 7a1c9d4e2f01
Create Date: 2026-06-11

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '8b2d0e5f3a12'
down_revision: str | None = '7a1c9d4e2f01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'bot_accounts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('username', sa.Text(), nullable=False),
        sa.Column('sessionid', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('last_poll_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bot_accounts_username'), 'bot_accounts', ['username'], unique=True)
    op.create_index(op.f('ix_bot_accounts_status'), 'bot_accounts', ['status'], unique=False)

    op.add_column('users', sa.Column('bot_account_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_users_bot_account_id', 'users', 'bot_accounts', ['bot_account_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_users_bot_account_id', 'users', type_='foreignkey')
    op.drop_column('users', 'bot_account_id')
    op.drop_index(op.f('ix_bot_accounts_status'), table_name='bot_accounts')
    op.drop_index(op.f('ix_bot_accounts_username'), table_name='bot_accounts')
    op.drop_table('bot_accounts')
