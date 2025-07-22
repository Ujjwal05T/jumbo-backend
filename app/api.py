from fastapi import APIRouter, Depends, HTTPException, status, Response, Header
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional
import logging
import uuid
import json
from uuid import UUID

from . import crud, schemas, models, database, auth

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
@router.post("/auth/register", response_model=schemas.User)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user.
    This endpoint is public and doesn't require authentication.
    """
    # Check if username already exists
    db_user = crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Create the user
    return crud.create_user(db=db, user=user)

@router.post("/auth/login", response_model=Dict[str, Any])
def login(credentials: HTTPBasicCredentials = Depends(auth.security), db: Session = Depends(get_db)):
    """
    Login endpoint that authenticates a user and creates a session.
    Uses HTTP Basic Authentication to validate credentials and returns a session token.
    """
    user = auth.authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    # Create a new session
    session = auth.create_user_session(db, user.id)
    
    return {
        "message": "Login successful",
        "user_id": str(user.id),
        "username": user.username,
        "role": user.role,
        "session_token": session.session_token,
        "expires_at": session.expires_at.isoformat()
    }

@router.post("/auth/logout")
def logout(
    response: Response, 
    authorization: Optional[str] = Header(None),
    current_user: models.User = Depends(auth.get_current_user), 
    db: Session = Depends(get_db)
):
    """
    Logout endpoint that invalidates the current session.
    Accepts either HTTP Basic Auth or Bearer token for authentication.
    """
    # Check if using session token (Bearer)
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]  # Remove "Bearer " prefix
        auth.invalidate_session(db, token)
    else:
        # If using Basic Auth or no specific token provided, invalidate all user sessions
        auth.invalidate_all_user_sessions(db, current_user.id)
    
    return {"message": "Logout successful"}

@router.get("/auth/me", response_model=schemas.User)
def get_current_user_info(current_user: models.User = Depends(auth.get_current_active_user)):
    """
    Get information about the currently authenticated user.
    Accepts either HTTP Basic Auth or Bearer token for authentication.
    """
    return current_user

@router.get("/auth/session-check")
def check_session(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """
    Check if a session token is valid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
            headers={"WWW-Authenticate": 'Bearer realm="session"'},
        )
    
    token = authorization[7:]  # Remove "Bearer " prefix
    session = auth.get_session_by_token(db, token)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": 'Bearer realm="session"'},
        )
    
    user = crud.get_user(db, session.user_id)
    
    return {
        "valid": True,
        "user_id": str(user.id),
        "username": user.username,
        "role": user.role,
        "expires_at": session.expires_at.isoformat()
    }

# User endpoints
@router.post("/users/", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db), 
                current_user: models.User = Depends(auth.get_current_active_user)):
    """
    Create a new user (requires authentication).
    """
    # In the future, we could add role-based checks here
    db_user = crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud.create_user(db=db, user=user)

@router.get("/users/{user_id}", response_model=schemas.User)
def read_user(user_id: uuid.UUID, db: Session = Depends(get_db), 
              current_user: models.User = Depends(auth.get_current_active_user)):
    """
    Get user information by ID (requires authentication).
    """
    db_user = crud.get_user(db, user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@router.get("/users/", response_model=List[schemas.User])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db),
               current_user: models.User = Depends(auth.get_current_active_user)):
    """
    Get a list of users (requires authentication).
    """
    users = db.query(models.User).offset(skip).limit(limit).all()
    return users

# Order endpoints
@router.post("/orders/", response_model=schemas.Order)
def create_order(order: schemas.OrderCreate, db: Session = Depends(get_db),
                current_user: models.User = Depends(auth.get_current_active_user)):
    """
    Create a new order directly from form input
    """
    return crud.create_order(db=db, order=order, created_by=current_user.id)

@router.post("/orders/from-message", response_model=schemas.Order)
def create_order_from_message(
    message_id: UUID,
    order_data: Optional[schemas.OrderCreate] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    """
    Create a new order from a parsed message
    """
    # Get the parsed message
    message = db.query(models.ParsedMessage).filter(models.ParsedMessage.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # If order_data is provided, use it; otherwise, try to use the parsed JSON
    if not order_data and message.parsed_json:
        try:
            # Parse the JSON data from the message
            parsed_data = json.loads(message.parsed_json)
            
            # Convert to OrderCreate schema
            order_data = schemas.OrderCreate(
                customer_name=parsed_data.get("customer_name", "Unknown"),
                width_inches=parsed_data.get("width_inches", 0),
                gsm=parsed_data.get("gsm", 0),
                bf=parsed_data.get("bf", 0),
                shade=parsed_data.get("shade", ""),
                quantity_rolls=parsed_data.get("quantity_rolls", 0),
                quantity_tons=parsed_data.get("quantity_tons"),
                source_message_id=message_id
            )
        except Exception as e:
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to parse order data from message: {str(e)}"
            )
    elif not order_data:
        raise HTTPException(
            status_code=400,
            detail="No order data provided and message has no parsed JSON"
        )
    else:
        # Make sure the source_message_id is set
        order_data.source_message_id = message_id
    
    # Create the order
    return crud.create_order(db=db, order=order_data, created_by=current_user.id)

@router.get("/orders/", response_model=List[schemas.Order])
def read_orders(
    skip: int = 0, 
    limit: int = 100, 
    customer_name: Optional[str] = None,
    status: Optional[str] = None,
    width_inches: Optional[int] = None,
    gsm: Optional[int] = None,
    bf: Optional[float] = None,
    shade: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    """
    Get a list of orders with optional filtering.
    """
    # Convert string dates to datetime if provided
    from_date = None
    to_date = None
    
    if date_from:
        try:
            from_date = datetime.fromisoformat(date_from)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date_from format. Use ISO format (YYYY-MM-DDTHH:MM:SS)."
            )
    
    if date_to:
        try:
            to_date = datetime.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date_to format. Use ISO format (YYYY-MM-DDTHH:MM:SS)."
            )
    
    # Create filter object if any filter is provided
    filters = None
    if any([customer_name, status, width_inches, gsm, bf, shade, from_date, to_date]):
        filters = schemas.OrderFilter(
            customer_name=customer_name,
            status=status,
            width_inches=width_inches,
            gsm=gsm,
            bf=Decimal(str(bf)) if bf is not None else None,
            shade=shade,
            date_from=from_date,
            date_to=to_date
        )
    
    orders = crud.get_orders(db, skip=skip, limit=limit, filters=filters)
    return orders

@router.get("/orders/{order_id}", response_model=schemas.Order)
def read_order(order_id: uuid.UUID, db: Session = Depends(get_db),
              current_user: models.User = Depends(auth.get_current_active_user)):
    db_order = crud.get_order(db, order_id=order_id)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@router.put("/orders/{order_id}", response_model=schemas.Order)
def update_order(
    order_id: uuid.UUID,
    order_update: schemas.OrderUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    """
    Update an order's status or quantities.
    """
    db_order = crud.get_order(db, order_id=order_id)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    
    updated_order = crud.update_order(db, order_id=order_id, update=order_update)
    return updated_order

@router.get("/orders/status/{status_value}", response_model=List[schemas.Order])
def read_orders_by_status(
    status_value: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    """
    Get orders by status (pending, processing, completed, cancelled).
    """
    # Validate status
    valid_statuses = ["pending", "processing", "completed", "cancelled"]
    if status_value not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    filters = schemas.OrderFilter(status=status_value)
    orders = crud.get_orders(db, skip=skip, limit=limit, filters=filters)
    return orders

@router.get("/orders/{order_id}/details", response_model=schemas.OrderWithDetails)
def read_order_details(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    """
    Get detailed order information including related parsed message and cut rolls.
    """
    db_order = crud.get_order_with_details(db, order_id=order_id)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@router.delete("/orders/{order_id}", response_model=Dict[str, Any])
def delete_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    """
    Delete an order or mark it as cancelled if it has related cut rolls.
    """
    # Check if user has permission (admin or manager)
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete orders"
        )
    
    result = crud.delete_order(db, order_id=order_id)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return {"success": True, "message": "Order deleted or cancelled successfully"}

# Message parsing endpoints
@router.post("/messages/", response_model=schemas.ParsedMessage)
def create_parsed_message(message: schemas.ParsedMessageCreate, db: Session = Depends(get_db),
                         current_user: models.User = Depends(auth.get_current_active_user)):
    return crud.create_parsed_message(db=db, message=message, created_by=current_user.id)

@router.post("/messages/parse", response_model=schemas.ParsedMessage)
def parse_message(message: schemas.ParsedMessageCreate, db: Session = Depends(get_db),
                 current_user: models.User = Depends(auth.get_current_active_user)):
    # Create the message first
    db_message = crud.create_parsed_message(db=db, message=message, created_by=current_user.id)
    
    # TODO: Implement GPT parsing logic here
    # For now, just return the created message
    return db_message

# Jumbo roll endpoints
@router.post("/jumbo-rolls/", response_model=schemas.JumboRoll)
def create_jumbo_roll(
    roll: schemas.JumboRollCreate, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    return crud.create_jumbo_roll(db=db, roll=roll, created_by=current_user.id)

@router.get("/jumbo-rolls/", response_model=List[schemas.JumboRoll])
def read_jumbo_rolls(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    rolls = crud.get_jumbo_rolls(db, skip=skip, limit=limit)
    return rolls

@router.get("/jumbo-rolls/{roll_id}", response_model=schemas.JumboRoll)
def read_jumbo_roll(
    roll_id: uuid.UUID, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    db_roll = crud.get_jumbo_roll(db, roll_id=roll_id)
    if db_roll is None:
        raise HTTPException(status_code=404, detail="Jumbo roll not found")
    return db_roll

# Cut roll endpoints
@router.post("/cut-rolls/", response_model=schemas.CutRoll)
def create_cut_roll(
    roll: schemas.CutRollCreate, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user)
):
    return crud.create_cut_roll(db=db, roll=roll, created_by=current_user.id)
# Database status endpoint
@router.get("/db-status")
def check_db_status(current_user: models.User = Depends(auth.get_current_active_user)):
    """
    Check database connection status (requires authentication)
    """
    # Only allow admins to check database status
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this endpoint"
        )
    
    status = {
        "database_configured": database.engine is not None,
        "connection_string": database.DATABASE_URL.replace(
            # Hide password in connection string
            database.DATABASE_URL.split(":")[-2].split("@")[0],
            "********"
        ) if database.DATABASE_URL else None,
    }
    
    # Try to connect if engine exists
    if database.engine is not None:
        try:
            # Test connection
            with database.engine.connect() as connection:
                result = connection.execute(database.text("SELECT 1"))
                status["connection_test"] = "successful"
                status["message"] = "Database connection is working properly"
        except SQLAlchemyError as e:
            status["connection_test"] = "failed"
            status["error"] = str(e)
            status["message"] = "Database is configured but connection failed"
    else:
        status["connection_test"] = "skipped"
        status["message"] = "Database is not configured properly"
        
    return status