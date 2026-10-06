"""add_signals_table

Revision ID: e22f6f9b76ea
Revises: d11e5e8a65df
Create Date: 2026-10-06 03:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e22f6f9b76ea'
down_revision: Union[str, None] = 'd11e5e8a65df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'signals',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('signal_id', sa.String(length=64), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=True),
        sa.Column('domain', sa.String(length=50), nullable=False),
        sa.Column('signal_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('source', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('canonical_event_id', sa.String(length=100), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('location_name', sa.String(length=255), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('summary', sa.String(length=1000), nullable=True),
        sa.Column('entity_type', sa.String(length=50), nullable=True),
        sa.Column('entity_id', sa.String(length=64), nullable=True),
        sa.Column('delay_minutes', sa.Float(), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_signals_signal_id'), 'signals', ['signal_id'], unique=True)
    op.create_index(op.f('ix_signals_org_id'), 'signals', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_signals_org_id'), table_name='signals')
    op.drop_index(op.f('ix_signals_signal_id'), table_name='signals')
    op.drop_table('signals')
