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
        Generate ORDER-BASED roll suggestions for pending orders.
        Groups by original order and shows 118" roll sets per order with manual addition capability.
        """
        try:
            # Calculate target width for each 118" roll
            target_width = 119 - wastage
            
            # Get pending orders with available quantity and use eager loading for relationships
            from sqlalchemy.orm import joinedload
            pending_items = self.db.query(models.PendingOrderItem).options(
                joinedload(models.PendingOrderItem.original_order).joinedload(models.OrderMaster.client)
            ).filter(
                models.PendingOrderItem._status == "pending",
                models.PendingOrderItem.quantity_pending > 0
            ).all()
            
            if not pending_items:
                return {
                    "status": "no_pending_orders",
                    "target_width": target_width,
                    "wastage": wastage,
                    "order_suggestions": [],
                    "summary": {
                        "total_pending_input": 0,
                        "orders_processed": 0,
                        "roll_sets_suggested": 0,
                        "total_rolls_suggested": 0
                    }
                }
            
            # Group by original order ID
            order_groups = self._group_by_orders(pending_items)
            
            # Generate roll set suggestions for each order
            order_suggestions = []
            total_rolls_suggested = 0
            
            for order_id, order_data in order_groups.items():
                order_suggestion = self._generate_order_suggestions(order_data, target_width)
                if order_suggestion:
                    order_suggestions.append(order_suggestion)
                    total_rolls_suggested += order_suggestion['summary']['total_cuts']

            return {
                "status": "success",
                "target_width": target_width,
                "wastage": wastage,
                "order_suggestions": order_suggestions,
                "summary": {
                    "total_pending_input": len(pending_items),
                    "orders_processed": len(order_groups),
                    "roll_sets_suggested": len(order_suggestions),
                    "total_rolls_suggested": total_rolls_suggested
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating roll suggestions: {e}")
            raise
    
    # Removed complex optimization methods - using simplified suggestions approach
    
    # Removed old suggestion methods - using simplified approach
    
    def _group_by_orders(self, pending_items: List[models.PendingOrderItem]) -> Dict[str, Dict]:
        """Group pending items by original order AND paper specs to handle mixed-spec orders."""
        order_groups = {}
        for item in pending_items:
            order_id = str(item.original_order_id)
            # FIXED: Create composite key with order_id + paper_specs to handle mixed-spec orders
            paper_spec_key = f"{item.gsm}_{item.bf}_{item.shade}"
            composite_key = f"{order_id}|{paper_spec_key}"
            
            if composite_key not in order_groups:
                # Get order and client info from the joined query
                order_info = {
                    'order_id': order_id,
                    'order_frontend_id': item.original_order.frontend_id if item.original_order else 'Unknown',
                    'client_name': item.original_order.client.company_name if item.original_order and item.original_order.client else 'Unknown',
                    'paper_spec': {
                        'gsm': item.gsm,
                        'bf': float(item.bf),
                        'shade': item.shade
                    },
                    'pending_items': []
                }
                order_groups[composite_key] = order_info
            
            order_groups[composite_key]['pending_items'].append(item)
        return order_groups
    
    def _group_by_specs(self, pending_items: List[models.PendingOrderItem]) -> Dict[Tuple, List[models.PendingOrderItem]]:
        """Group pending items by paper specifications. (Legacy method)"""
        spec_groups = {}
        for item in pending_items:
            spec_key = (item.gsm, item.shade, float(item.bf))
            if spec_key not in spec_groups:
                spec_groups[spec_key] = []
            spec_groups[spec_key].append(item)
        return spec_groups
    
    def _generate_order_suggestions(self, order_data: Dict, target_width: float) -> Dict:
        """Generate jumbo roll suggestions for a specific order (proper hierarchy: Order → Jumbo Rolls → 118" Sets → Cuts)."""
        pending_items = order_data['pending_items']
        
        # Convert items to width-quantity pairs
        width_quantities = {}
        for item in pending_items:
            width = float(item.width_inches)
            if width not in width_quantities:
                width_quantities[width] = 0
            width_quantities[width] += item.quantity_pending
        
        total_input_quantity = sum(width_quantities.values())
        logger.info(f"🔍 DUPLICATION CHECK - Order {order_data['order_frontend_id']}:")
        logger.info(f"📦 INPUT INVENTORY: {dict(width_quantities)} (Total: {total_input_quantity})")
        
        # Generate jumbo rolls for this order (each jumbo = 3 sets of 118" rolls)  
        jumbo_rolls = self._create_order_jumbo_rolls(width_quantities, target_width)
        
        if not jumbo_rolls:
            return None
        
        # Calculate total cuts produced
        total_cuts_produced = sum(
            sum(cut.get('used_widths', {}).values()) 
            for jr in jumbo_rolls 
            for s in jr['sets'] 
            for cut in s['cuts']
        )
        
        logger.info(f"✅ OUTPUT CUTS: {total_cuts_produced}")
        logger.info(f"📊 RATIO: {total_cuts_produced}/{total_input_quantity} = {(total_cuts_produced/total_input_quantity)*100:.1f}%")
        
        if total_cuts_produced > total_input_quantity:
            logger.error(f"🚨 DUPLICATION DETECTED! Produced {total_cuts_produced} cuts from {total_input_quantity} input items")
        else:
            logger.info(f"✅ NO DUPLICATION: Cuts ≤ Input")
        
        # Create order suggestion
        suggestion = {
            'suggestion_id': str(uuid.uuid4()),
            'order_info': {
                'order_id': order_data['order_id'],
                'order_frontend_id': order_data['order_frontend_id'],
                'client_name': order_data['client_name']
            },
            'paper_spec': order_data['paper_spec'],
            'target_width': target_width,
            'jumbo_rolls': jumbo_rolls,
            'pending_order_ids': [str(item.id) for item in pending_items],
            'manual_addition_enabled': True,
            'summary': {
                'total_jumbo_rolls': len(jumbo_rolls),
                'total_118_sets': sum(len(jr['sets']) for jr in jumbo_rolls),
                'total_cuts': sum(len(s['cuts']) for jr in jumbo_rolls for s in jr['sets']),
                'using_existing_cuts': sum(len([c for c in s['cuts'] if c['uses_existing']]) for jr in jumbo_rolls for s in jr['sets'])
            }
        }
        
        return suggestion
    
    def _create_order_jumbo_rolls(self, width_quantities: Dict[float, int], target_width: float) -> List[Dict]:
        """Create optimized jumbo rolls for an order (each jumbo = 3 sets of 118" rolls)."""
        jumbo_rolls = []
        remaining_quantities = width_quantities.copy()
        
        jumbo_number = 1
        while sum(remaining_quantities.values()) > 0 and jumbo_number <= 3:  # Limit to 3 jumbo rolls per order
            # Create one jumbo roll (with up to 3 sets of 118" rolls)
            jumbo_roll = self._create_single_jumbo_roll(remaining_quantities, target_width, jumbo_number)
            
            if jumbo_roll and jumbo_roll['sets']:
                jumbo_rolls.append(jumbo_roll)
                
                # Update remaining quantities based on what was used in all sets
                for roll_set in jumbo_roll['sets']:
                    for cut in roll_set['cuts']:
                        if cut['uses_existing']:
                            for width_str, qty in cut.get('used_widths', {}).items():
                                width = float(width_str)  # Convert string back to float
                                if width in remaining_quantities:
                                    before_qty = remaining_quantities[width]
                                    remaining_quantities[width] -= qty
                                    logger.info(f"🔄 CONSUMED: {width}\" qty {qty} (was {before_qty}, now {remaining_quantities[width]})")
                                    if remaining_quantities[width] <= 0:
                                        logger.info(f"🏁 DEPLETED: {width}\" inventory exhausted")
                                        del remaining_quantities[width]
            else:
                break  # Can't create more useful jumbo rolls
                
            jumbo_number += 1
        
        return jumbo_rolls
    
    def _create_single_jumbo_roll(self, available_widths: Dict[float, int], target_width: float, jumbo_number: int) -> Optional[Dict]:
        """Create a single jumbo roll with up to 3 sets of 118\" rolls."""
        if not available_widths:
            return None
        
        sets = []
        temp_remaining = available_widths.copy()
        
        # Create up to 3 sets (118" rolls) for this jumbo
        for set_num in range(1, 4):  # Sets 1, 2, 3
            roll_set = self._create_single_118_roll_set(temp_remaining, target_width, set_num)
            if roll_set and roll_set['cuts']:
                sets.append(roll_set)
                
                # Update temp quantities
                for cut in roll_set['cuts']:
                    if cut['uses_existing']:
                        for width_str, qty in cut['used_widths'].items():
                            width = float(width_str)  # Convert string back to float
                            if width in temp_remaining:
                                before_qty = temp_remaining[width]
                                temp_remaining[width] -= qty
                                logger.info(f"⚙️ TEMP CONSUMED: {width}\" qty {qty} (was {before_qty}, now {temp_remaining[width]})")
                                if temp_remaining[width] <= 0:
                                    del temp_remaining[width]
            else:
                break  # Can't create more useful 118" sets
        
        if not sets:
            return None
        
        return {
            'jumbo_id': f"jumbo_{jumbo_number}",
            'jumbo_number': jumbo_number,
            'target_width': target_width,
            'sets': sets,
            'summary': {
                'total_sets': len(sets),
                'total_cuts': sum(len(s['cuts']) for s in sets),
                'using_existing_cuts': sum(len([c for c in s['cuts'] if c['uses_existing']]) for s in sets),
                'total_actual_width': sum(s['summary']['total_actual_width'] for s in sets),
                'total_waste': sum(s['summary']['total_waste'] for s in sets),
                'efficiency': round((sum(s['summary']['total_actual_width'] for s in sets) / (target_width * len(sets))) * 100, 1) if sets else 0
            }
        }
    
    def _create_single_118_roll_set(self, available_widths: Dict[float, int], target_width: float, set_number: int) -> Optional[Dict]:
        """Create a single 118\" roll set with optimal cut combinations."""
        if not available_widths:
            return None
        
        width_list = [w for w, q in available_widths.items() if q > 0]
        if not width_list:
            return None
        
        # Find best combination of cuts to fill target width
        best_combo = self._find_best_combination(width_list, available_widths, target_width)
        
        if not best_combo:
            return None
        
        # Create cuts from the best combination using actual needed quantities
        cuts = []
        cut_number = 1
        for width, quantity in best_combo['used_widths'].items():
            # Create one cut entry per width type (with correct quantity)
            cut = {
                'cut_id': f"cut_{cut_number}",
                'width_inches': width,
                'uses_existing': True,
                'used_widths': {str(width): quantity},  # Use actual quantity needed
                'description': f"{width}\" from pending (qty: {quantity})"
            }
            cuts.append(cut)
            cut_number += 1
        
        # Only allow manual addition if waste is greater than 20 inches
        manual_addition_available = best_combo['waste'] > 20.0
        
        return {
            'set_id': f"set_{set_number}",
            'set_number': set_number,
            'target_width': target_width,
            'cuts': cuts,
            'manual_addition_available': manual_addition_available,
            'summary': {
                'total_cuts': len(cuts),
                'using_existing_cuts': len(cuts),
                'total_actual_width': best_combo['total_width'],
                'total_waste': best_combo['waste'],
                'efficiency': round((best_combo['total_width'] / target_width) * 100, 1)
            }
        }
    
    def _create_single_roll_set(self, available_widths: Dict[float, int], target_width: float, set_number: int) -> Optional[Dict]:
        """Create a single 118" roll set with optimal piece combinations."""
        if not available_widths:
            return None
        
        width_list = [w for w, q in available_widths.items() if q > 0]
        if not width_list:
            return None
        
        # Try to create 1-3 rolls for this set
        rolls = []
        temp_remaining = available_widths.copy()
        
        for roll_num in range(1, 4):  # Up to 3 rolls per set
            roll = self._create_single_optimal_roll(temp_remaining, target_width)
            if roll:
                roll['roll_number'] = roll_num
                rolls.append(roll)
                
                # Update temp quantities
                if roll['uses_existing']:
                    for width, qty in roll['used_widths'].items():
                        if width in temp_remaining:
                            temp_remaining[width] -= qty
                            if temp_remaining[width] <= 0:
                                del temp_remaining[width]
            else:
                break
        
        if not rolls:
            return None
        
        return {
            'set_id': f"set_{set_number}",
            'set_number': set_number,
            'target_width': target_width,
            'rolls': rolls,
            'manual_addition_available': len(rolls) < 3,  # Can add more if less than 3 rolls
            'summary': {
                'total_rolls': len(rolls),
                'using_existing': sum(1 for r in rolls if r['uses_existing']),
                'total_width': sum(r['actual_width'] for r in rolls),
                'total_waste': sum(r['waste'] for r in rolls),
                'efficiency': round((sum(r['actual_width'] for r in rolls) / (target_width * len(rolls))) * 100, 1) if rolls else 0
            }
        }
    
    # Legacy methods for backward compatibility
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