from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from typing import Optional
import hashlib

from . import crud_operations, models, schemas, database

# Set up HTTP Basic Auth
security = HTTPBasic()

def hash_password(password: str) -> str:
    """
    Simple password hashing for user registration.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string
    """
    return password

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        plain_password: Plain text password to verify
        hashed_password: Stored hashed password
        
    Returns:
        True if password matches, False otherwise
    """
    return hash_password(plain_password) == hashed_password

def authenticate_user(db: Session, username: str, password: str) -> Optional[models.UserMaster]:
    """
    Authenticate a user with username and password using UserMaster.
    
    Args:
        db: Database session
        username: Username to authenticate
        password: Password to authenticate (plain text)
        
    Returns:
        UserMaster object if authentication successful, None otherwise
    """
    user = crud_operations.get_user_by_username(db, username)
    if not user:
        return None
    
    # Verify password
    if not verify_password(password, user.password_hash):
        return None
    
    # Check if user is active
    if user.status != "active":
        return None
    
    return user

def register_user(db: Session, user_data: schemas.UserMasterCreate) -> models.UserMaster:
    """
    Register a new user in UserMaster with hashed password.
    
    Args:
        db: Database session
        user_data: User registration data
        
    Returns:
        Created UserMaster object
        
    Raises:
        HTTPException: If username already exists or other validation errors
    """
    # Check if username already exists
    existing_user = crud_operations.get_user_by_username(db, user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Create user data with hashed password
    user_create_data = schemas.UserMasterCreate(
        name=user_data.name,
        username=user_data.username,
        password=user_data.password,  # Store hashed password
        role=user_data.role,
        contact=user_data.contact,
        department=user_data.department,
        status=user_data.status
    )
    
    # Create user using CRUD
    return crud_operations.create_user(db, user_create_data)

def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(database.get_db)
) -> models.UserMaster:
    """
    Get the current authenticated user using HTTP Basic Auth with UserMaster.
    
    Args:
        credentials: HTTP Basic Auth credentials
        db: Database session
        
    Returns:
        UserMaster object if authentication successful
        
    Raises:
        HTTPException: If authentication fails
    """
    user = authenticate_user(db, credentials.username, credentials.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return user

def get_current_active_user(current_user: models.UserMaster = Depends(get_current_user)) -> models.UserMaster:
    """
    Dependency to ensure the user is active.
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        UserMaster object if active
        
    Raises:
        HTTPException: If user is not active
    """
    if current_user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Inactive user"
        )
    return current_user

def require_role(required_role: str):
    """
    Dependency factory to require specific user role.
    
    Args:
        required_role: Required role (e.g., 'admin', 'planner', 'supervisor')
        
    Returns:
        Dependency function that checks user role
    """
    def role_checker(current_user: models.UserMaster = Depends(get_current_active_user)) -> models.UserMaster:
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires {required_role} role"
            )
        return current_user
    
    return role_checker

def require_roles(allowed_roles: list):
    """
    Dependency factory to require one of multiple user roles.
    
    Args:
        allowed_roles: List of allowed roles
        
    Returns:
        Dependency function that checks if user has one of the allowed roles
    """
    def roles_checker(current_user: models.UserMaster = Depends(get_current_active_user)) -> models.UserMaster:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of these roles: {', '.join(allowed_roles)}"
            )
        return current_user
    
    return roles_checker