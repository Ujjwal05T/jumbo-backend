from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from uuid import UUID
import hashlib

from .base import CRUDBase
from .. import models, schemas


class CRUDUser(CRUDBase[models.UserMaster, schemas.UserMasterCreate, schemas.UserMasterUpdate]):
    def get_users(
        self, 
        db: Session, 
        *, 
        skip: int = 0, 
        limit: int = 100, 
        role: Optional[str] = None,
        status: str = "active"
    ) -> List[models.UserMaster]:
        """Get users with filtering by role and status"""
        query = db.query(models.UserMaster).filter(models.UserMaster.status == status)
        
        if role:
            query = query.filter(models.UserMaster.role == role)
            
        return query.order_by(models.UserMaster.created_at.desc()).offset(skip).limit(limit).all()
    
    def get_user(self, db: Session, user_id: UUID) -> Optional[models.UserMaster]:
        """Get user by ID"""
        return db.query(models.UserMaster).filter(models.UserMaster.id == user_id).first()
    
    def get_user_by_username(self, db: Session, username: str) -> Optional[models.UserMaster]:
        """Get user by username"""
        return db.query(models.UserMaster).filter(models.UserMaster.username == username).first()
    
    def create_user(self, db: Session, *, user: schemas.UserMasterCreate) -> models.UserMaster:
        """Create new user with hashed password"""
        # Hash password (using simple hash for now)
        
        
        db_user = models.UserMaster(
            name=user.name,
            username=user.username,
            password_hash=user.password,
            role=user.role,
            contact=user.contact,
            department=user.department
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    
    def update_user(
        self, db: Session, *, user_id: UUID, user_update: schemas.UserMasterUpdate
    ) -> Optional[models.UserMaster]:
        """Update user"""
        db_user = self.get_user(db, user_id)
        if db_user:
            update_data = user_update.model_dump(exclude_unset=True)
            
            # Hash password if provided
            if "password" in update_data:
                password_hash = hashlib.sha256(update_data["password"].encode()).hexdigest()
                update_data["password_hash"] = password_hash
                del update_data["password"]
            
            for field, value in update_data.items():
                setattr(db_user, field, value)
            db.commit()
            db.refresh(db_user)
        return db_user
    
    def authenticate_user(self, db: Session, username: str, password: str) -> Optional[models.UserMaster]:
        """Authenticate user login"""
        user = self.get_user_by_username(db, username)
        if not user:
            return None
        
        # Verify password (using simple hash)
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        if password_hash == user.password_hash:
            # Update last login
            from datetime import datetime
            user.last_login = datetime.utcnow()
            db.commit()
            return user
        return None


user = CRUDUser(models.UserMaster)