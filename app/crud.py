from sqlalchemy.orm import Session
from sqlalchemy import or_
from . import models, schemas
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

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
    db_order = models.Order(
        customer_name=order.customer_name,
        width_inches=order.width_inches,
        gsm=order.gsm,
        bf=order.bf,
        shade=order.shade,
        quantity_rolls=order.quantity_rolls,
        quantity_tons=order.quantity_tons,
        status=order.status if hasattr(order, 'status') else 'pending',
        source_message_id=order.source_message_id if hasattr(order, 'source_message_id') else None
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