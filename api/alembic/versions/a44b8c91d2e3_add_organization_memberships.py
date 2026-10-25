"""add organization memberships table

Revision ID: a44b8c91d2e3
Revises: f33a7b8c91d2
Create Date: 2026-10-26 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a44b8c91d2e3'
down_revision: Union[str, None] = 'f33a7b8c91d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'organization_memberships',
        sa.Column('id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(length=64), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('org_id', sa.String(length=64), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='ANALYST'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'org_id', name='uq_user_org_membership'),
    )
    op.create_index(
        op.f('ix_organization_memberships_user_id'),
        'organization_memberships',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_organization_memberships_org_id'),
        'organization_memberships',
        ['org_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_organization_memberships_org_id'), table_name='organization_memberships')
    op.drop_index(op.f('ix_organization_memberships_user_id'), table_name='organization_memberships')
    op.drop_table('organization_memberships')
