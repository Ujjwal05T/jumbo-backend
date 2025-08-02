from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from typing import List, Optional, Dict, Any
from uuid import UUID

from .base import CRUDBase
from .. import models, schemas


class CRUDInventory(CRUDBase[models.InventoryMaster, schemas.InventoryMasterCreate, schemas.InventoryMasterUpdate]):
    def get_inventory_items(
        self, 
        db: Session, 
        *, 
        skip: int = 0, 
        limit: int = 100, 
        roll_type: str = None,
        status: str = "available"
    ) -> List[models.InventoryMaster]:
        """Get inventory items with filtering"""
        query = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.created_by)
        )
        
        if roll_type:
            query = query.filter(models.InventoryMaster.roll_type == roll_type)
        if status:
            query = query.filter(models.InventoryMaster.status == status)
            
        return query.order_by(models.InventoryMaster.created_at.desc()).offset(skip).limit(limit).all()
    
    def get_inventory_item(self, db: Session, inventory_id: UUID) -> Optional[models.InventoryMaster]:
        """Get inventory item by ID with relationships"""
        return (
            db.query(models.InventoryMaster)
            .options(
                joinedload(models.InventoryMaster.paper),
                joinedload(models.InventoryMaster.created_by)
            )
            .filter(models.InventoryMaster.id == inventory_id)
            .first()
        )
    
    def get_inventory_by_type(
        self, 
        db: Session, 
        *, 
        roll_type: str, 
        skip: int = 0, 
        limit: int = 100,
        status: str = "available"
    ) -> List[models.InventoryMaster]:
        """Get inventory items by roll type"""
        return (
            db.query(models.InventoryMaster)
            .options(joinedload(models.InventoryMaster.paper))
            .filter(
                and_(
                    models.InventoryMaster.roll_type == roll_type,
                    models.InventoryMaster.status == status
                )
            )
            .order_by(models.InventoryMaster.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    
    def get_available_inventory_by_paper(
        self, db: Session, *, paper_id: UUID, roll_type: str = None
    ) -> List[models.InventoryMaster]:
        """Get available inventory for specific paper specification"""
        query = (
            db.query(models.InventoryMaster)
            .options(joinedload(models.InventoryMaster.paper))
            .filter(
                and_(
                    models.InventoryMaster.paper_id == paper_id,
                    models.InventoryMaster.status == "available"
                )
            )
        )
        
        if roll_type:
            query = query.filter(models.InventoryMaster.roll_type == roll_type)
            
        return query.all()
    
    def get_available_inventory_by_paper_specs(
        self, db: Session, paper_specs: List[Dict[str, Any]]
    ) -> List[models.InventoryMaster]:
        """Get available 20-25 inch waste inventory for paper specs - NEW FLOW"""
        if not paper_specs:
            return []
        
        # Build filter conditions for multiple paper specs
        spec_conditions = []
        for spec in paper_specs:
            spec_condition = and_(
                models.PaperMaster.gsm == spec['gsm'],
                models.PaperMaster.bf == spec['bf'], 
                models.PaperMaster.shade == spec['shade']
            )
            spec_conditions.append(spec_condition)
        
        # Combine with OR
        from sqlalchemy import or_
        paper_filter = or_(*spec_conditions) if len(spec_conditions) > 1 else spec_conditions[0]
        
        return (
            db.query(models.InventoryMaster)
            .join(models.PaperMaster)
            .filter(
                and_(
                    models.InventoryMaster.status == "available",
                    models.InventoryMaster.roll_type == "cut",
                    models.InventoryMaster.width_inches >= 20,
                    models.InventoryMaster.width_inches <= 25,
                    paper_filter
                )
            )
            .all()
        )
    
    def create_inventory_item(
        self, db: Session, *, inventory: schemas.InventoryMasterCreate
    ) -> models.InventoryMaster:
        """Create new inventory item"""
        db_inventory = models.InventoryMaster(
            paper_id=inventory.paper_id,
            width_inches=inventory.width_inches,
            weight_kg=inventory.weight_kg,
            roll_type=inventory.roll_type,
            location=inventory.location,
            qr_code=inventory.qr_code,
            barcode_id=inventory.barcode_id,
            created_by_id=inventory.created_by_id
        )
        db.add(db_inventory)
        db.commit()
        db.refresh(db_inventory)
        return db_inventory
    
    def create_inventory_from_waste(
        self, db: Session, waste_items: List[Dict[str, Any]], user_id: UUID
    ) -> List[models.InventoryMaster]:
        """Create inventory records from waste items - NEW FLOW"""
        created_items = []
        
        for waste in waste_items:
            if 20 <= waste['width'] <= 25:  # Only 20-25" waste becomes inventory
                db_inventory = models.InventoryMaster(
                    paper_id=waste['paper_id'],
                    width_inches=waste['width'],
                    weight_kg=waste.get('weight', 0),
                    roll_type="cut",
                    status="available",
                    location="warehouse",
                    created_by_id=user_id
                )
                db.add(db_inventory)
                created_items.append(db_inventory)
        
        if created_items:
            db.commit()
            for item in created_items:
                db.refresh(item)
        
        return created_items
    
    def update_inventory_item(
        self, db: Session, *, inventory_id: UUID, inventory_update: schemas.InventoryMasterUpdate
    ) -> Optional[models.InventoryMaster]:
        """Update inventory item"""
        db_inventory = self.get_inventory_item(db, inventory_id)
        if db_inventory:
            update_data = inventory_update.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(db_inventory, field, value)
            db.commit()
            db.refresh(db_inventory)
        return db_inventory
    
    def update_inventory_status(
        self, db: Session, *, inventory_id: UUID, new_status: str
    ) -> Optional[models.InventoryMaster]:
        """Update inventory status"""
        db_inventory = self.get_inventory_item(db, inventory_id)
        if db_inventory:
            db_inventory.status = new_status
            db.commit()
            db.refresh(db_inventory)
        return db_inventory


inventory = CRUDInventory(models.InventoryMaster)