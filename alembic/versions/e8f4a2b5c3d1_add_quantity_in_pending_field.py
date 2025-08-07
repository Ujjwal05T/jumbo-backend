"""add quantity_in_pending field

Revision ID: e8f4a2b5c3d1
Revises: d9f96d4657e3
Create Date: 2025-01-15 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8f4a2b5c3d1'
down_revision = 'd9f96d4657e3'
branch_labels = None
depends_on = None


def upgrade():
    # Add quantity_in_pending column to order_item table
    op.add_column('order_item', sa.Column('quantity_in_pending', sa.Integer(), nullable=False, server_default='0'))
    
    # Update existing records to have 0 pending quantity
    op.execute("UPDATE order_item SET quantity_in_pending = 0 WHERE quantity_in_pending IS NULL")


def downgrade():
    # Remove the column
    op.drop_column('order_item', 'quantity_in_pending')