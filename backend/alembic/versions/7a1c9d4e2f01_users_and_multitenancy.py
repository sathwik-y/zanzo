"""users table, per-user item scoping

Revision ID: 7a1c9d4e2f01
Revises: 56bbf504f257
Create Date: 2026-06-11

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '7a1c9d4e2f01'
down_revision: str | None = '56bbf504f257'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=True),
        sa.Column('role', sa.String(length=8), nullable=False),
        sa.Column('ig_username', sa.Text(), nullable=True),
        sa.Column('ig_user_pk', sa.Text(), nullable=True),
        sa.Column('ig_verified', sa.Boolean(), nullable=False),
        sa.Column('ig_verification_code', sa.String(length=16), nullable=True),
        sa.Column('ig_verification_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_ig_username'), 'users', ['ig_username'], unique=False)
    op.create_index(op.f('ix_users_ig_user_pk'), 'users', ['ig_user_pk'], unique=True)

    op.add_column('saved_items', sa.Column('user_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_saved_items_user_id'), 'saved_items', ['user_id'], unique=False)
    op.create_foreign_key(
        'fk_saved_items_user_id', 'saved_items', 'users', ['user_id'], ['id'],
        ondelete='CASCADE',
    )
    # media_pk is now unique per user (the same reel DMed by two users is two rows)
    op.drop_index('ix_saved_items_media_pk', table_name='saved_items')
    op.create_index(op.f('ix_saved_items_media_pk'), 'saved_items', ['media_pk'], unique=False)
    op.create_unique_constraint(
        'uq_saved_items_user_media', 'saved_items', ['user_id', 'media_pk'],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_constraint('uq_saved_items_user_media', 'saved_items', type_='unique')
    op.drop_index(op.f('ix_saved_items_media_pk'), table_name='saved_items')
    op.create_index('ix_saved_items_media_pk', 'saved_items', ['media_pk'], unique=True)
    op.drop_constraint('fk_saved_items_user_id', 'saved_items', type_='foreignkey')
    op.drop_index(op.f('ix_saved_items_user_id'), table_name='saved_items')
    op.drop_column('saved_items', 'user_id')
    op.drop_index(op.f('ix_users_ig_user_pk'), table_name='users')
    op.drop_index(op.f('ix_users_ig_username'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
