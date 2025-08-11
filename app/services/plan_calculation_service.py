"""
Plan Calculation Service - Read-Only Optimization Logic

This service provides pure calculation functionality for plan generation
without any database operations. It separates the planning logic from
the database persistence logic.
"""

from typing import List, Dict, Optional, Any
import uuid
import logging
from sqlalchemy.orm import Session

from .. import crud_operations
from .cutting_optimizer import CuttingOptimizer

logger = logging.getLogger(__name__)


class PlanCalculationService:
    """
    Pure calculation service for plan generation.
    No database writes - only reads data and returns calculation results.
    """
    
    def __init__(self, db: Session, jumbo_roll_width: int = 118):
        self.db = db
        self.jumbo_roll_width = jumbo_roll_width
        self.optimizer = CuttingOptimizer(jumbo_roll_width=jumbo_roll_width)
    
    def calculate_plan_for_orders(
        self, 
        order_ids: List[uuid.UUID], 
        include_pending_orders: bool = True,
        include_available_inventory: bool = True
    ) -> Dict[str, Any]:
        """
        Calculate optimization plan for given orders (READ-ONLY).
        
        Args:
            order_ids: List of order UUIDs to process
            include_pending_orders: Whether to include pending orders in calculation
            include_available_inventory: Whether to include available inventory
            
        Returns:
            Dict containing calculation results without any database writes
        """
        try:
            # READ ONLY: Get order requirements
            order_requirements = crud_operations.get_orders_with_paper_specs(self.db, order_ids)
            
            if not order_requirements:
                return self._empty_result()
            
            # READ ONLY: Get paper specifications from orders
            paper_specs = self._extract_paper_specs(order_requirements)
            
            # READ ONLY: Fetch pending orders if requested
            pending_requirements = []
            if include_pending_orders:
                pending_orders = crud_operations.get_pending_orders_by_specs(self.db, paper_specs)
                pending_requirements = self._format_pending_requirements(pending_orders)
            
            # READ ONLY: Fetch available inventory if requested
            available_inventory = []
            if include_available_inventory:
                available_inventory = self._get_available_inventory(paper_specs)
            
            logger.info(f"CALCULATION: Processing {len(order_requirements)} orders, "
                       f"{len(pending_requirements)} pending, {len(available_inventory)} inventory")
            
            # PURE CALCULATION: Run optimization algorithm
            optimization_result = self.optimizer.optimize_with_new_algorithm(
                order_requirements=order_requirements,
                pending_orders=pending_requirements,
                available_inventory=available_inventory,
                interactive=False
            )
            
            # CALCULATION ONLY: Process and format results
            return self._format_calculation_result(optimization_result, order_ids)
            
        except Exception as e:
            logger.error(f"Error in plan calculation: {str(e)}")
            raise
    
    def _empty_result(self) -> Dict[str, Any]:
        """Return empty result structure."""
        return {
            "cut_rolls_generated": [],
            "jumbo_rolls_available": 0,
            "pending_orders": [],
            "summary": {
                "total_cut_rolls": 0,
                "total_individual_118_rolls": 0,
                "total_jumbo_rolls_available": 0,
                "total_pending_orders": 0,
                "total_pending_quantity": 0,
                "specification_groups_processed": 0,
                "high_trim_patterns": 0,
                "jumbo_roll_width": self.jumbo_roll_width,
                "algorithm_note": "No orders to process"
            }
        }
    
    def _extract_paper_specs(self, order_requirements: List[Dict]) -> List[Dict]:
        """Extract unique paper specifications from orders."""
        paper_specs = []
        for req in order_requirements:
            spec = {'gsm': req['gsm'], 'bf': req['bf'], 'shade': req['shade']}
            if spec not in paper_specs:
                paper_specs.append(spec)
        return paper_specs
    
    def _format_pending_requirements(self, pending_orders: List[Dict]) -> List[Dict]:
        """Format pending orders for optimizer input."""
        pending_requirements = []
        for pending in pending_orders:
            pending_req = {
                'order_id': str(pending.get('original_order_id', 'unknown')),
                'original_order_id': str(pending.get('original_order_id', 'unknown')),
                'width': float(pending.get('width', 0)),
                'quantity': pending.get('quantity', 0),
                'gsm': pending.get('gsm', 0),
                'bf': float(pending.get('bf', 0)),
                'shade': pending.get('shade', ''),
                'pending_id': str(pending.get('pending_order_id', 'unknown')),
                'reason': pending.get('reason', 'unknown')
            }
            pending_requirements.append(pending_req)
        return pending_requirements
    
    def _get_available_inventory(self, paper_specs: List[Dict]) -> List[Dict]:
        """Get available inventory formatted for optimizer."""
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
        
        return available_inventory
    
    def _format_calculation_result(
        self, 
        optimization_result: Dict, 
        order_ids: List[uuid.UUID]
    ) -> Dict[str, Any]:
        """Format optimization results for frontend consumption."""
        
        # Calculate available jumbo rolls based on generated 118" rolls
        total_118_rolls = len([roll for roll in optimization_result.get('cut_rolls_generated', [])
                              if roll.get('source') == 'cutting'])
        jumbo_rolls_available = total_118_rolls // 3  # Complete jumbos only
        
        # Enhanced summary with jumbo roll width
        summary = optimization_result.get('summary', {})
        summary.update({
            'jumbo_roll_width': self.jumbo_roll_width,
            'jumbo_rolls_available': jumbo_rolls_available,
            'individual_118_rolls_available': total_118_rolls,
            'max_selectable_rolls': jumbo_rolls_available * 3
        })
        
        return {
            "cut_rolls_generated": optimization_result.get('cut_rolls_generated', []),
            "jumbo_rolls_available": jumbo_rolls_available,
            "pending_orders": optimization_result.get('pending_orders', []),
            "summary": summary,
            "order_ids_processed": [str(oid) for oid in order_ids],
            "calculation_only": True  # Flag to indicate this is calculation-only result
        }