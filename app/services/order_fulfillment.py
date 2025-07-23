from typing import List, Dict, Optional, Tuple
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
import logging

from .. import models, schemas
from .cutting_optimizer import CuttingOptimizer
from .status_service import StatusService

logger = logging.getLogger(__name__)

class OrderFulfillmentService:
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id
        self.optimizer = CuttingOptimizer()
        self.status_service = StatusService(db, user_id)
        self.min_jumbo_roll_width = 36  # Minimum useful width for a jumbo roll

    def fulfill_order(self, order_id: uuid.UUID) -> Dict:
        """
        Fulfill an order with transaction management and status tracking.
        Handles both full and partial fulfillment with backorder creation.
        """
        try:
            with self.db.begin_nested():  # Start a savepoint
                order = self._get_order_for_fulfillment(order_id)
                self.status_service.update_status(order, "processing", commit=False)
                
                # Try to fulfill from inventory first
                fulfilled, remaining = self._fulfill_from_inventory(order)
                
                if remaining > 0:
                    # If we couldn't fulfill everything from inventory
                    result = self._handle_remaining_quantity(order, remaining)
                else:
                    # Everything was fulfilled from inventory
                    self.status_service.update_status(
                        order, 
                        "completed",
                        "Order fully fulfilled from existing inventory"
                    )
                    result = {
                        "status": "completed",
                        "order_id": str(order.id),
                        "message": "Order fully fulfilled from existing inventory"
                    }
                
                self.db.commit()
                return result
                
        except Exception as e:
            self.db.rollback()
            logger.error(f"Order fulfillment failed for order {order_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Order fulfillment failed: {str(e)}"
            )

    def _get_order_for_fulfillment(self, order_id: uuid.UUID) -> models.Order:
        """Get and validate order for fulfillment"""
        order = self.db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise ValueError("Order not found")
            
        if order.status == "completed":
            raise ValueError("Order is already completed")
            
        if order.status == "cancelled":
            raise ValueError("Cannot fulfill a cancelled order")
            
        return order

    def _fulfill_from_inventory(self, order: models.Order) -> Tuple[bool, int]:
        """
        Try to fulfill order from existing cut rolls in inventory.
        Returns (success, remaining_quantity)
        """
        # Find matching cut rolls in inventory
        matching_rolls = self.db.query(models.InventoryItem).join(models.CutRoll).filter(
            models.CutRoll.width_inches == order.width_inches,
            models.CutRoll.gsm == order.gsm,
            models.CutRoll.bf == order.bf,
            models.CutRoll.shade == order.shade,
            models.CutRoll.status == "available",
            models.InventoryItem.allocated_to_order.is_(None)
        ).limit(order.remaining_quantity).all()
        
        allocated = min(len(matching_rolls), order.remaining_quantity)
        
        if allocated == 0:
            return False, order.remaining_quantity
            
        # Allocate the rolls
        for item in matching_rolls[:allocated]:
            item.roll.status = "allocated"
            item.allocated_to_order_id = order.id
            self.db.add(item)
            
            # Log the allocation
            self.status_service._log_status_change(
                model_type="CutRoll",
                model_id=item.roll_id,
                old_status="available",
                new_status="allocated",
                notes=f"Allocated to order {order.id}",
                commit=False
            )
        
        # Update order fulfillment
        order.quantity_fulfilled += allocated
        remaining = order.remaining_quantity
        
        # Update order status based on fulfillment
        if remaining == 0:
            status = "completed"
            message = f"Fully fulfilled {allocated} rolls from inventory"
        else:
            status = "partially_fulfilled"
            message = f"Partially fulfilled {allocated}/{order.quantity_rolls} rolls from inventory"
        
        self.status_service.update_status(
            order,
            status,
            message,
            commit=False
        )
        
        return True, remaining

    def _handle_remaining_quantity(self, order: models.Order, remaining: int) -> Dict:
        """Handle remaining quantity after inventory check"""
        # Try to find a suitable jumbo roll
        jumbo_roll = self._find_matching_jumbo_roll(order, remaining)
        
        if jumbo_roll:
            # Create and execute cutting plan
            cutting_plan = self._create_cutting_plan(order, jumbo_roll, remaining)
            self._execute_cutting_plan(cutting_plan)
            
            # Update order status
            self.status_service.update_status(
                order,
                "completed" if order.is_fully_fulfilled else "partially_fulfilled",
                f"Cut {remaining} rolls from jumbo roll {jumbo_roll.id}"
            )
            
            return {
                "status": "completed" if order.is_fully_fulfilled else "partially_fulfilled",
                "order_id": str(order.id),
                "cutting_plan_id": str(cutting_plan.id),
                "message": f"Cut {remaining} rolls from jumbo roll"
            }
        else:
            # No suitable jumbo roll, create production order
            production_order = self._create_production_order(order, remaining)
            
            # Create backorder for remaining quantity
            backorder = self.status_service.create_backorder(
                order,
                remaining,
                "No suitable jumbo roll available, created production order"
            )
            
            self.status_service.update_status(
                production_order,
                "pending",
                "Awaiting production of jumbo rolls"
            )
            
            return {
                "status": "waiting_for_production",
                "order_id": str(order.id),
                "backorder_id": str(backorder.id),
                "production_order_id": str(production_order.id),
                "message": f"Created production order for {remaining} rolls"
            }

    # ... (rest of the existing methods with status_service integration) ...
