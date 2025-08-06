"""add_source_tracking_fields

Revision ID: d9f96d4657e3
Revises: b7e4e57afaa4
Create Date: 2025-08-06 11:21:34.806607

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER


# revision identifiers, used by Alembic.
revision: str = 'd9f96d4657e3'
down_revision: Union[str, None] = 'b7e4e57afaa4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add source tracking fields to inventory_master table
    op.add_column('inventory_master', sa.Column('source_type', sa.String(length=50), nullable=True))
    op.add_column('inventory_master', sa.Column('source_pending_id', UNIQUEIDENTIFIER(), nullable=True))
    
    # Add indexes for source tracking fields in inventory_master
    op.create_index('ix_inventory_master_source_type', 'inventory_master', ['source_type'])
    op.create_index('ix_inventory_master_source_pending_id', 'inventory_master', ['source_pending_id'])
    
    # Add foreign key constraint for source_pending_id in inventory_master
    op.create_foreign_key(
        'fk_inventory_master_source_pending_id', 
        'inventory_master', 
        'pending_order_item', 
        ['source_pending_id'], 
        ['id']
    )
    
    # Add source tracking fields to cut_roll_production table
    op.add_column('cut_roll_production', sa.Column('source_type', sa.String(length=50), nullable=True))
    op.add_column('cut_roll_production', sa.Column('source_pending_id', UNIQUEIDENTIFIER(), nullable=True))
    
    # Add indexes for source tracking fields in cut_roll_production
    op.create_index('ix_cut_roll_production_source_type', 'cut_roll_production', ['source_type'])
    op.create_index('ix_cut_roll_production_source_pending_id', 'cut_roll_production', ['source_pending_id'])
    
    # Add foreign key constraint for source_pending_id in cut_roll_production
    op.create_foreign_key(
        'fk_cut_roll_production_source_pending_id', 
        'cut_roll_production', 
        'pending_order_item', 
        ['source_pending_id'], 
        ['id']
    )


def downgrade() -> None:
    # Remove foreign key constraints
    op.drop_constraint('fk_cut_roll_production_source_pending_id', 'cut_roll_production', type_='foreignkey')
    op.drop_constraint('fk_inventory_master_source_pending_id', 'inventory_master', type_='foreignkey')
    
    # Remove indexes for cut_roll_production
    op.drop_index('ix_cut_roll_production_source_pending_id', 'cut_roll_production')
    op.drop_index('ix_cut_roll_production_source_type', 'cut_roll_production')
    
    # Remove indexes for inventory_master
    op.drop_index('ix_inventory_master_source_pending_id', 'inventory_master')
    op.drop_index('ix_inventory_master_source_type', 'inventory_master')
    
    # Remove columns from cut_roll_production table
    op.drop_column('cut_roll_production', 'source_pending_id')
    op.drop_column('cut_roll_production', 'source_type')
    
    # Remove columns from inventory_master table
    op.drop_column('inventory_master', 'source_pending_id')
    op.drop_column('inventory_master', 'source_type')
