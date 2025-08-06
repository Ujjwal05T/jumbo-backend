from typing import List, Dict, Optional, Tuple
import uuid
import json
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
import logging

from .. import models, crud_operations, schemas
from .cutting_optimizer import CuttingOptimizer
from .id_generator import FrontendIDGenerator

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
            order_requirements = crud_operations.get_orders_with_paper_specs(self.db, order_ids)
            
            # Store order requirements for later use in plan linking
            self.processed_order_requirements = order_requirements
            
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
            logger.info(f"🔍 DEBUG WF: Fetching pending orders for paper specs: {paper_specs}")
            pending_orders = crud_operations.get_pending_orders_by_specs(self.db, paper_specs)
            logger.info(f"📋 DEBUG WF: Found {len(pending_orders)} pending order items")
            
            pending_requirements = []
            for i, pending in enumerate(pending_orders):
                logger.info(f"  Processing pending item {i+1}: ID={pending.get('pending_order_id', 'unknown')}, width={pending.get('width', 0)}\"")
                # pending is already a dictionary from crud_operations
                pending_req = {
                    'order_id': str(pending.get('original_order_id', 'unknown')),
                    'original_order_id': str(pending.get('original_order_id', 'unknown')),  # Add the correct field name
                    'width': float(pending.get('width', 0)),
                    'quantity': pending.get('quantity', 0),
                    'gsm': pending.get('gsm', 0),
                    'bf': float(pending.get('bf', 0)),
                    'shade': pending.get('shade', ''),
                    'pending_id': str(pending.get('pending_order_id', 'unknown')),
                    'reason': pending.get('reason', 'unknown')
                }
                pending_requirements.append(pending_req)
                logger.info(f"  ✅ Added pending requirement: {pending_req}")
            
            logger.info(f"📊 DEBUG WF: Final pending_requirements: {pending_requirements}")
            
            # DEBUG: Log the pending_id values being passed to optimizer
            for i, req in enumerate(pending_requirements):
                logger.info(f"🔍 DEBUG PENDING INPUT {i+1}: pending_id='{req.get('pending_id')}', width={req.get('width')}, quantity={req.get('quantity')}")
            
            # NEW FLOW: Fetch available inventory (20-25" waste rolls)
            available_inventory_items = crud_operations.get_available_inventory_by_paper_specs(self.db, paper_specs)
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
            result = self._process_optimizer_outputs(optimization_result, order_ids, pending_requirements)
            
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
    
    def _process_optimizer_outputs(self, optimization_result: Dict, order_ids: List[uuid.UUID], pending_requirements: List[Dict]) -> Dict:
        """
        NEW FLOW: Process the 4 outputs from optimization algorithm.
        Creates database records for each output type.
        
        Args:
            optimization_result: Result from 3-input/4-output optimization
            order_ids: Original order IDs being processed
            pending_requirements: Input pending orders to track status updates
            
        Returns:
            Summary of processing results
        """
        try:
            created_plans = []
            created_plan_ids = []  # Store IDs separately to avoid session issues
            created_pending = []
            created_inventory = []
            created_production = []
            created_production_ids = []  # Store IDs separately to avoid session issues
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
                created_plan_ids.append(str(plan.id))  # Store ID immediately
                
                # Link order items to plan using the processed requirements
                for requirement in self.processed_order_requirements:
                    frontend_id = FrontendIDGenerator.generate_frontend_id("plan_order_link", self.db)
                    
                    # Handle UUID conversion safely
                    order_id = requirement['order_id']
                    if isinstance(order_id, str):
                        order_id = uuid.UUID(order_id)
                    elif not isinstance(order_id, uuid.UUID):
                        logger.error(f"Invalid order_id type: {type(order_id)} - {order_id}")
                        continue
                    
                    order_item_id = requirement['order_item_id']
                    if isinstance(order_item_id, str):
                        order_item_id = uuid.UUID(order_item_id)
                    elif not isinstance(order_item_id, uuid.UUID):
                        logger.error(f"Invalid order_item_id type: {type(order_item_id)} - {order_item_id}")
                        continue
                    
                    plan_order_link = models.PlanOrderLink(
                        frontend_id=frontend_id,
                        plan_id=plan.id,
                        order_id=order_id,
                        order_item_id=order_item_id,
                        quantity_allocated=requirement['quantity']  # Use actual quantity
                    )
                    self.db.add(plan_order_link)
                    self.db.flush()  # Ensure this record is committed before generating next frontend_id
            
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
                    paper = crud_operations.get_paper_by_specs(self.db, gsm=gsm, bf=bf, shade=shade)
                    if not paper and self.user_id:
                        paper_data = type('PaperCreate', (), {
                            'name': f"{shade} {gsm}GSM BF{bf}",
                            'gsm': gsm,
                            'bf': bf,
                            'shade': shade,
                            'type': 'standard',
                            'created_by_id': self.user_id
                        })()
                        paper = crud_operations.create_paper(self.db, paper_data=paper_data)
                    
                    if paper:
                        production_order = models.ProductionOrderMaster(
                            paper_id=paper.id,
                            quantity=1,  # One jumbo roll per production order
                            priority="normal",
                            status=schemas.ProductionOrderStatus.PENDING.value,
                            created_by_id=self.user_id
                        )
                        self.db.add(production_order)
                        self.db.flush()  # Get ID
                        created_production.append(production_order)
                        created_production_ids.append(str(production_order.id))  # Store ID immediately
            
            # OUTPUT 3: Create pending orders for unfulfillable requirements (PHASE 1 per documentation)
            # These are algorithm limitations where cutting efficiency is insufficient
            logger.info("Creating pending orders for unfulfillable requirements (algorithm limitations)")
            
            pending_orders_from_algorithm = optimization_result.get('pending_orders', [])
            for pending_order_data in pending_orders_from_algorithm:
                try:
                    # Find the original order this pending requirement came from
                    original_order_id = None
                    paper_id = None
                    
                    # Match with order requirements to get original order ID
                    for req in self.processed_order_requirements:
                        if (req.get('gsm') == pending_order_data.get('gsm') and
                            req.get('bf') == pending_order_data.get('bf') and 
                            req.get('shade') == pending_order_data.get('shade')):
                            original_order_id = req['order_id']
                            break
                    
                    if original_order_id:
                        # Convert string UUID to UUID object if needed
                        if isinstance(original_order_id, str):
                            original_order_id = uuid.UUID(original_order_id)
                        
                        # Generate frontend ID for the pending order
                        frontend_id = FrontendIDGenerator.generate_frontend_id("pending_order_item", self.db)
                        
                        # Create pending order with PHASE 1 flags (algorithm limitation)
                        # Note: PendingOrderItem stores paper specs directly (gsm, bf, shade) instead of paper_id
                        pending_order = models.PendingOrderItem(
                            frontend_id=frontend_id,
                            original_order_id=original_order_id,
                            width_inches=float(pending_order_data['width']),
                            quantity_pending=pending_order_data['quantity'],
                            gsm=pending_order_data['gsm'],
                            bf=float(pending_order_data['bf']),
                            shade=pending_order_data['shade'],
                            status="pending",
                            included_in_plan_generation=False,  # PHASE 1: Algorithm limitation
                            reason="insufficient_cutting_efficiency",
                            created_by_id=self.user_id
                        )
                        
                        self.db.add(pending_order)
                        created_pending.append(pending_order)
                        logger.info(f"Created PHASE 1 pending order: {pending_order_data['quantity']} rolls of {pending_order_data['width']}\" {pending_order_data['shade']} paper (algorithm limitation)")
                        
                    else:
                        logger.warning(f"Could not find original order for pending requirement: {pending_order_data}")
                        
                except Exception as e:
                    logger.error(f"Error creating pending order for algorithm limitation: {e}")
            
            self.db.flush()  # Ensure pending orders are saved before continuing
            
            # OUTPUT 4: Mark pending orders that contributed to plan generation with tracking flags
            # Per two-phase strategy: Only mark as included_in_plan_generation=True if they generated cut rolls
            # Status remains "pending" until production start (PHASE 2)
            logger.info("Setting plan generation tracking flags for pending orders that generated cut rolls")
            self._mark_pending_orders_in_plan_generation(pending_requirements, optimization_result)
            
            # IMPORTANT: Two-Phase Pending Order Strategy Implementation Complete
            # PHASE 1 (Plan Generation): Created pending orders for algorithm limitations (included_in_plan_generation=FALSE)  
            # PHASE 2 (Production Start): Will create pending orders for user deferrals (included_in_plan_generation=TRUE)
            # 
            # Order status updates happen only during production start, not plan generation
            # Orders remain in "created" status until production actually starts
            
            self.db.commit()
            
            # Calculate summary statistics and enhance cut rolls with paper_id
            cut_rolls_generated = optimization_result.get('cut_rolls_generated', [])
            
            # Enhance cut rolls with paper_id by looking up paper master records
            logger.info(f"🔍 DEBUG WF: Starting paper_id enhancement for {len(cut_rolls_generated)} cut rolls")
            enhanced_cut_rolls = []
            for i, cut_roll in enumerate(cut_rolls_generated):
                enhanced_roll = cut_roll.copy()
                
                # FALLBACK: Map to paper_id from order requirements (simpler and more reliable)
                paper_id_found = False
                if 'gsm' in cut_roll and 'bf' in cut_roll and 'shade' in cut_roll:
                    # Try to find matching order requirement
                    for req in self.processed_order_requirements:
                        if (req.get('gsm') == cut_roll['gsm'] and 
                            req.get('bf') == cut_roll['bf'] and 
                            req.get('shade') == cut_roll['shade']):
                            enhanced_roll['paper_id'] = req['paper_id']
                            enhanced_roll['order_id'] = req['order_id']  # Add the order_id so it can match pending orders
                            paper_id_found = True
                            break
                    
                    # If no match found in order requirements, try database lookup
                    if not paper_id_found:
                        logger.info(f"🔍 DEBUG WF: No match in order requirements, trying database lookup")
                        try:
                            paper = crud_operations.get_paper_by_specs(
                                self.db, 
                                gsm=cut_roll['gsm'], 
                                bf=cut_roll['bf'], 
                                shade=cut_roll['shade']
                            )
                            if paper:
                                enhanced_roll['paper_id'] = str(paper.id)
                                logger.info(f"✅ DEBUG WF: Found existing paper in DB with ID: {paper.id}")
                                
                                # Also try to find matching pending order for order_id
                                for pending_req in pending_requirements:
                                    if (pending_req.get('gsm') == cut_roll['gsm'] and 
                                        pending_req.get('bf') == cut_roll['bf'] and 
                                        pending_req.get('shade') == cut_roll['shade']):
                                        enhanced_roll['order_id'] = pending_req['original_order_id']
                                        break
                                
                                paper_id_found = True
                            else:
                                logger.info(f"📝 DEBUG WF: Paper not found in DB, using first order requirement paper_id as fallback")
                                # Use first order requirement's paper_id as fallback
                                if self.processed_order_requirements:
                                    enhanced_roll['paper_id'] = self.processed_order_requirements[0]['paper_id']
                                    enhanced_roll['order_id'] = self.processed_order_requirements[0]['order_id']
                                    paper_id_found = True
                        except Exception as paper_error:
                            logger.error(f"❌ DEBUG WF: Error in paper lookup: {paper_error}")
                
                    if not paper_id_found:
                        enhanced_roll['paper_id'] = ''
                        logger.error(f"❌ DEBUG WF: Could not find any paper_id for cut roll")
                else:
                    logger.error(f"❌ DEBUG WF: Cut roll missing paper specs: gsm={cut_roll.get('gsm')}, bf={cut_roll.get('bf')}, shade={cut_roll.get('shade')}")
                    enhanced_roll['paper_id'] = ''
                
                # Generate barcode for this cut roll (NEW: Using barcode instead of QR)
                try:
                    from ..services.barcode_generator import BarcodeGenerator
                    barcode_id = BarcodeGenerator.generate_cut_roll_barcode(self.db)
                    enhanced_roll['barcode_id'] = barcode_id
                except Exception as barcode_error:
                    logger.error(f"❌ DEBUG WF: Error generating barcode for cut roll {i+1}: {barcode_error}")
                    # Fallback to a timestamp-based ID
                    import time
                    enhanced_roll['barcode_id'] = f"CUT_ROLL_{int(time.time() * 1000)}_{i+1}"
                    
                enhanced_cut_rolls.append(enhanced_roll)
            
            logger.info(f"🔍 DEBUG WF: Finished enhancing {len(enhanced_cut_rolls)} cut rolls")
            
            total_cut_rolls = len(enhanced_cut_rolls)
            total_pending_orders = len(created_pending)
            total_pending_quantity = sum(po.quantity_pending for po in created_pending)
            
            return {
                "status": "success",
                "cut_rolls_generated": enhanced_cut_rolls,
                "jumbo_rolls_needed": optimization_result.get('jumbo_rolls_needed', 0),
                "pending_orders": [
                    {
                        "width": float(po.width_inches),
                        "quantity": po.quantity_pending,
                        "gsm": po.gsm,
                        "bf": float(po.bf),
                        "shade": po.shade,
                        "reason": po.reason
                    } for po in created_pending
                ],
                # NEW: Store source tracking metadata for production start
                "source_tracking_map": {
                    f"{cr.get('width', 0)}-{cr.get('gsm', 0)}-{cr.get('bf', 0)}-{cr.get('shade', '')}-{cr.get('individual_roll_number', 1)}": {
                        "source_type": cr.get('source_type'),
                        "source_pending_id": cr.get('source_pending_id'),
                        "source_order_id": cr.get('source_order_id')
                    }
                    for cr in enhanced_cut_rolls if cr.get('source_type')
                },
                "summary": {
                    "total_cut_rolls": total_cut_rolls,
                    "total_individual_118_rolls": optimization_result.get('summary', {}).get('total_individual_118_rolls', 0),
                    "total_jumbo_rolls_needed": optimization_result.get('jumbo_rolls_needed', 0),
                    "total_pending_orders": total_pending_orders,
                    "total_pending_quantity": total_pending_quantity,
                    "specification_groups_processed": len(set((cr.get('gsm'), cr.get('shade'), cr.get('bf')) for cr in enhanced_cut_rolls)),
                    "high_trim_patterns": 0,  # TODO: Calculate from optimization result
                    "algorithm_note": "Updated: 1-20\" trim accepted, >20\" goes to pending, no waste inventory created"
                },
                "orders_updated": [],  # No orders updated during plan generation
                "plans_created": created_plan_ids,
                "production_orders_created": created_production_ids
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
                
                # Create plan using crud_operations
                plan_master = crud_operations.create_plan(self.db, plan_data=type('PlanCreate', (), plan_data)())
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
        paper = crud_operations.get_paper_by_specs(
            self.db,
            gsm=paper_spec.get('gsm', 90),
            bf=paper_spec.get('bf', 18.0),
            shade=paper_spec.get('shade', 'white'),
            type=paper_spec.get('type', 'standard')
        )
        
        if not paper:
            # Create new paper master using crud_operations
            paper_data = type('PaperCreate', (), {
                'gsm': paper_spec.get('gsm', 90),
                'bf': paper_spec.get('bf', 18.0),
                'shade': paper_spec.get('shade', 'white'),
                'type': paper_spec.get('type', 'standard'),
                'created_by_id': self.user_id
            })()
            paper = crud_operations.create_paper(self.db, paper_data=paper_data)
        
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
            models.OrderMaster.status == schemas.OrderStatus.CREATED.value
        ).count()
        
        partial_orders = self.db.query(models.OrderMaster).filter(
            models.OrderMaster.status == schemas.OrderStatus.IN_PROCESS.value
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
                "created": pending_orders,
                "in_process": partial_orders,
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
    
    def _update_resolved_pending_orders(self, input_pending: List[Dict], output_pending: List[Dict]):
        """
        Update status of pending orders that were resolved by optimization.
        
        Args:
            input_pending: Pending orders that were input to optimization
            output_pending: Pending orders that remain after optimization
        """
        logger.info("🚀 _update_resolved_pending_orders method called!")
        try:
            logger.info(f"🔍 PENDING STATUS DEBUG: Starting with {len(input_pending) if input_pending else 0} input and {len(output_pending) if output_pending else 0} output pending orders")
            
            if not input_pending:
                logger.info("No input pending orders to check for resolution")
                return
            
            # Debug: Log input pending orders
            logger.info("🔍 INPUT PENDING ORDERS:")
            for i, item in enumerate(input_pending):
                logger.info(f"  {i+1}: width={item.get('width')}, gsm={item.get('gsm')}, bf={item.get('bf')}, shade={item.get('shade')}")
                logger.info(f"       order_id={item.get('order_id')}, original_order_id={item.get('original_order_id')}")
                logger.info(f"       all_keys={list(item.keys())}")
            
            # Debug: Log output pending orders  
            logger.info("🔍 OUTPUT PENDING ORDERS:")
            for i, item in enumerate(output_pending):
                logger.info(f"  {i+1}: width={item.get('width')}, gsm={item.get('gsm')}, bf={item.get('bf')}, shade={item.get('shade')}, order_id={item.get('original_order_id')}")
            
            # Create lookup sets for comparison
            # Use (width, gsm, bf, shade, original_order_id) as unique key
            def make_key(pending_item):
                return (
                    float(pending_item.get('width', 0)),
                    int(pending_item.get('gsm', 0)),
                    float(pending_item.get('bf', 0)),
                    str(pending_item.get('shade', '')),
                    str(pending_item.get('original_order_id', ''))
                )
            
            input_keys = set(make_key(item) for item in input_pending)
            output_keys = set(make_key(item) for item in output_pending)
            
            # Debug: Log the keys
            logger.info("🔍 INPUT KEYS:")
            for key in input_keys:
                logger.info(f"  {key}")
            logger.info("🔍 OUTPUT KEYS:")
            for key in output_keys:
                logger.info(f"  {key}")
            
            # Find pending orders that were resolved (in input but not in output)
            resolved_keys = input_keys - output_keys
            
            logger.info(f"🔍 RESOLVED KEYS:")
            for key in resolved_keys:
                logger.info(f"  {key}")
            
            logger.info(f"Pending orders analysis: {len(input_keys)} input, {len(output_keys)} output, {len(resolved_keys)} resolved")
            
            if not resolved_keys:
                logger.info("No pending orders were resolved in this optimization")
                return
            
            # Update status of resolved pending orders
            updated_count = 0
            for resolved_key in resolved_keys:
                width, gsm, bf, shade, original_order_id = resolved_key
                
                # Find and update matching pending order records
                from .. import models
                
                # Handle UUID conversion for original_order_id
                try:
                    order_id_uuid = uuid.UUID(original_order_id) if isinstance(original_order_id, str) else original_order_id
                except (ValueError, TypeError):
                    logger.warning(f"Invalid order_id format: {original_order_id}")
                    continue
                
                # Convert to Decimal to match database types exactly
                from decimal import Decimal
                width_decimal = Decimal(str(width))
                bf_decimal = Decimal(str(bf))
                
                resolved_items = self.db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.width_inches == width_decimal,
                    models.PendingOrderItem.gsm == gsm,
                    models.PendingOrderItem.bf == bf_decimal,
                    models.PendingOrderItem.shade == shade,
                    models.PendingOrderItem.original_order_id == order_id_uuid,
                    models.PendingOrderItem._status == "pending"
                ).all()
                
                for item in resolved_items:
                    try:
                        item.status = "included_in_plan"
                        item.resolved_at = datetime.utcnow()
                        updated_count += 1
                        logger.info(f"Marked pending order {item.frontend_id} as resolved: {width}\" {shade} paper")
                    except Exception as item_error:
                        logger.warning(f"Failed to update pending order {item.frontend_id}: {item_error}")
            
            logger.info(f"Updated {updated_count} pending orders to 'included_in_plan' status")
            
        except Exception as e:
            logger.error(f"Error updating resolved pending orders: {e}")
            # Don't raise - this shouldn't break the main workflow
    
    def _mark_pending_orders_in_plan_generation(self, pending_requirements: List[Dict], optimization_result: Dict):
        """
        Mark pending orders that were included in plan generation and actually generated cut rolls.
        Per documentation: Only mark with included_in_plan_generation = True if they contributed to the solution.
        Status remains "pending" until production start (PHASE 2).
        """
        from datetime import datetime
        
        try:
            cut_rolls_generated = optimization_result.get('cut_rolls_generated', [])
            
            # Count how many cut rolls were generated from each pending order
            pending_cut_roll_counts = {}
            
            for cut_roll in cut_rolls_generated:
                if cut_roll.get('source_type') == 'pending_order' and cut_roll.get('source_pending_id'):
                    pending_id = cut_roll.get('source_pending_id')
                    if pending_id in pending_cut_roll_counts:
                        pending_cut_roll_counts[pending_id] += 1
                    else:
                        pending_cut_roll_counts[pending_id] = 1
            
            logger.info(f"🔍 PLAN TRACKING: Found {len(pending_cut_roll_counts)} pending orders that generated cut rolls")
            
            # Update the tracking fields ONLY for pending orders that generated cut rolls
            for pending_id, cut_roll_count in pending_cut_roll_counts.items():
                try:
                    # Convert string UUID to UUID object if needed
                    if isinstance(pending_id, str):
                        import uuid
                        pending_uuid = uuid.UUID(pending_id)
                    else:
                        pending_uuid = pending_id
                    
                    # Find and update the pending order
                    pending_order = self.db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.id == pending_uuid
                    ).first()
                    
                    if pending_order:
                        # IMPORTANT: Only set to True for orders that actually generated cut rolls
                        pending_order.included_in_plan_generation = True
                        pending_order.generated_cut_rolls_count = cut_roll_count
                        pending_order.plan_generation_date = datetime.utcnow()
                        
                        # Status remains "pending" - will change to "included_in_plan" during production start
                        
                        logger.info(f"✅ PLAN TRACKING: Marked pending {pending_order.frontend_id} as included in plan generation ({cut_roll_count} cut rolls generated)")
                    else:
                        logger.warning(f"⚠️ PLAN TRACKING: Could not find pending order with ID {pending_id}")
                        
                except Exception as e:
                    logger.error(f"❌ PLAN TRACKING: Error updating pending order {pending_id}: {e}")
            
            # Ensure all other pending orders remain with included_in_plan_generation = False
            # This includes orders that were input but didn't generate cut rolls (high waste, etc.)
            for req in pending_requirements:
                pending_id = req.get('pending_id')
                if pending_id and pending_id not in pending_cut_roll_counts:
                    logger.info(f"📊 PLAN TRACKING: Pending order {pending_id} was NOT included in plan generation (likely high waste or technical limitation)")
                    # These orders maintain included_in_plan_generation = False (default)
            
        except Exception as e:
            logger.error(f"❌ PLAN TRACKING: Error in _mark_pending_orders_in_plan_generation: {e}")
            # Don't raise - this shouldn't break plan generation