"""add_auth_invitations_and_passwords

Revision ID: f33a7b8c91d2
Revises: e22f6f9b76ea
Create Date: 2026-10-25 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f33a7b8c91d2'
down_revision: Union[str, None] = 'e22f6f9b76ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add hashed_password column to users table
    op.add_column(
        'users',
        sa.Column('hashed_password', sa.String(length=255), nullable=True),
    )

    # 2. Create organization_invitations table
    op.create_table(
        'organization_invitations',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('invited_by_user_id', sa.String(length=64), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='ANALYST'),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_organization_invitations_token_hash'), 'organization_invitations', ['token_hash'], unique=True)
    op.create_index(op.f('ix_organization_invitations_org_id'), 'organization_invitations', ['org_id'], unique=False)
    op.create_index(op.f('ix_organization_invitations_email'), 'organization_invitations', ['email'], unique=False)

    # 3. Create password_reset_tokens table
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_password_reset_tokens_token_hash'), 'password_reset_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_token_hash'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')

    op.drop_index(op.f('ix_organization_invitations_email'), table_name='organization_invitations')
    op.drop_index(op.f('ix_organization_invitations_org_id'), table_name='organization_invitations')
    op.drop_index(op.f('ix_organization_invitations_token_hash'), table_name='organization_invitations')
    op.drop_table('organization_invitations')

    op.drop_column('users', 'hashed_password')
