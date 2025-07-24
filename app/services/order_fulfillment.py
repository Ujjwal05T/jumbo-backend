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
                    # Check for matching pending orders before creating cutting plans
                    matching_orders = self._find_matching_pending_orders(order)
                    if matching_orders:
                        # Process together with matching orders for better optimization
                        result = self._handle_batch_fulfillment([order] + matching_orders)
                    else:
                        # Process single order
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
            models.InventoryItem.allocated_to_order_id == None
        ).order_by(models.InventoryItem.id).limit(order.remaining_quantity).all()
        
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
        """Handle remaining quantity using the new cutting optimizer"""
        # Create order requirements for the optimizer
        order_requirements = [{
            'width': order.width_inches,
            'quantity': remaining,
            'gsm': order.gsm,
            'bf': float(order.bf),
            'shade': order.shade,
            'min_length': 1000
        }]
        
        # Use the new cutting optimizer
        plan = self.optimizer.generate_optimized_plan(
            order_requirements=order_requirements,
            interactive=False
        )
        
        # Check if we can fulfill from the plan
        if plan['jumbo_rolls_used']:
            # We can cut from available jumbo rolls
            cutting_plans_created = []
            
            for jumbo_plan in plan['jumbo_rolls_used']:
                # Find or create jumbo roll
                jumbo_roll = self._find_or_create_jumbo_roll(jumbo_plan['paper_spec'])
                
                # Create cutting plan
                cutting_plan = models.CuttingPlan(
                    order_id=order.id,
                    jumbo_roll_id=jumbo_roll.id,
                    cut_pattern=jumbo_plan['rolls'],
                    expected_waste_percentage=jumbo_plan['waste_percentage'],
                    status="planned"
                )
                self.db.add(cutting_plan)
                cutting_plans_created.append(cutting_plan)
                
                # Update jumbo roll status
                jumbo_roll.status = models.JumboRollStatus.CUTTING
            
            # Update order fulfillment
            fulfilled_quantity = sum(len(jp['rolls']) for jp in plan['jumbo_rolls_used'])
            order.quantity_fulfilled += min(fulfilled_quantity, remaining)
            
            self.status_service.update_status(
                order,
                "completed" if order.is_fully_fulfilled else "partially_fulfilled",
                f"Created {len(cutting_plans_created)} cutting plans"
            )
            
            return {
                "status": "completed" if order.is_fully_fulfilled else "partially_fulfilled",
                "order_id": str(order.id),
                "cutting_plans_created": len(cutting_plans_created),
                "message": f"Created cutting plans for {fulfilled_quantity} rolls"
            }
        
        # Handle pending orders - create production orders
        if plan['pending_orders']:
            production_orders = []
            total_pending = 0
            
            for pending in plan['pending_orders']:
                production_order = models.ProductionOrder(
                    gsm=pending['gsm'],
                    bf=pending['bf'],
                    shade=pending['shade'],
                    quantity=1,  # One jumbo roll per production order
                    status="pending",
                    order_id=order.id
                )
                self.db.add(production_order)
                production_orders.append(production_order)
                total_pending += pending['quantity']
            
            # Create backorder for pending quantity
            if total_pending > 0:
                backorder = self.status_service.create_backorder(
                    order,
                    total_pending,
                    f"Created {len(production_orders)} production orders for pending rolls"
                )
                
                return {
                    "status": "waiting_for_production",
                    "order_id": str(order.id),
                    "backorder_id": str(backorder.id),
                    "production_orders_created": len(production_orders),
                    "message": f"Created production orders for {total_pending} pending rolls"
                }
        
        # Fallback - no solution found
        return {
            "status": "cannot_fulfill",
            "order_id": str(order.id),
            "message": "No suitable cutting plan or production option available"
        }
    
    def _find_or_create_jumbo_roll(self, paper_spec: Dict[str, Any]) -> models.JumboRoll:
        """Find an existing jumbo roll or create a new one with the required specifications."""
        # Try to find an existing available jumbo roll
        jumbo_roll = self.db.query(models.JumboRoll).filter(
            models.JumboRoll.gsm == paper_spec['gsm'],
            models.JumboRoll.bf == paper_spec['bf'],
            models.JumboRoll.shade == paper_spec['shade'],
            models.JumboRoll.status == models.JumboRollStatus.AVAILABLE
        ).first()
        
        if not jumbo_roll:
            # Create a new jumbo roll (this would typically be from production)
            jumbo_roll = models.JumboRoll(
                gsm=paper_spec['gsm'],
                bf=paper_spec['bf'],
                shade=paper_spec['shade'],
                status=models.JumboRollStatus.AVAILABLE
            )
            self.db.add(jumbo_roll)
            self.db.flush()  # Get the ID without committing
        
        return jumbo_roll
    
    def _find_matching_pending_orders(self, current_order: models.Order) -> List[models.Order]:
        """
        Find pending orders that match the current order's specifications.
        This allows for batch processing and better optimization.
        """
        matching_orders = self.db.query(models.Order).filter(
            models.Order.id != current_order.id,  # Exclude current order
            models.Order.gsm == current_order.gsm,
            models.Order.shade == current_order.shade,
            models.Order.bf == current_order.bf,
            models.Order.status.in_([models.OrderStatus.PENDING, models.OrderStatus.PARTIALLY_FULFILLED]),
            models.Order.remaining_quantity > 0
        ).order_by(models.Order.id).limit(10).all()  # Limit to prevent too large batches
        
        if matching_orders:
            logger.info(f"Found {len(matching_orders)} matching pending orders for batch processing")
        
        return matching_orders
    
    def _handle_batch_fulfillment(self, orders: List[models.Order]) -> Dict:
        """
        Handle fulfillment of multiple orders together for better optimization.
        """
        logger.info(f"Processing batch of {len(orders)} orders together")
        
        # Use workflow manager for batch processing
        from .workflow_manager import WorkflowManager
        workflow_manager = WorkflowManager(self.db, self.user_id)
        
        order_ids = [order.id for order in orders]
        result = workflow_manager.process_multiple_orders(order_ids)
        
        # Return result in the expected format for single order fulfillment
        primary_order = orders[0]
        return {
            "status": "batch_processed",
            "order_id": str(primary_order.id),
            "batch_size": len(orders),
            "cutting_plans_created": result.get("summary", {}).get("cutting_plans_created", 0),
            "production_orders_created": result.get("summary", {}).get("production_orders_created", 0),
            "message": f"Processed in batch with {len(orders)-1} matching orders for better optimization"
        }
