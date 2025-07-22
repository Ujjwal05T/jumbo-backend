from sqlalchemy.orm import Session
from . import models, schemas
from datetime import datetime

# User CRUD operations
def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def create_user(db: Session, user: schemas.UserCreate):
    # In a real app, you'd hash the password here
    db_user = models.User(username=user.username, password=user.password, role=user.role)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# Order CRUD operations
def get_order(db: Session, order_id: int):
    return db.query(models.Order).filter(models.Order.id == order_id).first()

def get_orders(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Order).offset(skip).limit(limit).all()

def create_order(db: Session, order: schemas.OrderCreate):
    db_order = models.Order(
        customer_name=order.customer_name,
        status=order.status,
        order_date=datetime.utcnow()
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order

# WhatsApp message CRUD operations
def create_whatsapp_message(db: Session, message: schemas.WhatsAppMessageCreate, order_id: int = None):
    db_message = models.WhatsAppMessage(
        message_text=message.message_text,
        parsed=message.parsed,
        order_id=order_id
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

# Jumbo roll CRUD operations
def get_jumbo_roll(db: Session, roll_id: int):
    return db.query(models.JumboRoll).filter(models.JumboRoll.id == roll_id).first()

def get_jumbo_rolls(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.JumboRoll).offset(skip).limit(limit).all()

def create_jumbo_roll(db: Session, roll: schemas.JumboRollCreate):
    db_roll = models.JumboRoll(
        width=roll.width,
        length=roll.length,
        gsm=roll.gsm,
        paper_type=roll.paper_type
    )
    db.add(db_roll)
    db.commit()
    db.refresh(db_roll)
    return db_roll

# Cut roll CRUD operations
def create_cut_roll(db: Session, roll: schemas.CutRollCreate):
    db_roll = models.CutRoll(
        width=roll.width,
        length=roll.length,
        gsm=roll.gsm,
        paper_type=roll.paper_type,
        qr_code=roll.qr_code,
        jumbo_roll_id=roll.jumbo_roll_id,
        order_id=roll.order_id
    )
    db.add(db_roll)
    db.commit()
    db.refresh(db_roll)
    return db_roll