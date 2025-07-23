from typing import Any, Type, Optional, TypeVar, Generic
from sqlalchemy.orm import Session, InstrumentedAttribute
from datetime import datetime
import uuid
import logging

from ..models.status_enums import StatusLog
from ..models.order import Order

logger = logging.getLogger(__name__)

T = TypeVar('T')

class StatusService:
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id

    def update_status(
        self,
        obj: Any,
        new_status: str,
        notes: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """
        Update the status of any model that has a status field.
        Automatically logs the status change.
        """
        model_type = obj.__class__.__name__
        old_status = getattr(obj, 'status', None)
        
        if not hasattr(obj, 'status'):
            raise ValueError(f"Model {model_type} does not have a status field")
        
        # Update the status
        setattr(obj, 'status', new_status)
        
        # Update timestamps if they exist
        if hasattr(obj, 'updated_at'):
            obj.updated_at = datetime.utcnow()
        
        # Log the status change
        self._log_status_change(
            model_type=model_type,
            model_id=obj.id,
            old_status=old_status,
            new_status=new_status,
            notes=notes,
            commit=commit
        )
        
        if commit:
            try:
                self.db.commit()
            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to update status for {model_type} {obj.id}: {str(e)}")
                raise

    def _log_status_change(
        self,
        model_type: str,
        model_id: uuid.UUID,
        old_status: Optional[str],
        new_status: str,
        notes: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """Create a status log entry"""
        log = StatusLog(
            model_type=model_type,
            model_id=model_id,
            old_status=old_status,
            new_status=new_status,
            changed_by_id=self.user_id,
            notes=notes
        )
        self.db.add(log)
        
        if commit:
            try:
                self.db.commit()
            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to log status change: {str(e)}")
                raise

    def get_status_history(
        self,
        model_type: str,
        model_id: uuid.UUID,
        limit: int = 100
    ) -> list[StatusLog]:
        """Get status change history for a model"""
        return (
            self.db.query(StatusLog)
            .filter(
                StatusLog.model_type == model_type,
                StatusLog.model_id == model_id
            )
            .order_by(StatusLog.changed_at.desc())
            .limit(limit)
            .all()
        )

    def create_backorder(
        self,
        order: Order,
        quantity: int,
        notes: Optional[str] = None
    ) -> Order:
        """Create a backorder from an existing order"""
        if quantity <= 0:
            raise ValueError("Backorder quantity must be greater than 0")
            
        if quantity > order.remaining_quantity:
            raise ValueError("Backorder quantity exceeds remaining quantity")
        
        # Create the backorder
        backorder = Order(
            customer_id=order.customer_id,
            width_inches=order.width_inches,
            gsm=order.gsm,
            bf=order.bf,
            shade=order.shade,
            quantity_rolls=quantity,
            status="pending",
            parent_order_id=order.id,
            original_order_id=order.original_order_id or order.id,
            notes=f"Backorder from order {order.id}. {notes or ''}".strip()
        )
        
        self.db.add(backorder)
        
        # Update the original order's fulfilled quantity
        order.quantity_fulfilled = order.quantity_rolls - quantity
        
        # Log the backorder creation
        self.update_status(
            order,
            "partially_fulfilled" if order.remaining_quantity > 0 else "completed",
            f"Created backorder for {quantity} rolls. {notes or ''}".strip(),
            commit=False
        )
        
        try:
            self.db.commit()
            return backorder
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create backorder: {str(e)}")
            raise
