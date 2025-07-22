from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional
import logging
import uuid
import json
from uuid import UUID
from datetime import datetime

from . import crud, schemas, models, database

# Set up logging
logger = logging.getLogger(__name__)

# Create tables on startup only if database engine is available
router = APIRouter()

# Try to create tables, but don't fail if database is not available
if database.engine is not None:
    try:
        models.Base.metadata.create_all(bind=database.engine)
        logger.info("Database tables created successfully")
    except SQLAlchemyError as e:
        logger.error(f"Failed to create database tables: {e}")
else:
    logger.warning("Database engine not available, skipping table creation")

# Dependency
def get_db():
    if database.SessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection not available. Please check server logs."
        )
    
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Authentication endpoints
@router.post("/register", response_model=schemas.AuthResponse)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check if user already exists
    db_user = crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(
            status_code=400,
            detail="Username already registered"
        )
    
    # Create new user
    db_user = crud.create_user(db=db, user=user)
    if not db_user:
        raise HTTPException(
            status_code=500,
            detail="Error creating user"
        )
    
    # Return success response with username
    return {
        "status": "success",
        "username": db_user.username
    }

@router.post("/login", response_model=schemas.AuthResponse)
def login_user(credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    # Authenticate user
    user = crud.authenticate_user(
        db=db, 
        username=credentials.username, 
        password=credentials.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Return success response with username
    return {
        "status": "success",
        "username": user.username
    }

# Order endpoints
@router.post("/orders", response_model=schemas.Order)
def create_order(order: schemas.OrderCreate, db: Session = Depends(get_db)):
    return crud.create_order(db=db, order=order)

@router.get("/orders", response_model=List[schemas.Order])
def read_orders(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    orders = crud.get_orders(db, skip=skip, limit=limit)
    return orders

@router.get("/orders/{order_id}", response_model=schemas.Order)
def read_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    db_order = crud.get_order(db, order_id=order_id)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@router.put("/orders/{order_id}", response_model=schemas.Order)
def update_order(order_id: uuid.UUID, order_update: schemas.OrderUpdate, db: Session = Depends(get_db)):
    db_order = crud.update_order(db=db, order_id=order_id, update=order_update)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@router.get("/orders/status/{status_value}", response_model=List[schemas.Order])
def read_orders_by_status(status_value: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    orders = crud.get_orders(db, skip=skip, limit=limit)
    return [order for order in orders if order.status == status_value]

@router.get("/orders/{order_id}/details", response_model=schemas.Order)
def read_order_details(order_id: uuid.UUID, db: Session = Depends(get_db)):
    db_order = crud.get_order_with_details(db, order_id=order_id)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    if not crud.delete_order(db=db, order_id=order_id):
        raise HTTPException(status_code=404, detail="Order not found")
    return Response(status_code=204)

# Message parsing endpoints
@router.post("/messages/", response_model=schemas.ParsedMessage)
def create_parsed_message(message: schemas.ParsedMessageCreate, db: Session = Depends(get_db)):
    return crud.create_parsed_message(db=db, message=message)

@router.post("/messages/parse", response_model=schemas.ParsedMessage)
def parse_message(message: schemas.ParsedMessageCreate, db: Session = Depends(get_db)):
    # Add any message parsing logic here if needed
    return crud.create_parsed_message(db=db, message=message)

# Jumbo roll endpoints
@router.post("/jumbo-rolls/", response_model=schemas.JumboRoll)
def create_jumbo_roll(roll: schemas.JumboRollCreate, db: Session = Depends(get_db)):
    return crud.create_jumbo_roll(db=db, roll=roll)

@router.get("/jumbo-rolls/", response_model=List[schemas.JumboRoll])
def read_jumbo_rolls(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_jumbo_rolls(db=db, skip=skip, limit=limit)

@router.get("/jumbo-rolls/{roll_id}", response_model=schemas.JumboRoll)
def read_jumbo_roll(roll_id: uuid.UUID, db: Session = Depends(get_db)):
    db_roll = crud.get_jumbo_roll(db, roll_id=roll_id)
    if db_roll is None:
        raise HTTPException(status_code=404, detail="Jumbo roll not found")
    return db_roll

# Cut roll endpoints
@router.post("/cut-rolls/", response_model=schemas.CutRoll)
def create_cut_roll(roll: schemas.CutRollCreate, db: Session = Depends(get_db)):
    return crud.create_cut_roll(db=db, roll=roll)

@router.get("/cut-rolls/", response_model=List[schemas.CutRoll])
def read_cut_rolls(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_cut_rolls(db=db, skip=skip, limit=limit)

# Database status endpoint
@router.get("/status/")
def check_db_status(db: Session = Depends(get_db)):
    try:
        # Try to execute a simple query
        db.execute("SELECT 1")
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }
    except SQLAlchemyError as e:
        logger.error(f"Database connection error: {e}")
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }