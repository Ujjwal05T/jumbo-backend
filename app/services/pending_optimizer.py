from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from datetime import datetime
from itertools import combinations_with_replacement, permutations
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
    
    def get_roll_suggestions(self, wastage: float) -> Dict[str, Any]:
        """
        Generate jumbo roll suggestions based on pending orders.
        Creates optimal 1-3 roll combinations per jumbo roll using existing pending items.
        
        Args:
            wastage: Amount to subtract from 119 inches for target width calculation
            
        Returns:
            Dict containing:
            - target_width: Calculated target width (119 - wastage)
            - wastage: Input wastage amount
            - jumbo_suggestions: List of jumbo roll suggestions with 1-3 rolls each
            - summary: Statistics about pending items and suggestions
        """
        try:
            # Calculate target width for each 118" roll
            target_width = 119 - wastage
            logger.info(f"🎯 Generating JUMBO ROLL suggestions for target width: {target_width}\" (119 - {wastage} wastage)")
            
            # Get pending orders with available quantity
            pending_items = self.db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem._status == "pending",
                models.PendingOrderItem.quantity_pending > 0
            ).all()
            
            logger.info(f"🔍 Found {len(pending_items)} pending items")
            
            if not pending_items:
                logger.warning("❌ No pending orders found")
                return {
                    "status": "no_pending_orders",
                    "target_width": target_width,
                    "wastage": wastage,
                    "jumbo_suggestions": [],
                    "summary": {
                        "total_pending_input": 0,
                        "spec_groups_processed": 0,
                        "jumbo_rolls_suggested": 0,
                        "total_rolls_suggested": 0
                    }
                }
            
            # Group by paper specifications
            spec_groups = self._group_by_specs(pending_items)
            logger.info(f"🔍 Created {len(spec_groups)} spec groups")
            
            # Generate jumbo roll suggestions for each spec group
            jumbo_suggestions = []
            total_rolls_suggested = 0
            
            for spec_key, items in spec_groups.items():
                spec_suggestions = self._generate_jumbo_suggestions(spec_key, items, target_width)
                jumbo_suggestions.extend(spec_suggestions)
                
                for suggestion in spec_suggestions:
                    total_rolls_suggested += len(suggestion['rolls'])
            
            logger.info(f"🎯 JUMBO ROLL SUGGESTIONS RESULTS:")
            logger.info(f"  Total input items: {len(pending_items)}")
            logger.info(f"  Spec groups processed: {len(spec_groups)}")
            logger.info(f"  Jumbo rolls suggested: {len(jumbo_suggestions)}")
            logger.info(f"  Total rolls suggested: {total_rolls_suggested}")
            logger.info(f"  Target width per roll: {target_width}\"")

            return {
                "status": "success",
                "target_width": target_width,
                "wastage": wastage,
                "jumbo_suggestions": jumbo_suggestions,
                "summary": {
                    "total_pending_input": len(pending_items),
                    "spec_groups_processed": len(spec_groups),
                    "jumbo_rolls_suggested": len(jumbo_suggestions),
                    "total_rolls_suggested": total_rolls_suggested
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating jumbo roll suggestions: {e}")
            raise
    
    # Removed complex optimization methods - using simplified suggestions approach
    
    # Removed old suggestion methods - using simplified approach
    
    def _group_by_specs(self, pending_items: List[models.PendingOrderItem]) -> Dict[Tuple, List[models.PendingOrderItem]]:
        """Group pending items by paper specifications."""
        spec_groups = {}
        for item in pending_items:
            spec_key = (item.gsm, item.shade, float(item.bf))
            if spec_key not in spec_groups:
                spec_groups[spec_key] = []
            spec_groups[spec_key].append(item)
        return spec_groups
    
    # Removed complex optimization helper methods - no longer needed
    
    def _generate_jumbo_suggestions(self, spec_key: Tuple, items: List[models.PendingOrderItem], target_width: float) -> List[Dict]:
        """Generate jumbo roll suggestions for a specific paper specification."""
        suggestions = []
        
        # Convert items to width-quantity pairs for easier processing
        width_quantities = {}
        for item in items:
            width = float(item.width_inches)
            if width not in width_quantities:
                width_quantities[width] = 0
            width_quantities[width] += item.quantity_pending
        
        # Get available widths sorted by quantity (most available first)
        available_widths = sorted(width_quantities.keys(), key=lambda w: width_quantities[w], reverse=True)
        
        logger.info(f"  📊 Processing {spec_key[1]} {spec_key[0]}GSM: {len(available_widths)} unique widths, {sum(width_quantities.values())} total quantity")
        logger.info(f"  📊 Available widths: {dict(width_quantities)}")
        
        # Create working copy of quantities for consumption
        remaining_quantities = width_quantities.copy()
        
        # Generate jumbo roll suggestions while we have pending items
        jumbo_count = 0
        while sum(remaining_quantities.values()) > 0 and jumbo_count < 5:  # Limit to 5 jumbo suggestions per spec
            jumbo_count += 1
            
            # Try to create optimized rolls for this jumbo (1-3 rolls per jumbo, flexible)
            jumbo_rolls = self._create_optimal_jumbo_rolls(remaining_quantities, target_width)
            
            # Only create jumbo suggestion if we have actual rolls with existing items
            if not jumbo_rolls or all(not roll['uses_existing'] for roll in jumbo_rolls):
                break  # Can't create any more useful combinations using existing items
            
            # Create jumbo suggestion with pending order IDs
            pending_order_ids = [str(item.id) for item in items]  # Get all pending order IDs for this spec group
            
            suggestion = {
                'suggestion_id': str(uuid.uuid4()),
                'paper_specs': {
                    'gsm': spec_key[0],
                    'shade': spec_key[1],
                    'bf': spec_key[2]
                },
                'jumbo_number': jumbo_count,
                'target_width': target_width,
                'rolls': jumbo_rolls,
                'pending_order_ids': pending_order_ids,  # Add pending order IDs
                'summary': {
                    'total_rolls': len(jumbo_rolls),
                    'using_existing': sum(1 for roll in jumbo_rolls if roll['uses_existing']),
                    'new_rolls_needed': sum(1 for roll in jumbo_rolls if not roll['uses_existing']),
                    'total_waste': sum(roll['waste'] for roll in jumbo_rolls),
                    'avg_waste': round(sum(roll['waste'] for roll in jumbo_rolls) / len(jumbo_rolls), 2) if jumbo_rolls else 0
                }
            }
            
            suggestions.append(suggestion)
            logger.info(f"  📜 Jumbo #{jumbo_count}: {len(jumbo_rolls)} rolls, {suggestion['summary']['using_existing']} using existing, {suggestion['summary']['new_rolls_needed']} new needed")
        
        return suggestions
    
    def _create_optimal_jumbo_rolls(self, remaining_quantities: Dict[float, int], target_width: float, max_rolls: int = 3) -> List[Dict]:
        """Create optimal 118\" roll combinations for a jumbo roll."""
        rolls = []
        
        for roll_num in range(max_rolls):
            roll = self._create_single_optimal_roll(remaining_quantities, target_width)
            if roll:
                # Set the correct roll number
                roll['roll_number'] = roll_num + 1
                rolls.append(roll)
                # Update remaining quantities based on what was used
                if roll['uses_existing']:
                    for width, qty in roll['used_widths'].items():
                        if width in remaining_quantities:
                            remaining_quantities[width] -= qty
                            if remaining_quantities[width] <= 0:
                                del remaining_quantities[width]
            else:
                # Stop creating rolls if we can't use existing items
                # Don't create unnecessary "new roll needed" entries
                break
        
        return rolls
    
    def _create_single_optimal_roll(self, available_widths: Dict[float, int], target_width: float) -> Optional[Dict]:
        """Create a single optimized roll using available pending widths with unlimited pieces."""
        if not available_widths:
            return None
        
        width_list = [w for w, q in available_widths.items() if q > 0]
        if not width_list:
            return None
        
        # Use dynamic programming approach to find best combination
        best_combo = self._find_best_combination(width_list, available_widths, target_width)
        
        if best_combo:
            return {
                'roll_number': 1,  # Will be set by caller
                'target_width': target_width,
                'actual_width': best_combo['total_width'],
                'waste': best_combo['waste'],
                'display_as': best_combo.get('display_as', 'waste'),
                'needed_width': best_combo.get('needed_width', 0),
                'uses_existing': True,
                'widths': best_combo['widths'],
                'used_widths': best_combo['used_widths'],
                'description': f"{' + '.join(map(str, best_combo['widths']))} = {best_combo['total_width']}\" ({best_combo['display_message']})"
            }
        
        return None  # No good combination found
    
    def _find_best_combination(self, width_list: List[float], available_widths: Dict[float, int], target_width: float) -> Optional[Dict]:
        """Find the best combination of widths to fill target width with minimum waste."""
        best_combo = None
        min_waste = float('inf')
        
        # Try combinations with increasing number of pieces (up to reasonable limit)
        max_pieces = min(10, sum(available_widths.values()))  # Reasonable limit
        
        for num_pieces in range(1, max_pieces + 1):
            combo = self._try_combination_with_n_pieces(width_list, available_widths, target_width, num_pieces)
            if combo and combo['waste'] < min_waste:
                min_waste = combo['waste']
                best_combo = combo
                
                # If we found a perfect fit or very good fit, stop searching
                if combo['waste'] <= 2.0:  # Within 2 inches is excellent
                    break
        
        # Only return combinations with reasonable waste (up to 40% of target)
        if best_combo and best_combo['waste'] <= target_width * 0.4:
            # Determine if we should show as waste or needed width
            if best_combo['waste'] <= 5.0:
                best_combo['display_as'] = 'waste'
                best_combo['display_message'] = f"waste: {best_combo['waste']:.1f}\""
            else:
                best_combo['display_as'] = 'needed'
                best_combo['needed_width'] = best_combo['waste']
                best_combo['display_message'] = f"+ {best_combo['waste']:.1f}\" needed"
            return best_combo
        
        return None
    
    def _try_combination_with_n_pieces(self, width_list: List[float], available_widths: Dict[float, int], target_width: float, n: int) -> Optional[Dict]:
        """Try to find best combination using exactly n pieces."""
        from itertools import combinations_with_replacement
        
        best_combo = None
        min_waste = float('inf')
        
        # Generate combinations of n pieces
        for combo in combinations_with_replacement(width_list, n):
            # Check if we have enough of each width
            needed = {}
            for width in combo:
                needed[width] = needed.get(width, 0) + 1
            
            # Verify availability
            if all(available_widths.get(w, 0) >= needed.get(w, 0) for w in needed):
                total_width = sum(combo)
                if total_width <= target_width:
                    waste = target_width - total_width
                    if waste < min_waste:
                        min_waste = waste
                        best_combo = {
                            'widths': list(combo),
                            'used_widths': needed,
                            'total_width': total_width,
                            'waste': waste
                        }
        
        return best_combo
    
    # Removed complex practical combinations method - using simple suggestions
    
    # All complex optimization and acceptance methods removed - now only providing simple suggestions