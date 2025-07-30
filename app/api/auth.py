from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging

from .base import get_db
from .. import schemas, auth

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@router.post("/auth/register", response_model=schemas.UserMaster, tags=["Authentication"])
def register_user(user_data: schemas.UserMasterCreate, db: Session = Depends(get_db)):
    """Register a new user in UserMaster"""
    try:
        return auth.register_user(db=db, user_data=user_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/login", response_model=schemas.UserMaster, tags=["Authentication"])
def login_user(credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    """Authenticate user and return user information"""
    try:
        user = auth.authenticate_user(db=db, username=credentials.username, password=credentials.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail=str(e))