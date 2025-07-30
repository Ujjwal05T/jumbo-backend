from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from uuid import UUID

from .base import CRUDBase
from .. import models, schemas


class CRUDClient(CRUDBase[models.ClientMaster, schemas.ClientMasterCreate, schemas.ClientMasterUpdate]):
    def get_clients(
        self, db: Session, *, skip: int = 0, limit: int = 100, status: str = "active"
    ) -> List[models.ClientMaster]:
        """Get clients with filtering by status"""
        return (
            db.query(models.ClientMaster)
            .filter(models.ClientMaster.status == status)
            .order_by(models.ClientMaster.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    
    def get_client(self, db: Session, client_id: UUID) -> Optional[models.ClientMaster]:
        """Get client by ID with relationships"""
        return (
            db.query(models.ClientMaster)
            .options(joinedload(models.ClientMaster.created_by))
            .filter(models.ClientMaster.id == client_id)
            .first()
        )
    
    def create_client(self, db: Session, *, client: schemas.ClientMasterCreate) -> models.ClientMaster:
        """Create new client"""
        db_client = models.ClientMaster(
            company_name=client.company_name,
            email=client.email,
            gst_number=client.gst_number,
            address=client.address,
            contact_person=client.contact_person,
            phone=client.phone,
            created_by_id=client.created_by_id
        )
        db.add(db_client)
        db.commit()
        db.refresh(db_client)
        return db_client
    
    def update_client(
        self, db: Session, *, client_id: UUID, client_update: schemas.ClientMasterUpdate
    ) -> Optional[models.ClientMaster]:
        """Update client"""
        db_client = self.get_client(db, client_id)
        if db_client:
            update_data = client_update.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(db_client, field, value)
            db.commit()
            db.refresh(db_client)
        return db_client
    
    def delete_client(self, db: Session, *, client_id: UUID) -> bool:
        """Soft delete client (deactivate)"""
        db_client = self.get_client(db, client_id)
        if db_client:
            db_client.status = "inactive"
            db.commit()
            return True
        return False


client = CRUDClient(models.ClientMaster)