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
            
            # WASTAGE ALLOCATION: Check and allocate available wastage before planning
            wastage_allocations, reduced_order_requirements = self._check_and_reduce_orders_with_wastage(order_requirements)
            
            logger.info(f"CALCULATION: Processing {len(order_requirements)} orders, "
                       f"{len(pending_requirements)} pending, {len(available_inventory)} inventory, "
                       f"{len(wastage_allocations)} wastage matches")
            
            # PURE CALCULATION: Run optimization algorithm with reduced order requirements
            optimization_result = self.optimizer.optimize_with_new_algorithm(
                order_requirements=reduced_order_requirements,
                pending_orders=pending_requirements,
                available_inventory=available_inventory,
                interactive=False
            )
            
            # CALCULATION ONLY: Process and format results including wastage allocations
            result = self._format_calculation_result(optimization_result, order_ids)
            result['wastage_allocations'] = wastage_allocations
            return result
            
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
                'reason': pending.get('reason', 'unknown'),
                'client_name': pending.get('client_name', 'Unknown'),  # FIX: Pass through client name
                'client_id': pending.get('client_id'),                 # FIX: Pass through client ID
                'source_type': 'pending_order',                       # FIX: Add source type for tracking
                'source_pending_id': str(pending.get('pending_order_id', 'unknown')),  # FIX: Add source pending ID
                'source_order_id': str(pending.get('original_order_id', 'unknown'))    # FIX: Add source order ID
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
        cut_rolls = optimization_result.get('cut_rolls_generated', [])
        total_118_rolls = len([roll for roll in cut_rolls if roll.get('source') == 'cutting'])
        jumbo_rolls_available = total_118_rolls  # FLEXIBLE: Each 118" roll can be a separate jumbo (1-3 rolls per jumbo)
        
        # Enhanced: Add jumbo roll hierarchy information
        enhanced_cut_rolls, jumbo_roll_details = self._enhance_with_jumbo_hierarchy(cut_rolls)
        
        # Enhanced summary with jumbo roll width
        summary = optimization_result.get('summary', {})
        summary.update({
            'jumbo_roll_width': self.jumbo_roll_width,
            'jumbo_rolls_available': jumbo_rolls_available,
            'individual_118_rolls_available': total_118_rolls,
            'max_selectable_rolls': jumbo_rolls_available,  # FLEXIBLE: Can select any number of rolls
            'complete_jumbos': len([jr for jr in jumbo_roll_details if jr['roll_count'] >= 1]),  # FLEXIBLE: All jumbos with 1+ rolls
            'partial_jumbos': 0  # FLEXIBLE: No partial jumbos in new system
        })
        
        return {
            "cut_rolls_generated": enhanced_cut_rolls,
            "jumbo_rolls_available": jumbo_rolls_available,
            "pending_orders": optimization_result.get('pending_orders', []),
            "summary": summary,
            "jumbo_roll_details": jumbo_roll_details,
            "order_ids_processed": [str(oid) for oid in order_ids],
            "calculation_only": True  # Flag to indicate this is calculation-only result
        }
    
    def _enhance_with_jumbo_hierarchy(self, cut_rolls: List[Dict]) -> tuple:
        """
        Enhance cut rolls with jumbo hierarchy information.
        
        Returns:
            Tuple of (enhanced_cut_rolls, jumbo_roll_details)
        """
        enhanced_cut_rolls = []
        jumbo_roll_details = []
        
        # Group cut rolls by paper specification and individual roll number
        spec_groups = {}
        for roll in cut_rolls:
            if roll.get('source') != 'cutting':
                # Keep inventory rolls as-is
                enhanced_cut_rolls.append(roll)
                continue
                
            spec_key = f"{roll.get('gsm', 0)}gsm-{roll.get('bf', 0)}bf-{roll.get('shade', '')}"
            if spec_key not in spec_groups:
                spec_groups[spec_key] = {}
            
            roll_num = roll.get('individual_roll_number', 0)
            if roll_num not in spec_groups[spec_key]:
                spec_groups[spec_key][roll_num] = []
            
            spec_groups[spec_key][roll_num].append(roll)
        
        # Create jumbo roll hierarchy
        jumbo_counter = 1
        
        for spec_key, roll_groups in spec_groups.items():
            # Sort roll numbers by AVERAGE WASTAGE instead of roll number for wastage-based JR assignment
            def get_avg_wastage(roll_num):
                rolls_in_group = roll_groups[roll_num]
                if not rolls_in_group:
                    return 999  # High value for empty groups
                total_trim = sum(roll.get('trim_left', 0) for roll in rolls_in_group)
                return total_trim / len(rolls_in_group)
            
            # WASTAGE-BASED SORTING: JR-001 gets lowest wastage, JR-002 gets medium, etc.
            sorted_roll_numbers = sorted(roll_groups.keys(), key=get_avg_wastage)
            
            logger.info(f"🔄 JR ASSIGNMENT: Sorted rolls by wastage for {spec_key}")
            for i, roll_num in enumerate(sorted_roll_numbers[:5]):  # Log first 5
                avg_waste = get_avg_wastage(roll_num)
                logger.info(f"  Roll {roll_num}: {avg_waste:.1f}\" avg wastage → will be in JR-{jumbo_counter + i // 3:03d}")
            
            # Group rolls flexibly into jumbos (1-3 rolls per jumbo, optimized grouping)
            i = 0
            while i < len(sorted_roll_numbers):
                jumbo_id = f"JR-{jumbo_counter:03d}"
                jumbo_frontend_id = f"JR-{jumbo_counter:03d}"
                
                # FLEXIBLE: Get 1-3 rolls for this jumbo (adaptive grouping)
                remaining_rolls = len(sorted_roll_numbers) - i
                if remaining_rolls >= 3:
                    rolls_to_take = 3  # Take 3 if we have 3 or more
                elif remaining_rolls == 2:
                    rolls_to_take = 2  # Take 2 if only 2 remain
                else:
                    rolls_to_take = 1  # Take 1 if only 1 remains
                
                rolls_in_jumbo = sorted_roll_numbers[i:i+rolls_to_take]
                i += rolls_to_take
                roll_count = len(rolls_in_jumbo)
                total_cuts = 0
                total_used_width = 0
                
                # Process each 118" roll in this jumbo
                for seq_num, roll_num in enumerate(rolls_in_jumbo, 1):
                    roll_118_id = f"R118-{jumbo_counter:03d}-{seq_num}"
                    cuts_in_roll = roll_groups[roll_num]
                    
                    # Enhance each cut roll with hierarchy info
                    for cut_roll in cuts_in_roll:
                        enhanced_roll = cut_roll.copy()
                        enhanced_roll.update({
                            'jumbo_roll_id': jumbo_id,
                            'jumbo_roll_frontend_id': jumbo_frontend_id,
                            'parent_118_roll_id': roll_118_id,
                            'roll_sequence': seq_num,
                            'individual_roll_number': roll_num
                        })
                        enhanced_cut_rolls.append(enhanced_roll)
                        total_cuts += 1
                        total_used_width += cut_roll.get('width', 0)
                
                # Calculate jumbo statistics
                efficiency = 0
                if roll_count > 0:
                    avg_width_per_roll = total_used_width / roll_count
                    efficiency = (avg_width_per_roll / self.jumbo_roll_width) * 100
                
                # Calculate average wastage for this jumbo
                total_wastage = 0
                wastage_count = 0
                for roll_num in rolls_in_jumbo:
                    for cut_roll in roll_groups[roll_num]:
                        total_wastage += cut_roll.get('trim_left', 0)
                        wastage_count += 1
                
                avg_wastage = total_wastage / wastage_count if wastage_count > 0 else 0
                
                # Log the wastage grouping result
                logger.info(f"✅ {jumbo_id}: {avg_wastage:.1f}\" avg wastage ({wastage_count} cuts)")
                
                # Create jumbo roll detail
                jumbo_detail = {
                    'jumbo_id': jumbo_id,
                    'jumbo_frontend_id': jumbo_frontend_id,
                    'paper_spec': spec_key.replace('-', ', '),
                    'roll_count': roll_count,
                    'total_cuts': total_cuts,
                    'total_used_width': total_used_width,
                    'efficiency_percentage': round(efficiency, 1),
                    'average_wastage': round(avg_wastage, 1),  # NEW: Add average wastage to jumbo details
                    'is_complete': roll_count >= 1,  # FLEXIBLE: Any jumbo with 1+ rolls is complete
                    'roll_numbers': rolls_in_jumbo
                }
                
                jumbo_roll_details.append(jumbo_detail)
                jumbo_counter += 1
        
        return enhanced_cut_rolls, jumbo_roll_details
    
    def _check_wastage_allocations(self, order_requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Check available wastage rolls that can fulfill order requirements.
        Returns list of potential wastage allocations without making database changes.
        """
        from ..crud.inventory import CRUDInventory
        from .. import models
        
        wastage_allocations = []
        inventory_crud = CRUDInventory(models.InventoryMaster)
        
        for order_req in order_requirements:
            paper_id = order_req.get('paper_id')
            width_inches = order_req.get('width_inches')
            
            logger.info(f"🔍 ORDER REQ: Looking for wastage matching Order {order_req.get('order_id')} - "
                       f"Width: {width_inches}\", Paper: {paper_id}")
            
            # Find available wastage rolls for this specification
            available_wastage = inventory_crud.get_available_wastage_rolls(
                self.db,
                paper_id=paper_id,
                width_inches=width_inches
            )
            
            logger.info(f"🔍 QUERY RESULT: Found {len(available_wastage)} available wastage rolls")
            
            for wastage_roll in available_wastage:
                # Consider wastage regardless of weight (weight will be set during QR scan)
                # Log the wastage roll details for debugging
                logger.info(f"🔍 WASTAGE DEBUG: Found wastage roll {wastage_roll.frontend_id} - "
                           f"Width: {wastage_roll.width_inches}\", Paper: {wastage_roll.paper_id}, "
                           f"Weight: {wastage_roll.weight_kg}kg, Status: {wastage_roll.status}")
                
                allocation = {
                    'wastage_id': wastage_roll.id,
                    'wastage_frontend_id': wastage_roll.frontend_id,
                    'order_id': order_req.get('order_id'),
                    'order_item_id': order_req.get('order_item_id'),
                    'paper_id': paper_id,
                    'width_inches': width_inches,
                    'weight_kg': wastage_roll.weight_kg,
                    'source_order_id': wastage_roll.wastage_source_order_id,
                    'source_plan_id': wastage_roll.wastage_source_plan_id
                }
                wastage_allocations.append(allocation)
                logger.info(f"✅ WASTAGE MATCH: Allocated {wastage_roll.frontend_id} to order {order_req.get('order_id')}")
                
                # Only one wastage roll per order requirement for now
                break
        
        logger.info(f"🔄 WASTAGE ALLOCATION: Found {len(wastage_allocations)} potential wastage matches")
        return wastage_allocations
    
    def _check_and_reduce_orders_with_wastage(self, order_requirements: List[Dict[str, Any]]) -> tuple:
        """
        Check available wastage from wastage_inventory table and reduce order item quantities.
        
        Returns:
            Tuple of (wastage_allocations, reduced_order_requirements)
        """
        from .. import models
        
        wastage_allocations = []
        reduced_order_requirements = []
        
        logger.info(f"🔄 WASTAGE: Checking wastage allocation for {len(order_requirements)} orders")
        
        for order_req in order_requirements:
            paper_id = order_req.get('paper_id')
            # Handle both 'width_inches' and 'width' field names for compatibility
            width_inches = order_req.get('width_inches') or order_req.get('width')
            order_id = order_req.get('order_id')
            order_item_id = order_req.get('order_item_id')
            current_quantity = order_req.get('quantity', 0)

            logger.info(f"🔍 ORDER {order_id}: Looking for wastage - Width: {width_inches}\", Paper: {paper_id}, Qty: {current_quantity}")
            
            # Find available wastage rolls matching this order's specifications
            available_wastage = self.db.query(models.WastageInventory).filter(
                models.WastageInventory.paper_id == paper_id,
                models.WastageInventory.width_inches == width_inches,
                models.WastageInventory.status == models.WastageStatus.AVAILABLE.value
            ).order_by(models.WastageInventory.weight_kg.desc()).all()
            
            logger.info(f"🔍 WASTAGE QUERY: Found {len(available_wastage)} available wastage rolls")
            
            total_wastage_weight = 0
            used_wastage = []
            
            # Use available wastage to reduce order quantity (1 wastage roll = 1 roll)
            for wastage_roll in available_wastage:
                if current_quantity <= 0:
                    break

                logger.info(f"🔍 WASTAGE ROLL: {wastage_roll.frontend_id} - {wastage_roll.width_inches}\" (1 roll)")

                # Each wastage roll = 1 roll that can fulfill order
                allocation = {
                    'wastage_id': wastage_roll.id,
                    'wastage_frontend_id': wastage_roll.frontend_id,
                    'order_id': order_id,
                    'order_item_id': order_item_id,
                    'paper_id': paper_id,
                    'width_inches': float(width_inches) if width_inches else 0,
                    'weight_kg': wastage_roll.weight_kg,
                    'quantity_reduced': 1  # Always 1 roll
                }

                wastage_allocations.append(allocation)
                used_wastage.append(wastage_roll)
                total_wastage_weight += 1  # Count rolls, not kg
                current_quantity -= 1  # Reduce by 1 roll

                logger.info(f"✅ WASTAGE ALLOCATED: {wastage_roll.frontend_id} (1 roll) to order {order_id}, remaining qty: {current_quantity}")
            
            # Create reduced order requirement
            if current_quantity > 0:
                # Still have remaining quantity after wastage allocation
                reduced_req = order_req.copy()
                reduced_req['quantity'] = current_quantity
                reduced_req['original_quantity'] = order_req.get('quantity', 0)
                reduced_req['wastage_allocated'] = total_wastage_weight
                reduced_order_requirements.append(reduced_req)

                logger.info(f"📉 ORDER REDUCED: {order_id} quantity reduced from {order_req.get('quantity', 0)} to {current_quantity} (wastage: {total_wastage_weight} rolls)")
            else:
                # Order fully satisfied by wastage
                logger.info(f"✅ ORDER FULFILLED: {order_id} completely fulfilled by wastage ({total_wastage_weight} rolls)")
        
        logger.info(f"🔄 WASTAGE SUMMARY: {len(wastage_allocations)} allocations, {len(reduced_order_requirements)} orders need cutting")
        
        return wastage_allocations, reduced_order_requirements