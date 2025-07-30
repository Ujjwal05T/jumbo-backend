from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid

from .base import CRUDBase
from .. import models, schemas


class CRUDOrder(CRUDBase[models.OrderMaster, schemas.OrderMasterCreate, schemas.OrderMasterUpdate]):
    def get_orders(
        self, 
        db: Session, 
        *, 
        skip: int = 0, 
        limit: int = 100, 
        status: str = None,
        client_id: str = None
    ) -> List[models.OrderMaster]:
        """Get orders with filtering"""
        query = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
        )
        
        if status:
            query = query.filter(models.OrderMaster.status == status)
        if client_id:
            query = query.filter(models.OrderMaster.client_id == UUID(client_id))
            
        return query.order_by(models.OrderMaster.created_at.desc()).offset(skip).limit(limit).all()
    
    def get_order(self, db: Session, order_id: UUID) -> Optional[models.OrderMaster]:
        """Get order by ID with all relationships"""
        return (
            db.query(models.OrderMaster)
            .options(
                joinedload(models.OrderMaster.client),
                joinedload(models.OrderMaster.created_by),
                joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
            )
            .filter(models.OrderMaster.id == order_id)
            .first()
        )
    
    def create_order_with_items(self, db: Session, *, order_data: Dict[str, Any]) -> models.OrderMaster:
        """Create order with multiple order items"""
        # Create order master
        db_order = models.OrderMaster(
            client_id=UUID(order_data["client_id"]),
            status=order_data.get("status", "created"),
            priority=order_data.get("priority", "normal"),
            payment_type=order_data.get("payment_type", "bill"),
            delivery_date=order_data.get("delivery_date"),
            created_by_id=UUID(order_data["created_by_id"])
        )
        db.add(db_order)
        db.flush()  # Get order ID
        
        # Create order items
        for item_data in order_data.get("order_items", []):
            db_item = models.OrderItem(
                order_id=db_order.id,
                paper_id=UUID(item_data["paper_id"]),
                width_inches=item_data["width_inches"],
                quantity_rolls=item_data["quantity_rolls"],
                quantity_kg=item_data["quantity_kg"],
                rate=item_data["rate"],
                amount=item_data["amount"]
            )
            db.add(db_item)
        
        db.commit()
        db.refresh(db_order)
        
        # Return the order with all relationships loaded
        return self.get_order(db, db_order.id)
    
    def update_order(
        self, db: Session, *, order_id: UUID, order_update: schemas.OrderMasterUpdate
    ) -> Optional[models.OrderMaster]:
        """Update order"""
        db_order = self.get_order(db, order_id)
        if db_order:
            update_data = order_update.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(db_order, field, value)
            db.commit()
            db.refresh(db_order)
        return db_order


class CRUDOrderItem(CRUDBase[models.OrderItem, schemas.OrderItemCreate, schemas.OrderItemUpdate]):
    def get_order_items(self, db: Session, order_id: UUID) -> List[models.OrderItem]:
        """Get all items for an order"""
        return (
            db.query(models.OrderItem)
            .options(joinedload(models.OrderItem.paper))
            .filter(models.OrderItem.order_id == order_id)
            .all()
        )
    
    def get_order_item(self, db: Session, item_id: UUID) -> Optional[models.OrderItem]:
        """Get order item by ID"""
        return (
            db.query(models.OrderItem)
            .options(
                joinedload(models.OrderItem.order).joinedload(models.OrderMaster.client),
                joinedload(models.OrderItem.paper)
            )
            .filter(models.OrderItem.id == item_id)
            .first()
        )


order = CRUDOrder(models.OrderMaster)
order_item = CRUDOrderItem(models.OrderItem)