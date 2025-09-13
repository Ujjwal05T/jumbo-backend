

"""
Main CRUD module that imports from split CRUD files
"""

# Database session dependency
from typing import List, Dict, Any, Optional
import uuid
from sqlalchemy.orm import Session, joinedload
from . import models
from .database import get_db

# Import from new split CRUD files
from .crud.clients import client
from .crud.users import user as user_crud
from .crud.papers import paper
from .crud.orders import order, order_item
from .crud.inventory import inventory
from .crud.plans import plan
from .crud.pending_orders import pending_order
from .crud import material_management

# Import individual functions for backward compatibility
def create_client(db, client_data):
    return client.create_client(db=db, client=client_data)

def get_clients(db, skip=0, limit=100, status="active"):
    return client.get_clients(db=db, skip=skip, limit=limit, status=status)

def get_client(db, client_id):
    return client.get_client(db=db, client_id=client_id)

def update_client(db, client_id, client_update):
    return client.update_client(db=db, client_id=client_id, client_update=client_update)

def delete_client(db, client_id):
    return client.delete_client(db=db, client_id=client_id)

def get_users(db, skip=0, limit=100, role=None, status="active"):
    return user_crud.get_users(db=db, skip=skip, limit=limit, role=role, status=status)

def get_user(db, user_id):
    return user_crud.get_user(db=db, user_id=user_id)

def update_user(db, user_id, user_update):
    return user_crud.update_user(db=db, user_id=user_id, user_update=user_update)

def create_user(db, user_data):
    return user_crud.create_user(db=db, user=user_data)

def get_user_by_username(db, username):
    return user_crud.get_user_by_username(db=db, username=username)

def login_user(db, username, password):
    return user_crud.authenticate_user(db=db, username=username, password=password)

def create_paper(db, paper_data):
    return paper.create_paper(db=db, paper=paper_data)

def get_papers(db, skip=0, limit=100, status="active"):
    return paper.get_papers(db=db, skip=skip, limit=limit, status=status)

def get_paper(db, paper_id):
    return paper.get_paper(db=db, paper_id=paper_id)

def get_paper_by_specs(db, gsm, bf, shade):
    return paper.get_paper_by_specs(db=db, gsm=gsm, bf=bf, shade=shade)

def update_paper(db, paper_id, paper_update):
    return paper.update_paper(db=db, paper_id=paper_id, paper_update=paper_update)

def delete_paper(db, paper_id):
    return paper.delete_paper(db=db, paper_id=paper_id)

def debug_paper_validation(db):
    return paper.debug_paper_validation(db=db)

def create_order_with_items(db, order_data):
    return order.create_order_with_items(db=db, order_data=order_data)

def get_orders(db, skip=0, limit=100, status=None, client_id=None):
    return order.get_orders(db=db, skip=skip, limit=limit, status=status, client_id=client_id)

def get_order(db, order_id):
    return order.get_order(db=db, order_id=order_id)

def update_order(db, order_id, order_update):
    return order.update_order(db=db, order_id=order_id, order_update=order_update)

def update_order_with_items(db, order_id, order_update):
    return order.update_order_with_items(db=db, order_id=order_id, order_update=order_update)

def delete_order(db, order_id):
    return order.delete_order(db=db, order_id=order_id)

def get_order_items(db, order_id):
    return order_item.get_order_items(db=db, order_id=order_id)

def get_order_item(db, item_id):
    return order_item.get_order_item(db=db, item_id=item_id)

def create_inventory_item(db, inventory_data):
    return inventory.create_inventory_item(db=db, inventory=inventory_data)

def get_inventory_items(db, skip=0, limit=100, roll_type=None, status="available"):
    return inventory.get_inventory_items(db=db, skip=skip, limit=limit, roll_type=roll_type, status=status)

def get_inventory_item(db, inventory_id):
    return inventory.get_inventory_item(db=db, inventory_id=inventory_id)

def get_inventory_by_type(db, roll_type, skip=0, limit=100, status="available"):
    return inventory.get_inventory_by_type(db=db, roll_type=roll_type, skip=skip, limit=limit, status=status)

def get_available_inventory_by_paper(db, paper_id, roll_type=None):
    return inventory.get_available_inventory_by_paper(db=db, paper_id=paper_id, roll_type=roll_type)

def get_available_inventory_by_paper_specs(db, paper_specs):
    return inventory.get_available_inventory_by_paper_specs(db=db, paper_specs=paper_specs)

def create_inventory_from_waste(db, waste_items, user_id):
    return inventory.create_inventory_from_waste(db=db, waste_items=waste_items, user_id=user_id)

def update_inventory_status(db, inventory_id, new_status):
    return inventory.update_inventory_status(db=db, inventory_id=inventory_id, new_status=new_status)

def create_plan(db, plan_data):
    return plan.create_plan(db=db, plan=plan_data)

def get_plans(db, skip=0, limit=100, status=None):
    return plan.get_plans(db=db, skip=skip, limit=limit, status=status)

def get_plan(db, plan_id):
    return plan.get_plan(db=db, plan_id=plan_id)

def update_plan_status(db, plan_id, new_status):
    return plan.update_plan_status(db=db, plan_id=plan_id, new_status=new_status)

def execute_plan(db, plan_id):
    return plan.execute_plan(db=db, plan_id=plan_id)

def complete_plan(db, plan_id):
    return plan.complete_plan(db=db, plan_id=plan_id)

def start_production_for_plan(db, plan_id, request_data):
    return plan.start_production_for_plan(db=db, plan_id=plan_id, request_data=request_data)

def start_production_from_pending_orders(db, request_data):
    from .crud.pending_orders import start_production_from_pending_orders_impl  # ✅ RENAMED FUNCTION
    return start_production_from_pending_orders_impl(db=db, request_data=request_data)

def create_pending_order_item(db, pending_data):
    return pending_order.create_pending_order_item(db=db, pending=pending_data)

def get_pending_order_items(db, skip=0, limit=100, status="pending"):
    return pending_order.get_pending_order_items(db=db, skip=skip, limit=limit, status=status)

def get_pending_orders_by_specs(db, paper_specs):
    return pending_order.get_pending_orders_by_specs(db=db, paper_specs=paper_specs)

# ============================================================================
# MATERIAL MANAGEMENT CRUD FUNCTIONS
# ============================================================================

# Material Master functions
def create_material(db, material_data):
    return material_management.create_material(db=db, material=material_data)

def get_materials(db, skip=0, limit=100):
    return material_management.get_materials(db=db, skip=skip, limit=limit)

def get_material(db, material_id):
    return material_management.get_material(db=db, material_id=material_id)

def update_material(db, material_id, material_update):
    return material_management.update_material(db=db, material_id=material_id, material_update=material_update)

def delete_material(db, material_id):
    return material_management.delete_material(db=db, material_id=material_id)

# Inward Challan functions
def create_inward_challan(db, challan_data):
    return material_management.create_inward_challan(db=db, challan=challan_data)

def get_inward_challans(db, skip=0, limit=100, material_id=None):
    return material_management.get_inward_challans(db=db, skip=skip, limit=limit, material_id=material_id)

def get_inward_challan(db, challan_id):
    return material_management.get_inward_challan(db=db, challan_id=challan_id)

def update_inward_challan(db, challan_id, challan_update):
    return material_management.update_inward_challan(db=db, challan_id=challan_id, challan_update=challan_update)

def delete_inward_challan(db, challan_id):
    return material_management.delete_inward_challan(db=db, challan_id=challan_id)

# Outward Challan functions
def create_outward_challan(db, challan_data):
    return material_management.create_outward_challan(db=db, challan=challan_data)

def get_outward_challans(db, skip=0, limit=100):
    return material_management.get_outward_challans(db=db, skip=skip, limit=limit)

def get_outward_challan(db, challan_id):
    return material_management.get_outward_challan(db=db, challan_id=challan_id)

def update_outward_challan(db, challan_id, challan_update):
    return material_management.update_outward_challan(db=db, challan_id=challan_id, challan_update=challan_update)

def delete_outward_challan(db, challan_id):
    return material_management.delete_outward_challan(db=db, challan_id=challan_id)

def get_pending_items_summary(db):
    return pending_order.get_pending_items_summary(db=db)

def get_consolidation_opportunities(db):
    return pending_order.get_consolidation_opportunities(db=db)

def bulk_create_pending_orders(db, pending_orders, user_id):
    return pending_order.create_pending_items_from_optimization(db=db, pending_orders=pending_orders, user_id=user_id)

def debug_pending_items(db):
    return pending_order.debug_pending_items(db=db)

def get_orders_with_paper_specs(db: Session, order_ids: List[uuid.UUID]) -> List[Dict]:
    """
    NEW FLOW: Get orders with their paper specifications for optimization input.
    Used to prepare order data for 3-input optimization.
    
    Args:
        db: Database session
        order_ids: List of order IDs to fetch
        
    Returns:
        List of orders formatted for optimization input
    """
    orders = db.query(models.OrderMaster).options(
        joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper),
        joinedload(models.OrderMaster.client)
    ).filter(
        models.OrderMaster.id.in_(order_ids),
        models.OrderMaster.status.in_(["created", "in_process"])
    ).all()
    
    order_requirements = []
    for order in orders:
        # Process each order item (different paper specs/widths)
        for item in order.order_items:
            if item.paper:
                remaining_qty = item.remaining_to_plan  # Use property that excludes quantity_in_pending
                if remaining_qty > 0:
                    order_requirements.append({
                        'order_id': str(order.id),
                        'order_item_id': str(item.id),
                        'width': float(item.width_inches),
                        'quantity': remaining_qty,
                        'gsm': item.paper.gsm,
                        'bf': float(item.paper.bf),
                        'shade': item.paper.shade,
                        'min_length': 1600,  # Default since OrderItem doesn't have min_length
                        'client_name': order.client.company_name if order.client else 'Unknown',
                        'client_id': str(order.client.id) if order.client else None,
                        'paper_id': str(item.paper.id),
                        'source_type': 'regular_order',           # FIX: Add source type for consistency
                        'source_order_id': str(order.id),        # FIX: Add source order ID
                        'source_pending_id': None                # FIX: Regular orders don't have pending ID
                    })
    
    return order_requirements


