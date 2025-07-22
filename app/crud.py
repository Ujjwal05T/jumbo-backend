from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from . import models, schemas
from datetime import datetime
from uuid import UUID
from typing import Optional, List
import uuid
import qrcode
from io import BytesIO
import base64

# User CRUD operations
def get_user(db: Session, user_id: UUID):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def create_user(db: Session, user: schemas.UserCreate):
    # In production, you'd hash the password here
    db_user = models.User(
        username=user.username, 
        password=user.password,  # Store plain text for now as per requirements
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user_last_login(db: Session, user_id: UUID):
    db_user = get_user(db, user_id)
    if db_user:
        db_user.last_login = datetime.utcnow()
        db.commit()
        db.refresh(db_user)
    return db_user

# WhatsApp message CRUD operations
def create_whatsapp_message(db: Session, message: schemas.WhatsAppMessageCreate, created_by: Optional[UUID] = None):
    db_message = models.WhatsAppMessage(
        raw_message=message.raw_message,
        sender=message.sender,
        created_by=created_by
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def update_whatsapp_message_parsing(db: Session, message_id: UUID, update: schemas.WhatsAppMessageUpdate):
    db_message = db.query(models.WhatsAppMessage).filter(models.WhatsAppMessage.id == message_id).first()
    if db_message:
        if update.parsed_json is not None:
            db_message.parsed_json = update.parsed_json
        if update.parsing_confidence is not None:
            db_message.parsing_confidence = update.parsing_confidence
        if update.parsing_status is not None:
            db_message.parsing_status = update.parsing_status
        db.commit()
        db.refresh(db_message)
    return db_message

def get_whatsapp_messages(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.WhatsAppMessage).offset(skip).limit(limit).all()

# Order CRUD operations
def get_order(db: Session, order_id: UUID):
    return db.query(models.Order).filter(models.Order.id == order_id).first()

def get_orders(db: Session, skip: int = 0, limit: int = 100, filters: Optional[schemas.OrderFilter] = None):
    query = db.query(models.Order)
    
    if filters:
        if filters.customer_name:
            query = query.filter(models.Order.customer_name.ilike(f"%{filters.customer_name}%"))
        if filters.status:
            query = query.filter(models.Order.status == filters.status)
        if filters.width_inches:
            query = query.filter(models.Order.width_inches == filters.width_inches)
        if filters.gsm:
            query = query.filter(models.Order.gsm == filters.gsm)
        if filters.bf:
            query = query.filter(models.Order.bf == filters.bf)
        if filters.shade:
            query = query.filter(models.Order.shade.ilike(f"%{filters.shade}%"))
        if filters.date_from:
            query = query.filter(models.Order.created_at >= filters.date_from)
        if filters.date_to:
            query = query.filter(models.Order.created_at <= filters.date_to)
    
    return query.offset(skip).limit(limit).all()

def create_order(db: Session, order: schemas.OrderCreate, created_by: Optional[UUID] = None):
    db_order = models.Order(
        customer_name=order.customer_name,
        width_inches=order.width_inches,
        gsm=order.gsm,
        bf=order.bf,
        shade=order.shade,
        quantity_rolls=order.quantity_rolls,
        quantity_tons=order.quantity_tons,
        source_message_id=order.source_message_id,
        created_by=created_by
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order

def update_order(db: Session, order_id: UUID, update: schemas.OrderUpdate):
    db_order = get_order(db, order_id)
    if db_order:
        if update.status is not None:
            db_order.status = update.status
        if update.quantity_rolls is not None:
            db_order.quantity_rolls = update.quantity_rolls
        if update.quantity_tons is not None:
            db_order.quantity_tons = update.quantity_tons
        db_order.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_order)
    return db_order

# Jumbo roll CRUD operations
def get_jumbo_roll(db: Session, roll_id: UUID):
    return db.query(models.JumboRoll).filter(models.JumboRoll.id == roll_id).first()

def get_jumbo_rolls(db: Session, skip: int = 0, limit: int = 100, status: Optional[str] = None):
    query = db.query(models.JumboRoll)
    if status:
        query = query.filter(models.JumboRoll.status == status)
    return query.offset(skip).limit(limit).all()

def create_jumbo_roll(db: Session, roll: schemas.JumboRollCreate, created_by: Optional[UUID] = None):
    db_roll = models.JumboRoll(
        width_inches=roll.width_inches,
        weight_kg=roll.weight_kg,
        gsm=roll.gsm,
        bf=roll.bf,
        shade=roll.shade,
        production_date=roll.production_date,
        created_by=created_by
    )
    db.add(db_roll)
    db.commit()
    db.refresh(db_roll)
    return db_roll

def update_jumbo_roll_status(db: Session, roll_id: UUID, status: str):
    db_roll = get_jumbo_roll(db, roll_id)
    if db_roll:
        db_roll.status = status
        db.commit()
        db.refresh(db_roll)
    return db_roll

# Cut roll CRUD operations
def generate_qr_code(roll_id: UUID) -> str:
    """Generate a unique QR code string for a roll"""
    return f"ROLL_{str(roll_id).replace('-', '').upper()[:12]}"

def create_cut_roll(db: Session, roll: schemas.CutRollCreate, created_by: Optional[UUID] = None):
    # Generate unique QR code
    roll_id = uuid.uuid4()
    qr_code = generate_qr_code(roll_id)
    
    db_roll = models.CutRoll(
        id=roll_id,
        jumbo_roll_id=roll.jumbo_roll_id,
        width_inches=roll.width_inches,
        gsm=roll.gsm,
        bf=roll.bf,
        shade=roll.shade,
        weight_kg=roll.weight_kg,
        qr_code=qr_code,
        order_id=roll.order_id,
        created_by=created_by
    )
    db.add(db_roll)
    db.commit()
    db.refresh(db_roll)
    
    # Create inventory item for the cut roll
    create_inventory_item(db, schemas.InventoryItemCreate(roll_id=roll_id))
    
    return db_roll

def get_cut_roll(db: Session, roll_id: UUID):
    return db.query(models.CutRoll).filter(models.CutRoll.id == roll_id).first()

def get_cut_roll_by_qr(db: Session, qr_code: str):
    return db.query(models.CutRoll).filter(models.CutRoll.qr_code == qr_code).first()

def update_cut_roll(db: Session, roll_id: UUID, update: schemas.CutRollUpdate):
    db_roll = get_cut_roll(db, roll_id)
    if db_roll:
        if update.weight_kg is not None:
            db_roll.weight_kg = update.weight_kg
        if update.status is not None:
            db_roll.status = update.status
        db.commit()
        db.refresh(db_roll)
    return db_roll

# Inventory CRUD operations
def create_inventory_item(db: Session, item: schemas.InventoryItemCreate):
    db_item = models.InventoryItem(
        roll_id=item.roll_id,
        location=item.location
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

def get_inventory_items(db: Session, skip: int = 0, limit: int = 100, filters: Optional[schemas.InventoryFilter] = None):
    query = db.query(models.InventoryItem).join(models.CutRoll)
    
    if filters:
        if filters.width_inches:
            query = query.filter(models.CutRoll.width_inches == filters.width_inches)
        if filters.gsm:
            query = query.filter(models.CutRoll.gsm == filters.gsm)
        if filters.bf:
            query = query.filter(models.CutRoll.bf == filters.bf)
        if filters.shade:
            query = query.filter(models.CutRoll.shade.ilike(f"%{filters.shade}%"))
        if filters.status:
            query = query.filter(models.CutRoll.status == filters.status)
        if filters.allocated is not None:
            if filters.allocated:
                query = query.filter(models.InventoryItem.allocated_to_order.isnot(None))
            else:
                query = query.filter(models.InventoryItem.allocated_to_order.is_(None))
        if filters.location:
            query = query.filter(models.InventoryItem.location.ilike(f"%{filters.location}%"))
    
    return query.offset(skip).limit(limit).all()

def update_inventory_item(db: Session, item_id: UUID, update: schemas.InventoryItemUpdate):
    db_item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item_id).first()
    if db_item:
        if update.location is not None:
            db_item.location = update.location
        if update.allocated_to_order is not None:
            db_item.allocated_to_order = update.allocated_to_order
        db_item.last_updated = datetime.utcnow()
        db.commit()
        db.refresh(db_item)
    return db_item

def find_matching_inventory(db: Session, width_inches: int, gsm: int, bf: float, shade: str, quantity: int = 1):
    """Find available inventory items that match the specifications"""
    return db.query(models.InventoryItem).join(models.CutRoll).filter(
        and_(
            models.CutRoll.width_inches == width_inches,
            models.CutRoll.gsm == gsm,
            models.CutRoll.bf == bf,
            models.CutRoll.shade == shade,
            models.CutRoll.status == "weighed",
            models.InventoryItem.allocated_to_order.is_(None)
        )
    ).limit(quantity).all()

# Cutting plan CRUD operations
def create_cutting_plan(db: Session, plan: schemas.CuttingPlanCreate, created_by: Optional[UUID] = None):
    db_plan = models.CuttingPlan(
        jumbo_roll_id=plan.jumbo_roll_id,
        plan_data=plan.plan_data,
        expected_waste_percentage=plan.expected_waste_percentage,
        created_by=created_by
    )
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan

def get_cutting_plans(db: Session, skip: int = 0, limit: int = 100, status: Optional[str] = None):
    query = db.query(models.CuttingPlan)
    if status:
        query = query.filter(models.CuttingPlan.status == status)
    return query.offset(skip).limit(limit).all()

def update_cutting_plan(db: Session, plan_id: UUID, update: schemas.CuttingPlanUpdate):
    db_plan = db.query(models.CuttingPlan).filter(models.CuttingPlan.id == plan_id).first()
    if db_plan:
        if update.status is not None:
            db_plan.status = update.status
        if update.plan_data is not None:
            db_plan.plan_data = update.plan_data
        if update.expected_waste_percentage is not None:
            db_plan.expected_waste_percentage = update.expected_waste_percentage
        db.commit()
        db.refresh(db_plan)
    return db_plan

def get_order_with_details(db: Session, order_id: UUID):
    """
    Get an order with related WhatsApp message and cut rolls.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    
    if not order:
        return None
    
    # Load relationships
    if order.source_message_id:
        db.query(models.WhatsAppMessage).filter(models.WhatsAppMessage.id == order.source_message_id).first()
    
    db.query(models.CutRoll).filter(models.CutRoll.order_id == order.id).all()
    
    return order

def delete_order(db: Session, order_id: UUID) -> bool:
    """
    Delete an order by ID.
    Returns True if order was deleted, False if order was not found.
    """
    db_order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not db_order:
        return False
    
    # Check if order has related cut rolls
    cut_rolls = db.query(models.CutRoll).filter(models.CutRoll.order_id == order_id).all()
    if cut_rolls:
        # Don't delete orders with related cut rolls, just mark as cancelled
        db_order.status = "cancelled"
        db.commit()
        return True
    
    # Delete the order if no related cut rolls
    db.delete(db_order)
    db.commit()
    return True