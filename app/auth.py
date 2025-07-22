from fastapi import Depends, HTTPException, status, Request, Header
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import uuid
import secrets
import base64
from typing import Optional, Tuple, Union

from . import crud, models, schemas, database

# Set up HTTP Basic Auth
security = HTTPBasic()

# Session expiration time (24 hours)
SESSION_EXPIRATION = timedelta(hours=24)

def authenticate_user(db: Session, username: str, password: str) -> Union[models.User, bool]:
    """
    Authenticate a user with username and password.
    For internal use only, using plain text password comparison as per requirements.
    
    Args:
        db: Database session
        username: Username to authenticate
        password: Password to authenticate (plain text)
        
    Returns:
        User object if authentication successful, False otherwise
    """
    user = crud.get_user_by_username(db, username)
    if not user:
        return False
    
    # Simple plain text password check (as per requirements for internal use)
    if user.password != password:
        return False
    
    # Update last login time
    crud.update_user_last_login(db, user.id)
    return user

def create_user_session(db: Session, user_id: uuid.UUID) -> models.UserSession:
    """
    Create a new session for the user and store it in the database.
    
    Args:
        db: Database session
        user_id: User ID to create session for
        
    Returns:
        Created UserSession object
    """
    # Generate a secure random token
    token = secrets.token_hex(32)
    
    # Create session with expiration
    expires_at = datetime.utcnow() + SESSION_EXPIRATION
    
    # Create session in database
    db_session = models.UserSession(
        user_id=user_id,
        session_token=token,
        expires_at=expires_at,
        is_active=True
    )
    
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    
    return db_session

def get_session_by_token(db: Session, token: str) -> Optional[models.UserSession]:
    """
    Get a session by token if it's valid and not expired.
    
    Args:
        db: Database session
        token: Session token to look up
        
    Returns:
        UserSession object if found and valid, None otherwise
    """
    session = db.query(models.UserSession).filter(
        models.UserSession.session_token == token,
        models.UserSession.is_active == True,
        models.UserSession.expires_at > datetime.utcnow()
    ).first()
    
    return session

def invalidate_session(db: Session, token: str) -> bool:
    """
    Invalidate a session by setting is_active to False.
    
    Args:
        db: Database session
        token: Session token to invalidate
        
    Returns:
        True if session was found and invalidated, False otherwise
    """
    session = db.query(models.UserSession).filter(
        models.UserSession.session_token == token
    ).first()
    
    if session:
        session.is_active = False
        db.commit()
        return True
    
    return False

def invalidate_all_user_sessions(db: Session, user_id: uuid.UUID) -> int:
    """
    Invalidate all active sessions for a user.
    
    Args:
        db: Database session
        user_id: User ID to invalidate sessions for
        
    Returns:
        Number of sessions invalidated
    """
    sessions = db.query(models.UserSession).filter(
        models.UserSession.user_id == user_id,
        models.UserSession.is_active == True
    ).all()
    
    count = 0
    for session in sessions:
        session.is_active = False
        count += 1
    
    db.commit()
    return count

def parse_basic_auth_header(auth_header: str) -> Tuple[str, str]:
    """
    Parse HTTP Basic Authentication header.
    
    Args:
        auth_header: Authorization header value
        
    Returns:
        Tuple of (username, password)
        
    Raises:
        ValueError: If header is invalid
    """
    if not auth_header or not auth_header.startswith("Basic "):
        raise ValueError("Invalid Authorization header")
    
    try:
        auth_decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, password = auth_decoded.split(":", 1)
        return username, password
    except Exception as e:
        raise ValueError(f"Invalid Authorization header: {str(e)}")

def get_current_user(credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(database.get_db)):
    """
    Dependency to get the current authenticated user from HTTP Basic Auth.
    
    Args:
        credentials: HTTP Basic Auth credentials
        db: Database session
        
    Returns:
        User object if authentication successful
        
    Raises:
        HTTPException: If authentication fails
    """
    user = authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user

def get_current_active_user(current_user: models.User = Depends(get_current_user)):
    """
    Dependency to ensure the user is active.
    
    Args:
        current_user: User object from get_current_user dependency
        
    Returns:
        User object if user is active
        
    Raises:
        HTTPException: If user is not active
    """
    # In the future, we could add user status checks here
    # For example, check if user.is_active is True
    return current_user

def get_user_from_session_token(
    db: Session = Depends(database.get_db),
    authorization: Optional[str] = Header(None)
) -> Optional[models.User]:
    """
    Get user from session token in Authorization header.
    
    Args:
        db: Database session
        authorization: Authorization header value
        
    Returns:
        User object if session is valid, None otherwise
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    token = authorization[7:]  # Remove "Bearer " prefix
    session = get_session_by_token(db, token)
    
    if not session:
        return None
    
    return crud.get_user(db, session.user_id)

def get_current_user_from_session(
    db: Session = Depends(database.get_db),
    authorization: Optional[str] = Header(None)
) -> models.User:
    """
    Dependency to get the current authenticated user from session token.
    
    Args:
        db: Database session
        authorization: Authorization header value
        
    Returns:
        User object if session is valid
        
    Raises:
        HTTPException: If session is invalid or expired
    """
    user = get_user_from_session_token(db, authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": 'Bearer realm="session"'},
        )
    return user

def get_current_user_optional(
    request: Request,
    db: Session = Depends(database.get_db)
) -> Optional[models.User]:
    """
    Dependency to get the current user if authenticated, or None if not.
    Tries both Basic Auth and session token.
    
    Args:
        request: FastAPI request object
        db: Database session
        
    Returns:
        User object if authenticated, None otherwise
    """
    # Try session token first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        user = get_user_from_session_token(db, auth_header)
        if user:
            return user
    
    # Try Basic Auth
    if auth_header and auth_header.startswith("Basic "):
        try:
            username, password = parse_basic_auth_header(auth_header)
            user = authenticate_user(db, username, password)
            if user:
                return user
        except ValueError:
            pass
    
    return None