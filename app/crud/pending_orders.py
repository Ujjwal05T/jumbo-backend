from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, desc
from typing import List, Optional, Dict, Any
from uuid import UUID
from collections import defaultdict

from .base import CRUDBase
from .. import models, schemas


class CRUDPendingOrder(CRUDBase[models.PendingOrderItem, schemas.PendingOrderItemCreate, schemas.PendingOrderItemUpdate]):
    def get_pending_order_items(
        self, 
        db: Session, 
        *, 
        skip: int = 0, 
        limit: int = 100, 
        status: str = "pending"
    ) -> List[models.PendingOrderItem]:
        """Get pending order items with filtering"""
        return (
            db.query(models.PendingOrderItem)
            .options(joinedload(models.PendingOrderItem.original_order).joinedload(models.OrderMaster.client))
            .filter(models.PendingOrderItem.status == status)
            .order_by(desc(models.PendingOrderItem.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )
    
    def get_pending_orders_by_specs(
        self, db: Session, paper_specs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get pending orders grouped by paper specifications - NEW FLOW"""
        if not paper_specs:
            return []
        
        # Build filter conditions for multiple paper specs
        spec_conditions = []
        for spec in paper_specs:
            spec_condition = and_(
                models.PendingOrderItem.gsm == spec['gsm'],
                models.PendingOrderItem.bf == spec['bf'],
                models.PendingOrderItem.shade == spec['shade']
            )
            spec_conditions.append(spec_condition)
        
        # Combine with OR
        from sqlalchemy import or_
        paper_filter = or_(*spec_conditions) if len(spec_conditions) > 1 else spec_conditions[0]
        
        pending_items = (
            db.query(models.PendingOrderItem)
            .filter(
                and_(
                    models.PendingOrderItem.status == "pending",
                    paper_filter
                )
            )
            .all()
        )
        
        # Convert to optimizer format
        pending_requirements = []
        for item in pending_items:
            pending_requirements.append({
                'width': float(item.width_inches),
                'quantity': item.quantity_pending,
                'gsm': item.gsm,
                'bf': float(item.bf),
                'shade': item.shade,
                'pending_order_id': str(item.id),
                'original_order_id': str(item.original_order_id),
                'reason': item.reason
            })
        
        return pending_requirements
    
    def create_pending_order_item(
        self, db: Session, *, pending: schemas.PendingOrderItemCreate
    ) -> models.PendingOrderItem:
        """Create new pending order item"""
        db_pending = models.PendingOrderItem(
            original_order_id=pending.original_order_id,
            width_inches=pending.width_inches,
            gsm=pending.gsm,
            bf=pending.bf,
            shade=pending.shade,
            quantity_pending=pending.quantity_pending,
            reason=pending.reason,
            created_by_id=pending.created_by_id
        )
        db.add(db_pending)
        db.commit()
        db.refresh(db_pending)
        return db_pending
    
    def create_pending_items_from_optimization(
        self, db: Session, pending_orders: List[Dict[str, Any]], user_id: UUID
    ) -> List[models.PendingOrderItem]:
        """Create pending order items from optimization output - NEW FLOW"""
        created_items = []
        
        for pending in pending_orders:
            # Check if similar pending item already exists
            existing = db.query(models.PendingOrderItem).filter(
                and_(
                    models.PendingOrderItem.width_inches == pending['width'],
                    models.PendingOrderItem.gsm == pending['gsm'],
                    models.PendingOrderItem.bf == pending['bf'],
                    models.PendingOrderItem.shade == pending['shade'],
                    models.PendingOrderItem.status == "pending"
                )
            ).first()
            
            if existing:
                # Update existing quantity
                existing.quantity_pending += pending['quantity']
                created_items.append(existing)
            else:
                # Create new pending item (original_order_id should be provided by workflow manager)
                original_order_id = pending.get('original_order_id')
                if not original_order_id:
                    raise ValueError(f"original_order_id is required for pending order: {pending}")
                
                db_pending = models.PendingOrderItem(
                    original_order_id=original_order_id,
                    width_inches=pending['width'],
                    gsm=pending['gsm'],
                    bf=pending['bf'],
                    shade=pending['shade'],
                    quantity_pending=pending['quantity'],
                    reason=pending.get('reason', 'waste_too_high'),
                    created_by_id=user_id
                )
                db.add(db_pending)
                created_items.append(db_pending)
        
        if created_items:
            db.commit()
            for item in created_items:
                db.refresh(item)
        
        return created_items
    
    def get_pending_items_summary(self, db: Session) -> Dict[str, Any]:
        """Get summary statistics for pending order items"""
        # Total pending items
        total_pending = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "pending"
        ).count()
        
        # Total pending quantity
        total_quantity = db.query(func.sum(models.PendingOrderItem.quantity_pending)).filter(
            models.PendingOrderItem.status == "pending"
        ).scalar() or 0
        
        # Group by paper specs
        spec_groups = db.query(
            models.PendingOrderItem.gsm,
            models.PendingOrderItem.bf,
            models.PendingOrderItem.shade,
            func.count(models.PendingOrderItem.id).label('count'),
            func.sum(models.PendingOrderItem.quantity_pending).label('total_quantity')
        ).filter(
            models.PendingOrderItem.status == "pending"
        ).group_by(
            models.PendingOrderItem.gsm,
            models.PendingOrderItem.bf,
            models.PendingOrderItem.shade
        ).all()
        
        return {
            "total_pending_items": total_pending,
            "total_pending_quantity": int(total_quantity),
            "unique_specifications": len(spec_groups),
            "specification_breakdown": [
                {
                    "gsm": group.gsm,
                    "bf": float(group.bf),
                    "shade": group.shade,
                    "item_count": group.count,
                    "total_quantity": int(group.total_quantity)
                }
                for group in spec_groups
            ]
        }
    
    def get_consolidation_opportunities(self, db: Session) -> Dict[str, Any]:
        """Get consolidation opportunities for pending items"""
        # Group pending items by paper specs
        pending_groups = defaultdict(list)
        
        pending_items = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "pending"
        ).all()
        
        for item in pending_items:
            spec_key = (item.gsm, float(item.bf), item.shade)
            pending_groups[spec_key].append({
                "id": str(item.id),
                "width": float(item.width_inches),
                "quantity": item.quantity_pending,
                "reason": item.reason,
                "created_at": item.created_at.isoformat()
            })
        
        # Find consolidation opportunities
        opportunities = []
        for spec_key, items in pending_groups.items():
            if len(items) > 1:  # Multiple items with same specs
                total_quantity = sum(item['quantity'] for item in items)
                opportunities.append({
                    "gsm": spec_key[0],
                    "bf": spec_key[1],
                    "shade": spec_key[2],
                    "item_count": len(items),
                    "total_quantity": total_quantity,
                    "items": items
                })
        
        return {
            "consolidation_opportunities": len(opportunities),
            "opportunities": opportunities
        }
    
    def debug_pending_items(self, db: Session) -> Dict[str, Any]:
        """Debug endpoint to check pending items data"""
        pending_items = db.query(models.PendingOrderItem).all()
        
        return {
            "total_items": len(pending_items),
            "status_breakdown": {
                status: len([item for item in pending_items if item.status == status])
                for status in ["pending", "included_in_plan", "resolved", "cancelled"]
            },
            "recent_items": [
                {
                    "id": str(item.id),
                    "width": float(item.width_inches),
                    "gsm": item.gsm,
                    "bf": float(item.bf),
                    "shade": item.shade,
                    "quantity": item.quantity_pending,
                    "status": item.status,
                    "created_at": item.created_at.isoformat()
                }
                for item in sorted(pending_items, key=lambda x: x.created_at, reverse=True)[:10]
            ]
        }


pending_order = CRUDPendingOrder(models.PendingOrderItem)