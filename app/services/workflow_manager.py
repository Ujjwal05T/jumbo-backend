from typing import List, Dict, Optional, Tuple
import uuid
import json
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
        NEW FLOW: Process multiple orders together for optimal cutting plans.
        SKIP INVENTORY CHECK - Always go directly to plan generation.
        Uses 3-input/4-output optimization algorithm.
        """
        try:
            # NEW FLOW: Get order requirements directly (no inventory check)
            order_requirements = crud.get_orders_with_paper_specs(self.db, order_ids)
            
            if not order_requirements:
                return {
                    "status": "no_orders",
                    "cut_rolls_generated": [],
                    "jumbo_rolls_needed": 0,
                    "pending_orders_created": [],
                    "inventory_created": [],
                    "orders_updated": [],
                    "plans_created": [],
                    "production_orders_created": []
                }
            
            # NEW FLOW: Get paper specifications from orders
            paper_specs = []
            for req in order_requirements:
                spec = {'gsm': req['gsm'], 'bf': req['bf'], 'shade': req['shade']}
                if spec not in paper_specs:
                    paper_specs.append(spec)
            
            # NEW FLOW: Fetch pending orders for same paper specifications
            pending_orders = crud.get_pending_orders_by_paper_specs(self.db, paper_specs)
            pending_requirements = []
            for pending in pending_orders:
                if pending.paper:
                    pending_requirements.append({
                        'order_id': str(pending.order_id),
                        'width': float(pending.width_inches),
                        'quantity': pending.quantity_pending,
                        'gsm': pending.paper.gsm,
                        'bf': float(pending.paper.bf),
                        'shade': pending.paper.shade,
                        'pending_id': str(pending.id)
                    })
            
            # NEW FLOW: Fetch available inventory (20-25" waste rolls)
            available_inventory_items = crud.get_available_inventory_by_paper_specs(self.db, paper_specs)
            available_inventory = []
            for inv_item in available_inventory_items:
                if inv_item.paper:
                    available_inventory.append({
                        'id': str(inv_item.id),
                        'width': float(inv_item.width_inches),
                        'gsm': inv_item.paper.gsm,
                        'bf': float(inv_item.paper.bf),
                        'shade': inv_item.paper.shade,
                        'weight': float(inv_item.weight_kg) if inv_item.weight_kg else 0
                    })
            
            logger.info(f"NEW FLOW Processing: {len(order_requirements)} orders, {len(pending_requirements)} pending, {len(available_inventory)} inventory")
            
            # NEW FLOW: Run 3-input optimization
            optimization_result = self.optimizer.optimize_with_new_algorithm(
                order_requirements=order_requirements,
                pending_orders=pending_requirements,
                available_inventory=available_inventory,
                interactive=False
            )
            
            # NEW FLOW: Process 4 outputs
            result = self._process_optimizer_outputs(optimization_result, order_ids)
            
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
    
    def _process_optimizer_outputs(self, optimization_result: Dict, order_ids: List[uuid.UUID]) -> Dict:
        """
        NEW FLOW: Process the 4 outputs from optimization algorithm.
        Creates database records for each output type.
        
        Args:
            optimization_result: Result from 3-input/4-output optimization
            order_ids: Original order IDs being processed
            
        Returns:
            Summary of processing results
        """
        try:
            created_plans = []
            created_pending = []
            created_inventory = []
            created_production = []
            updated_orders = []
            
            # OUTPUT 1: Create Plan Master from cut_rolls_generated
            if optimization_result.get('cut_rolls_generated'):
                plan_name = f"NEW FLOW Plan {datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                plan = models.PlanMaster(
                    name=plan_name,
                    cut_pattern=json.dumps(optimization_result['cut_rolls_generated']),
                    expected_waste_percentage=optimization_result['summary'].get('average_waste', 0),
                    status=schemas.PlanStatus.PLANNED.value,
                    created_by_id=self.user_id
                )
                
                self.db.add(plan)
                self.db.flush()  # Get ID
                created_plans.append(plan)
                
                # Link orders to plan
                for order_id in order_ids:
                    plan_order_link = models.PlanOrderLink(
                        plan_id=plan.id,
                        order_id=order_id,
                        quantity_allocated=1  # Will be calculated properly later
                    )
                    self.db.add(plan_order_link)
            
            # OUTPUT 2: Create Production Orders for jumbo_rolls_needed
            if optimization_result.get('jumbo_rolls_needed', 0) > 0:
                # Group by paper specifications for production orders
                paper_specs_for_production = set()
                for cut_roll in optimization_result.get('cut_rolls_generated', []):
                    if cut_roll.get('source') == 'cutting':
                        spec_key = (cut_roll['gsm'], cut_roll['bf'], cut_roll['shade'])
                        paper_specs_for_production.add(spec_key)
                
                for gsm, bf, shade in paper_specs_for_production:
                    # Find or create paper master
                    paper = crud.get_paper_by_specs(self.db, gsm=gsm, bf=bf, shade=shade)
                    if not paper and self.user_id:
                        paper_data = type('PaperCreate', (), {
                            'name': f"{shade} {gsm}GSM BF{bf}",
                            'gsm': gsm,
                            'bf': bf,
                            'shade': shade,
                            'type': 'standard',
                            'created_by_id': self.user_id
                        })()
                        paper = crud.create_paper(self.db, paper_data)
                    
                    if paper:
                        production_order = models.ProductionOrderMaster(
                            paper_id=paper.id,
                            quantity=1,  # One jumbo roll per production order
                            priority="normal",
                            status=schemas.ProductionOrderStatus.PENDING.value,
                            created_by_id=self.user_id
                        )
                        self.db.add(production_order)
                        created_production.append(production_order)
            
            # OUTPUT 3: Create Pending Orders from pending_orders
            if optimization_result.get('pending_orders'):
                created_pending_records = crud.bulk_create_pending_orders(
                    self.db,
                    optimization_result['pending_orders'],
                    order_ids
                )
                created_pending.extend(created_pending_records)
            
            # OUTPUT 4: Create Inventory from inventory_remaining (waste)
            if optimization_result.get('inventory_remaining'):
                waste_items = [
                    inv for inv in optimization_result['inventory_remaining'] 
                    if inv.get('source') == 'waste'
                ]
                if waste_items and self.user_id:
                    created_inventory_records = crud.create_inventory_from_waste(
                        self.db,
                        waste_items,
                        self.user_id
                    )
                    created_inventory.extend(created_inventory_records)
            
            # Update order statuses to "processing" (ready for fulfillment)
            for order_id in order_ids:
                order = crud.get_order(self.db, order_id)
                if order:
                    order.status = schemas.OrderStatus.PROCESSING.value
                    order.updated_at = datetime.utcnow()
                    updated_orders.append(str(order_id))
            
            self.db.commit()
            
            return {
                "status": "success",
                "cut_rolls_generated": optimization_result.get('cut_rolls_generated', []),
                "jumbo_rolls_needed": optimization_result.get('jumbo_rolls_needed', 0),
                "pending_orders_created": [
                    {
                        "width": float(po.width_inches),
                        "quantity": po.quantity_pending,
                        "gsm": po.paper.gsm if po.paper else 90,
                        "bf": float(po.paper.bf) if po.paper else 18.0,
                        "shade": po.paper.shade if po.paper else "white",
                        "reason": po.reason
                    } for po in created_pending
                ],
                "inventory_created": [
                    {
                        "id": str(inv.id),
                        "width": float(inv.width_inches),
                        "weight": float(inv.weight_kg),
                        "source": "waste"
                    } for inv in created_inventory
                ],
                "orders_updated": updated_orders,
                "plans_created": [str(p.id) for p in created_plans],
                "production_orders_created": [str(po.id) for po in created_production]
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error processing optimizer outputs: {str(e)}")
            raise
    
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