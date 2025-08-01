from typing import List, Dict, Optional, Tuple
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import logging

from .. import models
from .status_service import StatusService
from .id_generator import FrontendIDGenerator

logger = logging.getLogger(__name__)

class PendingOrderService:
    """
    Service to manage pending order items that cannot be immediately fulfilled.
    Provides persistence, tracking, and resolution of pending requirements.
    """
    
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id
        self.status_service = StatusService(db, user_id)
    
    def create_pending_items(self, pending_orders: List[Dict], original_order_id: uuid.UUID, reason: str = "no_suitable_jumbo") -> List[models.PendingOrderItem]:
        """
        Create pending order items from cutting optimizer output.
        
        Args:
            pending_orders: List of pending order dicts from cutting optimizer
            original_order_id: ID of the original order that couldn't be fully fulfilled
            reason: Reason why these items are pending
            
        Returns:
            List of created PendingOrderItem objects
        """
        created_items = []
        
        try:
            for pending in pending_orders:
                # Check if a similar pending item already exists
                existing_item = self.db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.original_order_id == original_order_id,
                    models.PendingOrderItem.width_inches == pending['width'],
                    models.PendingOrderItem.gsm == pending['gsm'],
                    models.PendingOrderItem.shade == pending['shade'],
                    models.PendingOrderItem.bf == pending['bf'],
                    models.PendingOrderItem.status == "pending"
                ).first()
                
                if existing_item:
                    # Update existing item quantity
                    existing_item.quantity_pending += pending['quantity']
                    created_items.append(existing_item)
                    logger.info(f"Updated existing pending item {existing_item.id} with additional {pending['quantity']} units")
                else:
                    # Create new pending item
                    frontend_id = FrontendIDGenerator.generate_frontend_id("pending_order_item", self.db)
                    pending_item = models.PendingOrderItem(
                        frontend_id=frontend_id,
                        original_order_id=original_order_id,
                        width_inches=int(pending['width']),
                        gsm=pending['gsm'],
                        bf=pending['bf'],
                        shade=pending['shade'],
                        quantity_pending=pending['quantity'],
                        reason=reason,
                        status="pending",
                        created_by_id=self.user_id
                    )
                    self.db.add(pending_item)
                    self.db.flush()  # Ensure this record is committed before generating next frontend_id
                    created_items.append(pending_item)
                    logger.info(f"Created pending item for {pending['quantity']} x {pending['width']}\" {pending['shade']} paper")
            
            self.db.commit()
            logger.info(f"Created/updated {len(created_items)} pending order items")
            return created_items
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating pending items: {str(e)}")
            raise
    
    def get_pending_items_by_specification(self, gsm: int, shade: str, bf: float) -> List[models.PendingOrderItem]:
        """Get all pending items matching a specific paper specification."""
        return self.db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.gsm == gsm,
            models.PendingOrderItem.shade == shade,
            models.PendingOrderItem.bf == bf,
            models.PendingOrderItem.status == "pending"
        ).all()
    
    def get_consolidation_opportunities(self) -> List[Dict]:
        """
        Get pending items grouped by specification for consolidation opportunities.
        """
        from sqlalchemy import func
        
        # Group pending items by specification
        grouped_items = self.db.query(
            models.PendingOrderItem.gsm,
            models.PendingOrderItem.shade,
            models.PendingOrderItem.bf,
            func.count(models.PendingOrderItem.id).label('item_count'),
            func.sum(models.PendingOrderItem.quantity_pending).label('total_quantity')
        ).filter(
            models.PendingOrderItem.status == "pending"
        ).group_by(
            models.PendingOrderItem.gsm,
            models.PendingOrderItem.shade,
            models.PendingOrderItem.bf
        ).all()
        
        opportunities = []
        for group in grouped_items:
            # Get the actual items in this group
            items_in_group = self.get_pending_items_by_specification(
                group.gsm, group.shade, group.bf
            )
            
            opportunities.append({
                "specification": {
                    "gsm": group.gsm,
                    "shade": group.shade,
                    "bf": float(group.bf)
                },
                "item_count": group.item_count,
                "total_quantity": int(group.total_quantity),
                "pending_item_ids": [str(item.id) for item in items_in_group],
                "original_order_ids": list(set(str(item.original_order_id) for item in items_in_group)),
                "priority": "High" if group.total_quantity >= 10 else "Medium" if group.total_quantity >= 5 else "Low",
                "estimated_jumbos_needed": max(1, int(group.total_quantity / 8))  # Rough estimate
            })
        
        return opportunities
    
    def link_to_production_order(self, pending_item_ids: List[uuid.UUID], production_order_id: uuid.UUID) -> int:
        """
        Link pending items to a production order.
        
        Returns:
            Number of items linked
        """
        try:
            updated_count = self.db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.id.in_(pending_item_ids),
                models.PendingOrderItem.status == "pending"
            ).update({
                models.PendingOrderItem.production_order_id: production_order_id,
                models.PendingOrderItem.status: "in_production"
            }, synchronize_session=False)
            
            self.db.commit()
            logger.info(f"Linked {updated_count} pending items to production order {production_order_id}")
            return updated_count
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error linking pending items to production order: {str(e)}")
            raise
    
    def resolve_pending_items(self, specification: Dict[str, any], jumbo_roll_id: uuid.UUID) -> List[models.PendingOrderItem]:
        """
        Resolve pending items when a suitable jumbo roll becomes available.
        
        Args:
            specification: Paper specification dict (gsm, shade, bf)
            jumbo_roll_id: ID of the jumbo roll that can fulfill these items
            
        Returns:
            List of resolved pending items
        """
        try:
            # Find matching pending items
            pending_items = self.get_pending_items_by_specification(
                specification['gsm'], specification['shade'], specification['bf']
            )
            
            resolved_items = []
            for item in pending_items:
                item.status = "resolved"
                item.resolved_at = datetime.utcnow()
                resolved_items.append(item)
                
                # Update the original order status if needed
                original_order = item.original_order
                if original_order and not original_order.is_fully_fulfilled:
                    # Check if all pending items for this order are now resolved
                    remaining_pending = self.db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.original_order_id == original_order.id,
                        models.PendingOrderItem.status == "pending"
                    ).count()
                    
                    if remaining_pending == 0:
                        self.status_service.update_status(
                            original_order,
                            "in_process",
                            f"All pending items resolved with jumbo roll {jumbo_roll_id}",
                            commit=False
                        )
            
            self.db.commit()
            logger.info(f"Resolved {len(resolved_items)} pending items with jumbo roll {jumbo_roll_id}")
            return resolved_items
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error resolving pending items: {str(e)}")
            raise
    
    def get_pending_summary(self) -> Dict:
        """Get summary statistics for pending orders."""
        from sqlalchemy import func
        
        # Total pending items
        total_pending = self.db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "pending"
        ).count()
        
        # Items in production
        in_production = self.db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "in_production"
        ).count()
        
        # Total quantity pending
        total_quantity = self.db.query(
            func.sum(models.PendingOrderItem.quantity_pending)
        ).filter(
            models.PendingOrderItem.status == "pending"
        ).scalar() or 0
        
        # Unique specifications
        unique_specs = self.db.query(
            models.PendingOrderItem.gsm,
            models.PendingOrderItem.shade,
            models.PendingOrderItem.bf
        ).filter(
            models.PendingOrderItem.status == "pending"
        ).distinct().count()
        
        # Oldest pending item
        oldest_pending = self.db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "pending"
        ).order_by(models.PendingOrderItem.created_at).first()
        
        return {
            "total_pending_items": total_pending,
            "items_in_production": in_production,
            "total_quantity_pending": int(total_quantity),
            "unique_specifications": unique_specs,
            "oldest_pending_date": oldest_pending.created_at if oldest_pending else None,
            "consolidation_opportunities": len(self.get_consolidation_opportunities())
        }
    
    def cleanup_resolved_items(self, days_old: int = 30) -> int:
        """
        Clean up resolved pending items older than specified days.
        
        Args:
            days_old: Number of days after which resolved items should be cleaned up
            
        Returns:
            Number of items cleaned up
        """
        from datetime import timedelta
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        try:
            deleted_count = self.db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.status == "resolved",
                models.PendingOrderItem.resolved_at < cutoff_date
            ).delete(synchronize_session=False)
            
            self.db.commit()
            logger.info(f"Cleaned up {deleted_count} resolved pending items older than {days_old} days")
            return deleted_count
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error cleaning up resolved items: {str(e)}")
            raise