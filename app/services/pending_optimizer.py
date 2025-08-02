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
        Groups rolls by jumbo and provides selection metadata.
        """
        combinations = []
        
        # Group cut rolls by their source jumbo roll or pattern
        jumbo_groups = {}
        for i, roll in enumerate(cut_rolls):
            # Create a group key based on paper specs and pattern
            group_key = f"{roll.get('gsm')}_{roll.get('shade')}_{roll.get('bf')}_pattern_{i//3}"  # Assume max 3 rolls per jumbo
            
            if group_key not in jumbo_groups:
                jumbo_groups[group_key] = {
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
            
            jumbo_groups[group_key]['rolls'].append({
                'width': roll.get('width'),
                'quantity': roll.get('quantity', 1),
                'source': roll.get('source', 'cutting')
            })
            jumbo_groups[group_key]['total_width'] += roll.get('width', 0)
        
        # Calculate trim for each combination
        for group_data in jumbo_groups.values():
            group_data['trim'] = round(118 - group_data['total_width'], 2)
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
            
            # Create plan master
            plan = models.PlanMaster(
                name=plan_name,
                cut_pattern=json.dumps(cut_rolls_generated),
                expected_waste_percentage=0,  # Calculate if needed
                status=schemas.PlanStatus.PLANNED.value,
                created_by_id=self.user_id
            )
            
            self.db.add(plan)
            self.db.flush()  # Get plan ID
            
            # Find and update pending orders that match the accepted combinations
            resolved_pending_orders = []
            for combo in combinations:
                paper_specs = combo['paper_specs']
                for roll_data in combo.get('rolls', []):
                    width = roll_data['width']
                    
                    # Find matching pending orders
                    matching_pending = self.db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.width_inches == width,
                        models.PendingOrderItem.gsm == paper_specs['gsm'],
                        models.PendingOrderItem.bf == paper_specs['bf'],
                        models.PendingOrderItem.shade == paper_specs['shade'],
                        models.PendingOrderItem.status == "pending"
                    ).limit(roll_data.get('quantity', 1)).all()
                    
                    # Update status of matching pending orders
                    for pending_item in matching_pending:
                        pending_item.status = "included_in_plan"
                        pending_item.resolved_at = datetime.utcnow()
                        resolved_pending_orders.append({
                            'pending_id': str(pending_item.id),
                            'frontend_id': pending_item.frontend_id,
                            'width': float(pending_item.width_inches),
                            'paper_specs': paper_specs
                        })
            
            self.db.commit()
            
            return {
                "status": "success",
                "plan_id": str(plan.id),
                "plan_name": plan_name,
                "resolved_pending_orders": resolved_pending_orders,
                "summary": {
                    "combinations_accepted": len(combinations),
                    "pending_orders_resolved": len(resolved_pending_orders),
                    "plan_created": True
                }
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error accepting pending combinations: {e}")
            raise