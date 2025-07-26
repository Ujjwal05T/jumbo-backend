"""add_order_items_table

Revision ID: 047cd19e0c1c
Revises: 3c7e5b80a833
Create Date: 2025-07-26 17:43:03.009389

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = '047cd19e0c1c'
down_revision: Union[str, None] = '3c7e5b80a833'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create order_item table first
    op.create_table('order_item',
        sa.Column('id', mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column('order_id', mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column('width_inches', sa.Integer(), nullable=False),
        sa.Column('quantity_rolls', sa.Integer(), nullable=False),
        sa.Column('quantity_fulfilled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('GETDATE()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('GETDATE()')),
        sa.ForeignKeyConstraint(['order_id'], ['order_master.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_order_item_id'), 'order_item', ['id'], unique=False)
    op.create_index(op.f('ix_order_item_order_id'), 'order_item', ['order_id'], unique=False)
    
    # Migrate existing order data to order_items
    op.execute("""
        INSERT INTO order_item (id, order_id, width_inches, quantity_rolls, quantity_fulfilled, created_at, updated_at)
        SELECT NEWID(), id, width_inches, quantity_rolls, quantity_fulfilled, created_at, updated_at
        FROM order_master
        WHERE width_inches IS NOT NULL
    """)
    
    # Add order_item_id as nullable first with a default value
    op.add_column('pending_order_master', sa.Column('order_item_id', mssql.UNIQUEIDENTIFIER(), nullable=True, server_default=sa.text('NEWID()')))
    
    # Update pending_order_master to link to order_items
    op.execute("""
        UPDATE pom
        SET order_item_id = oi.id
        FROM pending_order_master pom
        INNER JOIN order_item oi ON pom.order_id = oi.order_id 
        AND pom.width_inches = oi.width_inches
    """)
    
    # Remove the default and make it NOT NULL
    op.alter_column('pending_order_master', 'order_item_id', server_default=None)
    op.alter_column('pending_order_master', 'order_item_id', nullable=False)
    
    # Add foreign key constraint and index
    op.create_index(op.f('ix_pending_order_master_order_item_id'), 'pending_order_master', ['order_item_id'], unique=False)
    op.create_foreign_key(None, 'pending_order_master', 'order_item', ['order_item_id'], ['id'])
    
    # Similarly for plan_order_link
    op.add_column('plan_order_link', sa.Column('order_item_id', mssql.UNIQUEIDENTIFIER(), nullable=True, server_default=sa.text('NEWID()')))
    
    op.execute("""
        UPDATE pol
        SET order_item_id = oi.id
        FROM plan_order_link pol
        INNER JOIN order_item oi ON pol.order_id = oi.order_id
    """)
    
    # Remove the default and make it NOT NULL
    op.alter_column('plan_order_link', 'order_item_id', server_default=None)
    op.alter_column('plan_order_link', 'order_item_id', nullable=False)
    op.create_index(op.f('ix_plan_order_link_order_item_id'), 'plan_order_link', ['order_item_id'], unique=False)
    op.create_foreign_key(None, 'plan_order_link', 'order_item', ['order_item_id'], ['id'])
    
    # Finally, remove old columns from order_master
    op.drop_column('order_master', 'width_inches')
    op.drop_column('order_master', 'quantity_rolls')
    op.drop_column('order_master', 'quantity_fulfilled')


def downgrade() -> None:
    # Add back columns to order_master as nullable first
    op.add_column('order_master', sa.Column('quantity_fulfilled', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('order_master', sa.Column('width_inches', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('order_master', sa.Column('quantity_rolls', sa.INTEGER(), autoincrement=False, nullable=True))
    
    # Migrate data back from order_items to order_master (taking first item only)
    op.execute("""
        UPDATE om
        SET width_inches = oi.width_inches,
            quantity_rolls = oi.quantity_rolls,
            quantity_fulfilled = oi.quantity_fulfilled
        FROM order_master om
        INNER JOIN (
            SELECT order_id, 
                   MIN(width_inches) as width_inches,
                   SUM(quantity_rolls) as quantity_rolls,
                   SUM(quantity_fulfilled) as quantity_fulfilled
            FROM order_item 
            GROUP BY order_id
        ) oi ON om.id = oi.order_id
    """)
    
    # Make columns NOT NULL
    op.alter_column('order_master', 'quantity_fulfilled', nullable=False)
    op.alter_column('order_master', 'width_inches', nullable=False)
    op.alter_column('order_master', 'quantity_rolls', nullable=False)
    
    # Remove foreign key constraints and columns
    op.drop_constraint(None, 'plan_order_link', type_='foreignkey')
    op.drop_index(op.f('ix_plan_order_link_order_item_id'), table_name='plan_order_link')
    op.drop_column('plan_order_link', 'order_item_id')
    
    op.drop_constraint(None, 'pending_order_master', type_='foreignkey')
    op.drop_index(op.f('ix_pending_order_master_order_item_id'), table_name='pending_order_master')
    op.drop_column('pending_order_master', 'order_item_id')
    
    # Drop order_item table
    op.drop_index(op.f('ix_order_item_order_id'), table_name='order_item')
    op.drop_index(op.f('ix_order_item_id'), table_name='order_item')
    op.drop_table('order_item')
