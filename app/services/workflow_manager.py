from typing import List, Dict, Optional, Tuple
import uuid
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
import logging

from .. import models, crud, schemas
from .cutting_optimizer import CuttingOptimizer

logger = logging.getLogger(__name__)

class WorkflowManager:
    """
    Manages the complete workflow from order creation to fulfillment,
    integrating cutting optimization, inventory management, and production planning.
    Uses master-based architecture with proper foreign key relationships.
    """
    
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id
        self.optimizer = CuttingOptimizer()
    
    def process_multiple_orders(self, order_ids: List[uuid.UUID]) -> Dict:
        """
        Process multiple orders together for optimal cutting plans.
        This is the main entry point for batch order processing.
        Uses master-based relationships to fetch User, Client, Paper via foreign keys.
        """
        try:
            # Get all orders with related data via foreign keys
            orders = self.db.query(models.OrderMaster).options(
                joinedload(models.OrderMaster.client),
                joinedload(models.OrderMaster.paper),
                joinedload(models.OrderMaster.created_by)
            ).filter(
                models.OrderMaster.id.in_(order_ids),
                models.OrderMaster.status.in_([schemas.OrderStatus.PENDING.value, schemas.OrderStatus.PARTIALLY_FULFILLED.value])
            ).all()
            
            if not orders:
                raise ValueError("No valid orders found")
            
            # Check for matching pending orders and consolidate
            consolidated_orders = self._consolidate_with_pending_orders(orders)
            
            # Convert to optimizer format using master relationships
            order_requirements = []
            for order in consolidated_orders:
                remaining_qty = order.quantity - (order.quantity_fulfilled or 0)
                if remaining_qty > 0:
                    # Access paper specifications via foreign key relationship
                    paper = order.paper
                    if not paper:
                        logger.warning(f"Order {order.id} has no associated paper, skipping")
                        continue
                        
                    order_requirements.append({
                        'order_id': str(order.id),
                        'width': float(order.width_inches),
                        'quantity': remaining_qty,
                        'gsm': paper.gsm,
                        'bf': float(paper.bf),
                        'shade': paper.shade,
                        'min_length': order.min_length or 1000,
                        'client_name': order.client.name if order.client else 'Unknown',
                        'created_by': order.created_by.name if order.created_by else 'Unknown'
                    })
            
            if not order_requirements:
                return {"message": "All orders are already fulfilled"}
            
            # Generate optimized cutting plan
            plan = self.optimizer.optimize_with_new_algorithm(
                order_requirements=order_requirements,
                interactive=False
            )
            
            # Execute the plan with consolidated orders
            result = self._execute_comprehensive_plan(consolidated_orders, plan)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing multiple orders: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def _consolidate_with_pending_orders(self, current_orders: List[models.OrderMaster]) -> List[models.OrderMaster]:
        """
        Find and consolidate matching pending orders with current orders.
        This maximizes efficiency by batching similar specifications together.
        Uses master-based relationships to access paper specifications.
        """
        logger.info(f"Consolidating {len(current_orders)} current orders with pending orders")
        
        # Get all current order specifications using paper foreign key
        current_specs = set()
        for order in current_orders:
            if order.paper:
                spec = (order.paper.gsm, order.paper.shade, float(order.paper.bf))
                current_specs.add(spec)
        
        # Find matching pending orders with paper relationship loaded
        matching_pending = self.db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.paper),
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.created_by)
        ).filter(
            models.OrderMaster.status.in_([schemas.OrderStatus.PENDING.value, schemas.OrderStatus.PARTIALLY_FULFILLED.value]),
            models.OrderMaster.id.notin_([o.id for o in current_orders])  # Exclude current orders
        ).all()
        
        # Filter pending orders that match current specifications
        consolidated_orders = list(current_orders)  # Start with current orders
        added_orders = []
        
        for pending_order in matching_pending:
            if pending_order.paper:
                pending_spec = (pending_order.paper.gsm, pending_order.paper.shade, float(pending_order.paper.bf))
                remaining_qty = pending_order.quantity - (pending_order.quantity_fulfilled or 0)
                
                if pending_spec in current_specs and remaining_qty > 0:
                    consolidated_orders.append(pending_order)
                    added_orders.append(pending_order)
                    logger.info(f"Added pending order {pending_order.id} with spec {pending_spec}")
        
        if added_orders:
            logger.info(f"Consolidated {len(added_orders)} pending orders with current batch")
            
            # Update status of added orders to processing
            for order in added_orders:
                order.status = schemas.OrderStatus.PROCESSING.value
                order.updated_at = datetime.utcnow()
        
        return consolidated_orders
    
    def _execute_comprehensive_plan(self, orders: List[models.OrderMaster], plan: Dict) -> Dict:
        """Execute the comprehensive cutting plan with proper database transactions using master-based architecture."""
        
        plans_created = []
        production_orders_created = []
        orders_updated = []
        
        try:
            # Process jumbo rolls that can be cut
            for jumbo_plan in plan.get('jumbo_rolls_used', []):
                # Find or create paper master for this specification
                paper_spec = jumbo_plan.get('paper_spec', {})
                paper = self._find_or_create_paper_master(paper_spec)
                
                # Create plan master using the new architecture
                plan_data = {
                    'name': f"Cutting Plan {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    'cut_pattern': jumbo_plan,
                    'expected_waste_percentage': jumbo_plan['waste_percentage'],
                    'created_by_id': self.user_id,
                    'order_ids': [order.id for order in orders if self._order_matches_plan(order, jumbo_plan['rolls'])],
                    'inventory_ids': []  # Will be populated when inventory is allocated
                }
                
                # Create plan using CRUD
                plan_master = crud.create_plan(self.db, type('PlanCreate', (), plan_data)())
                plans_created.append(plan_master)
                
                # Update order fulfillment tracking
                self._update_order_fulfillment_from_plan(orders, jumbo_plan['rolls'])
            
            # Handle pending orders - create production orders
            for pending in plan.get('pending_orders', []):
                # Find the order that needs this specification
                target_order = self._find_order_for_pending(orders, pending)
                
                # Find or create paper master for production
                paper = self._find_or_create_paper_master({
                    'gsm': pending['gsm'],
                    'bf': pending['bf'],
                    'shade': pending['shade']
                })
                
                # Create production order using master architecture
                production_order = models.ProductionOrderMaster(
                    paper_id=paper.id,
                    quantity=1,  # One jumbo roll
                    status=schemas.ProductionOrderStatus.PENDING.value,
                    created_by_id=self.user_id
                )
                self.db.add(production_order)
                production_orders_created.append(production_order)
                
                # Create pending order master for tracking
                if target_order:
                    pending_order = models.PendingOrderMaster(
                        original_order_id=target_order.id,
                        paper_id=paper.id,
                        width=pending['width'],
                        quantity=pending['quantity'],
                        min_length=pending.get('min_length', 1000),
                        reason="no_suitable_inventory",
                        production_order_id=None,  # Will be set after flush
                        created_by_id=self.user_id
                    )
                    self.db.add(pending_order)
                    self.db.flush()  # Get IDs
                    pending_order.production_order_id = production_order.id
            
            # Update all order statuses
            for order in orders:
                fulfilled_qty = order.quantity_fulfilled or 0
                if fulfilled_qty >= order.quantity:
                    order.status = schemas.OrderStatus.COMPLETED.value
                    orders_updated.append(order)
                elif fulfilled_qty > 0:
                    order.status = schemas.OrderStatus.PARTIALLY_FULFILLED.value
                    orders_updated.append(order)
            
            self.db.commit()
            
            return {
                "status": "success",
                "summary": {
                    "orders_processed": len(orders),
                    "orders_completed": len([o for o in orders if o.status == schemas.OrderStatus.COMPLETED.value]),
                    "orders_partially_fulfilled": len([o for o in orders if o.status == schemas.OrderStatus.PARTIALLY_FULFILLED.value]),
                    "plans_created": len(plans_created),
                    "production_orders_created": len(production_orders_created),
                    "total_jumbos_used": plan['summary']['total_jumbos_used'],
                    "overall_waste_percentage": plan['summary']['overall_waste_percentage'],
                    "total_trim_inches": plan['summary']['total_trim_inches']
                },
                "plans": [str(p.id) for p in plans_created],
                "production_orders": [str(po.id) for po in production_orders_created],
                "next_steps": self._generate_next_steps(plans_created, production_orders_created)
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error executing comprehensive plan: {str(e)}")
            raise
    
    def _find_or_create_paper_master(self, paper_spec: Dict) -> models.PaperMaster:
        """Find an existing paper master or create a new one using master-based architecture."""
        if not paper_spec:
            # Default specifications if not provided
            paper_spec = {'gsm': 90, 'bf': 18.0, 'shade': 'white', 'type': 'standard'}
        
        # Try to find existing paper master
        paper = crud.get_paper_by_specs(
            self.db,
            gsm=paper_spec.get('gsm', 90),
            bf=paper_spec.get('bf', 18.0),
            shade=paper_spec.get('shade', 'white'),
            type=paper_spec.get('type', 'standard')
        )
        
        if not paper:
            # Create new paper master using CRUD
            paper_data = type('PaperCreate', (), {
                'gsm': paper_spec.get('gsm', 90),
                'bf': paper_spec.get('bf', 18.0),
                'shade': paper_spec.get('shade', 'white'),
                'type': paper_spec.get('type', 'standard'),
                'created_by_id': self.user_id
            })()
            paper = crud.create_paper(self.db, paper_data)
        
        return paper
    
    def _order_matches_plan(self, order: models.OrderMaster, rolls: List[Dict]) -> bool:
        """Check if an order matches any roll in the cutting plan using master relationships."""
        if not order.paper:
            return False
            
        for roll in rolls:
            if (float(order.width_inches) == roll.get('width') and
                order.paper.gsm == roll.get('gsm') and
                order.paper.shade == roll.get('shade')):
                return True
        return False
    
    def _find_order_for_pending(self, orders: List[models.OrderMaster], pending: Dict) -> Optional[models.OrderMaster]:
        """Find the order that corresponds to a pending requirement using master relationships."""
        for order in orders:
            if (order.paper and
                float(order.width_inches) == pending.get('width') and
                order.paper.gsm == pending.get('gsm') and
                order.paper.shade == pending.get('shade')):
                return order
        return None
    
    def _update_order_fulfillment_from_plan(self, orders: List[models.OrderMaster], rolls: List[Dict]):
        """Update order fulfillment quantities based on cutting plan using master relationships."""
        # Count how many rolls of each specification are in the plan
        roll_counts = {}
        for roll in rolls:
            key = (roll.get('width'), roll.get('gsm'), roll.get('shade'))
            roll_counts[key] = roll_counts.get(key, 0) + 1
        
        # Update corresponding orders using paper master relationship
        for order in orders:
            if order.paper:
                key = (float(order.width_inches), order.paper.gsm, order.paper.shade)
                if key in roll_counts:
                    remaining_qty = order.quantity_rolls - (order.quantity_fulfilled or 0)
                    fulfilled = min(roll_counts[key], remaining_qty)
                    order.quantity_fulfilled = (order.quantity_fulfilled or 0) + fulfilled
                    roll_counts[key] -= fulfilled
                    if roll_counts[key] <= 0:
                        del roll_counts[key]
    
    def _generate_next_steps(self, plans: List[models.PlanMaster], 
                           production_orders: List[models.ProductionOrderMaster]) -> List[str]:
        """Generate next steps for the user using master-based architecture."""
        steps = []
        
        if plans:
            steps.append(f"Execute {len(plans)} cutting plans to create cut rolls")
        
        if production_orders:
            steps.append(f"Process {len(production_orders)} production orders to create jumbo rolls")
        
        if not plans and not production_orders:
            steps.append("All orders fulfilled from existing inventory")
        
        return steps
    
    def create_cutting_plan_from_orders(self, order_ids: List[uuid.UUID], plan_name: Optional[str] = None) -> models.PlanMaster:
        """
        Create a cutting plan from order IDs using the optimizer and master-based architecture.
        This integrates the cutting optimizer with the workflow manager.
        """
        try:
            # Use the cutting optimizer to create the plan
            plan = self.optimizer.create_plan_from_orders(
                db=self.db,
                order_ids=order_ids,
                created_by_id=self.user_id,
                plan_name=plan_name,
                interactive=False
            )
            
            logger.info(f"Created cutting plan {plan.id} from {len(order_ids)} orders")
            return plan
            
        except Exception as e:
            logger.error(f"Error creating cutting plan from orders: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def get_orders_with_relationships(self, order_ids: List[uuid.UUID]) -> List[models.OrderMaster]:
        """
        Fetch orders with all related data (User, Client, Paper) via foreign keys.
        This demonstrates the master-based relationship usage.
        """
        return self.db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.paper),
            joinedload(models.OrderMaster.created_by)
        ).filter(
            models.OrderMaster.id.in_(order_ids)
        ).all()
    
    def get_workflow_status(self) -> Dict:
        """Get overall workflow status and metrics using master-based architecture."""
        # Get counts of various statuses using master tables
        pending_orders = self.db.query(models.OrderMaster).filter(
            models.OrderMaster.status == schemas.OrderStatus.PENDING.value
        ).count()
        
        partial_orders = self.db.query(models.OrderMaster).filter(
            models.OrderMaster.status == schemas.OrderStatus.PARTIALLY_FULFILLED.value
        ).count()
        
        planned_cuts = self.db.query(models.PlanMaster).filter(
            models.PlanMaster.status == schemas.PlanStatus.PLANNED.value
        ).count()
        
        pending_production = self.db.query(models.ProductionOrderMaster).filter(
            models.ProductionOrderMaster.status == schemas.ProductionOrderStatus.PENDING.value
        ).count()
        
        available_inventory = self.db.query(models.InventoryMaster).filter(
            models.InventoryMaster.status == schemas.InventoryStatus.AVAILABLE.value,
            models.InventoryMaster.roll_type == schemas.RollType.JUMBO.value
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
                "available_jumbo_rolls": available_inventory
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