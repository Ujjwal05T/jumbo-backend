from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
import logging
import json

from .. import models, crud_operations, schemas
from .cutting_optimizer import CuttingOptimizer
from .id_generator import FrontendIDGenerator

logger = logging.getLogger(__name__)

class PendingOptimizer:
    """
    Optimization service for pending orders that provides preview functionality
    and selective plan creation from user-accepted combinations.
    """
    
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id
        self.optimizer = CuttingOptimizer()
    
    def preview_optimization(self) -> Dict[str, Any]:
        """
        Run optimization on all pending orders to preview possible solutions.
        Returns what-if scenarios without saving anything to database.
        
        Returns:
            Dict containing:
            - remaining_pending: Orders that still can't be fulfilled
            - roll_combinations: Achievable combinations with their details
            - roll_suggestions: What rolls are needed to complete 118-inch rolls
            - summary: Statistics about the optimization
        """
        try:
            logger.info("🔍 Starting pending order optimization preview")
            
            # Get all pending order items
            pending_items = crud_operations.get_pending_order_items(
                db=self.db, 
                skip=0, 
                limit=1000, 
                status="pending"
            )
            
            if not pending_items:
                return {
                    "status": "no_pending_orders",
                    "remaining_pending": [],
                    "roll_combinations": [],
                    "roll_suggestions": [],
                    "summary": {
                        "total_pending_input": 0,
                        "combinations_found": 0,
                        "remaining_pending": 0,
                        "suggested_rolls": 0
                    }
                }
            
            # Convert pending items to optimization format
            pending_requirements = []
            for item in pending_items:
                pending_req = {
                    'order_id': str(item.original_order_id) if item.original_order_id else 'unknown',
                    'original_order_id': str(item.original_order_id) if item.original_order_id else 'unknown',
                    'width': float(item.width_inches),
                    'quantity': item.quantity_pending,
                    'gsm': item.gsm,
                    'bf': float(item.bf),
                    'shade': item.shade,
                    'pending_id': str(item.id),
                    'frontend_id': item.frontend_id,
                    'reason': item.reason
                }
                pending_requirements.append(pending_req)
            
            logger.info(f"📊 Processing {len(pending_requirements)} pending order items")
            
            # Get available inventory for same paper specifications
            paper_specs = []
            for req in pending_requirements:
                spec = {'gsm': req['gsm'], 'bf': req['bf'], 'shade': req['shade']}
                if spec not in paper_specs:
                    paper_specs.append(spec)
            
            available_inventory_items = crud_operations.get_available_inventory_by_paper_specs(
                self.db, paper_specs
            )
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
            
            # Run optimization (preview mode - no database changes)
            optimization_result = self.optimizer.optimize_with_new_algorithm(
                order_requirements=[],  # Empty - we're only optimizing pending orders
                pending_orders=pending_requirements,
                available_inventory=available_inventory,
                interactive=False
            )
            
            # Process results for preview
            roll_combinations = self._process_roll_combinations(optimization_result.get('cut_rolls_generated', []))
            roll_suggestions = self._generate_roll_suggestions(optimization_result, pending_requirements)
            remaining_pending = optimization_result.get('pending_orders', [])
            
            # Debug logging
            logger.info(f"🔍 PENDING OPTIMIZER DEBUG:")
            logger.info(f"  Input pending requirements: {len(pending_requirements)}")
            logger.info(f"  Cut rolls generated: {len(optimization_result.get('cut_rolls_generated', []))}")
            logger.info(f"  Roll combinations processed: {len(roll_combinations)}")
            logger.info(f"  Remaining pending: {len(remaining_pending)}")
            logger.info(f"  Optimization result: {optimization_result}")

            return {
                "status": "success",
                "remaining_pending": remaining_pending,
                "roll_combinations": roll_combinations,
                "roll_suggestions": roll_suggestions,
                "summary": {
                    "total_pending_input": len(pending_requirements),
                    "combinations_found": len(roll_combinations),
                    "remaining_pending": len(remaining_pending),
                    "suggested_rolls": len(roll_suggestions),
                    "jumbo_rolls_needed": optimization_result.get('jumbo_rolls_needed', 0)
                }
            }
            
        except Exception as e:
            logger.error(f"Error in pending order optimization preview: {e}")
            raise
    
    def _process_roll_combinations(self, cut_rolls: List[Dict]) -> List[Dict]:
        """
        Process cut rolls into user-selectable combinations.
        The cutting optimizer already provides optimized combinations - we just need to format them properly.
        """
        logger.info(f"🔍 PROCESSING {len(cut_rolls)} cut rolls for combinations")
        combinations = []
        
        # Group cut rolls by their actual jumbo roll number (if provided by optimizer)
        # The cutting optimizer should already provide proper groupings
        jumbo_groups = {}
        
        for i, roll in enumerate(cut_rolls):
            logger.debug(f"  Roll {i+1}: {roll}")
            
            # Use individual_roll_number from main algorithm for proper 118" grouping
            jumbo_key = roll.get('individual_roll_number')
            
            # If no individual_roll_number, something is very wrong - create separate group
            if jumbo_key is None:
                logger.error(f"🚨 CRITICAL: Cut roll missing individual_roll_number: {roll}")
                jumbo_key = f"ERROR_{roll.get('gsm')}_{roll.get('shade')}_{roll.get('bf')}_{len(jumbo_groups)}"
            
            logger.debug(f"  Using jumbo_key: {jumbo_key} for roll {roll.get('width')} inches")
            
            if jumbo_key not in jumbo_groups:
                jumbo_groups[jumbo_key] = {
                    'combination_id': str(uuid.uuid4()),
                    'paper_specs': {
                        'gsm': roll.get('gsm'),
                        'bf': roll.get('bf'),
                        'shade': roll.get('shade')
                    },
                    'rolls': [],
                    'total_width': 0,
                    'trim': 0,
                    'jumbo_width': 118
                }
            
            jumbo_groups[jumbo_key]['rolls'].append({
                'width': roll.get('width'),
                'quantity': roll.get('quantity', 1),
                'source': roll.get('source', 'cutting')
            })
            jumbo_groups[jumbo_key]['total_width'] += roll.get('width', 0)
        
        # Calculate trim for each combination and validate 118" constraint
        for group_key, group_data in jumbo_groups.items():
            total_width = group_data['total_width']
            
            # 🚨 CRITICAL VALIDATION: Ensure no combination exceeds 118"
            if total_width > 118:
                logger.error(f"🚨 CRITICAL ERROR: Combination {group_key} exceeds 118\"!")
                logger.error(f"   Total width: {total_width}\" (over 118\" limit)")
                logger.error(f"   Rolls in combination: {group_data['rolls']}")
                logger.error(f"   This should NEVER happen if main algorithm worked correctly!")
                # Skip this invalid combination
                continue
            
            group_data['trim'] = round(118 - total_width, 2)
            
            # Additional validation: trim should be positive
            if group_data['trim'] < 0:
                logger.error(f"🚨 NEGATIVE TRIM: Combination {group_key} has negative trim: {group_data['trim']}\"")
                continue
                
            combinations.append(group_data)
        
        # Sort by efficiency (lower trim first)
        combinations.sort(key=lambda x: x['trim'])
        
        return combinations
    
    def _generate_roll_suggestions(self, optimization_result: Dict, pending_requirements: List[Dict]) -> List[Dict]:
        """
        Generate suggestions for what roll sizes are needed to complete 118-inch rolls
        for remaining pending orders.
        """
        suggestions = []
        remaining_pending = optimization_result.get('pending_orders', [])
        
        # Group remaining pending by paper specs
        spec_groups = {}
        for pending in remaining_pending:
            spec_key = (pending['gsm'], pending['shade'], pending['bf'])
            if spec_key not in spec_groups:
                spec_groups[spec_key] = {
                    'paper_specs': {
                        'gsm': pending['gsm'],
                        'bf': pending['bf'],
                        'shade': pending['shade']
                    },
                    'pending_widths': []
                }
            
            spec_groups[spec_key]['pending_widths'].append({
                'width': pending['width'],
                'quantity': pending['quantity']
            })
        
        # For each spec group, suggest combinations to reach 118 inches
        for spec_key, group_data in spec_groups.items():
            paper_specs = group_data['paper_specs']
            widths = [p['width'] for p in group_data['pending_widths']]
            
            # Generate simple suggestions (this could be enhanced with more complex algorithms)
            for width in widths:
                remaining_width = 118 - width
                if remaining_width > 20:  # Only suggest if significant space remains
                    suggestion = {
                        'suggestion_id': str(uuid.uuid4()),
                        'paper_specs': paper_specs,
                        'existing_width': width,
                        'needed_width': remaining_width,
                        'possible_combinations': self._suggest_width_combinations(remaining_width),
                        'description': f"Available: {width}\" | Required: {remaining_width}\""
                    }
                    suggestions.append(suggestion)
        
        return suggestions
    
    def _suggest_width_combinations(self, target_width: float) -> List[Dict]:
        """
        Suggest possible width combinations to fill the target width.
        """
        common_widths = [12, 15, 18, 20, 24, 25, 30, 36, 40, 42, 48, 54, 60]
        combinations = []
        
        # Single roll suggestions
        for width in common_widths:
            if width <= target_width and (target_width - width) <= 20:  # Max 20" trim
                combinations.append({
                    'rolls': [width],
                    'total_width': width,
                    'trim': round(target_width - width, 2)
                })
        
        # Two roll combinations
        for w1 in common_widths:
            for w2 in common_widths:
                if w1 <= w2:  # Avoid duplicates
                    total = w1 + w2
                    if total <= target_width and (target_width - total) <= 20:
                        combinations.append({
                            'rolls': [w1, w2],
                            'total_width': total,
                            'trim': round(target_width - total, 2)
                        })
        
        # Sort by trim (lower is better)
        combinations.sort(key=lambda x: x['trim'])
        
        # Return top 5 suggestions
        return combinations[:5]
    
    def accept_combinations(self, combinations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Accept selected roll combinations from optimization preview.
        Creates a new plan with selected combinations and marks relevant pending orders as resolved.
        
        Machine constraint: Only multiples of 3 combinations allowed (1 jumbo = 3 x 118" rolls).
        
        Args:
            combinations: List of combination objects with combination_id and other details
            
        Returns:
            Dict with plan ID, updated pending orders, and summary
        """
        try:
            logger.info(f"🎯 Accepting {len(combinations)} roll combinations")
            
            if not combinations:
                return {
                    "status": "no_combinations_selected",
                    "plan_id": None,
                    "resolved_pending_orders": [],
                    "summary": {"combinations_accepted": 0}
                }
            
            # Validate multiple of 3 constraint (machine limitation)
            if len(combinations) % 3 != 0:
                logger.warning(f"❌ Invalid combination count: {len(combinations)} (must be multiple of 3)")
                raise ValueError("Only multiple of 3 roll combinations can be selected. Machine creates 1 jumbo roll = 3 x 118 inch rolls.")
            
            # Create a new plan for accepted combinations
            plan_name = f"Pending Orders Plan {datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Convert combinations to cut_rolls format
            cut_rolls_generated = []
            for combo in combinations:
                for roll_data in combo.get('rolls', []):
                    cut_roll = {
                        'width': roll_data['width'],
                        'quantity': roll_data.get('quantity', 1),
                        'gsm': combo['paper_specs']['gsm'],
                        'bf': combo['paper_specs']['bf'],
                        'shade': combo['paper_specs']['shade'],
                        'source': 'cutting',
                        'combination_id': combo.get('combination_id')
                    }
                    cut_rolls_generated.append(cut_roll)
            
            # Create plan master - handle missing user_id by using system user
            user_id_to_use = self.user_id
            if user_id_to_use is None:
                # Try to get a system user or create a default one
                system_user = self.db.query(models.UserMaster).filter(
                    models.UserMaster.name == "System"
                ).first()
                
                if system_user:
                    user_id_to_use = system_user.id
                    logger.warning(f"⚠️ Using system user for pending orders plan: {system_user.id}")
                else:
                    # Create a temporary system user
                    system_user = models.UserMaster(
                        id=uuid.uuid4(),
                        name="System",
                        username="system",
                        password_hash="system_hash",  # Not used for system user
                        role="system",
                        status="active"
                    )
                    self.db.add(system_user)
                    self.db.flush()
                    user_id_to_use = system_user.id
                    logger.warning(f"⚠️ Created temporary system user for pending orders plan: {system_user.id}")
            
            plan = models.PlanMaster(
                name=plan_name,
                cut_pattern=json.dumps(cut_rolls_generated),
                expected_waste_percentage=0,  # Calculate if needed
                status=schemas.PlanStatus.PLANNED.value,
                created_by_id=user_id_to_use
            )
            
            self.db.add(plan)
            self.db.flush()  # Get plan ID
            
            # ✅ FIX: Create actual inventory items for each cut roll in the plan
            from ..services.barcode_generator import BarcodeGenerator
            created_inventory_items = []
            
            for combo in combinations:
                paper_specs = combo['paper_specs']
                
                # Find matching paper master record
                paper = self.db.query(models.PaperMaster).filter(
                    models.PaperMaster.gsm == paper_specs['gsm'],
                    models.PaperMaster.bf == paper_specs['bf'],
                    models.PaperMaster.shade == paper_specs['shade']
                ).first()
                
                if not paper:
                    logger.warning(f"No paper master found for {paper_specs}, skipping inventory creation")
                    continue
                
                for roll_data in combo.get('rolls', []):
                    width = roll_data['width']
                    quantity = roll_data.get('quantity', 1)
                    
                    # Find the best matching original order for this cut roll
                    best_order_id = None
                    
                    # Query pending items to find matching specifications and get original_order_id
                    # Convert to Decimal to match database types exactly
                    from decimal import Decimal
                    width_decimal = Decimal(str(width))
                    bf_decimal = Decimal(str(paper_specs['bf']))
                    
                    matching_pending = self.db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.width_inches == width_decimal,
                        models.PendingOrderItem.gsm == paper_specs['gsm'],
                        models.PendingOrderItem.bf == bf_decimal,
                        models.PendingOrderItem.shade == paper_specs['shade'],
                        models.PendingOrderItem.status == "pending",
                        models.PendingOrderItem.original_order_id.isnot(None)
                    ).first()
                    
                    if matching_pending:
                        best_order_id = matching_pending.original_order_id
                    
                    # Create inventory items for each quantity
                    for _ in range(quantity):
                        # Generate barcode for this cut roll
                        barcode_id = BarcodeGenerator.generate_cut_roll_barcode(self.db)
                        qr_code = f"QR{plan.id.hex[:8].upper()}{len(created_inventory_items)+1:03d}"
                        
                        # Create inventory item
                        inventory_item = models.InventoryMaster(
                            id=uuid.uuid4(),
                            paper_id=paper.id,
                            width_inches=width,
                            weight_kg=0.1,  # Placeholder weight (will be updated during production)
                            roll_type="cut",
                            location="production_floor",
                            status="cutting",  # Start in cutting status
                            qr_code=qr_code,
                            barcode_id=barcode_id,
                            production_date=datetime.utcnow(),
                            allocated_to_order_id=best_order_id,
                            created_by_id=user_id_to_use,
                            created_at=datetime.utcnow()
                        )
                        
                        self.db.add(inventory_item)
                        self.db.flush()  # Get inventory item ID
                        
                        # Create plan inventory link
                        plan_inventory_link = models.PlanInventoryLink(
                            id=uuid.uuid4(),
                            plan_id=plan.id,
                            inventory_id=inventory_item.id,
                            quantity_used=1.0  # One roll used
                        )
                        
                        self.db.add(plan_inventory_link)
                        created_inventory_items.append(inventory_item)
                        
            logger.info(f"✅ Created {len(created_inventory_items)} inventory items for plan {plan.id}")
            logger.info(f"✅ Created {len(created_inventory_items)} plan inventory links")
            
            # Find and update pending orders that match the accepted combinations
            resolved_pending_orders = []
            logger.info(f"Processing {len(combinations)} combinations to reduce pending orders...")
            
            for combo_idx, combo in enumerate(combinations):
                paper_specs = combo['paper_specs']
                logger.info(f"   Combo {combo_idx + 1}: {paper_specs['shade']} {paper_specs['gsm']}GSM")
                
                for roll_idx, roll_data in enumerate(combo.get('rolls', [])):
                    width = roll_data['width']
                    roll_quantity = roll_data.get('quantity', 1)
                    
                    logger.info(f"     Processing roll {roll_idx + 1}: {width}\" x{roll_quantity}")
                    
                    # Find matching pending orders that need to be reduced
                    # Convert to Decimal to match database types exactly
                    from decimal import Decimal
                    width_decimal = Decimal(str(width))
                    bf_decimal = Decimal(str(paper_specs['bf']))
                    
                    matching_pending = self.db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.width_inches == width_decimal,
                        models.PendingOrderItem.gsm == paper_specs['gsm'],
                        models.PendingOrderItem.bf == bf_decimal,
                        models.PendingOrderItem.shade == paper_specs['shade'],
                        models.PendingOrderItem.status == "pending",
                        models.PendingOrderItem.quantity_pending > 0
                    ).order_by(models.PendingOrderItem.created_at).all()
                    
                    logger.info(f"       Found {len(matching_pending)} matching pending orders")
                    
                    # Reduce quantities from pending orders
                    remaining_to_fulfill = roll_quantity
                    for pending_item in matching_pending:
                        if remaining_to_fulfill <= 0:
                            break
                            
                        current_pending = pending_item.quantity_pending
                        logger.info(f"         Pending item {pending_item.frontend_id}: has {current_pending}, need to reduce by {remaining_to_fulfill}")
                        
                        if current_pending <= remaining_to_fulfill:
                            # This pending order is fully resolved
                            logger.info(f"         FULLY RESOLVED: {pending_item.frontend_id} ({current_pending} rolls)")
                            pending_item.status = "resolved"
                            pending_item.quantity_pending = 0
                            pending_item.resolved_at = datetime.utcnow()
                            remaining_to_fulfill -= current_pending
                            
                            resolved_pending_orders.append({
                                'pending_id': str(pending_item.id),
                                'frontend_id': pending_item.frontend_id,
                                'width': float(pending_item.width_inches),
                                'quantity_resolved': current_pending,
                                'paper_specs': paper_specs,
                                'status': 'fully_resolved'
                            })
                        else:
                            # This pending order is partially resolved
                            logger.info(f"         PARTIALLY RESOLVED: {pending_item.frontend_id} ({remaining_to_fulfill} of {current_pending} rolls)")
                            pending_item.quantity_pending -= remaining_to_fulfill
                            # Keep status as pending since some quantity remains
                            
                            resolved_pending_orders.append({
                                'pending_id': str(pending_item.id),
                                'frontend_id': pending_item.frontend_id,
                                'width': float(pending_item.width_inches),
                                'quantity_resolved': remaining_to_fulfill,
                                'quantity_remaining': pending_item.quantity_pending,
                                'paper_specs': paper_specs,
                                'status': 'partially_resolved'
                            })
                            remaining_to_fulfill = 0
                    
                    if remaining_to_fulfill > 0:
                        logger.warning(f"Could not fully fulfill {width}\" roll requirement. {remaining_to_fulfill} rolls still needed but no matching pending orders found.")
            
            logger.info(f"PENDING ORDER REDUCTION SUMMARY:")
            logger.info(f"   Total resolved/reduced: {len(resolved_pending_orders)} items")
            for item in resolved_pending_orders:
                logger.info(f"   - {item['frontend_id']}: {item['width']}\" - {item['quantity_resolved']} rolls {item['status']}")
                if item.get('quantity_remaining'):
                    logger.info(f"     -> {item['quantity_remaining']} rolls still pending")
            
            self.db.commit()
            
            return {
                "status": "success",
                "plan_id": str(plan.id),
                "plan_name": plan_name,
                "resolved_pending_orders": resolved_pending_orders,
                "inventory_items_created": len(created_inventory_items),
                "summary": {
                    "combinations_accepted": len(combinations),
                    "pending_orders_resolved": len(resolved_pending_orders),
                    "inventory_items_created": len(created_inventory_items),
                    "plan_created": True
                }
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error accepting pending combinations: {e}")
            raise