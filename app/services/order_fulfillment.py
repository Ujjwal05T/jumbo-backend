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
    Service to handle order fulfillment using master-based architecture.
    Implements the flow: OrderMaster → PendingOrderMaster → PlanMaster
    """
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id
        self.optimizer = CuttingOptimizer()
        self.min_jumbo_roll_width = 36  # Minimum useful width for a jumbo roll

    def fulfill_order(self, order_id: uuid.UUID) -> Dict:
        """
        Fulfill an order using master-based architecture.
        Flow: OrderMaster → PendingOrderMaster → PlanMaster
        """
        try:
            # Get order with related data via foreign keys
            order = self._get_order_with_relationships(order_id)
            
            # Update order status to processing
            order.status = "processing"
            order.updated_at = datetime.utcnow()
            
            # Try to fulfill from existing inventory first
            fulfilled_from_inventory = self._fulfill_from_inventory(order)
            
            if fulfilled_from_inventory:
                remaining_qty = order.quantity - (order.quantity_fulfilled or 0)
                if remaining_qty <= 0:
                    order.status = "completed"
                    self.db.commit()
                    return {
                        "status": "completed",
                        "order_id": str(order.id),
                        "message": "Order fully fulfilled from existing inventory"
                    }
            
            # Move unfulfilled quantity to PendingOrderMaster
            pending_order = self._create_pending_order_from_order(order)
            
            # Try to create cutting plan from pending orders
            plan_result = self._create_plan_from_pending_orders([pending_order])
            
            self.db.commit()
            return plan_result
                
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

    def _fulfill_from_inventory(self, order: models.OrderMaster) -> bool:
        """
        Try to fulfill order from existing inventory using master-based architecture.
        Returns True if any quantity was fulfilled from inventory.
        """
        if not order.paper:
            logger.warning(f"Order {order.id} has no associated paper")
            return False
        
        # Find matching inventory items
        matching_inventory = self.db.query(models.InventoryMaster).filter(
            models.InventoryMaster.paper_id == order.paper_id,
            models.InventoryMaster.width_inches == order.width_inches,
            models.InventoryMaster.status == "available",
            models.InventoryMaster.roll_type == "cut",
            models.InventoryMaster.allocated_order_id.is_(None)
        ).order_by(models.InventoryMaster.created_at).all()
        
        remaining_qty = order.quantity - (order.quantity_fulfilled or 0)
        allocated = 0
        
        for inventory_item in matching_inventory:
            if allocated >= remaining_qty:
                break
                
            # Allocate this inventory item to the order
            inventory_item.allocated_order_id = order.id
            inventory_item.status = "allocated"
            inventory_item.updated_at = datetime.utcnow()
            allocated += 1
        
        if allocated > 0:
            # Update order fulfillment
            order.quantity_fulfilled = (order.quantity_fulfilled or 0) + allocated
            
            # Update order status
            if order.quantity_fulfilled >= order.quantity:
                order.status = "completed"
            else:
                order.status = "partially_fulfilled"
            
            logger.info(f"Fulfilled {allocated} rolls from inventory for order {order.id}")
            return True
        
        return False
    
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
        elif order.status == "partially_fulfilled" and not pending_orders:
            return "partially_fulfilled_no_pending"
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
    
    def execute_complete_fulfillment_flow(self, order_ids: List[uuid.UUID]) -> Dict:
        """
        Execute the complete OrderMaster → PendingOrderMaster → PlanMaster flow for multiple orders.
        This is the main method that demonstrates the full data flow implementation.
        """
        try:
            results = []
            
            for order_id in order_ids:
                # Step 1: Get order with relationships
                order = self._get_order_with_relationships(order_id)
                
                # Step 2: Try inventory fulfillment
                inventory_fulfilled = self._fulfill_from_inventory(order)
                
                # Step 3: Create pending order for remaining quantity
                remaining_qty = order.quantity - (order.quantity_fulfilled or 0)
                if remaining_qty > 0:
                    pending_order = self._create_pending_order_from_order(order)
                    
                    # Step 4: Create plan from pending order
                    plan_result = self._create_plan_from_pending_orders([pending_order])
                    
                    results.append({
                        "order_id": str(order_id),
                        "inventory_fulfilled": inventory_fulfilled,
                        "pending_order_created": str(pending_order.id),
                        "plan_result": plan_result
                    })
                else:
                    results.append({
                        "order_id": str(order_id),
                        "inventory_fulfilled": inventory_fulfilled,
                        "status": "completed_from_inventory"
                    })
            
            self.db.commit()
            
            return {
                "status": "flow_completed",
                "orders_processed": len(order_ids),
                "results": results,
                "message": "Complete OrderMaster → PendingOrderMaster → PlanMaster flow executed"
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Complete fulfillment flow failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Complete fulfillment flow failed: {str(e)}"
            )
