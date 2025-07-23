from sqlalchemy.orm import Session
from sqlalchemy import or_
from . import models, schemas
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
from fastapi import HTTPException

# User CRUD operations
def get_user(db: Session, user_id: uuid.UUID):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def create_user(db: Session, user: schemas.UserCreate):
    # Check if user already exists
    db_user = get_user_by_username(db, username=user.username)
    if db_user:
        return None  # User already exists
    
    # Create new user with plain text password
    db_user = models.User(
        username=user.username,
        password=user.password,  # Storing plain text password
        created_at=datetime.utcnow()
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, username: str, password: str):
    user = get_user_by_username(db, username=username)
    if not user or user.password != password:  # Simple plain text comparison
        return None
    return user

# Parsed message CRUD operations
def create_parsed_message(db: Session, message: schemas.ParsedMessageCreate):
    db_message = models.ParsedMessage(**message.dict())
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_parsed_message(db: Session, message_id: uuid.UUID):
    return db.query(models.ParsedMessage).filter(models.ParsedMessage.id == message_id).first()

def update_parsed_message(db: Session, message_id: uuid.UUID, update: schemas.ParsedMessageUpdate):
    db_message = db.query(models.ParsedMessage).filter(models.ParsedMessage.id == message_id).first()
    if db_message:
        update_data = update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_message, field, value)
        db.commit()
        db.refresh(db_message)
    return db_message

def get_parsed_messages(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.ParsedMessage).offset(skip).limit(limit).all()

# Order CRUD operations
def create_order(db: Session, order: schemas.OrderCreate):
    # Validate order specifications
    if not all([order.width_inches, order.gsm, order.bf, order.shade, order.quantity_rolls]):
        raise HTTPException(
            status_code=400,
            detail="Missing required order specifications"
        )
    
    # Check if we have matching inventory
    matching_inventory = find_matching_inventory(
        db=db,
        width_inches=order.width_inches,
        gsm=order.gsm,
        bf=order.bf,
        shade=order.shade,
        quantity=order.quantity_rolls
    )
    
    if len(matching_inventory) < order.quantity_rolls:
        # Not enough in inventory, check if we can cut from jumbo rolls
        jumbo_roll = find_matching_jumbo_roll(
            db=db,
            gsm=order.gsm,
            bf=order.bf,
            shade=order.shade,
            min_width_inches=order.width_inches * order.quantity_rolls  # Total width needed
        )
        
        if not jumbo_roll:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient inventory. Need {order.quantity_rolls} rolls of "
                    f"{order.width_inches}\" (W) x {order.gsm} GSM x {order.bf} BF {order.shade}"
                )
            )
    
    # If we get here, we either have enough inventory or can cut from jumbo roll
    db_order = models.Order(
        customer_name=order.customer_name,
        width_inches=order.width_inches,
        gsm=order.gsm,
        bf=order.bf,
        shade=order.shade,
        quantity_rolls=order.quantity_rolls,
        status="pending",
        source_message_id=getattr(order, 'source_message_id', None)
    )
    
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order
def get_orders(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Order).order_by(models.Order.id).offset(skip).limit(limit).all()

def get_order(db: Session, order_id: uuid.UUID):
    return db.query(models.Order).filter(models.Order.id == order_id).first()

def update_order(db: Session, order_id: uuid.UUID, order_update: schemas.OrderUpdate):
    db_order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not db_order:
        return None
    
    update_data = order_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_order, field, value)
    
    db.commit()
    db.refresh(db_order)
    return db_order

def delete_order(db: Session, order_id: uuid.UUID):
    db_order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not db_order:
        return False
    
    # Check if the order has any cut rolls
    if db_order.cut_rolls:
        # Instead of deleting, mark as cancelled
        db_order.status = 'cancelled'
        db.commit()
        return True
    else:
        # No cut rolls, safe to delete
        db.delete(db_order)
        db.commit()
        return True

# Jumbo roll CRUD operations
def create_jumbo_roll(db: Session, roll: schemas.JumboRollCreate):
    db_roll = models.JumboRoll(**roll.dict())
    db.add(db_roll)
    db.commit()
    db.refresh(db_roll)
    return db_roll

def get_jumbo_rolls(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.JumboRoll).offset(skip).limit(limit).all()

def get_jumbo_roll(db: Session, roll_id: uuid.UUID):
    return db.query(models.JumboRoll).filter(models.JumboRoll.id == roll_id).first()

# Cut roll CRUD operations
def create_cut_roll(db: Session, roll: schemas.CutRollCreate):
    db_roll = models.CutRoll(**roll.dict())
    db.add(db_roll)
    db.commit()
    db.refresh(db_roll)
    return db_roll

def get_cut_rolls(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.CutRoll).offset(skip).limit(limit).all()

def get_cut_roll(db: Session, roll_id: uuid.UUID):
    return db.query(models.CutRoll).filter(models.CutRoll.id == roll_id).first()

def update_cut_roll(db: Session, roll_id: uuid.UUID, update: schemas.CutRollUpdate):
    db_roll = db.query(models.CutRoll).filter(models.CutRoll.id == roll_id).first()
    if db_roll:
        update_data = update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_roll, field, value)
        db.commit()
        db.refresh(db_roll)
    return db_roll

# Inventory CRUD operations
def create_inventory_item(db: Session, item: schemas.InventoryItemCreate):
    db_item = models.InventoryItem(**item.dict())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

def get_inventory_items(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.InventoryItem).offset(skip).limit(limit).all()

def update_inventory_item(db: Session, item_id: uuid.UUID, update: schemas.InventoryItemUpdate):
    db_item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item_id).first()
    if db_item:
        update_data = update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_item, field, value)
        db_item.last_updated = datetime.utcnow()
        db.commit()
        db.refresh(db_item)
    return db_item

# Cutting plan CRUD operations
def create_cutting_plan(db: Session, plan: schemas.CuttingPlanCreate):
    db_plan = models.CuttingPlan(**plan.dict())
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan

def get_cutting_plans(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.CuttingPlan).offset(skip).limit(limit).all()

def update_cutting_plan(db: Session, plan_id: uuid.UUID, update: schemas.CuttingPlanUpdate):
    db_plan = db.query(models.CuttingPlan).filter(models.CuttingPlan.id == plan_id).first()
    if db_plan:
        update_data = update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_plan, field, value)
        db.commit()
        db.refresh(db_plan)
    return db_plan

def get_order_with_details(db: Session, order_id: uuid.UUID):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    
    if not order:
        return None
    
    # Load relationships
    if order.source_message_id:
        db.query(models.ParsedMessage).filter(models.ParsedMessage.id == order.source_message_id).first()
    
    db.query(models.CutRoll).filter(models.CutRoll.order_id == order.id).all()
    
    return order

def find_matching_inventory(db: Session, width_inches: int, gsm: int, bf: float, shade: str, quantity: int = 1):
    return db.query(models.InventoryItem).join(models.CutRoll).filter(
        or_(
            models.CutRoll.width_inches == width_inches,
            models.CutRoll.gsm == gsm,
            models.CutRoll.bf == bf,
            models.CutRoll.shade == shade,
            models.CutRoll.status == "weighed",
            models.InventoryItem.allocated_to_order.is_(None)
        )
    ).limit(quantity).all()

def generate_qr_code(roll_id: uuid.UUID) -> str:
    return f"ROLL_{str(roll_id).replace('-', '').upper()[:12]}"

def get_order_with_inventory(db: Session, order_id: uuid.UUID):
    """Get an order with its associated inventory items"""
    return db.query(models.Order).\
        options(joinedload(models.Order.cut_rolls)).\
        filter(models.Order.id == order_id).\
        first()

def update_order_delivery(
    db: Session,
    order_id: uuid.UUID,
    delivery_update: schemas.OrderDeliveryUpdate,
    user_id: Optional[uuid.UUID] = None
):
    """
    Update order delivery status and handle inventory changes
    
    Args:
        db: Database session
        order_id: ID of the order to update
        delivery_update: Delivery update data
        user_id: Optional user ID making the change (None if unauthenticated)
        
    Returns:
        Updated order object
        
    Raises:
        HTTPException: If order not found, invalid status transition, or over-delivery detected
    """
    db_order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Validate status transition
    valid_transitions = {
        "processing": ["ready_for_delivery"],
        "ready_for_delivery": ["in_transit", "cancelled"],
        "in_transit": ["delivered", "cancelled"],
    }
    
    current_status = db_order.status.lower()
    new_status = delivery_update.status.lower()
    
    if current_status == new_status:
        return db_order
        
    if current_status in valid_transitions and new_status not in valid_transitions[current_status]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from {current_status} to {new_status}"
        )
    
    # Check for over-delivery when marking as delivered
    if new_status == "delivered":
        # Get total ordered quantity
        ordered_quantity = db_order.quantity_rolls
        
        # Get already delivered quantity from cut rolls
        delivered_quantity = sum(
            1 for roll in db_order.cut_rolls 
            if roll.status == "delivered"
        )
        
        # Get current delivery quantity (non-delivered cut rolls)
        current_delivery = sum(
            1 for roll in db_order.cut_rolls 
            if roll.status != "delivered"
        )
        
        # Calculate remaining quantity that can be delivered
        remaining_quantity = ordered_quantity - delivered_quantity
        
        if current_delivery > remaining_quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot deliver {current_delivery} rolls. "
                    f"Order quantity: {ordered_quantity}, "
                    f"Already delivered: {delivered_quantity}, "
                    f"Remaining: {remaining_quantity}"
                )
            )
    
    try:
        # Update order status
        previous_status = db_order.status
        db_order.status = new_status
        
        if new_status == "delivered":
            db_order.actual_delivery_date = delivery_update.actual_delivery_date or datetime.utcnow()
            if delivery_update.delivery_notes:
                db_order.delivery_notes = delivery_update.delivery_notes
        
        # Handle inventory changes
        if new_status == "delivered":
            # Update all cut rolls to delivered
            for cut_roll in db_order.cut_rolls:
                if cut_roll.status != "delivered":  # Only process undelivered rolls
                    # Log the inventory change
                    log = models.InventoryLog(
                        roll_id=cut_roll.id,
                        order_id=order_id,
                        action="delivered",
                        previous_status=cut_roll.status,
                        new_status="delivered",
                        notes=f"Order {order_id} marked as delivered" + 
                              (f" by user {user_id}" if user_id else ""),
                        created_by_id=user_id
                    )
                    db.add(log)
                    
                    # Update cut roll status
                    cut_roll.status = "delivered"
                    
                    # Remove from inventory
                    if cut_roll.inventory_item:
                        db.delete(cut_roll.inventory_item)
        
        db.commit()
        db.refresh(db_order)
        return db_order
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

def log_inventory_change(
    db: Session,
    roll_id: uuid.UUID,
    action: str,
    new_status: str,
    user_id: uuid.UUID,
    order_id: Optional[uuid.UUID] = None,
    previous_status: Optional[str] = None,
    notes: Optional[str] = None
) -> models.InventoryLog:
    """
    Log an inventory change with proper validation
    
    Args:
        db: Database session
        roll_id: ID of the cut roll
        action: Action performed (e.g., 'created', 'allocated', 'delivered')
        new_status: New status of the roll
        user_id: ID of the user performing the action
        order_id: Optional associated order ID
        previous_status: Optional previous status
        notes: Optional notes about the change
    """
    log = models.InventoryLog(
        roll_id=roll_id,
        order_id=order_id,
        action=action,
        previous_status=previous_status,
        new_status=new_status,
        notes=notes,
        created_by_id=user_id
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log

def get_inventory_logs(
    db: Session,
    roll_id: Optional[uuid.UUID] = None,
    order_id: Optional[uuid.UUID] = None,
    skip: int = 0,
    limit: int = 100
) -> List[models.InventoryLog]:
    """
    Get inventory logs with optional filtering
    
    Args:
        db: Database session
        roll_id: Optional filter by roll ID
        order_id: Optional filter by order ID
        skip: Number of records to skip
        limit: Maximum number of records to return
        
    Returns:
        List of inventory log entries
    """
    query = db.query(models.InventoryLog)
    
    if roll_id is not None:
        query = query.filter(models.InventoryLog.roll_id == roll_id)
    if order_id is not None:
        query = query.filter(models.InventoryLog.order_id == order_id)
    
    return query.order_by(models.InventoryLog.created_at.desc())\
                .offset(skip)\
                .limit(limit)\
                .all()

def find_matching_inventory(
    db: Session, 
    width_inches: int, 
    gsm: int, 
    bf: float, 
    shade: str, 
    quantity: int = 1
):
    """
    Find available cut rolls that match the specified criteria.
    
    Args:
        db: Database session
        width_inches: Required roll width in inches
        gsm: Required GSM value
        bf: Required Brightness Factor
        shade: Required shade/color
        quantity: Number of matching rolls needed
        
    Returns:
        List of matching InventoryItem objects
    """
    return db.query(models.InventoryItem).join(models.CutRoll).filter(
        models.CutRoll.width_inches == width_inches,
        models.CutRoll.gsm == gsm,
        models.CutRoll.bf == bf,
        models.CutRoll.shade == shade,
        models.CutRoll.status == "available",
        models.InventoryItem.allocated_to_order.is_(None)
    ).limit(quantity).all()

def find_matching_jumbo_roll(
    db: Session,
    gsm: int,
    bf: float,
    shade: str,
    min_width_inches: int = 0   
    ):
    """
    Find a jumbo roll that can be used to cut the required specifications.
    
    Args:
        db: Database session
        gsm: Required GSM value
        bf: Required Brightness Factor
        shade: Required shade/color
        min_width_inches: Total width needed for all cuts
        
    Returns:
        JumboRoll object if found, None otherwise
    """
    return db.query(models.JumboRoll).filter(
        models.JumboRoll.gsm == gsm,
        models.JumboRoll.bf == bf,
        models.JumboRoll.shade == shade,
        models.JumboRoll.status == "available",
        models.JumboRoll.width_inches >= min_width_inches
    ).order_by(models.JumboRoll.width_inches).first()  # Use smallest suitable roll first

def cut_jumbo_roll(
    db: Session,
    jumbo_roll_id: uuid.UUID,
    order_id: uuid.UUID,
    cut_widths: List[int],  # List of widths to cut
    user_id: Optional[uuid.UUID] = None
):
    """
    Cut a jumbo roll into smaller rolls and update inventory.
    
    Args:
        db: Database session
        jumbo_roll_id: ID of the jumbo roll to cut
        order_id: ID of the order being fulfilled
        cut_widths: List of widths to cut (in inches)
        user_id: Optional user ID performing the action
    """
    jumbo_roll = db.query(models.JumboRoll).filter(
        models.JumboRoll.id == jumbo_roll_id,
        models.JumboRoll.status == "available"
    ).first()
    
    if not jumbo_roll:
        raise HTTPException(status_code=404, detail="Jumbo roll not found or not available")
    
    total_cut_width = sum(cut_widths)
    if total_cut_width > jumbo_roll.width_inches:
        raise HTTPException(
            status_code=400,
            detail=f"Total cut width ({total_cut_width}\") exceeds jumbo roll width ({jumbo_roll.width_inches}\")"
        )
    
    try:
        # Mark jumbo roll as being cut
        jumbo_roll.status = "cutting"
        db.add(jumbo_roll)
        
        # Create cut rolls
        cut_rolls = []
        for width in cut_widths:
            cut_roll = models.CutRoll(
                jumbo_roll_id=jumbo_roll.id,
                width_inches=width,
                gsm=jumbo_roll.gsm,
                bf=jumbo_roll.bf,
                shade=jumbo_roll.shade,
                status="cut",  # Will be updated to weighed after weighing
                order_id=order_id,
                created_by_id=user_id
            )
            db.add(cut_roll)
            cut_rolls.append(cut_roll)
        
        # Update jumbo roll status
        if total_cut_width == jumbo_roll.width_inches:
            jumbo_roll.status = "used"  # Fully used
        else:
            jumbo_roll.status = "partial"  # Partially used
            # Optionally create a new jumbo roll with remaining width
            remaining_width = jumbo_roll.width_inches - total_cut_width
            if remaining_width >= 36:  # Minimum useful width
                new_jumbo = models.JumboRoll(
                    width_inches=remaining_width,
                    gsm=jumbo_roll.gsm,
                    bf=jumbo_roll.bf,
                    shade=jumbo_roll.shade,
                    weight_kg=int(jumbo_roll.weight_kg * (remaining_width / jumbo_roll.width_inches)),
                    production_date=datetime.utcnow(),
                    status="available",
                    created_by_id=user_id
                )
                db.add(new_jumbo)
        
        db.commit()
        return cut_rolls
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))