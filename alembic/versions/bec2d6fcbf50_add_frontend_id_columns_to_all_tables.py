"""add_frontend_id_columns_to_all_tables

Revision ID: bec2d6fcbf50
Revises: 55e5d8a86145
Create Date: 2025-08-01 07:57:20.230254

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bec2d6fcbf50'
down_revision: Union[str, None] = '55e5d8a86145'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add columns without unique indexes first
    op.add_column('client_master', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('cut_roll_production', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('dispatch_item', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('dispatch_record', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('inventory_master', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('order_item', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('order_master', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('paper_master', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('pending_order_item', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('pending_order_master', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('plan_inventory_link', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('plan_master', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('plan_order_link', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('production_order_master', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    op.add_column('user_master', sa.Column('frontend_id', sa.String(length=50), nullable=True))
    
    # Step 2: Generate frontend_ids for existing records
    connection = op.get_bind()
    
    # Tables with created_at column - simple counters
    tables_with_created_at = [
        ('client_master', 'CL'),
        ('user_master', 'USR'),
        ('paper_master', 'PAP'),
        ('order_item', 'ORI'),
        ('pending_order_master', 'POM'),
        ('pending_order_item', 'POI'),
        ('inventory_master', 'INV'),
        ('production_order_master', 'PRO')
    ]
    
    for table_name, prefix in tables_with_created_at:
        connection.execute(sa.text(f"""
            WITH numbered_rows AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) as row_num
                FROM {table_name}
                WHERE frontend_id IS NULL
            )
            UPDATE {table_name}
            SET frontend_id = '{prefix}-' + RIGHT('000' + CAST(numbered_rows.row_num AS VARCHAR), 3)
            FROM numbered_rows
            WHERE {table_name}.id = numbered_rows.id
        """))
    
    # Tables with other datetime columns for ordering
    # CutRollProduction uses selected_at column
    connection.execute(sa.text("""
        WITH numbered_rows AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY selected_at) as row_num
            FROM cut_roll_production
            WHERE frontend_id IS NULL
        )
        UPDATE cut_roll_production
        SET frontend_id = 'CRP-' + RIGHT('000' + CAST(numbered_rows.row_num AS VARCHAR), 3)
        FROM numbered_rows
        WHERE cut_roll_production.id = numbered_rows.id
    """))
    
    # DispatchItem uses dispatched_at column
    connection.execute(sa.text("""
        WITH numbered_rows AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY dispatched_at) as row_num
            FROM dispatch_item
            WHERE frontend_id IS NULL
        )
        UPDATE dispatch_item
        SET frontend_id = 'DSI-' + RIGHT('000' + CAST(numbered_rows.row_num AS VARCHAR), 3)
        FROM numbered_rows
        WHERE dispatch_item.id = numbered_rows.id
    """))
    
    # Tables without datetime columns - use id for ordering
    tables_without_datetime = [
        ('plan_order_link', 'POL'),
        ('plan_inventory_link', 'PIL')
    ]
    
    for table_name, prefix in tables_without_datetime:
        connection.execute(sa.text(f"""
            WITH numbered_rows AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY id) as row_num
                FROM {table_name}
                WHERE frontend_id IS NULL
            )
            UPDATE {table_name}
            SET frontend_id = '{prefix}-' + RIGHT('000' + CAST(numbered_rows.row_num AS VARCHAR), 3)
            FROM numbered_rows
            WHERE {table_name}.id = numbered_rows.id
        """))
    
    # Year-based tables with created_at
    year_based_created_at = [
        ('order_master', 'ORD'),
        ('plan_master', 'PLN')
    ]
    
    for table_name, prefix in year_based_created_at:
        connection.execute(sa.text(f"""
            WITH numbered_rows AS (
                SELECT id, 
                       YEAR(created_at) as year_created,
                       ROW_NUMBER() OVER (PARTITION BY YEAR(created_at) ORDER BY created_at) as row_num
                FROM {table_name}
                WHERE frontend_id IS NULL
            )
            UPDATE {table_name}
            SET frontend_id = '{prefix}-' + CAST(numbered_rows.year_created AS VARCHAR) + '-' + RIGHT('000' + CAST(numbered_rows.row_num AS VARCHAR), 3)
            FROM numbered_rows
            WHERE {table_name}.id = numbered_rows.id
        """))
    
    # DispatchRecord uses dispatch_date for year-based numbering
    connection.execute(sa.text("""
        WITH numbered_rows AS (
            SELECT id, 
                   YEAR(dispatch_date) as year_created,
                   ROW_NUMBER() OVER (PARTITION BY YEAR(dispatch_date) ORDER BY dispatch_date) as row_num
            FROM dispatch_record
            WHERE frontend_id IS NULL
        )
        UPDATE dispatch_record
        SET frontend_id = 'DSP-' + CAST(numbered_rows.year_created AS VARCHAR) + '-' + RIGHT('000' + CAST(numbered_rows.row_num AS VARCHAR), 3)
        FROM numbered_rows
        WHERE dispatch_record.id = numbered_rows.id
    """))
    
    # Step 3: Create unique indexes after data is populated
    op.create_index(op.f('ix_client_master_frontend_id'), 'client_master', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_cut_roll_production_frontend_id'), 'cut_roll_production', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_dispatch_item_frontend_id'), 'dispatch_item', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_dispatch_record_frontend_id'), 'dispatch_record', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_inventory_master_frontend_id'), 'inventory_master', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_order_item_frontend_id'), 'order_item', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_order_master_frontend_id'), 'order_master', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_paper_master_frontend_id'), 'paper_master', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_pending_order_item_frontend_id'), 'pending_order_item', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_pending_order_master_frontend_id'), 'pending_order_master', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_plan_inventory_link_frontend_id'), 'plan_inventory_link', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_plan_master_frontend_id'), 'plan_master', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_plan_order_link_frontend_id'), 'plan_order_link', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_production_order_master_frontend_id'), 'production_order_master', ['frontend_id'], unique=True)
    op.create_index(op.f('ix_user_master_frontend_id'), 'user_master', ['frontend_id'], unique=True)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_user_master_frontend_id'), table_name='user_master')
    op.drop_column('user_master', 'frontend_id')
    op.drop_index(op.f('ix_production_order_master_frontend_id'), table_name='production_order_master')
    op.drop_column('production_order_master', 'frontend_id')
    op.drop_index(op.f('ix_plan_order_link_frontend_id'), table_name='plan_order_link')
    op.drop_column('plan_order_link', 'frontend_id')
    op.drop_index(op.f('ix_plan_master_frontend_id'), table_name='plan_master')
    op.drop_column('plan_master', 'frontend_id')
    op.drop_index(op.f('ix_plan_inventory_link_frontend_id'), table_name='plan_inventory_link')
    op.drop_column('plan_inventory_link', 'frontend_id')
    op.drop_index(op.f('ix_pending_order_master_frontend_id'), table_name='pending_order_master')
    op.drop_column('pending_order_master', 'frontend_id')
    op.drop_index(op.f('ix_pending_order_item_frontend_id'), table_name='pending_order_item')
    op.drop_column('pending_order_item', 'frontend_id')
    op.drop_index(op.f('ix_paper_master_frontend_id'), table_name='paper_master')
    op.drop_column('paper_master', 'frontend_id')
    op.drop_index(op.f('ix_order_master_frontend_id'), table_name='order_master')
    op.drop_column('order_master', 'frontend_id')
    op.drop_index(op.f('ix_order_item_frontend_id'), table_name='order_item')
    op.drop_column('order_item', 'frontend_id')
    op.drop_index(op.f('ix_inventory_master_frontend_id'), table_name='inventory_master')
    op.drop_column('inventory_master', 'frontend_id')
    op.drop_index(op.f('ix_dispatch_record_frontend_id'), table_name='dispatch_record')
    op.drop_column('dispatch_record', 'frontend_id')
    op.drop_index(op.f('ix_dispatch_item_frontend_id'), table_name='dispatch_item')
    op.drop_column('dispatch_item', 'frontend_id')
    op.drop_index(op.f('ix_cut_roll_production_frontend_id'), table_name='cut_roll_production')
    op.drop_column('cut_roll_production', 'frontend_id')
    op.drop_index(op.f('ix_client_master_frontend_id'), table_name='client_master')
    op.drop_column('client_master', 'frontend_id')
    # ### end Alembic commands ###
