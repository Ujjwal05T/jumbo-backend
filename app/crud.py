from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func
from . import models, schemas
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
from fastapi import HTTPException
import hashlib

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def hash_password(password: str) -> str:
    """Simple password hashing (for registration only, no authentication)"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_qr_code(roll_id: uuid.UUID) -> str:
    """Generate QR code for inventory items"""
    return f"ROLL_{str(roll_id).replace('-', '').upper()[:12]}"

# ============================================================================
# CLIENT MASTER CRUD
# ============================================================================

def create_client(db: Session, client: schemas.ClientMasterCreate) -> models.ClientMaster:
    """Create a new client in Client Master"""
    # Check if client with same company name already exists
    existing_client = db.query(models.ClientMaster).filter(
        models.ClientMaster.company_name == client.company_name,
        models.ClientMaster.status == "active"
    ).first()
    
    if existing_client:
        raise HTTPException(
            status_code=400,
            detail=f"Client with company name '{client.company_name}' already exists"
        )
    
    db_client = models.ClientMaster(
        company_name=client.company_name,
        email=client.email,
        address=client.address,
        contact_person=client.contact_person,
        phone=client.phone,
        created_by_id=client.created_by_id,
        status=client.status
    )
    
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client

def get_client(db: Session, client_id: uuid.UUID) -> Optional[models.ClientMaster]:
    """Get client by ID"""
    return db.query(models.ClientMaster).filter(models.ClientMaster.id == client_id).first()

def get_client_by_name(db: Session, company_name: str) -> Optional[models.ClientMaster]:
    """Get client by company name"""
    return db.query(models.ClientMaster).filter(
        models.ClientMaster.company_name == company_name,
        models.ClientMaster.status == "active"
    ).first()

def get_clients(db: Session, skip: int = 0, limit: int = 100, status: str = "active") -> List[models.ClientMaster]:
    """Get all clients with pagination"""
    query = db.query(models.ClientMaster)
    
    if status:
        query = query.filter(models.ClientMaster.status == status)
    
    return query.order_by(models.ClientMaster.company_name).offset(skip).limit(limit).all()

def update_client(db: Session, client_id: uuid.UUID, client_update: schemas.ClientMasterUpdate) -> Optional[models.ClientMaster]:
    """Update client information"""
    db_client = get_client(db, client_id)
    if not db_client:
        return None
    
    update_data = client_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_client, field, value)
    
    db.commit()
    db.refresh(db_client)
    return db_client

def delete_client(db: Session, client_id: uuid.UUID) -> bool:
    """Soft delete client (set status to inactive)"""
    db_client = get_client(db, client_id)
    if not db_client:
        return False
    
    # Check if client has active orders
    active_orders = db.query(models.OrderMaster).filter(
        models.OrderMaster.client_id == client_id,
        models.OrderMaster.status.in_(["pending", "processing", "partially_fulfilled"])
    ).count()
    
    if active_orders > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete client with {active_orders} active orders"
        )
    
    db_client.status = "inactive"
    db.commit()
    return True

# ============================================================================
# USER MASTER CRUD
# ============================================================================

def create_user(db: Session, user: schemas.UserMasterCreate) -> models.UserMaster:
    """Create a new user in User Master"""
    # Check if username already exists
    existing_user = db.query(models.UserMaster).filter(
        models.UserMaster.username == user.username
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail=f"Username '{user.username}' already exists"
        )
    
    db_user = models.UserMaster(
        name=user.name,
        username=user.username,
        password_hash=hash_password(user.password),
        role=user.role,
        contact=user.contact,
        department=user.department,
        status=user.status
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user(db: Session, user_id: uuid.UUID) -> Optional[models.UserMaster]:
    """Get user by ID"""
    return db.query(models.UserMaster).filter(models.UserMaster.id == user_id).first()

def get_user_by_username(db: Session, username: str) -> Optional[models.UserMaster]:
    """Get user by username"""
    return db.query(models.UserMaster).filter(
        models.UserMaster.username == username,
        models.UserMaster.status == "active"
    ).first()

def get_users(db: Session, skip: int = 0, limit: int = 100, role: str = None) -> List[models.UserMaster]:
    """Get all users with pagination and optional role filter"""
    query = db.query(models.UserMaster).filter(models.UserMaster.status == "active")
    
    if role:
        query = query.filter(models.UserMaster.role == role)
    
    return query.order_by(models.UserMaster.name).offset(skip).limit(limit).all()

def update_user(db: Session, user_id: uuid.UUID, user_update: schemas.UserMasterUpdate) -> Optional[models.UserMaster]:
    """Update user information"""
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    
    update_data = user_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_user, field, value)
    
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, username: str, password: str) -> Optional[models.UserMaster]:
    """Simple user authentication for registration system"""
    user = get_user_by_username(db, username)
    if not user or user.password_hash != hash_password(password):
        return None
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    return user

# ============================================================================
# PAPER MASTER CRUD
# ============================================================================

def create_paper(db: Session, paper: schemas.PaperMasterCreate) -> models.PaperMaster:
    """Create a new paper specification in Paper Master"""
    # Check if paper with same specifications already exists
    existing_paper = db.query(models.PaperMaster).filter(
        models.PaperMaster.gsm == paper.gsm,
        models.PaperMaster.bf == paper.bf,
        models.PaperMaster.shade == paper.shade,
        models.PaperMaster.type == paper.type,
        models.PaperMaster.status == "active"
    ).first()
    
    if existing_paper:
        raise HTTPException(
            status_code=400,
            detail=f"Paper specification already exists: {paper.name}"
        )
    
    db_paper = models.PaperMaster(
        name=paper.name,
        gsm=paper.gsm,
        bf=paper.bf,
        shade=paper.shade,
        thickness=paper.thickness,
        type=paper.type,
        created_by_id=paper.created_by_id,
        status=paper.status
    )
    
    db.add(db_paper)
    db.commit()
    db.refresh(db_paper)
    return db_paper

def get_paper(db: Session, paper_id: uuid.UUID) -> Optional[models.PaperMaster]:
    """Get paper by ID"""
    return db.query(models.PaperMaster).filter(models.PaperMaster.id == paper_id).first()

def get_paper_by_specs(db: Session, gsm: int, bf: float, shade: str, type: str = None) -> Optional[models.PaperMaster]:
    """Get paper by specifications"""
    query = db.query(models.PaperMaster).filter(
        models.PaperMaster.gsm == gsm,
        models.PaperMaster.bf == bf,
        models.PaperMaster.shade == shade,
        models.PaperMaster.status == "active"
    )
    
    if type:
        query = query.filter(models.PaperMaster.type == type)
    
    return query.first()

def get_papers(db: Session, skip: int = 0, limit: int = 100, status: str = "active") -> List[models.PaperMaster]:
    """Get all papers with pagination"""
    query = db.query(models.PaperMaster)
    
    if status:
        query = query.filter(models.PaperMaster.status == status)
    
    return query.order_by(models.PaperMaster.name).offset(skip).limit(limit).all()

def update_paper(db: Session, paper_id: uuid.UUID, paper_update: schemas.PaperMasterUpdate) -> Optional[models.PaperMaster]:
    """Update paper specification"""
    db_paper = get_paper(db, paper_id)
    if not db_paper:
        return None
    
    update_data = paper_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_paper, field, value)
    
    db.commit()
    db.refresh(db_paper)
    return db_paper

def delete_paper(db: Session, paper_id: uuid.UUID) -> bool:
    """Soft delete paper (set status to inactive)"""
    db_paper = get_paper(db, paper_id)
    if not db_paper:
        return False
    
    # Check if paper is used in active orders or inventory
    active_orders = db.query(models.OrderMaster).filter(
        models.OrderMaster.paper_id == paper_id,
        models.OrderMaster.status.in_(["pending", "processing", "partially_fulfilled"])
    ).count()
    
    active_inventory = db.query(models.InventoryMaster).filter(
        models.InventoryMaster.paper_id == paper_id,
        models.InventoryMaster.status == "available"
    ).count()
    
    if active_orders > 0 or active_inventory > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete paper specification with {active_orders} active orders and {active_inventory} inventory items"
        )
    
    db_paper.status = "inactive"
    db.commit()
    return True

# ============================================================================
# ORDER MASTER CRUD
# ============================================================================

def create_order(db: Session, order: schemas.OrderMasterCreate) -> models.OrderMaster:
    """Create a new order in Order Master with multiple order items"""
    # Validate client exists
    client = get_client(db, order.client_id)
    if not client or client.status != "active":
        raise HTTPException(status_code=400, detail="Invalid or inactive client")
    
    # Validate order items
    if not order.order_items or len(order.order_items) == 0:
        raise HTTPException(status_code=400, detail="Order must have at least one order item")
    
    # Validate each order item's paper exists
    for item in order.order_items:
        paper = get_paper(db, item.paper_id)
        if not paper or paper.status != "active":
            raise HTTPException(status_code=400, detail=f"Invalid or inactive paper specification for item with paper_id {item.paper_id}")
    
    # Create the order header
    db_order = models.OrderMaster(
        client_id=order.client_id,
        priority=order.priority,
        payment_type=order.payment_type,
        delivery_date=order.delivery_date,
        notes=order.notes,
        created_by_id=order.created_by_id
    )
    
    db.add(db_order)
    db.flush()  # Get the order ID before committing
    
    # Create order items
    for item in order.order_items:
        # Calculate missing values
        quantity_kg = item.quantity_kg
        quantity_rolls = item.quantity_rolls
        amount = item.amount
        
        if quantity_kg is None and quantity_rolls is not None:
            quantity_kg = models.OrderItem.calculate_quantity_kg(item.width_inches, quantity_rolls)
        elif quantity_rolls is None and quantity_kg is not None:
            quantity_rolls = models.OrderItem.calculate_quantity_rolls(item.width_inches, quantity_kg)
            
        if amount is None and quantity_kg is not None:
            amount = quantity_kg * item.rate
        
        db_order_item = models.OrderItem(
            order_id=db_order.id,
            paper_id=item.paper_id,
            width_inches=item.width_inches,
            quantity_rolls=quantity_rolls,
            quantity_kg=quantity_kg,
            rate=item.rate,
            amount=amount
        )
        db.add(db_order_item)
    
    db.commit()
    db.refresh(db_order)
    return db_order

def get_order(db: Session, order_id: uuid.UUID) -> Optional[models.OrderMaster]:
    """Get order by ID with related data including order items"""
    return db.query(models.OrderMaster).options(
        joinedload(models.OrderMaster.client),
        joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
    ).filter(models.OrderMaster.id == order_id).first()

def get_orders(db: Session, skip: int = 0, limit: int = 100, status: str = None, client_id: uuid.UUID = None) -> List[models.OrderMaster]:
    """Get all orders with pagination and filters including order items"""
    query = db.query(models.OrderMaster).options(
        joinedload(models.OrderMaster.client),
        joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
    )
    
    if status:
        query = query.filter(models.OrderMaster.status == status)
    if client_id:
        query = query.filter(models.OrderMaster.client_id == client_id)
    
    return query.order_by(models.OrderMaster.created_at.desc()).offset(skip).limit(limit).all()

def update_order(db: Session, order_id: uuid.UUID, order_update: schemas.OrderMasterUpdate) -> Optional[models.OrderMaster]:
    """Update order information"""
    db_order = get_order(db, order_id)
    if not db_order:
        return None
    
    update_data = order_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_order, field, value)
    
    db_order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_order)
    return db_order

def get_pending_orders(db: Session, paper_id: uuid.UUID = None) -> List[models.OrderMaster]:
    """Get orders that need fulfillment - Updated for order items"""
    query = db.query(models.OrderMaster).options(
        joinedload(models.OrderMaster.order_items)
    ).join(models.OrderItem).filter(
        models.OrderMaster.status.in_(["pending", "partially_fulfilled"]),
        models.OrderItem.quantity_fulfilled < models.OrderItem.quantity_rolls
    )
    
    if paper_id:
        query = query.filter(models.OrderMaster.paper_id == paper_id)
    
    return query.order_by(models.OrderMaster.priority.desc(), models.OrderMaster.created_at).all()

# ============================================================================
# ORDER ITEM CRUD
# ============================================================================

def create_order_item(db: Session, order_id: uuid.UUID, order_item: schemas.OrderItemCreate) -> models.OrderItem:
    """Create a new order item"""
    db_order_item = models.OrderItem(
        order_id=order_id,
        width_inches=order_item.width_inches,
        quantity_rolls=order_item.quantity_rolls
    )
    
    db.add(db_order_item)
    db.commit()
    db.refresh(db_order_item)
    return db_order_item

def get_order_item(db: Session, order_item_id: uuid.UUID) -> Optional[models.OrderItem]:
    """Get order item by ID"""
    return db.query(models.OrderItem).filter(models.OrderItem.id == order_item_id).first()

def update_order_item(db: Session, order_item_id: uuid.UUID, order_item_update: schemas.OrderItemUpdate) -> Optional[models.OrderItem]:
    """Update order item"""
    db_order_item = get_order_item(db, order_item_id)
    if not db_order_item:
        return None
    
    update_data = order_item_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_order_item, field, value)
    
    db.commit()
    db.refresh(db_order_item)
    return db_order_item

def delete_order_item(db: Session, order_item_id: uuid.UUID) -> bool:
    """Delete order item"""
    db_order_item = get_order_item(db, order_item_id)
    if not db_order_item:
        return False
    
    db.delete(db_order_item)
    db.commit()
    return True

# ============================================================================
# PENDING ORDER MASTER CRUD
# ============================================================================

def create_pending_order(db: Session, pending: schemas.PendingOrderMasterCreate) -> models.PendingOrderMaster:
    """Create a new pending order"""
    db_pending = models.PendingOrderMaster(
        order_id=pending.order_id,
        paper_id=pending.paper_id,
        width_inches=pending.width_inches,
        quantity_pending=pending.quantity_pending,
        reason=pending.reason
    )
    
    db.add(db_pending)
    db.commit()
    db.refresh(db_pending)
    return db_pending

def get_pending_order(db: Session, pending_id: uuid.UUID) -> Optional[models.PendingOrderMaster]:
    """Get pending order by ID"""
    return db.query(models.PendingOrderMaster).options(
        joinedload(models.PendingOrderMaster.original_order),
        joinedload(models.PendingOrderMaster.paper)
    ).filter(models.PendingOrderMaster.id == pending_id).first()

def get_pending_orders_list(db: Session, skip: int = 0, limit: int = 100, status: str = "pending") -> List[models.PendingOrderMaster]:
    """Get all pending orders with pagination"""
    query = db.query(models.PendingOrderMaster).options(
        joinedload(models.PendingOrderMaster.original_order),
        joinedload(models.PendingOrderMaster.paper)
    )
    
    if status:
        query = query.filter(models.PendingOrderMaster.status == status)
    
    return query.order_by(models.PendingOrderMaster.created_at).offset(skip).limit(limit).all()

def update_pending_order(db: Session, pending_id: uuid.UUID, pending_update: schemas.PendingOrderMasterUpdate) -> Optional[models.PendingOrderMaster]:
    """Update pending order"""
    db_pending = get_pending_order(db, pending_id)
    if not db_pending:
        return None
    
    update_data = pending_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_pending, field, value)
    
    if pending_update.status == "resolved":
        db_pending.resolved_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_pending)
    return db_pending

def get_pending_by_specification(db: Session, paper_id: uuid.UUID) -> List[models.PendingOrderMaster]:
    """Get pending orders by paper specification for consolidation"""
    return db.query(models.PendingOrderMaster).filter(
        models.PendingOrderMaster.paper_id == paper_id,
        models.PendingOrderMaster.status == "pending"
    ).all()

# ============================================================================
# INVENTORY MASTER CRUD
# ============================================================================

def create_inventory_item(db: Session, inventory: schemas.InventoryMasterCreate) -> models.InventoryMaster:
    """Create a new inventory item"""
    # Validate paper exists
    paper = get_paper(db, inventory.paper_id)
    if not paper or paper.status != "active":
        raise HTTPException(status_code=400, detail="Invalid or inactive paper specification")
    
    db_inventory = models.InventoryMaster(
        paper_id=inventory.paper_id,
        width_inches=inventory.width_inches,
        weight_kg=inventory.weight_kg,
        roll_type=inventory.roll_type,
        location=inventory.location,
        qr_code=inventory.qr_code or generate_qr_code(uuid.uuid4()),
        production_date=inventory.production_date,
        created_by_id=inventory.created_by_id
    )
    
    db.add(db_inventory)
    db.commit()
    db.refresh(db_inventory)
    return db_inventory

def get_inventory_item(db: Session, inventory_id: uuid.UUID) -> Optional[models.InventoryMaster]:
    """Get inventory item by ID"""
    return db.query(models.InventoryMaster).options(
        joinedload(models.InventoryMaster.paper)
    ).filter(models.InventoryMaster.id == inventory_id).first()

def get_inventory_items(db: Session, skip: int = 0, limit: int = 100, roll_type: str = None, status: str = "available") -> List[models.InventoryMaster]:
    """Get all inventory items with pagination and filters"""
    query = db.query(models.InventoryMaster).options(
        joinedload(models.InventoryMaster.paper)
    )
    
    if roll_type:
        query = query.filter(models.InventoryMaster.roll_type == roll_type)
    if status:
        query = query.filter(models.InventoryMaster.status == status)
    
    return query.order_by(models.InventoryMaster.created_at.desc()).offset(skip).limit(limit).all()

def update_inventory_item(db: Session, inventory_id: uuid.UUID, inventory_update: schemas.InventoryMasterUpdate) -> Optional[models.InventoryMaster]:
    """Update inventory item"""
    db_inventory = get_inventory_item(db, inventory_id)
    if not db_inventory:
        return None
    
    update_data = inventory_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_inventory, field, value)
    
    db.commit()
    db.refresh(db_inventory)
    return db_inventory

def get_available_inventory(db: Session, paper_id: uuid.UUID, width_inches: int = None, roll_type: str = None) -> List[models.InventoryMaster]:
    """Get available inventory for cutting optimization"""
    query = db.query(models.InventoryMaster).filter(
        models.InventoryMaster.paper_id == paper_id,
        models.InventoryMaster.status == "available"
    )
    
    if width_inches:
        query = query.filter(models.InventoryMaster.width_inches >= width_inches)
    if roll_type:
        query = query.filter(models.InventoryMaster.roll_type == roll_type)
    
    return query.order_by(models.InventoryMaster.width_inches.desc()).all()

# ============================================================================
# PLAN MASTER CRUD
# ============================================================================

def create_plan(db: Session, plan: schemas.PlanMasterCreate) -> models.PlanMaster:
    """Create a new cutting plan"""
    import json
    
    db_plan = models.PlanMaster(
        name=plan.name,
        cut_pattern=json.dumps(plan.cut_pattern),  # Serialize list to JSON string
        expected_waste_percentage=plan.expected_waste_percentage,
        created_by_id=plan.created_by_id
    )
    
    db.add(db_plan)
    db.flush()  # Get the ID
    
    # Create order links
    for order_id in plan.order_ids:
        order_link = models.PlanOrderLink(
            plan_id=db_plan.id,
            order_id=order_id,
            quantity_allocated=1  # This should be calculated based on the plan
        )
        db.add(order_link)
    
    # Create inventory links
    for inventory_id in plan.inventory_ids:
        inventory_link = models.PlanInventoryLink(
            plan_id=db_plan.id,
            inventory_id=inventory_id,
            quantity_used=1.0  # This should be calculated based on the plan
        )
        db.add(inventory_link)
    
    db.commit()
    db.refresh(db_plan)
    return db_plan

def get_plan(db: Session, plan_id: uuid.UUID) -> Optional[models.PlanMaster]:
    """Get plan by ID"""
    return db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_id).first()

def get_plans(db: Session, skip: int = 0, limit: int = 100, status: str = None) -> List[models.PlanMaster]:
    """Get all plans with pagination"""
    query = db.query(models.PlanMaster)
    
    if status:
        query = query.filter(models.PlanMaster.status == status)
    
    return query.order_by(models.PlanMaster.created_at.desc()).offset(skip).limit(limit).all()

def update_plan(db: Session, plan_id: uuid.UUID, plan_update: schemas.PlanMasterUpdate) -> Optional[models.PlanMaster]:
    """Update plan"""
    db_plan = get_plan(db, plan_id)
    if not db_plan:
        return None
    
    update_data = plan_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_plan, field, value)
    
    if plan_update.status == "completed":
        db_plan.completed_at = datetime.utcnow()
    elif plan_update.status == "in_progress" and not db_plan.executed_at:
        db_plan.executed_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_plan)
    return db_plan

# ============================================================================
# PRODUCTION ORDER MASTER CRUD
# ============================================================================

def create_production_order(db: Session, production: schemas.ProductionOrderMasterCreate) -> models.ProductionOrderMaster:
    """Create a new production order"""
    # Validate paper exists
    paper = get_paper(db, production.paper_id)
    if not paper or paper.status != "active":
        raise HTTPException(status_code=400, detail="Invalid or inactive paper specification")
    
    db_production = models.ProductionOrderMaster(
        paper_id=production.paper_id,
        quantity=production.quantity,
        priority=production.priority,
        created_by_id=production.created_by_id
    )
    
    db.add(db_production)
    db.commit()
    db.refresh(db_production)
    return db_production

def get_production_order(db: Session, production_id: uuid.UUID) -> Optional[models.ProductionOrderMaster]:
    """Get production order by ID"""
    return db.query(models.ProductionOrderMaster).options(
        joinedload(models.ProductionOrderMaster.paper)
    ).filter(models.ProductionOrderMaster.id == production_id).first()

def get_production_orders(db: Session, skip: int = 0, limit: int = 100, status: str = None) -> List[models.ProductionOrderMaster]:
    """Get all production orders with pagination"""
    query = db.query(models.ProductionOrderMaster).options(
        joinedload(models.ProductionOrderMaster.paper)
    )
    
    if status:
        query = query.filter(models.ProductionOrderMaster.status == status)
    
    return query.order_by(
        models.ProductionOrderMaster.priority.desc(),
        models.ProductionOrderMaster.created_at
    ).offset(skip).limit(limit).all()

def update_production_order(db: Session, production_id: uuid.UUID, production_update: schemas.ProductionOrderMasterUpdate) -> Optional[models.ProductionOrderMaster]:
    """Update production order"""
    db_production = get_production_order(db, production_id)
    if not db_production:
        return None
    
    update_data = production_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_production, field, value)
    
    if production_update.status == "completed":
        db_production.completed_at = datetime.utcnow()
    elif production_update.status == "in_progress" and not db_production.started_at:
        db_production.started_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_production)
    return db_production

def complete_production_order(db: Session, production_id: uuid.UUID, created_by_id: uuid.UUID) -> Dict[str, Any]:
    """Complete production order and create inventory items"""
    db_production = get_production_order(db, production_id)
    if not db_production:
        raise HTTPException(status_code=404, detail="Production order not found")
    
    if db_production.status != "in_progress":
        raise HTTPException(status_code=400, detail="Production order is not in progress")
    
    # Create inventory items for completed production
    inventory_items = []
    for _ in range(db_production.quantity):
        inventory_item = models.InventoryMaster(
            paper_id=db_production.paper_id,
            width_inches=118,  # Standard jumbo roll width
            weight_kg=4500.0,  # Standard jumbo roll weight
            roll_type="jumbo",
            status="available",
            qr_code=generate_qr_code(uuid.uuid4()),
            created_by_id=created_by_id
        )
        db.add(inventory_item)
        inventory_items.append(inventory_item)
    
    # Update production order status
    db_production.status = "completed"
    db_production.completed_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "production_order_id": str(db_production.id),
        "inventory_items_created": len(inventory_items),
        "inventory_item_ids": [str(item.id) for item in inventory_items]
    }

# ============================================================================
# LEGACY COMPATIBILITY FUNCTIONS
# ============================================================================


# ============================================================================
# NEW FLOW CRUD OPERATIONS - Support for 3-input/4-output optimization
# ============================================================================

def get_pending_orders_by_paper_specs(db: Session, paper_specs: List[Dict]) -> List[models.PendingOrderMaster]:
    """
    NEW FLOW: Get pending orders matching specific paper specifications.
    Used to gather pending orders for 3-input optimization.
    
    Args:
        db: Database session
        paper_specs: List of paper specifications (GSM, BF, Shade)
        
    Returns:
        List of pending orders matching the specifications
    """
    spec_conditions = []
    for spec in paper_specs:
        condition = and_(
            models.PaperMaster.gsm == spec.get('gsm'),
            models.PaperMaster.bf == spec.get('bf'),
            models.PaperMaster.shade == spec.get('shade')
        )
        spec_conditions.append(condition)
    
    if not spec_conditions:
        return []
    
    return db.query(models.PendingOrderMaster).join(
        models.PaperMaster
    ).filter(
        models.PendingOrderMaster.status == "pending",
        or_(*spec_conditions)
    ).options(
        joinedload(models.PendingOrderMaster.paper),
        joinedload(models.PendingOrderMaster.original_order)
    ).all()

def get_available_inventory_by_paper_specs(
    db: Session, 
    paper_specs: List[Dict],
    width_range: tuple = (20, 25)
) -> List[models.InventoryMaster]:
    """
    NEW FLOW: Get available inventory (20-25" waste rolls) matching paper specifications.
    Used to gather available inventory for 3-input optimization.
    
    Args:
        db: Database session
        paper_specs: List of paper specifications (GSM, BF, Shade)
        width_range: Width range for waste rolls (default: 20-25")
        
    Returns:
        List of available inventory items in the specified width range
    """
    spec_conditions = []
    for spec in paper_specs:
        condition = and_(
            models.PaperMaster.gsm == spec.get('gsm'),
            models.PaperMaster.bf == spec.get('bf'),
            models.PaperMaster.shade == spec.get('shade')
        )
        spec_conditions.append(condition)
    
    if not spec_conditions:
        return []
    
    min_width, max_width = width_range
    
    return db.query(models.InventoryMaster).join(
        models.PaperMaster
    ).filter(
        models.InventoryMaster.status == "available",
        models.InventoryMaster.roll_type == "cut",
        models.InventoryMaster.width_inches >= min_width,
        models.InventoryMaster.width_inches <= max_width,
        or_(*spec_conditions)
    ).options(
        joinedload(models.InventoryMaster.paper)
    ).all()

def create_inventory_from_waste(
    db: Session, 
    waste_items: List[Dict], 
    created_by_id: uuid.UUID
) -> List[models.InventoryMaster]:
    """
    NEW FLOW: Create inventory items from waste rolls (20-25" range).
    Used to convert optimization output waste into reusable inventory.
    
    Args:
        db: Database session
        waste_items: List of waste item dictionaries from optimization
        created_by_id: ID of user creating the inventory
        
    Returns:
        List of created inventory items
    """
    created_items = []
    
    for waste_item in waste_items:
        # Find or create paper master
        paper = get_paper_by_specs(
            db,
            gsm=waste_item['gsm'],
            bf=waste_item['bf'],
            shade=waste_item['shade']
        )
        
        if not paper:
            # Create paper master if it doesn't exist
            paper_data = type('PaperCreate', (), {
                'name': f"{waste_item['shade']} {waste_item['gsm']}GSM BF{waste_item['bf']}",
                'gsm': waste_item['gsm'],
                'bf': waste_item['bf'],
                'shade': waste_item['shade'],
                'type': 'standard',
                'created_by_id': created_by_id
            })()
            paper = create_paper(db, paper_data)
        
        # Create inventory item
        inventory_item = models.InventoryMaster(
            paper_id=paper.id,
            width_inches=int(waste_item['width']),
            weight_kg=100.0,  # Estimated weight for waste rolls
            roll_type="cut",
            location="waste_storage",
            status="available",
            qr_code=generate_qr_code(uuid.uuid4()),
            created_by_id=created_by_id
        )
        
        db.add(inventory_item)
        created_items.append(inventory_item)
    
    db.flush()  # Get IDs
    return created_items

def bulk_create_pending_orders(
    db: Session, 
    pending_items: List[Dict], 
    original_order_ids: List[uuid.UUID]
) -> List[models.PendingOrderMaster]:
    """
    NEW FLOW: Create multiple pending orders from optimization output.
    Used to convert optimization pending orders into database records.
    
    Args:
        db: Database session
        pending_items: List of pending order dictionaries from optimization
        original_order_ids: List of original order IDs that generated these pending orders
        
    Returns:
        List of created pending order records
    """
    created_pending = []
    
    for pending_item in pending_items:
        # Find paper master
        paper = get_paper_by_specs(
            db,
            gsm=pending_item['gsm'],
            bf=pending_item['bf'],
            shade=pending_item['shade']
        )
        
        if not paper:
            continue  # Skip if paper doesn't exist
        
        # Find matching original order (simplified - takes first match)
        original_order_id = original_order_ids[0] if original_order_ids else None
        
        pending_order = models.PendingOrderMaster(
            order_id=original_order_id,
            paper_id=paper.id,
            width_inches=int(pending_item['width']),
            quantity_pending=pending_item['quantity'],
            reason=pending_item.get('reason', 'optimization_pending'),
            status="pending"
        )
        
        db.add(pending_order)
        created_pending.append(pending_order)
    
    db.flush()  # Get IDs
    
    # Reload with relationships
    if created_pending:
        pending_ids = [po.id for po in created_pending]
        return db.query(models.PendingOrderMaster).options(
            joinedload(models.PendingOrderMaster.paper)
        ).filter(models.PendingOrderMaster.id.in_(pending_ids)).all()
    
    return created_pending

def cleanup_fulfilled_pending_orders(db: Session, order_ids: List[uuid.UUID]) -> int:
    """
    NEW FLOW: Clean up pending orders when original orders are fulfilled.
    Used to maintain data consistency when orders are completed.
    
    Args:
        db: Database session
        order_ids: List of order IDs that have been fulfilled
        
    Returns:
        Number of pending orders cleaned up
    """
    cleanup_count = db.query(models.PendingOrderMaster).filter(
        models.PendingOrderMaster.order_id.in_(order_ids),
        models.PendingOrderMaster.status == "pending"
    ).update(
        {"status": "resolved", "resolved_at": datetime.utcnow()},
        synchronize_session=False
    )
    
    return cleanup_count

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
        models.OrderMaster.status.in_(["pending", "processing", "partially_fulfilled"])
    ).all()
    
    order_requirements = []
    for order in orders:
        # Process each order item (different paper specs/widths)
        for item in order.order_items:
            if item.paper:
                remaining_qty = item.quantity_rolls - (item.quantity_fulfilled or 0)
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
                        'paper_id': str(item.paper.id)
                    })
    
    return order_requirements

# ============================================================================
# BULK OPERATIONS - Helper methods for linking orders/inventory to plans
# ============================================================================

def bulk_link_orders_to_plan(
    db: Session, 
    plan_id: uuid.UUID, 
    order_links: List[Dict[str, Any]]
) -> List[models.PlanOrderLink]:
    """
    Bulk link multiple orders to a plan with specified quantities.
    
    Args:
        db: Database session
        plan_id: ID of the plan to link orders to
        order_links: List of dicts with 'order_id' and 'quantity_allocated'
        
    Returns:
        List of created PlanOrderLink objects
        
    Example:
        order_links = [
            {'order_id': uuid1, 'quantity_allocated': 5},
            {'order_id': uuid2, 'quantity_allocated': 3}
        ]
    """
    # Verify plan exists
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    created_links = []
    
    for link_data in order_links:
        order_id = link_data.get('order_id')
        quantity_allocated = link_data.get('quantity_allocated', 1)
        
        # Verify order exists
        order = get_order(db, order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Check if link already exists
        existing_link = db.query(models.PlanOrderLink).filter(
            models.PlanOrderLink.plan_id == plan_id,
            models.PlanOrderLink.order_id == order_id
        ).first()
        
        if existing_link:
            # Update existing link
            existing_link.quantity_allocated = quantity_allocated
            created_links.append(existing_link)
        else:
            # Create new link
            order_link = models.PlanOrderLink(
                plan_id=plan_id,
                order_id=order_id,
                quantity_allocated=quantity_allocated
            )
            db.add(order_link)
            created_links.append(order_link)
    
    db.commit()
    
    # Refresh all objects to get updated data
    for link in created_links:
        db.refresh(link)
    
    return created_links

def bulk_link_inventory_to_plan(
    db: Session, 
    plan_id: uuid.UUID, 
    inventory_links: List[Dict[str, Any]]
) -> List[models.PlanInventoryLink]:
    """
    Bulk link multiple inventory items to a plan with specified quantities used.
    
    Args:
        db: Database session
        plan_id: ID of the plan to link inventory to
        inventory_links: List of dicts with 'inventory_id' and 'quantity_used'
        
    Returns:
        List of created PlanInventoryLink objects
        
    Example:
        inventory_links = [
            {'inventory_id': uuid1, 'quantity_used': 100.5},
            {'inventory_id': uuid2, 'quantity_used': 250.0}
        ]
    """
    # Verify plan exists
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    created_links = []
    
    for link_data in inventory_links:
        inventory_id = link_data.get('inventory_id')
        quantity_used = link_data.get('quantity_used', 0.0)
        
        # Verify inventory item exists
        inventory_item = get_inventory_item(db, inventory_id)
        if not inventory_item:
            raise HTTPException(status_code=404, detail=f"Inventory item {inventory_id} not found")
        
        # Check if link already exists
        existing_link = db.query(models.PlanInventoryLink).filter(
            models.PlanInventoryLink.plan_id == plan_id,
            models.PlanInventoryLink.inventory_id == inventory_id
        ).first()
        
        if existing_link:
            # Update existing link
            existing_link.quantity_used = quantity_used
            created_links.append(existing_link)
        else:
            # Create new link
            inventory_link = models.PlanInventoryLink(
                plan_id=plan_id,
                inventory_id=inventory_id,
                quantity_used=quantity_used
            )
            db.add(inventory_link)
            created_links.append(inventory_link)
    
    db.commit()
    
    # Refresh all objects to get updated data
    for link in created_links:
        db.refresh(link)
    
    return created_links

def bulk_unlink_orders_from_plan(
    db: Session, 
    plan_id: uuid.UUID, 
    order_ids: List[uuid.UUID]
) -> int:
    """
    Bulk remove order links from a plan.
    
    Args:
        db: Database session
        plan_id: ID of the plan to remove order links from
        order_ids: List of order IDs to unlink
        
    Returns:
        Number of links removed
    """
    # Verify plan exists
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Remove links
    deleted_count = db.query(models.PlanOrderLink).filter(
        models.PlanOrderLink.plan_id == plan_id,
        models.PlanOrderLink.order_id.in_(order_ids)
    ).delete(synchronize_session=False)
    
    db.commit()
    return deleted_count

def bulk_unlink_inventory_from_plan(
    db: Session, 
    plan_id: uuid.UUID, 
    inventory_ids: List[uuid.UUID]
) -> int:
    """
    Bulk remove inventory links from a plan.
    
    Args:
        db: Database session
        plan_id: ID of the plan to remove inventory links from
        inventory_ids: List of inventory IDs to unlink
        
    Returns:
        Number of links removed
    """
    # Verify plan exists
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Remove links
    deleted_count = db.query(models.PlanInventoryLink).filter(
        models.PlanInventoryLink.plan_id == plan_id,
        models.PlanInventoryLink.inventory_id.in_(inventory_ids)
    ).delete(synchronize_session=False)
    
    db.commit()
    return deleted_count

def get_plan_with_all_links(db: Session, plan_id: uuid.UUID) -> Optional[models.PlanMaster]:
    """
    Get a plan with all its order and inventory links loaded.
    
    Args:
        db: Database session
        plan_id: ID of the plan to retrieve
        
    Returns:
        PlanMaster object with all relationships loaded, or None if not found
    """
    return db.query(models.PlanMaster).options(
        joinedload(models.PlanMaster.plan_orders).joinedload(models.PlanOrderLink.order),
        joinedload(models.PlanMaster.plan_inventory).joinedload(models.PlanInventoryLink.inventory),
        joinedload(models.PlanMaster.created_by)
    ).filter(models.PlanMaster.id == plan_id).first()

def get_plan_order_links(
    db: Session, 
    plan_id: uuid.UUID
) -> List[models.PlanOrderLink]:
    """
    Get all order links for a specific plan with order details.
    
    Args:
        db: Database session
        plan_id: ID of the plan
        
    Returns:
        List of PlanOrderLink objects with order details loaded
    """
    return db.query(models.PlanOrderLink).options(
        joinedload(models.PlanOrderLink.order).joinedload(models.OrderMaster.client),
        joinedload(models.PlanOrderLink.order).joinedload(models.OrderMaster.paper)
    ).filter(models.PlanOrderLink.plan_id == plan_id).all()

def get_plan_inventory_links(
    db: Session, 
    plan_id: uuid.UUID
) -> List[models.PlanInventoryLink]:
    """
    Get all inventory links for a specific plan with inventory details.
    
    Args:
        db: Database session
        plan_id: ID of the plan
        
    Returns:
        List of PlanInventoryLink objects with inventory details loaded
    """
    return db.query(models.PlanInventoryLink).options(
        joinedload(models.PlanInventoryLink.inventory).joinedload(models.InventoryMaster.paper)
    ).filter(models.PlanInventoryLink.plan_id == plan_id).all()

def bulk_update_order_fulfillment(
    db: Session, 
    order_updates: List[Dict[str, Any]]
) -> List[models.OrderMaster]:
    """
    Bulk update order fulfillment quantities.
    
    Args:
        db: Database session
        order_updates: List of dicts with 'order_id' and 'quantity_fulfilled'
        
    Returns:
        List of updated OrderMaster objects
        
    Example:
        order_updates = [
            {'order_id': uuid1, 'quantity_fulfilled': 5},
            {'order_id': uuid2, 'quantity_fulfilled': 3}
        ]
    """
    updated_orders = []
    
    for update_data in order_updates:
        order_id = update_data.get('order_id')
        quantity_fulfilled = update_data.get('quantity_fulfilled', 0)
        
        # Get order
        order = get_order(db, order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Update fulfillment quantity
        order.quantity_fulfilled = quantity_fulfilled
        
        # Update status based on fulfillment
        if quantity_fulfilled >= order.quantity:
            order.status = schemas.OrderStatus.COMPLETED.value
        elif quantity_fulfilled > 0:
            order.status = schemas.OrderStatus.PARTIALLY_FULFILLED.value
        else:
            order.status = schemas.OrderStatus.PENDING.value
        
        order.updated_at = datetime.utcnow()
        updated_orders.append(order)
    
    db.commit()
    
    # Refresh all objects
    for order in updated_orders:
        db.refresh(order)
    
    return updated_orders

def bulk_update_inventory_status(
    db: Session, 
    inventory_updates: List[Dict[str, Any]]
) -> List[models.InventoryMaster]:
    """
    Bulk update inventory item statuses.
    
    Args:
        db: Database session
        inventory_updates: List of dicts with 'inventory_id' and 'status'
        
    Returns:
        List of updated InventoryMaster objects
        
    Example:
        inventory_updates = [
            {'inventory_id': uuid1, 'status': 'used'},
            {'inventory_id': uuid2, 'status': 'reserved'}
        ]
    """
    valid_statuses = [status.value for status in schemas.InventoryStatus]
    updated_items = []
    
    for update_data in inventory_updates:
        inventory_id = update_data.get('inventory_id')
        status = update_data.get('status')
        
        # Validate status
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid status '{status}'. Must be one of: {valid_statuses}"
            )
        
        # Get inventory item
        inventory_item = get_inventory_item(db, inventory_id)
        if not inventory_item:
            raise HTTPException(status_code=404, detail=f"Inventory item {inventory_id} not found")
        
        # Update status
        inventory_item.status = status
        inventory_item.updated_at = datetime.utcnow()
        updated_items.append(inventory_item)
    
    db.commit()
    
    # Refresh all objects
    for item in updated_items:
        db.refresh(item)
    
    return updated_items

def get_orders_by_plan(db: Session, plan_id: uuid.UUID) -> List[models.OrderMaster]:
    """
    Get all orders linked to a specific plan.
    
    Args:
        db: Database session
        plan_id: ID of the plan
        
    Returns:
        List of OrderMaster objects linked to the plan
    """
    return db.query(models.OrderMaster).join(
        models.PlanOrderLink
    ).filter(
        models.PlanOrderLink.plan_id == plan_id
    ).options(
        joinedload(models.OrderMaster.client),
        joinedload(models.OrderMaster.paper),
        joinedload(models.OrderMaster.created_by)
    ).all()

def get_inventory_by_plan(db: Session, plan_id: uuid.UUID) -> List[models.InventoryMaster]:
    """
    Get all inventory items linked to a specific plan.
    
    Args:
        db: Database session
        plan_id: ID of the plan
        
    Returns:
        List of InventoryMaster objects linked to the plan
    """
    return db.query(models.InventoryMaster).join(
        models.PlanInventoryLink
    ).filter(
        models.PlanInventoryLink.plan_id == plan_id
    ).options(
        joinedload(models.InventoryMaster.paper),
        joinedload(models.InventoryMaster.created_by)
    ).all()

def create_plan_with_links(
    db: Session, 
    plan_data: schemas.PlanMasterCreate,
    order_links: Optional[List[Dict[str, Any]]] = None,
    inventory_links: Optional[List[Dict[str, Any]]] = None
) -> models.PlanMaster:
    """
    Create a plan and link orders/inventory in a single transaction.
    
    Args:
        db: Database session
        plan_data: Plan creation data
        order_links: Optional list of order links to create
        inventory_links: Optional list of inventory links to create
        
    Returns:
        Created PlanMaster object with all links
    """
    try:
        # Create the plan first
        plan = create_plan(db, plan_data)
        
        # Link orders if provided
        if order_links:
            bulk_link_orders_to_plan(db, plan.id, order_links)
        
        # Link inventory if provided
        if inventory_links:
            bulk_link_inventory_to_plan(db, plan.id, inventory_links)
        
        # Return plan with all links loaded
        return get_plan_with_all_links(db, plan.id)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating plan with links: {str(e)}")

def get_plan_summary(db: Session, plan_id: uuid.UUID) -> Dict[str, Any]:
    """
    Get a comprehensive summary of a plan including all linked data.
    
    Args:
        db: Database session
        plan_id: ID of the plan
        
    Returns:
        Dictionary with plan summary information
    """
    plan = get_plan_with_all_links(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Get linked orders and inventory
    orders = get_orders_by_plan(db, plan_id)
    inventory_items = get_inventory_by_plan(db, plan_id)
    
    # Calculate summary statistics
    total_orders = len(orders)
    total_quantity = sum(order.quantity for order in orders)
    total_fulfilled = sum(order.quantity_fulfilled or 0 for order in orders)
    total_inventory_items = len(inventory_items)
    
    return {
        "plan": {
            "id": str(plan.id),
            "name": plan.name,
            "status": plan.status,
            "expected_waste_percentage": float(plan.expected_waste_percentage),
            "actual_waste_percentage": float(plan.actual_waste_percentage) if plan.actual_waste_percentage else None,
            "created_at": plan.created_at,
            "created_by": plan.created_by.name if plan.created_by else None
        },
        "orders": {
            "total_count": total_orders,
            "total_quantity": total_quantity,
            "total_fulfilled": total_fulfilled,
            "fulfillment_percentage": (total_fulfilled / total_quantity * 100) if total_quantity > 0 else 0,
            "orders": [
                {
                    "id": str(order.id),
                    "width": order.width,
                    "quantity": order.quantity,
                    "quantity_fulfilled": order.quantity_fulfilled or 0,
                    "status": order.status,
                    "client_name": order.client.name if order.client else None,
                    "paper_specs": {
                        "gsm": order.paper.gsm,
                        "bf": order.paper.bf,
                        "shade": order.paper.shade
                    } if order.paper else None
                }
                for order in orders
            ]
        },
        "inventory": {
            "total_items": total_inventory_items,
            "items": [
                {
                    "id": str(item.id),
                    "roll_type": item.roll_type,
                    "width": item.width,
                    "length": item.length,
                    "weight": item.weight,
                    "status": item.status,
                    "paper_specs": {
                        "gsm": item.paper.gsm,
                        "bf": item.paper.bf,
                        "shade": item.paper.shade
                    } if item.paper else None
                }
                for item in inventory_items
            ]
        }
    }

# ============================================================================
# CUT ROLL PRODUCTION CRUD
# ============================================================================

def generate_cut_roll_qr_code(cut_roll_id: uuid.UUID, width: float, gsm: int) -> str:
    """Generate unique QR code for cut roll production"""
    # Format: CR_<width>_<gsm>_<short_id>
    short_id = str(cut_roll_id).replace('-', '').upper()[:8]
    return f"CR_{int(width)}_{gsm}_{short_id}"

def create_cut_roll_production(
    db: Session, 
    cut_roll: schemas.CutRollProductionCreate
) -> models.CutRollProduction:
    """Create a new cut roll production record"""
    # Generate unique QR code
    qr_code = generate_cut_roll_qr_code(uuid.uuid4(), cut_roll.width_inches, cut_roll.gsm)
    
    # Check if QR code already exists (should be very rare)
    existing_qr = db.query(models.CutRollProduction).filter(
        models.CutRollProduction.qr_code == qr_code
    ).first()
    
    if existing_qr:
        # Add timestamp to make it unique
        qr_code = f"{qr_code}_{int(datetime.utcnow().timestamp())}"
    
    db_cut_roll = models.CutRollProduction(
        qr_code=qr_code,
        width_inches=cut_roll.width_inches,
        length_meters=cut_roll.length_meters,
        actual_weight_kg=cut_roll.actual_weight_kg,
        paper_id=cut_roll.paper_id,
        gsm=cut_roll.gsm,
        bf=cut_roll.bf,
        shade=cut_roll.shade,
        plan_id=cut_roll.plan_id,
        order_id=cut_roll.order_id,
        client_id=cut_roll.client_id,
        status=cut_roll.status,
        individual_roll_number=cut_roll.individual_roll_number,
        trim_left=cut_roll.trim_left,
        created_by_id=cut_roll.created_by_id
    )
    
    db.add(db_cut_roll)
    db.commit()
    db.refresh(db_cut_roll)
    return db_cut_roll

def get_cut_roll_production(db: Session, cut_roll_id: uuid.UUID) -> Optional[models.CutRollProduction]:
    """Get cut roll production by ID"""
    return db.query(models.CutRollProduction).filter(
        models.CutRollProduction.id == cut_roll_id
    ).first()

def get_cut_roll_production_by_qr(db: Session, qr_code: str) -> Optional[models.CutRollProduction]:
    """Get cut roll production by QR code"""
    return db.query(models.CutRollProduction).options(
        joinedload(models.CutRollProduction.paper),
        joinedload(models.CutRollProduction.client),
        joinedload(models.CutRollProduction.order),
        joinedload(models.CutRollProduction.created_by),
        joinedload(models.CutRollProduction.weight_recorded_by)
    ).filter(models.CutRollProduction.qr_code == qr_code).first()

def get_cut_rolls_by_plan(
    db: Session, 
    plan_id: uuid.UUID, 
    status: Optional[str] = None
) -> List[models.CutRollProduction]:
    """Get all cut rolls for a specific plan"""
    query = db.query(models.CutRollProduction).options(
        joinedload(models.CutRollProduction.paper),
        joinedload(models.CutRollProduction.client),
        joinedload(models.CutRollProduction.order)
    ).filter(models.CutRollProduction.plan_id == plan_id)
    
    if status:
        query = query.filter(models.CutRollProduction.status == status)
    
    return query.all()

def update_cut_roll_production(
    db: Session, 
    cut_roll_id: uuid.UUID, 
    cut_roll_update: schemas.CutRollProductionUpdate
) -> Optional[models.CutRollProduction]:
    """Update cut roll production record"""
    db_cut_roll = db.query(models.CutRollProduction).filter(
        models.CutRollProduction.id == cut_roll_id
    ).first()
    
    if not db_cut_roll:
        return None
    
    update_data = cut_roll_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_cut_roll, field, value)
    
    db.commit()
    db.refresh(db_cut_roll)
    return db_cut_roll

def update_cut_roll_weight_by_qr(
    db: Session, 
    qr_code: str, 
    weight_data: schemas.WeightUpdateRequest
) -> Optional[models.CutRollProduction]:
    """Update cut roll weight via QR code scan"""
    db_cut_roll = db.query(models.CutRollProduction).filter(
        models.CutRollProduction.qr_code == qr_code
    ).first()
    
    if not db_cut_roll:
        return None
    
    db_cut_roll.actual_weight_kg = weight_data.actual_weight_kg
    db_cut_roll.weight_recorded_at = datetime.utcnow()
    db_cut_roll.weight_recorded_by_id = weight_data.updated_by_id
    
    # Auto-update status if needed
    if db_cut_roll.status == "selected":
        db_cut_roll.status = "in_production"
        db_cut_roll.production_started_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_cut_roll)
    return db_cut_roll

def select_cut_rolls_for_production(
    db: Session,
    selection_request: schemas.CutRollSelectionRequest
) -> List[models.CutRollProduction]:
    """Select cut rolls for production from plan generation results"""
    created_cut_rolls = []
    
    # Check if plan exists, if not create a temporary one
    plan_id_to_use = selection_request.plan_id
    existing_plan = get_plan(db, selection_request.plan_id)
    
    if not existing_plan:
        # Extract order IDs from cut roll selections to satisfy schema validation
        order_ids_from_selections = []
        for cut_roll_data in selection_request.cut_roll_selections:
            order_id = cut_roll_data.get('order_id')
            if order_id and order_id not in order_ids_from_selections:
                if isinstance(order_id, str):
                    order_ids_from_selections.append(uuid.UUID(order_id))
                else:
                    order_ids_from_selections.append(order_id)
        
        # If no order IDs found, use a dummy UUID to satisfy validation
        if not order_ids_from_selections:
            order_ids_from_selections = [uuid.uuid4()]
        
        # Create a temporary plan for production tracking
        temp_plan_create = schemas.PlanMasterCreate(
            name=f"Production Plan {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            cut_pattern=[],  # Empty list instead of dict
            expected_waste_percentage=5.0,  # Default value
            created_by_id=selection_request.created_by_id,
            order_ids=order_ids_from_selections
        )
        
        # Override the plan_id to use our provided one
        temp_plan = models.PlanMaster(
            id=selection_request.plan_id,
            name=temp_plan_create.name,
            cut_pattern=temp_plan_create.cut_pattern,
            expected_waste_percentage=temp_plan_create.expected_waste_percentage,
            status="planned",
            created_by_id=temp_plan_create.created_by_id,
            created_at=datetime.utcnow()
        )
        
        db.add(temp_plan)
        db.commit()
        db.refresh(temp_plan)
    
    for cut_roll_data in selection_request.cut_roll_selections:
        # Get or find paper_id if not provided
        paper_id = cut_roll_data.get('paper_id')
        if not paper_id:
            # Look up paper by specifications
            paper = get_paper_by_specs(
                db=db,
                gsm=cut_roll_data['gsm'],
                bf=cut_roll_data['bf'],
                shade=cut_roll_data['shade']
            )
            if paper:
                paper_id = paper.id
            else:
                # Skip this cut roll if paper not found
                continue
        else:
            # Convert string UUID to UUID object if needed
            if isinstance(paper_id, str):
                paper_id = uuid.UUID(paper_id)
        
        # Create cut roll production record
        cut_roll_create = schemas.CutRollProductionCreate(
            width_inches=cut_roll_data['width'],
            gsm=cut_roll_data['gsm'],
            bf=cut_roll_data['bf'],
            shade=cut_roll_data['shade'],
            paper_id=paper_id,
            plan_id=plan_id_to_use,
            order_id=uuid.UUID(cut_roll_data['order_id']) if cut_roll_data.get('order_id') else None,
            client_id=uuid.UUID(cut_roll_data['client_id']) if cut_roll_data.get('client_id') else None,
            individual_roll_number=cut_roll_data.get('individual_roll_number'),
            trim_left=cut_roll_data.get('trim_left'),
            created_by_id=selection_request.created_by_id
        )
        
        db_cut_roll = create_cut_roll_production(db, cut_roll_create)
        created_cut_rolls.append(db_cut_roll)
    
    # Update plan status to in_progress if cut rolls were created
    if created_cut_rolls:
        plan_update = schemas.PlanMasterUpdate(status="in_progress")
        update_plan(db, selection_request.plan_id, plan_update)
    
    return created_cut_rolls

def get_cut_roll_production_summary(db: Session, plan_id: uuid.UUID) -> Dict[str, Any]:
    """Get summary of cut roll production for a plan"""
    cut_rolls = get_cut_rolls_by_plan(db, plan_id)
    
    status_counts = {}
    total_weight = 0
    total_rolls = len(cut_rolls)
    
    for roll in cut_rolls:
        status = roll.status
        status_counts[status] = status_counts.get(status, 0) + 1
        if roll.actual_weight_kg:
            total_weight += float(roll.actual_weight_kg)
    
    # Calculate jumbo roll sets needed
    individual_rolls_count = len([r for r in cut_rolls if r.status in ['selected', 'in_production', 'completed']])
    jumbo_sets_needed = (individual_rolls_count + 2) // 3  # Round up division
    
    return {
        "plan_id": str(plan_id),
        "total_cut_rolls": total_rolls,
        "status_breakdown": status_counts,
        "total_weight_kg": round(total_weight, 2),
        "individual_118_rolls": individual_rolls_count,
        "jumbo_roll_sets_needed": jumbo_sets_needed,
        "cut_rolls": [
            {
                "id": str(roll.id),
                "qr_code": roll.qr_code,
                "width_inches": float(roll.width_inches),
                "status": roll.status,
                "actual_weight_kg": float(roll.actual_weight_kg) if roll.actual_weight_kg else None,
                "gsm": roll.gsm,
                "shade": roll.shade
            }
            for roll in cut_rolls
        ]
    }