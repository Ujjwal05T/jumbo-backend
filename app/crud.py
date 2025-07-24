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
    """Create a new order in Order Master"""
    # Validate client exists
    client = get_client(db, order.client_id)
    if not client or client.status != "active":
        raise HTTPException(status_code=400, detail="Invalid or inactive client")
    
    # Validate paper exists
    paper = get_paper(db, order.paper_id)
    if not paper or paper.status != "active":
        raise HTTPException(status_code=400, detail="Invalid or inactive paper specification")
    
    db_order = models.OrderMaster(
        client_id=order.client_id,
        paper_id=order.paper_id,
        width_inches=order.width_inches,
        quantity_rolls=order.quantity_rolls,
        priority=order.priority,
        delivery_date=order.delivery_date,
        notes=order.notes,
        created_by_id=order.created_by_id
    )
    
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order

def get_order(db: Session, order_id: uuid.UUID) -> Optional[models.OrderMaster]:
    """Get order by ID with related data"""
    return db.query(models.OrderMaster).options(
        joinedload(models.OrderMaster.client),
        joinedload(models.OrderMaster.paper)
    ).filter(models.OrderMaster.id == order_id).first()

def get_orders(db: Session, skip: int = 0, limit: int = 100, status: str = None, client_id: uuid.UUID = None) -> List[models.OrderMaster]:
    """Get all orders with pagination and filters"""
    query = db.query(models.OrderMaster).options(
        joinedload(models.OrderMaster.client),
        joinedload(models.OrderMaster.paper)
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
    """Get orders that need fulfillment"""
    query = db.query(models.OrderMaster).filter(
        models.OrderMaster.status.in_(["pending", "partially_fulfilled"]),
        models.OrderMaster.quantity_fulfilled < models.OrderMaster.quantity_rolls
    )
    
    if paper_id:
        query = query.filter(models.OrderMaster.paper_id == paper_id)
    
    return query.order_by(models.OrderMaster.priority.desc(), models.OrderMaster.created_at).all()

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
    db_plan = models.PlanMaster(
        name=plan.name,
        cut_pattern=plan.cut_pattern,
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

def create_order_legacy(db: Session, order: schemas.OrderCreate) -> models.OrderMaster:
    """Legacy order creation - converts to master-based format"""
    # Try to find or create client
    client = get_client_by_name(db, order.customer_name)
    if not client:
        # Create a default user for system operations
        system_user = get_user_by_username(db, "system")
        if not system_user:
            system_user = create_user(db, schemas.UserMasterCreate(
                name="System User",
                username="system",
                password="system123",
                role="admin"
            ))
        
        # Create new client
        client = create_client(db, schemas.ClientMasterCreate(
            company_name=order.customer_name,
            created_by_id=system_user.id
        ))
    
    # Try to find or create paper specification
    paper = get_paper_by_specs(db, order.gsm, order.bf, order.shade)
    if not paper:
        paper = create_paper(db, schemas.PaperMasterCreate(
            name=f"{order.shade} {order.gsm}GSM BF{order.bf}",
            gsm=order.gsm,
            bf=order.bf,
            shade=order.shade,
            created_by_id=client.created_by_id
        ))
    
    # Create order using master-based format
    return create_order(db, schemas.OrderMasterCreate(
        client_id=client.id,
        paper_id=paper.id,
        width_inches=order.width_inches,
        quantity_rolls=order.quantity_rolls,
        created_by_id=client.created_by_id
    ))