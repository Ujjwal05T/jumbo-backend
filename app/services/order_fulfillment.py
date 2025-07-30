from typing import List, Dict, Optional, Tuple
import uuid
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status
import logging
import json

from .. import models, schemas, crud
from .cutting_optimizer import CuttingOptimizer

logger = logging.getLogger(__name__)

class OrderFulfillmentService:
    """
    Service to handle manual order fulfillment using master-based architecture.
    NEW FLOW: Orders → WorkflowManager.process_multiple_orders() → Direct to optimization
    This service now only handles manual fulfillment tracking, not automatic inventory checking.
    """
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id
        self.optimizer = CuttingOptimizer()
        self.min_jumbo_roll_width = 36  # Minimum useful width for a jumbo roll

    def fulfill_order(self, order_id: uuid.UUID, quantity_to_fulfill: int = None) -> Dict:
        """
        NEW FLOW: Manual order fulfillment - ONLY updates quantity_fulfilled.
        No automatic plan generation - purely user-controlled fulfillment tracking.
        
        Args:
            order_id: ID of order to fulfill
            quantity_to_fulfill: Quantity to mark as fulfilled (optional, defaults to remaining)
            
        Returns:
            Updated order status
        """
        try:
            # Get order with related data via foreign keys
            order = self._get_order_with_relationships(order_id)
            
            # Calculate remaining quantity
            remaining_qty = order.quantity_rolls - (order.quantity_fulfilled or 0)
            
            if remaining_qty <= 0:
                return {
                    "status": "already_fulfilled",
                    "order_id": str(order.id),
                    "message": "Order is already fully fulfilled"
                }
            
            # Determine quantity to fulfill
            if quantity_to_fulfill is None:
                quantity_to_fulfill = remaining_qty
            else:
                quantity_to_fulfill = min(quantity_to_fulfill, remaining_qty)
            
            # NEW FLOW: Simply update quantity_fulfilled (no inventory allocation)
            order.quantity_fulfilled = (order.quantity_fulfilled or 0) + quantity_to_fulfill
            order.updated_at = datetime.utcnow()
            
            # Update order status based on fulfillment
            if order.quantity_fulfilled >= order.quantity_rolls:
                order.status = "completed"
                status_message = "Order fully fulfilled"
            else:
                order.status = "in_process"
                status_message = f"Order partially fulfilled: {order.quantity_fulfilled}/{order.quantity_rolls}"
            
            self.db.commit()
            
            return {
                "status": "success",
                "order_id": str(order.id),
                "quantity_fulfilled": quantity_to_fulfill,
                "total_fulfilled": order.quantity_fulfilled,
                "remaining_quantity": order.quantity_rolls - order.quantity_fulfilled,
                "order_status": order.status,
                "message": status_message
            }
                
        except Exception as e:
            self.db.rollback()
            logger.error(f"Order fulfillment failed for order {order_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Order fulfillment failed: {str(e)}"
            )

    def _get_order_with_relationships(self, order_id: uuid.UUID) -> models.OrderMaster:
        """Get order with all related data via foreign keys (User, Client, Paper)"""
        order = self.db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.paper),
            joinedload(models.OrderMaster.created_by)
        ).filter(models.OrderMaster.id == order_id).first()
        
        if not order:
            raise ValueError("Order not found")
            
        if order.status == "completed":
            raise ValueError("Order is already completed")
            
        if order.status == "cancelled":
            raise ValueError("Cannot fulfill a cancelled order")
            
        return order

    # OLD FLOW REMOVED: _fulfill_from_inventory() method
    # New flow always goes directly to cutting optimization

    def bulk_fulfill_orders(self, fulfillment_requests: List[Dict]) -> Dict:
        """
        NEW FLOW: Bulk fulfill multiple orders manually.
        
        Args:
            fulfillment_requests: List of dicts with 'order_id' and 'quantity' 
            
        Returns:
            Summary of bulk fulfillment results
        """
        try:
            results = []
            total_fulfilled = 0
            
            for request in fulfillment_requests:
                order_id = uuid.UUID(request['order_id'])
                quantity = request.get('quantity')
                
                # Fulfill individual order
                result = self.fulfill_order(order_id, quantity)
                results.append(result)
                
                if result['status'] == 'success':
                    total_fulfilled += result['quantity_fulfilled']
            
            return {
                "status": "bulk_fulfillment_completed",
                "orders_processed": len(fulfillment_requests),
                "total_quantity_fulfilled": total_fulfilled,
                "results": results,
                "message": f"Bulk fulfilled {len(fulfillment_requests)} orders with {total_fulfilled} total rolls"
            }
            
        except Exception as e:
            logger.error(f"Bulk fulfillment failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Bulk fulfillment failed: {str(e)}"
            )
    
    def _create_pending_order_from_order(self, order: models.OrderMaster) -> models.PendingOrderMaster:
        """
        Create a PendingOrderMaster from an OrderMaster for unfulfilled quantity.
        This is the first step in the OrderMaster → PendingOrderMaster → PlanMaster flow.
        """
        remaining_qty = order.quantity - (order.quantity_fulfilled or 0)
        
        if remaining_qty <= 0:
            raise ValueError("No remaining quantity to create pending order")
        
        # Check if pending order already exists for this order
        existing_pending = self.db.query(models.PendingOrderMaster).filter(
            models.PendingOrderMaster.original_order_id == order.id,
            models.PendingOrderMaster.status == "pending"
        ).first()
        
        if existing_pending:
            # Update existing pending order
            existing_pending.quantity = remaining_qty
            existing_pending.updated_at = datetime.utcnow()
            logger.info(f"Updated existing pending order {existing_pending.id} for order {order.id}")
            return existing_pending
        
        # Create new pending order
        pending_order = models.PendingOrderMaster(
            original_order_id=order.id,
            paper_id=order.paper_id,
            width=order.width_inches,
            quantity=remaining_qty,
            min_length=order.min_length,
            reason="insufficient_inventory",
            status="pending",
            created_by_id=self.user_id or order.created_by_id
        )
        
        self.db.add(pending_order)
        self.db.flush()  # Get the ID
        
        logger.info(f"Created pending order {pending_order.id} for {remaining_qty} rolls from order {order.id}")
        return pending_order
    
    def _create_plan_from_pending_orders(self, pending_orders: List[models.PendingOrderMaster]) -> Dict:
        """
        Create a PlanMaster from PendingOrderMaster records.
        This is the second step in the OrderMaster → PendingOrderMaster → PlanMaster flow.
        """
        if not pending_orders:
            return {"status": "no_pending_orders", "message": "No pending orders to process"}
        
        # Convert pending orders to optimizer format
        order_requirements = []
        for pending in pending_orders:
            if pending.paper:
                order_requirements.append({
                    'width': float(pending.width),
                    'quantity': pending.quantity,
                    'gsm': pending.paper.gsm,
                    'bf': float(pending.paper.bf),
                    'shade': pending.paper.shade,
                    'min_length': pending.min_length or 1000,
                    'pending_order_id': str(pending.id),
                    'original_order_id': str(pending.original_order_id)
                })
        
        if not order_requirements:
            return {"status": "no_valid_requirements", "message": "No valid order requirements found"}
        
        # Run optimization
        optimization_result = self.optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            interactive=False
        )
        
        # Create plan if we have jumbo rolls that can be cut
        if optimization_result['jumbo_rolls_used']:
            plan = self._create_plan_master_from_optimization(pending_orders, optimization_result)
            
            # Update pending orders status
            for pending in pending_orders:
                pending.status = "planned"
                pending.updated_at = datetime.utcnow()
            
            return {
                "status": "plan_created",
                "plan_id": str(plan.id),
                "pending_orders_processed": len(pending_orders),
                "jumbo_rolls_used": len(optimization_result['jumbo_rolls_used']),
                "message": f"Created cutting plan {plan.id} from {len(pending_orders)} pending orders"
            }
        
        # Handle case where production is needed
        if optimization_result['pending_orders']:
            production_orders = self._create_production_orders_from_pending(
                pending_orders, optimization_result['pending_orders']
            )
            
            return {
                "status": "production_required",
                "production_orders_created": len(production_orders),
                "pending_orders": len(optimization_result['pending_orders']),
                "message": f"Created {len(production_orders)} production orders for pending requirements"
            }
        
        return {
            "status": "no_solution",
            "message": "No cutting plan or production solution found"
        }
    
    def _create_plan_master_from_optimization(
        self, 
        pending_orders: List[models.PendingOrderMaster], 
        optimization_result: Dict
    ) -> models.PlanMaster:
        """
        Create a PlanMaster from optimization results.
        This completes the OrderMaster → PendingOrderMaster → PlanMaster flow.
        """
        # Create plan master
        plan_name = f"Plan from {len(pending_orders)} pending orders - {datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        plan = models.PlanMaster(
            name=plan_name,
            cut_pattern=json.dumps(optimization_result['jumbo_rolls_used']),
            expected_waste_percentage=optimization_result['summary']['overall_waste_percentage'],
            status="planned",
            created_by_id=self.user_id
        )
        
        self.db.add(plan)
        self.db.flush()  # Get the ID
        
        # Create plan-order links for original orders
        original_order_ids = set()
        for pending in pending_orders:
            if pending.original_order_id:
                original_order_ids.add(pending.original_order_id)
        
        for order_id in original_order_ids:
            # Calculate quantity allocated from this order
            allocated_qty = sum(
                pending.quantity for pending in pending_orders 
                if pending.original_order_id == order_id
            )
            
            plan_order_link = models.PlanOrderLink(
                plan_id=plan.id,
                order_id=order_id,
                quantity_allocated=allocated_qty
            )
            self.db.add(plan_order_link)
        
        # TODO: Create plan-inventory links when inventory allocation is implemented
        
        logger.info(f"Created plan master {plan.id} from {len(pending_orders)} pending orders")
        return plan
    
    def _create_production_orders_from_pending(
        self, 
        pending_orders: List[models.PendingOrderMaster], 
        pending_requirements: List[Dict]
    ) -> List[models.ProductionOrderMaster]:
        """
        Create production orders for requirements that cannot be fulfilled from existing inventory.
        """
        production_orders = []
        
        for requirement in pending_requirements:
            # Find the paper master for this requirement
            paper = crud.get_paper_by_specs(
                self.db,
                gsm=requirement['gsm'],
                bf=requirement['bf'],
                shade=requirement['shade'],
                type='standard'
            )
            
            if not paper:
                # Create paper master if it doesn't exist
                paper_data = type('PaperCreate', (), {
                    'gsm': requirement['gsm'],
                    'bf': requirement['bf'],
                    'shade': requirement['shade'],
                    'type': 'standard',
                    'created_by_id': self.user_id
                })()
                paper = crud.create_paper(self.db, paper_data)
            
            # Create production order
            production_order = models.ProductionOrderMaster(
                paper_id=paper.id,
                quantity=1,  # One jumbo roll
                priority="normal",
                status="pending",
                created_by_id=self.user_id
            )
            
            self.db.add(production_order)
            production_orders.append(production_order)
        
        self.db.flush()  # Get IDs
        
        # Link pending orders to production orders
        for pending in pending_orders:
            if pending.paper:
                # Find matching production order
                matching_prod_order = next(
                    (po for po in production_orders if po.paper_id == pending.paper_id),
                    None
                )
                if matching_prod_order:
                    pending.production_order_id = matching_prod_order.id
                    pending.status = "in_production"
        
        logger.info(f"Created {len(production_orders)} production orders for pending requirements")
        return production_orders

    def process_multiple_pending_orders(self, pending_order_ids: List[uuid.UUID]) -> Dict:
        """
        Process multiple pending orders together for optimal cutting plans.
        This allows batch processing of pending orders for better optimization.
        """
        # Get pending orders with relationships
        pending_orders = self.db.query(models.PendingOrderMaster).options(
            joinedload(models.PendingOrderMaster.paper),
            joinedload(models.PendingOrderMaster.original_order),
            joinedload(models.PendingOrderMaster.created_by)
        ).filter(
            models.PendingOrderMaster.id.in_(pending_order_ids),
            models.PendingOrderMaster.status == "pending"
        ).all()
        
        if not pending_orders:
            return {"status": "no_pending_orders", "message": "No valid pending orders found"}
        
        return self._create_plan_from_pending_orders(pending_orders)
    
    def get_pending_orders_by_specification(self, paper_id: uuid.UUID) -> List[models.PendingOrderMaster]:
        """
        Get all pending orders for a specific paper specification.
        This helps in grouping similar orders for batch processing.
        """
        return self.db.query(models.PendingOrderMaster).options(
            joinedload(models.PendingOrderMaster.paper),
            joinedload(models.PendingOrderMaster.original_order)
        ).filter(
            models.PendingOrderMaster.paper_id == paper_id,
            models.PendingOrderMaster.status == "pending"
        ).order_by(models.PendingOrderMaster.created_at).all()
    

    
    def get_order_fulfillment_status(self, order_id: uuid.UUID) -> Dict:
        """
        Get comprehensive fulfillment status for an order including related pending orders and plans.
        """
        order = self._get_order_with_relationships(order_id)
        
        # Get related pending orders
        pending_orders = self.db.query(models.PendingOrderMaster).filter(
            models.PendingOrderMaster.original_order_id == order_id
        ).all()
        
        # Get related plans through plan-order links
        plan_links = self.db.query(models.PlanOrderLink).filter(
            models.PlanOrderLink.order_id == order_id
        ).all()
        
        plans = []
        for link in plan_links:
            plan = crud.get_plan(self.db, link.plan_id)
            if plan:
                plans.append({
                    "plan_id": str(plan.id),
                    "status": plan.status,
                    "quantity_allocated": link.quantity_allocated,
                    "expected_waste": plan.expected_waste_percentage
                })
        
        return {
            "order": {
                "id": str(order.id),
                "status": order.status,
                "quantity": order.quantity,
                "quantity_fulfilled": order.quantity_fulfilled or 0,
                "remaining_quantity": order.quantity - (order.quantity_fulfilled or 0),
                "client": order.client.name if order.client else None,
                "paper_spec": {
                    "gsm": order.paper.gsm if order.paper else None,
                    "bf": order.paper.bf if order.paper else None,
                    "shade": order.paper.shade if order.paper else None
                }
            },
            "pending_orders": [
                {
                    "id": str(p.id),
                    "status": p.status,
                    "quantity": p.quantity,
                    "reason": p.reason,
                    "production_order_id": str(p.production_order_id) if p.production_order_id else None
                }
                for p in pending_orders
            ],
            "plans": plans,
            "flow_status": self._determine_flow_status(order, pending_orders, plans)
        }
    
    def _determine_flow_status(self, order: models.OrderMaster, pending_orders: List, plans: List) -> str:
        """
        Determine where the order is in the OrderMaster → PendingOrderMaster → PlanMaster flow.
        """
        if order.status == "completed":
            return "completed"
        elif order.status == "in_process" and not pending_orders:
            return "in_process_no_pending"
        elif pending_orders and any(p.status == "pending" for p in pending_orders):
            return "pending_orders_created"
        elif pending_orders and any(p.status == "planned" for p in pending_orders):
            return "plans_created"
        elif pending_orders and any(p.status == "in_production" for p in pending_orders):
            return "in_production"
        else:
            return "needs_processing"
    
    def consolidate_pending_orders_by_specification(self) -> Dict:
        """
        Find and group pending orders by paper specification for batch processing.
        This helps optimize cutting plans by processing similar orders together.
        """
        # Get all pending orders grouped by paper specification
        pending_orders = self.db.query(models.PendingOrderMaster).options(
            joinedload(models.PendingOrderMaster.paper)
        ).filter(
            models.PendingOrderMaster.status == "pending"
        ).all()
        
        # Group by paper specification
        spec_groups = {}
        for pending in pending_orders:
            if pending.paper:
                spec_key = f"{pending.paper.gsm}_{pending.paper.bf}_{pending.paper.shade}"
                if spec_key not in spec_groups:
                    spec_groups[spec_key] = {
                        "paper_spec": {
                            "gsm": pending.paper.gsm,
                            "bf": pending.paper.bf,
                            "shade": pending.paper.shade
                        },
                        "pending_orders": []
                    }
                spec_groups[spec_key]["pending_orders"].append(pending)
        
        # Process each group
        results = {}
        for spec_key, group in spec_groups.items():
            if len(group["pending_orders"]) > 1:  # Only process groups with multiple orders
                result = self._create_plan_from_pending_orders(group["pending_orders"])
                results[spec_key] = result
        
        return {
            "specifications_processed": len(results),
            "total_pending_orders": len(pending_orders),
            "results": results
        }
    
    # OLD FLOW REMOVED: execute_complete_fulfillment_flow() method
    # This used the old flow: inventory check → then planning
    # New flow always goes directly to WorkflowManager.process_multiple_orders()
