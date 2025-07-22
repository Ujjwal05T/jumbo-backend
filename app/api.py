from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from . import crud, schemas, models, database

# Create tables on startup
models.Base.metadata.create_all(bind=database.engine)

router = APIRouter()

# Dependency
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# User endpoints
@router.post("/users/", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud.create_user(db=db, user=user)

@router.get("/users/{user_id}", response_model=schemas.User)
def read_user(user_id: int, db: Session = Depends(get_db)):
    db_user = crud.get_user(db, user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

# Order endpoints
@router.post("/orders/", response_model=schemas.Order)
def create_order(order: schemas.OrderCreate, db: Session = Depends(get_db)):
    return crud.create_order(db=db, order=order)

@router.get("/orders/", response_model=List[schemas.Order])
def read_orders(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    orders = crud.get_orders(db, skip=skip, limit=limit)
    return orders

@router.get("/orders/{order_id}", response_model=schemas.Order)
def read_order(order_id: int, db: Session = Depends(get_db)):
    db_order = crud.get_order(db, order_id=order_id)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

# WhatsApp message endpoints
@router.post("/whatsapp/", response_model=schemas.WhatsAppMessage)
def create_whatsapp_message(message: schemas.WhatsAppMessageCreate, db: Session = Depends(get_db)):
    return crud.create_whatsapp_message(db=db, message=message)

# Jumbo roll endpoints
@router.post("/jumbo-rolls/", response_model=schemas.JumboRoll)
def create_jumbo_roll(roll: schemas.JumboRollCreate, db: Session = Depends(get_db)):
    return crud.create_jumbo_roll(db=db, roll=roll)

@router.get("/jumbo-rolls/", response_model=List[schemas.JumboRoll])
def read_jumbo_rolls(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    rolls = crud.get_jumbo_rolls(db, skip=skip, limit=limit)
    return rolls

@router.get("/jumbo-rolls/{roll_id}", response_model=schemas.JumboRoll)
def read_jumbo_roll(roll_id: int, db: Session = Depends(get_db)):
    db_roll = crud.get_jumbo_roll(db, roll_id=roll_id)
    if db_roll is None:
        raise HTTPException(status_code=404, detail="Jumbo roll not found")
    return db_roll

# Cut roll endpoints
@router.post("/cut-rolls/", response_model=schemas.CutRoll)
def create_cut_roll(roll: schemas.CutRollCreate, db: Session = Depends(get_db)):
    return crud.create_cut_roll(db=db, roll=roll)