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
            created_by_id=inventory.created_by_id,
            # Wastage fields (default to non-wastage)
            is_wastage_roll=getattr(inventory, 'is_wastage_roll', False),
            wastage_source_order_id=getattr(inventory, 'wastage_source_order_id', None),
            wastage_source_plan_id=getattr(inventory, 'wastage_source_plan_id', None)
        )
        db.add(db_inventory)
        db.commit()
        db.refresh(db_inventory)
        return db_inventory
    
    def create_wastage_rolls_from_plan(
        self, 
        db: Session, 
        *,
        plan_id: UUID,
        wastage_items: List[Dict[str, Any]], 
        user_id: UUID
    ) -> List[models.InventoryMaster]:
        """Create wastage inventory rolls from plan execution (9-21 inches)"""
        created_wastage = []
        
        for wastage in wastage_items:
            width = wastage['width_inches']
            
            # Only create wastage inventory for 9-21 inch range
            if 9 <= width <= 21:
                db_wastage = models.InventoryMaster(
                    paper_id=wastage['paper_id'],
                    width_inches=width,
                    weight_kg=0,  # Will be updated via QR scan
                    roll_type="cut",
                    status="available",
                    location="waste_storage",
                    created_by_id=user_id,
                    # Wastage specific fields
                    is_wastage_roll=True,
                    wastage_source_order_id=wastage.get('source_order_id'),
                    wastage_source_plan_id=plan_id
                )
                db.add(db_wastage)
                created_wastage.append(db_wastage)
        
        if created_wastage:
            db.commit()
            for item in created_wastage:
                db.refresh(item)
        
        return created_wastage
    
    def get_available_wastage_rolls(
        self, 
        db: Session, 
        *, 
        paper_id: UUID = None, 
        width_inches: float = None
    ) -> List[models.InventoryMaster]:
        """Get available wastage rolls for allocation"""
        query = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.is_wastage_roll == True,
            models.InventoryMaster.status == "available"
        ).options(joinedload(models.InventoryMaster.paper))
        
        if paper_id:
            query = query.filter(models.InventoryMaster.paper_id == paper_id)
        if width_inches:
            query = query.filter(models.InventoryMaster.width_inches == width_inches)
            
        return query.order_by(models.InventoryMaster.weight_kg.desc()).all()
    
    def allocate_wastage_to_order(
        self, 
        db: Session, 
        *, 
        wastage_id: UUID, 
        order_id: UUID
    ) -> Optional[models.InventoryMaster]:
        """Allocate wastage roll to an order"""
        wastage_roll = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.id == wastage_id,
            models.InventoryMaster.is_wastage_roll == True,
            models.InventoryMaster.status == "available"
        ).first()
        
        if wastage_roll:
            wastage_roll.allocated_to_order_id = order_id
            wastage_roll.status = "allocated"
            db.commit()
            db.refresh(wastage_roll)
            
        return wastage_roll
    
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