"""remove_unused_cut_roll_production_table

Revision ID: ea68956d80d2
Revises: 015e0cfc47e1
Create Date: 2025-08-08 15:44:43.556721

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER


# revision identifiers, used by Alembic.
revision: str = 'ea68956d80d2'
down_revision: Union[str, None] = '015e0cfc47e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove unused cut_roll_production table
    op.drop_table('cut_roll_production')


def downgrade() -> None:
    # Recreate cut_roll_production table if needed to rollback
    op.create_table('cut_roll_production',
        sa.Column('id', UNIQUEIDENTIFIER, nullable=False),
        sa.Column('frontend_id', sa.String(50), nullable=True),
        sa.Column('qr_code', sa.String(255), nullable=False),
        sa.Column('barcode_id', sa.String(50), nullable=True),
        sa.Column('width_inches', sa.Numeric(6, 2), nullable=False),
        sa.Column('length_meters', sa.Numeric(8, 2), nullable=True),
        sa.Column('actual_weight_kg', sa.Numeric(8, 2), nullable=True),
        sa.Column('paper_id', UNIQUEIDENTIFIER, nullable=False),
        sa.Column('gsm', sa.Integer, nullable=False),
        sa.Column('bf', sa.Numeric(4, 2), nullable=False),
        sa.Column('shade', sa.String(100), nullable=False),
        sa.Column('plan_id', UNIQUEIDENTIFIER, nullable=False),
        sa.Column('order_id', UNIQUEIDENTIFIER, nullable=True),
        sa.Column('client_id', UNIQUEIDENTIFIER, nullable=True),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('individual_roll_number', sa.Integer, nullable=True),
        sa.Column('trim_left', sa.Numeric(6, 2), nullable=True),
        sa.Column('source_type', sa.String(50), nullable=True),
        sa.Column('source_pending_id', UNIQUEIDENTIFIER, nullable=True),
        sa.Column('selected_at', sa.DateTime, nullable=False),
        sa.Column('production_started_at', sa.DateTime, nullable=True),
        sa.Column('production_completed_at', sa.DateTime, nullable=True),
        sa.Column('weight_recorded_at', sa.DateTime, nullable=True),
        sa.Column('created_by_id', UNIQUEIDENTIFIER, nullable=False),
        sa.Column('weight_recorded_by_id', UNIQUEIDENTIFIER, nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
