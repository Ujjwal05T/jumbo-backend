from collections import Counter, defaultdict
from itertools import product
from typing import List, Tuple, Dict, Optional, Set, Union, Any
import json
from dataclasses import dataclass
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
import uuid
import logging

from .. import models, schemas, crud_operations

logger = logging.getLogger(__name__)

class CutRollStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    USED = "used"

@dataclass
class RollSpec:
    """Specification for paper rolls including dimensions and quality."""
    width: int
    length: int
    gsm: int
    bf: float
    shade: str

# --- CONFIGURATIONS ---
DEFAULT_JUMBO_WIDTH = 118  # Default width, can be overridden
MIN_TRIM = 1
MAX_TRIM = 20
MAX_TRIM_WITH_CONFIRMATION = 20
MAX_ROLLS_PER_JUMBO = 5

class CuttingOptimizer:
    def __init__(self, jumbo_roll_width: int = DEFAULT_JUMBO_WIDTH):
        """
        Initialize the cutting optimizer with configuration.
        
        Args:
            jumbo_roll_width: Width of jumbo rolls in inches (default: 118)
        """
        self.jumbo_roll_width = jumbo_roll_width
    
    def generate_combos(self, sizes: List[float]) -> List[Tuple[Tuple[float, ...], float]]:
        """
        Generate all combos (1 to 3 rolls) with trim calculation.
        Returns combos sorted by: more rolls first, then lower trim.
        """
        logger.info(f"🔍 COMBO DEBUG: Generating combos for sizes: {sizes}")
        valid_combos = []
        for r in range(1, MAX_ROLLS_PER_JUMBO + 1):
            for combo in product(sizes, repeat=r):
                total = sum(combo)
                trim = round(self.jumbo_roll_width - total, 2)
                if 0 <= trim <= MAX_TRIM_WITH_CONFIRMATION:
                    valid_combos.append((tuple(sorted(combo)), trim))
                    logger.debug(f"🔍 COMBO DEBUG: Valid combo: {tuple(sorted(combo))} → {total}\" used, {trim}\" trim")
                else:
                    logger.debug(f"🔍 COMBO DEBUG: Rejected combo: {tuple(sorted(combo))} → {total}\" used, {trim}\" trim (outside 0-20\" range)")
        
        # Prefer: more rolls, then lower trim
        sorted_combos = sorted(valid_combos, key=lambda x: (-len(x[0]), x[1]))
        logger.info(f"🔍 COMBO DEBUG: Generated {len(sorted_combos)} valid combos, showing first 10:")
        for i, (combo, trim) in enumerate(sorted_combos[:10]):
            logger.info(f"  {i+1}. {combo} → trim={trim}\" ({len(combo)} pieces)")
        return sorted_combos

    def match_combos(self, orders: Dict[float, int], interactive: bool = False) -> Tuple[List[Tuple[Tuple[float, ...], float]], Dict[float, int], List[Tuple[Tuple[float, ...], float]]]:
        """
        Match combos with orders using the provided algorithm logic.
        
        Args:
            orders: Dictionary of {width: quantity}
            interactive: Whether to prompt user for high trim combos
            
        Returns:
            Tuple of (used_combos, pending_orders, high_trim_log)
        """
        order_counter = Counter(orders)
        combos = self.generate_combos(list(orders.keys()))
        used = []
        high_trim_log = []
        pending = defaultdict(int)
        
        # DETAILED MATCHING: Let's see exactly what's happening
        logger.info(f"🔧 DETAILED MATCHING: Starting with demand: {dict(order_counter)}")
        
        for combo_idx, (combo, trim) in enumerate(combos):
            combo_count = Counter(combo)
            applications_this_combo = 0
            
            logger.info(f"  🔍 Trying combo #{combo_idx+1}: {combo} → trim={trim}\" (needs: {dict(combo_count)})")
            
            while all(order_counter[k] >= v for k, v in combo_count.items()):
                if trim <= MAX_TRIM:
                    # Accept directly (up to 20" trim)
                    for k in combo:
                        order_counter[k] -= 1
                    used.append((combo, trim))
                    applications_this_combo += 1
                    
                    logger.info(f"    ✅ APPLIED #{applications_this_combo}: {combo} → remaining: {dict(order_counter)}")
                    
                    # Log trim decisions
                    if trim <= 6:
                        logger.debug(f"     ✅ ACCEPTED: {combo} → trim={trim}\" (normal)")
                    else:
                        logger.info(f"     ⚠️ ACCEPTED HIGH TRIM: {combo} → trim={trim}\" (6-20\" range)")
                        high_trim_log.append((combo, trim))
                else:
                    # >20" trim goes to pending orders
                    logger.warning(f"     ❌ REJECTED: {combo} → trim={trim}\" (>20\" - goes to pending)")
                    break
            
            if applications_this_combo == 0:
                logger.info(f"    ❌ SKIPPED: {combo} (insufficient demand: need {dict(combo_count)}, have {dict(order_counter)})")
            else:
                logger.info(f"    📊 TOTAL APPLIED: {combo} used {applications_this_combo} times")
        
        # Remaining = pending
        for size, qty in order_counter.items():
            if qty > 0:
                pending[size] = qty
                
        return used, dict(pending), high_trim_log



    def optimize_with_new_algorithm(
        self,
        order_requirements: List[Dict],
        pending_orders: List[Dict] = None,
        available_inventory: List[Dict] = None,
        interactive: bool = False
    ) -> Dict:
        """
        NEW FLOW: 3-input/4-output optimization algorithm.
        Groups orders by complete specification (GSM + Shade + BF) to ensure
        different paper types are not mixed in the same jumbo roll.
        
        Args:
            order_requirements: List of new order dicts with width, quantity, etc.
            pending_orders: List of pending orders from previous cycles
            available_inventory: List of available inventory rolls for reuse
            interactive: Whether to prompt user for high trim decisions
            
        Returns:
            Dict with 3 outputs:
            - cut_rolls_generated: Rolls that can be fulfilled
            - jumbo_rolls_needed: Number of jumbo rolls to procure
            - pending_orders: Orders that cannot be fulfilled (>20" trim)
        """
        logger.info(f"🔧 OPTIMIZER: Starting optimize_with_new_algorithm")
        logger.info(f"📦 INPUT: Order Requirements: {len(order_requirements)} items")
        logger.info(f"⏳ INPUT: Pending Orders: {len(pending_orders) if pending_orders else 0} items")
        logger.info(f"📋 INPUT: Available Inventory: {len(available_inventory) if available_inventory else 0} items")
        
        # Initialize default values for optional inputs
        if pending_orders is None:
            pending_orders = []
            logger.warning("⚠️  OPTIMIZER: pending_orders was None, initialized to empty list")
        if available_inventory is None:
            available_inventory = []
            logger.warning("⚠️  OPTIMIZER: available_inventory was None, initialized to empty list")
        
        # Log detailed input analysis
        logger.debug(f"📋 INPUT DETAILS: Order Requirements: {order_requirements}")
        logger.debug(f"📋 INPUT DETAILS: Pending Orders: {pending_orders}")
        logger.debug(f"📋 INPUT DETAILS: Available Inventory: {available_inventory}")
        
        # Combine all requirements but preserve source information
        # Tag each requirement with its source (regular order vs pending order)
        all_requirements = []
        
        # Add regular orders with source tag
        for req in order_requirements:
            req_with_source = req.copy()
            req_with_source['source_type'] = 'regular_order'
            req_with_source['source_order_id'] = req.get('order_id')
            all_requirements.append(req_with_source)
        
        # Add pending orders with source tag
        logger.info(f"🔍 OPTIMIZER DEBUG: Processing {len(pending_orders)} pending orders for source tracking")
        for i, req in enumerate(pending_orders):
            logger.info(f"🔍 OPTIMIZER DEBUG: Pending order {i+1}: {req}")
            logger.info(f"🔍 OPTIMIZER DEBUG: Available keys in pending order: {list(req.keys())}")
            req_with_source = req.copy()
            req_with_source['source_type'] = 'pending_order'
            req_with_source['source_order_id'] = req.get('original_order_id')  # Pending orders use original_order_id
            
            # TRY MULTIPLE POSSIBLE FIELD NAMES for pending ID
            source_pending_id = req.get('pending_id') or req.get('id') or req.get('frontend_id')
            req_with_source['source_pending_id'] = source_pending_id
            logger.info(f"🔍 OPTIMIZER DEBUG: Enhanced pending order {i+1}: source_type={req_with_source['source_type']}, source_pending_id={req_with_source['source_pending_id']}")
            logger.info(f"🔍 OPTIMIZER DEBUG: Used field for pending_id: pending_id={req.get('pending_id')}, id={req.get('id')}, frontend_id={req.get('frontend_id')}")
            all_requirements.append(req_with_source)
        
        logger.info(f"🔄 OPTIMIZER: Combined all_requirements: {len(all_requirements)} total items")
        logger.debug(f"📋 COMBINED REQUIREMENTS: {all_requirements}")
        
        # Group all requirements by complete specification (GSM + Shade + BF)
        # This ensures that different paper types are NEVER mixed in the same jumbo roll
        # Each jumbo roll will contain only 3 sets of 118" rolls with identical paper specs
        spec_groups = {}
        logger.info(f"🔍 OPTIMIZER: Grouping requirements by specification...")
        
        for i, req in enumerate(all_requirements):
            logger.debug(f"  📝 Processing requirement {i+1}: {req}")
            # Create unique key for paper specification - CRITICAL for avoiding paper mixing
            spec_key = (req['gsm'], req['shade'], req['bf'])
            logger.debug(f"  🔑 Spec key: {spec_key}")
            
            if spec_key not in spec_groups:
                spec_groups[spec_key] = {
                    'orders': {},
                    'inventory': [],
                    'spec': {'gsm': req['gsm'], 'shade': req['shade'], 'bf': req['bf']},
                    'source_tracking': {}  # NEW: Track which widths came from which sources
                }
                logger.info(f"  ✨ Created new spec group for {spec_key}")
            
            # Add width and quantity to this specification group
            width = float(req['width'])
            if width in spec_groups[spec_key]['orders']:
                old_qty = spec_groups[spec_key]['orders'][width]
                spec_groups[spec_key]['orders'][width] += req['quantity']
                logger.debug(f"  ➕ Added {req['quantity']} to existing width {width}\" (was {old_qty}, now {spec_groups[spec_key]['orders'][width]})")
            else:
                spec_groups[spec_key]['orders'][width] = req['quantity']
                logger.debug(f"  🆕 Added new width {width}\" with quantity {req['quantity']}")
            
            # NEW: Track source information for this width
            if width not in spec_groups[spec_key]['source_tracking']:
                spec_groups[spec_key]['source_tracking'][width] = []
            source_entry = {
                'source_type': req['source_type'],
                'source_order_id': req.get('source_order_id'),
                'source_pending_id': req.get('source_pending_id'),
                'quantity': req['quantity']
            }
            spec_groups[spec_key]['source_tracking'][width].append(source_entry)
            logger.info(f"  📋 SOURCE TRACKING: width={width}\", type={req['source_type']}, pending_id={req.get('source_pending_id')}")
        
        logger.info(f"📊 OPTIMIZER: Final spec_groups structure:")
        for spec_key, group_data in spec_groups.items():
            logger.info(f"  📋 Spec {spec_key}: {group_data['orders']}")
        
        # Add available inventory to matching specification groups
        print(f"\n📦 DEBUG: Adding available inventory to spec groups...")
        for i, inv_item in enumerate(available_inventory):
            print(f"  Processing inventory item {i+1}: {inv_item}")
            inv_spec_key = (inv_item['gsm'], inv_item['shade'], inv_item['bf'])
            print(f"  Inventory spec key: {inv_spec_key}")
            
            if inv_spec_key in spec_groups:
                spec_groups[inv_spec_key]['inventory'].append(inv_item)
                print(f"  ✅ Added inventory item to matching spec group {inv_spec_key}")
            else:
                print(f"  ❌ No matching spec group found for inventory item {inv_spec_key}")
        
        print(f"\n📋 DEBUG: Spec groups after adding inventory:")
        for spec_key, group_data in spec_groups.items():
            print(f"  Spec {spec_key}: {len(group_data['inventory'])} inventory items")
        
        # Process each specification group separately
        cut_rolls_generated = []
        new_pending_orders = []
        jumbo_rolls_needed = 0
        all_high_trims = []
        
        # NEW: Initialize assignment tracker for proper source distribution
        assignment_tracker = {}
        
        for spec_key, group_data in spec_groups.items():
            orders = group_data['orders']
            inventory = group_data['inventory']
            spec = group_data['spec']
            
            logger.info(f"🔧 OPTIMIZER: Processing Paper Spec: GSM={spec['gsm']}, Shade={spec['shade']}, BF={spec['bf']}")
            logger.info(f"   📦 Orders to fulfill: {orders}")
            logger.info(f"   📋 Available Inventory: {len(inventory)} items")
            for inv_idx, inv_item in enumerate(inventory):
                logger.debug(f"     📦 Inventory {inv_idx+1}: width={inv_item.get('width', 'N/A')}\", id={inv_item.get('id', 'N/A')}")
            
            total_order_quantity = sum(orders.values())
            logger.info(f"   📊 Total order quantity for this spec: {total_order_quantity} rolls")
            
            # First, try to fulfill orders using available inventory
            orders_copy = orders.copy()
            inventory_used = []
            
            logger.info(f"   🔄 OPTIMIZER: Starting inventory fulfillment phase...")
            logger.debug(f"   📦 Orders copy before inventory: {orders_copy}")
            
            for inv_idx, inv_item in enumerate(inventory):
                inv_width = float(inv_item['width'])
                print(f"     Checking inventory item {inv_idx+1}: width={inv_width}\"")
                
                if inv_width in orders_copy and orders_copy[inv_width] > 0:
                    # Use this inventory item
                    print(f"     ✅ MATCH! Using inventory for {inv_width}\" (had {orders_copy[inv_width]} orders)")
                    cut_rolls_generated.append({
                        'width': inv_width,
                        'quantity': 1,
                        'gsm': spec['gsm'],
                        'bf': spec['bf'],
                        'shade': spec['shade'],
                        'source': 'inventory',
                        'inventory_id': inv_item.get('id')
                    })
                    orders_copy[inv_width] -= 1
                    if orders_copy[inv_width] <= 0:
                        print(f"     📝 Fully satisfied {inv_width}\" orders, removing from list")
                        del orders_copy[inv_width]
                    else:
                        print(f"     📝 Still need {orders_copy[inv_width]} more {inv_width}\" rolls")
                    inventory_used.append(inv_item)
                else:
                    if inv_width not in orders_copy:
                        print(f"     ❌ No orders for {inv_width}\" width")
                    else:
                        print(f"     ❌ Already fulfilled all {inv_width}\" orders")
            
            print(f"   📦 Orders remaining after inventory: {orders_copy}")
            print(f"   📋 Inventory items used: {len(inventory_used)}")
            
            # Remove used inventory from available list
            remaining_inventory = [inv for inv in inventory if inv not in inventory_used]
            
            # Run the matching algorithm for remaining orders
            individual_118_rolls_needed = 0
            if orders_copy:
                logger.info(f"   🔪 OPTIMIZER: Running cutting algorithm for remaining orders: {orders_copy}")
                used, pending, high_trims = self.match_combos(orders_copy, interactive)
                logger.info(f"   📊 CUTTING RESULTS: {len(used)} patterns used, {len(list(pending.keys()))} pending widths")
                
                # Debug: Show what went to pending and why
                if pending:
                    logger.warning(f"   🔍 PENDING DEBUG: Items that couldn't be optimized:")
                    for width, qty in pending.items():
                        logger.warning(f"     • {width}\" x{qty} remaining - checking why this couldn't be optimized...")
                        
                        # Show some combinations that could work with this width
                        test_combos = []
                        for other_width in orders_copy.keys():
                            if other_width != width:
                                # Test 2-piece combo
                                combo_2 = width + other_width
                                trim_2 = 118 - combo_2
                                if 0 <= trim_2 <= 20:
                                    test_combos.append(f"({width}, {other_width}) = {combo_2}\", trim={trim_2}\"")
                                
                                # Test 3-piece combo
                                for third_width in orders_copy.keys():
                                    combo_3 = width + other_width + third_width
                                    trim_3 = 118 - combo_3
                                    if 0 <= trim_3 <= 20:
                                        test_combos.append(f"({width}, {other_width}, {third_width}) = {combo_3}\", trim={trim_3}\"")
                        
                        if test_combos:
                            logger.warning(f"       → Potential valid combos found:")
                            for combo in test_combos[:3]:  # Show first 3 potential combos
                                logger.warning(f"         {combo}")
                        else:
                            logger.warning(f"       → No valid combinations found within 0-20\" trim range")
                
                # Process successful cutting patterns (each pattern = 1 individual 118" roll)
                for pattern_idx, (combo, trim) in enumerate(used):
                    individual_118_rolls_needed += 1
                    logger.info(f"     ✂️ Pattern {pattern_idx+1}: {combo} → trim={trim}\" (Roll #{individual_118_rolls_needed})")
                    
                    # Add cut rolls from this pattern
                    for width in combo:
                        # NEW: Determine source information for this width with proper distribution
                        source_info = self._get_source_info_for_width(width, spec_groups[spec_key]['source_tracking'], assignment_tracker)
                        
                        cut_roll = {
                            'width': width,
                            'quantity': 1,
                            'gsm': spec['gsm'],
                            'bf': spec['bf'],
                            'shade': spec['shade'],
                            'source': 'cutting',
                            'individual_roll_number': individual_118_rolls_needed,
                            'trim_left': trim,
                            # NEW: Add source tracking fields
                            'source_type': source_info.get('source_type', 'regular_order'),
                            'source_order_id': source_info.get('source_order_id'),
                            'source_pending_id': source_info.get('source_pending_id'),
                            'order_id': source_info.get('source_order_id')  # Keep existing field for backward compatibility
                        }
                        cut_rolls_generated.append(cut_roll)
            else:
                logger.info(f"   ✅ OPTIMIZER: All orders fulfilled from inventory, no cutting needed")
            
            # JUMBO ROLL CALCULATION: Show ALL rolls to user, let them decide
            # Don't auto-move anything to pending - USER CHOICE!
            logger.info(f"   📊 JUMBO ROLL CALCULATION for spec {spec_key}:")
            logger.info(f"     🎯 Individual 118\" rolls generated: {individual_118_rolls_needed}")
            logger.info(f"     📦 Complete jumbo rolls possible: {individual_118_rolls_needed // 3}")
            if individual_118_rolls_needed % 3 > 0:
                logger.info(f"     ℹ️  Extra 118\" rolls available: {individual_118_rolls_needed % 3} (user can choose)")
            logger.info(f"     👤 USER DECIDES: All {individual_118_rolls_needed} rolls shown to user for selection")
            
            # Note: We don't auto-calculate jumbo_rolls_needed here anymore
            # It will be calculated based on user's actual selection in frontend
            
            # Add orders that couldn't be fulfilled to pending
            # CRITICAL: Only create new pending orders from unfulfilled REGULAR orders
            # Do NOT create duplicates of existing pending orders
            if orders_copy:
                logger.info(f"🔍 PENDING CONVERSION DEBUG: pending dict = {dict(pending)}")
                for width, qty in pending.items():
                    # Check source tracking to see if this unfulfilled order came from regular orders
                    source_tracking = spec_groups[spec_key]['source_tracking'].get(width, [])
                    regular_order_qty = 0
                    
                    # Count how many of these unfulfilled orders came from regular orders (not existing pending orders)
                    for source in source_tracking:
                        if source.get('source_type') == 'regular_order':
                            regular_order_qty += source.get('quantity', 0)
                    
                    # Only create pending orders for the portion that came from regular orders
                    pending_qty_to_create = min(qty, regular_order_qty)
                    
                    if pending_qty_to_create > 0:
                        logger.info(f"🔍 Creating pending order: {width}\" x{pending_qty_to_create} (from regular orders only)")
                        new_pending_orders.append({
                            'width': width,
                            'quantity': pending_qty_to_create,
                            'gsm': spec['gsm'],
                            'bf': spec['bf'],
                            'shade': spec['shade'],
                            'reason': 'waste_too_high'
                        })
                    else:
                        logger.info(f"🔍 SKIPPING pending order creation: {width}\" x{qty} (all from existing pending orders - no duplication)")
                        
                    # Log the breakdown for debugging
                    existing_pending_qty = qty - pending_qty_to_create
                    if existing_pending_qty > 0:
                        logger.info(f"     📋 Breakdown: {pending_qty_to_create} from regular orders, {existing_pending_qty} from existing pending orders")
                
                # Track high trim approvals
                for combo, trim in high_trims:
                    all_high_trims.append({
                        'combo': combo,
                        'trim': trim,
                        'waste_percentage': round((trim / self.jumbo_roll_width) * 100, 2),
                        'paper_spec': spec
                    })
        
        # Calculate summary statistics
        total_cut_rolls = len(cut_rolls_generated)
        total_pending = sum(order['quantity'] for order in new_pending_orders)
        total_individual_118_rolls = len([roll for roll in cut_rolls_generated if roll['source'] == 'cutting'])
        
        # Show total rolls available - user will decide how many to use
        # Don't auto-calculate jumbo_rolls_needed, let frontend calculate based on selection
        jumbo_rolls_needed = 0  # User choice - will be calculated when they select rolls
        
        # Log final results
        logger.info(f"🎯 OPTIMIZER RESULTS:")
        logger.info(f"   📦 Total cut rolls generated: {total_cut_rolls}")
        logger.info(f"   🎯 Total individual 118\" rolls: {total_individual_118_rolls}")
        logger.info(f"   👤 USER CHOICE: {total_individual_118_rolls} individual 118\" rolls available for selection")
        logger.info(f"   📦 MAX JUMBOS POSSIBLE: {total_individual_118_rolls // 3} complete jumbo rolls")
        logger.info(f"   ⏳ Total pending orders: {len(new_pending_orders)}")
        logger.info(f"   📊 Total pending quantity: {total_pending}")
        logger.info(f"   🔧 Specification groups processed: {len(spec_groups)}")
        logger.info(f"   ⚠️  High trim patterns: {len(all_high_trims)}")
        
        # Log detailed cut rolls
        logger.info(f"📋 DETAILED CUT ROLLS:")
        for i, roll in enumerate(cut_rolls_generated, 1):
            logger.info(f"   Roll {i}: {roll['width']}\" - GSM:{roll['gsm']}, BF:{roll['bf']}, Shade:{roll['shade']}, Source:{roll['source']}")
        
        # Log pending orders if any (consolidated to avoid duplicates)
        if new_pending_orders:
            logger.warning(f"⏳ PENDING ORDERS (>20\" trim):")
            logger.info(f"🔍 RAW PENDING ORDERS COUNT: {len(new_pending_orders)}")
            for i, pending in enumerate(new_pending_orders):
                logger.info(f"🔍 Raw pending {i+1}: {pending['width']}\" x{pending['quantity']}")
            
            # Consolidate pending orders by width, GSM, shade, BF to avoid duplicate logging
            consolidated_pending = {}
            for pending in new_pending_orders:
                key = (pending['width'], pending['gsm'], pending['bf'], pending['shade'], pending.get('reason', 'high_trim'))
                if key in consolidated_pending:
                    logger.info(f"🔍 CONSOLIDATING: {pending['width']}\" x{pending['quantity']} added to existing x{consolidated_pending[key]['quantity']}")
                    consolidated_pending[key]['quantity'] += pending['quantity']
                else:
                    logger.info(f"🔍 NEW PENDING: {pending['width']}\" x{pending['quantity']}")
                    consolidated_pending[key] = {
                        'width': pending['width'],
                        'quantity': pending['quantity'],
                        'gsm': pending['gsm'],
                        'bf': pending['bf'],
                        'shade': pending['shade'],
                        'reason': pending.get('reason', 'high_trim')
                    }
            
            # Log consolidated pending orders (no more duplicates!)
            for i, (key, pending_info) in enumerate(consolidated_pending.items(), 1):
                logger.warning(f"   Pending {i}: {pending_info['width']}\" x{pending_info['quantity']} - GSM:{pending_info['gsm']}, Reason:{pending_info['reason']}")
                
            # CRITICAL: Check what we're actually returning vs logging
            logger.info(f"🔍 FINAL PENDING ORDERS TO RETURN: {len(new_pending_orders)} items")
            for i, pending in enumerate(new_pending_orders):
                logger.info(f"🔍 Final return {i+1}: {pending}")
        
        # NEW FLOW: Return 3 distinct outputs (removed waste inventory)
        result = {
            'cut_rolls_generated': cut_rolls_generated,
            'jumbo_rolls_needed': jumbo_rolls_needed,  # CORRECTED: 1 jumbo roll = 3 sets of 118" rolls
            'pending_orders': new_pending_orders,
            'summary': {
                'total_cut_rolls': total_cut_rolls,
                'total_individual_118_rolls': total_individual_118_rolls,
                'total_jumbo_rolls_needed': jumbo_rolls_needed,  # CORRECTED: Each jumbo roll produces 3×118" rolls
                'total_pending_orders': len(new_pending_orders),
                'total_pending_quantity': total_pending,
                'specification_groups_processed': len(spec_groups),
                'high_trim_patterns': len(all_high_trims),
                'algorithm_note': 'Updated: 1-20" trim accepted, >20" goes to pending, no waste rolls created'
            },
            'high_trim_approved': all_high_trims
        }
        
        logger.info(f"🎯 OPTIMIZER COMPLETED: Returning result with {len(result)} main sections")
        return result

    def generate_optimized_plan(
        self,
        order_requirements: List[Dict],
        interactive: bool = False
    ) -> Dict:
        """
        Generate an optimized cutting plan using the new algorithm.
        This is now an alias for optimize_with_new_algorithm for backward compatibility.
        
        Args:
            order_requirements: List of order dicts with width, quantity, etc.
            interactive: Whether to prompt user for high trim decisions
            
        Returns:
            Optimized cutting plan with jumbo rolls used and pending orders
        """
        return self.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=[],
            available_inventory=[],
            interactive=interactive
        )

    def _get_source_info_for_width(self, width: float, source_tracking: Dict, assignment_tracker: Dict) -> Dict:
        """
        Get source information for a specific width from the source tracking data.
        PROPERLY DISTRIBUTES cut rolls across pending orders based on their quantities.
        
        Args:
            width: Width of the cut roll being assigned
            source_tracking: Source tracking data for this specification group
            assignment_tracker: Tracks how many cut rolls have been assigned to each source
        """
        if width in source_tracking and source_tracking[width]:
            sources = source_tracking[width]
            
            # Initialize tracking key for this width if not exists
            width_key = f"width_{width}"
            if width_key not in assignment_tracker:
                assignment_tracker[width_key] = {}
            
            # PRIORITIZE pending orders - distribute them properly based on quantity
            pending_sources = [s for s in sources if s.get('source_type') == 'pending_order']
            if pending_sources:
                # Find a pending order that hasn't exceeded its quantity limit
                for source in pending_sources:
                    source_id = source.get('source_pending_id')
                    if source_id:
                        # Track assignments for this specific pending order
                        current_assignments = assignment_tracker[width_key].get(source_id, 0)
                        max_quantity = source.get('quantity', 1)
                        
                        # If this pending order can still accept more cut rolls, use it
                        if current_assignments < max_quantity:
                            assignment_tracker[width_key][source_id] = current_assignments + 1
                            logger.debug(f"🎯 SOURCE ASSIGNMENT: Assigned cut roll {current_assignments + 1}/{max_quantity} to pending order {str(source_id)[:8]}...")
                            return source
                        else:
                            logger.debug(f"🚫 SOURCE SKIP: Pending order {str(source_id)[:8]}... already at capacity ({current_assignments}/{max_quantity})")
            
            # If no pending orders available or all at capacity, use regular order sources
            regular_sources = [s for s in sources if s.get('source_type') == 'regular_order']
            if regular_sources:
                return regular_sources[0]
            
            # Fallback to first source if no other option
            return sources[0]
        
        # Default fallback for width with no source tracking
        return {
            'source_type': 'regular_order',
            'source_order_id': None,
            'source_pending_id': None
        }

    def create_plan_from_orders(
        self,
        db: Session,
        order_ids: List[uuid.UUID],
        created_by_id: uuid.UUID,
        plan_name: Optional[str] = None,
        interactive: bool = False
    ) -> models.PlanMaster:
        """
        Create a cutting plan from order IDs using the master-based architecture.
        
        Args:
            db: Database session
            order_ids: List of order IDs to include in the plan
            created_by_id: ID of user creating the plan
            plan_name: Optional name for the plan
            interactive: Whether to prompt user for high trim decisions
            
        Returns:
            Created PlanMaster instance
        """
        # Fetch orders from database
        orders = []
        for order_id in order_ids:
            order = crud_operations.get_order(db, order_id)
            if not order:
                raise ValueError(f"Order with ID {order_id} not found")
            orders.append(order)
        
        # Convert orders to optimizer format
        order_requirements = []
        for order in orders:
            # Get paper specifications
            paper = crud_operations.get_paper(db, order.paper_id)
            if not paper:
                raise ValueError(f"Paper not found for order {order.id}")
            
            order_requirements.append({
                'width': float(order.width_inches),
                'quantity': order.quantity_rolls,
                'gsm': paper.gsm,
                'bf': paper.bf,
                'shade': paper.shade,
                'order_id': str(order.id)
            })
        
        # Generate optimization result
        optimization_result = self.optimize_with_new_algorithm(order_requirements, interactive)
        
        # Create plan in database
        plan_data = schemas.PlanMasterCreate(
            name=plan_name or f"Auto Plan {datetime.now().strftime('%Y%m%d_%H%M%S')}",
            cut_pattern=optimization_result['jumbo_rolls_used'],
            expected_waste_percentage=optimization_result['summary']['overall_waste_percentage'],
            created_by_id=created_by_id,
            order_ids=order_ids,
            inventory_ids=[]  # Will be populated when inventory is allocated
        )
        
        return crud_operations.create_plan(db, plan_data=plan_data)


# Example usage and testing
def test_optimizer():
    optimizer = CuttingOptimizer()
    
    # Test with mixed specifications to demonstrate proper grouping
    sample_orders = [
        # White paper, GSM 90, BF 18.0 - GROUP 1
        {"width": 29.5, "quantity": 2, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1500},
        {"width": 32.5, "quantity": 3, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1600},
        {"width": 38, "quantity": 2, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1600},
        
        # Blue paper, GSM 90, BF 18.0 - GROUP 2 (different shade)
        {"width": 32.5, "quantity": 2, "gsm": 90, "bf": 18.0, "shade": "blue", "min_length": 1600},
        {"width": 46, "quantity": 1, "gsm": 90, "bf": 18.0, "shade": "blue", "min_length": 1600},
        
        # White paper, GSM 120, BF 18.0 - GROUP 3 (different GSM)
        {"width": 38, "quantity": 2, "gsm": 120, "bf": 18.0, "shade": "white", "min_length": 1600},
        {"width": 48, "quantity": 3, "gsm": 120, "bf": 18.0, "shade": "white", "min_length": 1600},
        
        # White paper, GSM 90, BF 20.0 - GROUP 4 (different BF)
        {"width": 51, "quantity": 2, "gsm": 90, "bf": 20.0, "shade": "white", "min_length": 1600},
        {"width": 54, "quantity": 2, "gsm": 90, "bf": 20.0, "shade": "white", "min_length": 1600}
    ]
    
    print("=== CUTTING OPTIMIZER RESULTS ===")
    result = optimizer.generate_optimized_plan(
        order_requirements=sample_orders,
        interactive=False  # Set to True for interactive mode
    )
    
    print("\n✅ Cut Rolls Generated:")
    for i, roll in enumerate(result.get('cut_rolls_generated', []), 1):
        print(f"Roll #{i}: {roll['width']}\" - GSM {roll['gsm']}, Shade: {roll['shade']}")
    
    if result.get('pending_orders'):
        print("\n⏳ Pending Orders:")
        for pending in result['pending_orders']:
            print(f"• {pending['quantity']} roll(s) of size {pending['width']}\" - {pending.get('reason', 'high trim')}")
    else:
        print("\n🎯 All orders fulfilled!")
    
    if result.get('high_trim_approved'):
        print("\n📋 High Trim Patterns (6–20\"): ")
        for high_trim in result['high_trim_approved']:
            print(f"• {high_trim['combo']} → Trim: {high_trim['trim']}\"")
    
    print(f"\n📊 Summary:")
    print(f"Total Cut Rolls: {result.get('summary', {}).get('total_cut_rolls', 0)}")
    print(f"Total Jumbo Rolls Needed: {result.get('jumbo_rolls_needed', 0)}")
    print(f"Total Pending Orders: {result.get('summary', {}).get('total_pending_orders', 0)}")
    print(f"Algorithm: {result.get('summary', {}).get('algorithm_note', 'Updated algorithm')}")
    
    return result

if __name__ == "__main__":
    test_optimizer()