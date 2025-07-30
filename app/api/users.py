from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import logging

from .base import get_db
from .. import crud_operations, schemas

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# USER MASTER ENDPOINTS
# ============================================================================

@router.get("/users", response_model=List[schemas.UserMaster], tags=["User Master"])
def get_users(
    skip: int = 0,
    limit: int = 100,
    status: str = "active",
    db: Session = Depends(get_db)
):
    """Get all users with pagination and status filter"""
    try:
        return crud_operations.get_users(db=db, skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}", response_model=schemas.UserMaster, tags=["User Master"])
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    """Get user by ID"""
    user = crud_operations.get_user(db=db, user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/users/{user_id}", response_model=schemas.UserMaster, tags=["User Master"])
def update_user(
    user_id: UUID,
    user_update: schemas.UserMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update user information"""
    try:
        user = crud_operations.update_user(db=db, user_id=user_id, user_update=user_update)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))