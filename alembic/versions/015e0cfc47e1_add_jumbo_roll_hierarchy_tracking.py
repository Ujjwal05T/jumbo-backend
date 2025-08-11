"""add_jumbo_roll_hierarchy_tracking

Revision ID: 015e0cfc47e1
Revises: e8f4a2b5c3d1
Create Date: 2025-08-08 15:30:07.077739

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER


# revision identifiers, used by Alembic.
revision: str = '015e0cfc47e1'
down_revision: Union[str, None] = 'e8f4a2b5c3d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add jumbo roll hierarchy tracking fields to inventory_master table
    op.add_column('inventory_master', sa.Column('parent_jumbo_id', UNIQUEIDENTIFIER, nullable=True))
    op.add_column('inventory_master', sa.Column('parent_118_roll_id', UNIQUEIDENTIFIER, nullable=True))
    op.add_column('inventory_master', sa.Column('roll_sequence', sa.Integer, nullable=True))
    op.add_column('inventory_master', sa.Column('individual_roll_number', sa.Integer, nullable=True))
    
    # Create indexes for performance
    op.create_index('ix_inventory_master_parent_jumbo_id', 'inventory_master', ['parent_jumbo_id'])
    op.create_index('ix_inventory_master_parent_118_roll_id', 'inventory_master', ['parent_118_roll_id'])
    
    # Add foreign key constraints for self-referencing relationships
    op.create_foreign_key(
        'fk_inventory_master_parent_jumbo_id',
        'inventory_master', 'inventory_master',
        ['parent_jumbo_id'], ['id']
    )
    op.create_foreign_key(
        'fk_inventory_master_parent_118_roll_id', 
        'inventory_master', 'inventory_master',
        ['parent_118_roll_id'], ['id']
    )


def downgrade() -> None:
    # Remove foreign key constraints
    op.drop_constraint('fk_inventory_master_parent_118_roll_id', 'inventory_master', type_='foreignkey')
    op.drop_constraint('fk_inventory_master_parent_jumbo_id', 'inventory_master', type_='foreignkey')
    
    # Remove indexes
    op.drop_index('ix_inventory_master_parent_118_roll_id', 'inventory_master')
    op.drop_index('ix_inventory_master_parent_jumbo_id', 'inventory_master')
    
    # Remove columns
    op.drop_column('inventory_master', 'individual_roll_number')
    op.drop_column('inventory_master', 'roll_sequence')
    op.drop_column('inventory_master', 'parent_118_roll_id')
    op.drop_column('inventory_master', 'parent_jumbo_id')
