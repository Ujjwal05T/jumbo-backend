from typing import List, Dict, Optional, Tuple
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException
import logging

from .. import models
from .cutting_optimizer import CuttingOptimizer
from .order_fulfillment import OrderFulfillmentService
from .status_service import StatusService
from .pending_order_service import PendingOrderService

logger = logging.getLogger(__name__)

class WorkflowManager:
    """
    Manages the complete workflow from order creation to fulfillment,
    integrating cutting optimization, inventory management, and production planning.
    """
    
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id
        self.optimizer = CuttingOptimizer()
        self.fulfillment_service = OrderFulfillmentService(db, user_id)
        self.status_service = StatusService(db, user_id)
        self.pending_service = PendingOrderService(db, user_id)
    
    def process_multiple_orders(self, order_ids: List[uuid.UUID]) -> Dict:
        """
        Process multiple orders together for optimal cutting plans.
        This is the main entry point for batch order processing.
        """
        try:
            # Get all orders
            orders = self.db.query(models.Order).filter(
                models.Order.id.in_(order_ids),
                models.Order.status.in_(["pending", "partially_fulfilled"])
            ).all()
            
            if not orders:
                raise ValueError("No valid orders found")
            
            # Check for matching pending orders and consolidate
            consolidated_orders = self._consolidate_with_pending_orders(orders)
            
            # Convert to optimizer format
            order_requirements = []
            for order in consolidated_orders:
                remaining_qty = order.remaining_quantity
                if remaining_qty > 0:
                    order_requirements.append({
                        'order_id': str(order.id),
                        'width': order.width_inches,
                        'quantity': remaining_qty,
                        'gsm': order.gsm,
                        'bf': float(order.bf),
                        'shade': order.shade,
                        'min_length': 1000
                    })
            
            if not order_requirements:
                return {"message": "All orders are already fulfilled"}
            
            # Generate optimized cutting plan
            plan = self.optimizer.generate_optimized_plan(
                order_requirements=order_requirements,
                interactive=False
            )
            
            # Execute the plan with consolidated orders
            result = self._execute_comprehensive_plan(consolidated_orders, plan)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing multiple orders: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def _consolidate_with_pending_orders(self, current_orders: List[models.Order]) -> List[models.Order]:
        """
        Find and consolidate matching pending orders with current orders.
        This maximizes efficiency by batching similar specifications together.
        """
        logger.info(f"Consolidating {len(current_orders)} current orders with pending orders")
        
        # Get all current order specifications
        current_specs = set()
        for order in current_orders:
            spec = (order.gsm, order.shade, float(order.bf))
            current_specs.add(spec)
        
        # Find matching pending orders
        matching_pending = self.db.query(models.Order).filter(
            models.Order.status.in_([models.OrderStatus.PENDING, models.OrderStatus.PARTIALLY_FULFILLED]),
            models.Order.id.notin_([o.id for o in current_orders])  # Exclude current orders
        ).all()
        
        # Filter pending orders that match current specifications
        consolidated_orders = list(current_orders)  # Start with current orders
        added_orders = []
        
        for pending_order in matching_pending:
            pending_spec = (pending_order.gsm, pending_order.shade, float(pending_order.bf))
            
            if pending_spec in current_specs and pending_order.remaining_quantity > 0:
                consolidated_orders.append(pending_order)
                added_orders.append(pending_order)
                logger.info(f"Added pending order {pending_order.id} with spec {pending_spec}")
        
        if added_orders:
            logger.info(f"Consolidated {len(added_orders)} pending orders with current batch")
            
            # Update status of added orders to processing
            for order in added_orders:
                self.status_service.update_status(
                    order,
                    models.OrderStatus.PROCESSING,
                    f"Consolidated with batch processing for optimization",
                    commit=False
                )
        
        return consolidated_orders
    
    def _execute_comprehensive_plan(self, orders: List[models.Order], plan: Dict) -> Dict:
        """Execute the comprehensive cutting plan with proper database transactions."""
        
        cutting_plans_created = []
        production_orders_created = []
        orders_updated = []
        
        try:
            with self.db.begin_nested():  # Start savepoint
                
                # Process jumbo rolls that can be cut
                for jumbo_plan in plan.get('jumbo_rolls_used', []):
                    # Find or create jumbo roll
                    jumbo_roll = self._find_or_create_jumbo_roll(jumbo_plan.get('paper_spec', {}))
                    
                    # Create cutting plan
                    # Find the primary order for this cutting plan
                    primary_order = self._find_primary_order_for_plan(orders, jumbo_plan['rolls'])
                    
                    cutting_plan = models.CuttingPlan(
                        order_id=primary_order.id,
                        jumbo_roll_id=jumbo_roll.id,
                        cut_pattern=jumbo_plan['rolls'],
                        expected_waste_percentage=jumbo_plan['waste_percentage'],
                        status=models.CuttingPlanStatus.PLANNED,
                        created_by_id=self.user_id
                    )
                    self.db.add(cutting_plan)
                    cutting_plans_created.append(cutting_plan)
                    
                    # Update jumbo roll status
                    jumbo_roll.status = models.JumboRollStatus.CUTTING
                    
                    # Update order fulfillment tracking
                    self._update_order_fulfillment_from_plan(orders, jumbo_plan['rolls'])
                
                # Handle pending orders - create production orders and track pending items
                pending_items_created = []
                for pending in plan.get('pending_orders', []):
                    # Find the order that needs this specification
                    target_order = self._find_order_for_pending(orders, pending)
                    
                    # Create pending order items for tracking
                    if target_order:
                        pending_items = self.pending_service.create_pending_items(
                            [pending], 
                            target_order.id, 
                            "no_suitable_jumbo"
                        )
                        pending_items_created.extend(pending_items)
                    
                    production_order = models.ProductionOrder(
                        gsm=pending['gsm'],
                        bf=pending['bf'],
                        shade=pending['shade'],
                        quantity=1,  # One jumbo roll
                        status=models.ProductionOrderStatus.PENDING,
                        order_id=target_order.id if target_order else None,
                        created_by_id=self.user_id
                    )
                    self.db.add(production_order)
                    production_orders_created.append(production_order)
                    
                    # Link pending items to production order
                    if pending_items_created:
                        self.db.flush()  # Get production order ID
                        pending_item_ids = [item.id for item in pending_items_created if item.original_order_id == target_order.id]
                        if pending_item_ids:
                            self.pending_service.link_to_production_order(pending_item_ids, production_order.id)
                    
                    # Create backorder if we have a target order
                    if target_order:
                        backorder = self.status_service.create_backorder(
                            target_order,
                            pending['quantity'],
                            f"Waiting for production order {production_order.id}",
                            commit=False
                        )
                
                # Update all order statuses
                for order in orders:
                    if order.is_fully_fulfilled:
                        self.status_service.update_status(
                            order, 
                            models.OrderStatus.COMPLETED,
                            "Order fully fulfilled through cutting optimization",
                            commit=False
                        )
                        orders_updated.append(order)
                    elif order.quantity_fulfilled > 0:
                        self.status_service.update_status(
                            order,
                            models.OrderStatus.PARTIALLY_FULFILLED,
                            "Order partially fulfilled, remaining quantity in production",
                            commit=False
                        )
                        orders_updated.append(order)
                
                self.db.commit()
                
                return {
                    "status": "success",
                    "summary": {
                        "orders_processed": len(orders),
                        "orders_completed": len([o for o in orders if o.is_fully_fulfilled]),
                        "orders_partially_fulfilled": len([o for o in orders if not o.is_fully_fulfilled and o.quantity_fulfilled > 0]),
                        "cutting_plans_created": len(cutting_plans_created),
                        "production_orders_created": len(production_orders_created),
                        "total_jumbos_used": plan['summary']['total_jumbos_used'],
                        "overall_waste_percentage": plan['summary']['overall_waste_percentage'],
                        "total_trim_inches": plan['summary']['total_trim_inches']
                    },
                    "cutting_plans": [str(cp.id) for cp in cutting_plans_created],
                    "production_orders": [str(po.id) for po in production_orders_created],
                    "next_steps": self._generate_next_steps(cutting_plans_created, production_orders_created)
                }
                
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error executing comprehensive plan: {str(e)}")
            raise
    
    def _find_or_create_jumbo_roll(self, paper_spec: Dict) -> models.JumboRoll:
        """Find an existing jumbo roll or create a new one."""
        if not paper_spec:
            # Default specifications if not provided
            paper_spec = {'gsm': 90, 'bf': 18.0, 'shade': 'white'}
        
        # Try to find existing available jumbo roll
        jumbo_roll = self.db.query(models.JumboRoll).filter(
            models.JumboRoll.gsm == paper_spec.get('gsm', 90),
            models.JumboRoll.bf == paper_spec.get('bf', 18.0),
            models.JumboRoll.shade == paper_spec.get('shade', 'white'),
            models.JumboRoll.status == models.JumboRollStatus.AVAILABLE
        ).first()
        
        if not jumbo_roll:
            # Create new jumbo roll
            jumbo_roll = models.JumboRoll(
                gsm=paper_spec.get('gsm', 90),
                bf=paper_spec.get('bf', 18.0),
                shade=paper_spec.get('shade', 'white'),
                status=models.JumboRollStatus.AVAILABLE,
                created_by_id=self.user_id
            )
            self.db.add(jumbo_roll)
            self.db.flush()  # Get ID without committing
        
        return jumbo_roll
    
    def _find_primary_order_for_plan(self, orders: List[models.Order], rolls: List[Dict]) -> models.Order:
        """Find the primary order that this cutting plan should be associated with."""
        # For now, find the order that matches the first roll in the plan
        if rolls:
            first_roll = rolls[0]
            for order in orders:
                if (order.width_inches == first_roll.get('width') and
                    order.gsm == first_roll.get('gsm') and
                    order.shade == first_roll.get('shade')):
                    return order
        
        # Fallback to first order
        return orders[0] if orders else None
    
    def _find_order_for_pending(self, orders: List[models.Order], pending: Dict) -> Optional[models.Order]:
        """Find the order that corresponds to a pending requirement."""
        for order in orders:
            if (order.width_inches == pending.get('width') and
                order.gsm == pending.get('gsm') and
                order.shade == pending.get('shade')):
                return order
        return None
    
    def _update_order_fulfillment_from_plan(self, orders: List[models.Order], rolls: List[Dict]):
        """Update order fulfillment quantities based on cutting plan."""
        # Count how many rolls of each specification are in the plan
        roll_counts = {}
        for roll in rolls:
            key = (roll.get('width'), roll.get('gsm'), roll.get('shade'))
            roll_counts[key] = roll_counts.get(key, 0) + 1
        
        # Update corresponding orders
        for order in orders:
            key = (order.width_inches, order.gsm, order.shade)
            if key in roll_counts:
                fulfilled = min(roll_counts[key], order.remaining_quantity)
                order.quantity_fulfilled += fulfilled
                roll_counts[key] -= fulfilled
                if roll_counts[key] <= 0:
                    del roll_counts[key]
    
    def _generate_next_steps(self, cutting_plans: List[models.CuttingPlan], 
                           production_orders: List[models.ProductionOrder]) -> List[str]:
        """Generate next steps for the user."""
        steps = []
        
        if cutting_plans:
            steps.append(f"Execute {len(cutting_plans)} cutting plans to create cut rolls")
        
        if production_orders:
            steps.append(f"Process {len(production_orders)} production orders to create jumbo rolls")
        
        if not cutting_plans and not production_orders:
            steps.append("All orders fulfilled from existing inventory")
        
        return steps
    
    def get_workflow_status(self) -> Dict:
        """Get overall workflow status and metrics."""
        # Get counts of various statuses
        pending_orders = self.db.query(models.Order).filter(
            models.Order.status == models.OrderStatus.PENDING
        ).count()
        
        partial_orders = self.db.query(models.Order).filter(
            models.Order.status == models.OrderStatus.PARTIALLY_FULFILLED
        ).count()
        
        planned_cuts = self.db.query(models.CuttingPlan).filter(
            models.CuttingPlan.status == models.CuttingPlanStatus.PLANNED
        ).count()
        
        pending_production = self.db.query(models.ProductionOrder).filter(
            models.ProductionOrder.status == models.ProductionOrderStatus.PENDING
        ).count()
        
        available_jumbos = self.db.query(models.JumboRoll).filter(
            models.JumboRoll.status == models.JumboRollStatus.AVAILABLE
        ).count()
        
        return {
            "orders": {
                "pending": pending_orders,
                "partially_fulfilled": partial_orders,
                "total_needing_attention": pending_orders + partial_orders
            },
            "cutting_plans": {
                "planned": planned_cuts,
                "ready_to_execute": planned_cuts
            },
            "production": {
                "pending_orders": pending_production
            },
            "inventory": {
                "available_jumbo_rolls": available_jumbos
            },
            "recommendations": self._generate_recommendations(
                pending_orders, partial_orders, planned_cuts, pending_production
            )
        }
    
    def _generate_recommendations(self, pending_orders: int, partial_orders: int, 
                                planned_cuts: int, pending_production: int) -> List[str]:
        """Generate workflow recommendations."""
        recommendations = []
        
        if pending_orders + partial_orders > 0:
            recommendations.append(f"Process {pending_orders + partial_orders} orders needing fulfillment")
        
        if planned_cuts > 0:
            recommendations.append(f"Execute {planned_cuts} cutting plans to create inventory")
        
        if pending_production > 0:
            recommendations.append(f"Complete {pending_production} production orders to create jumbo rolls")
        
        if not any([pending_orders, partial_orders, planned_cuts, pending_production]):
            recommendations.append("All orders are up to date - system is running smoothly")
        
        return recommendations