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

from .. import models, schemas, crud_operations

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
JUMBO_WIDTH = 118
MIN_TRIM = 1
MAX_TRIM = 6
MAX_TRIM_WITH_CONFIRMATION = 20
MAX_ROLLS_PER_JUMBO = 5

class CuttingOptimizer:
    def __init__(self, jumbo_roll_width: int = JUMBO_WIDTH):
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
        valid_combos = []
        for r in range(1, MAX_ROLLS_PER_JUMBO + 1):
            for combo in product(sizes, repeat=r):
                total = sum(combo)
                trim = round(JUMBO_WIDTH - total, 2)
                if 0 <= trim <= MAX_TRIM_WITH_CONFIRMATION:
                    valid_combos.append((tuple(sorted(combo)), trim))
        
        # Prefer: more rolls, then lower trim
        return sorted(valid_combos, key=lambda x: (-len(x[0]), x[1]))

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
        
        for combo, trim in combos:
            combo_count = Counter(combo)
            while all(order_counter[k] >= v for k, v in combo_count.items()):
                if trim <= MAX_TRIM:
                    # Accept directly
                    for k in combo:
                        order_counter[k] -= 1
                    used.append((combo, trim))
                elif trim <= MAX_TRIM_WITH_CONFIRMATION:
                    # Ask user or auto-accept based on interactive flag
                    if interactive:
                        print(f"\n⚠️ Combo {combo} leaves {trim}\" trim. Use it? (yes/no):")
                        choice = input().strip().lower()
                        if choice == "yes":
                            for k in combo:
                                order_counter[k] -= 1
                            used.append((combo, trim))
                            high_trim_log.append((combo, trim))
                        else:
                            break
                    else:
                        # Auto-accept for non-interactive mode
                        for k in combo:
                            order_counter[k] -= 1
                        used.append((combo, trim))
                        high_trim_log.append((combo, trim))
                else:
                    break
        
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
            available_inventory: List of 20-25" waste rolls available for reuse
            interactive: Whether to prompt user for high trim decisions
            
        Returns:
            Dict with 4 outputs:
            - cut_rolls_generated: Rolls that can be fulfilled
            - jumbo_rolls_needed: Number of jumbo rolls to procure
            - pending_orders: Orders that cannot be fulfilled
            - inventory_remaining: 20-25" waste rolls for future use
        """
        print(f"\n🔧 DEBUG: Starting optimize_with_new_algorithm")
        print(f"📦 Input - Order Requirements: {len(order_requirements)} items")
        print(f"⏳ Input - Pending Orders: {len(pending_orders) if pending_orders else 0} items")
        print(f"📋 Input - Available Inventory: {len(available_inventory) if available_inventory else 0} items")
        
        # Initialize default values for optional inputs
        if pending_orders is None:
            pending_orders = []
            print("⚠️  DEBUG: pending_orders was None, initialized to empty list")
        if available_inventory is None:
            available_inventory = []
            print("⚠️  DEBUG: available_inventory was None, initialized to empty list")
        
        print(f"\n📋 DEBUG: Detailed Input Analysis:")
        print(f"Order Requirements: {order_requirements}")
        print(f"Pending Orders: {pending_orders}")
        print(f"Available Inventory: {available_inventory}")
        
        # Combine all requirements (new orders + pending orders)
        all_requirements = order_requirements + pending_orders
        print(f"\n🔄 DEBUG: Combined all_requirements: {len(all_requirements)} total items")
        print(f"Combined Requirements: {all_requirements}")
        
        # Group all requirements by complete specification (GSM + Shade + BF)
        # This ensures that different paper types are NEVER mixed in the same jumbo roll
        # Each jumbo roll will contain only 3 sets of 118" rolls with identical paper specs
        spec_groups = {}
        print(f"\n🔍 DEBUG: Grouping requirements by specification...")
        
        for i, req in enumerate(all_requirements):
            print(f"  Processing requirement {i+1}: {req}")
            # Create unique key for paper specification - CRITICAL for avoiding paper mixing
            spec_key = (req['gsm'], req['shade'], req['bf'])
            print(f"  Spec key: {spec_key}")
            
            if spec_key not in spec_groups:
                spec_groups[spec_key] = {
                    'orders': {},
                    'inventory': [],
                    'spec': {'gsm': req['gsm'], 'shade': req['shade'], 'bf': req['bf']}
                }
                print(f"  Created new spec group for {spec_key}")
            
            # Add width and quantity to this specification group
            width = float(req['width'])
            if width in spec_groups[spec_key]['orders']:
                old_qty = spec_groups[spec_key]['orders'][width]
                spec_groups[spec_key]['orders'][width] += req['quantity']
                print(f"  Added {req['quantity']} to existing width {width}\" (was {old_qty}, now {spec_groups[spec_key]['orders'][width]})")
            else:
                spec_groups[spec_key]['orders'][width] = req['quantity']
                print(f"  Added new width {width}\" with quantity {req['quantity']}")
        
        print(f"\n📊 DEBUG: Final spec_groups structure:")
        for spec_key, group_data in spec_groups.items():
            print(f"  Spec {spec_key}: {group_data['orders']}")
        
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
        inventory_remaining = []
        jumbo_rolls_needed = 0
        all_high_trims = []
        
        for spec_key, group_data in spec_groups.items():
            orders = group_data['orders']
            inventory = group_data['inventory']
            spec = group_data['spec']
            
            print(f"\n🔧 DEBUG: Processing Paper Spec: GSM={spec['gsm']}, Shade={spec['shade']}, BF={spec['bf']}")
            print(f"   📦 Orders to fulfill: {orders}")
            print(f"   📋 Available Inventory: {len(inventory)} items")
            for inv_idx, inv_item in enumerate(inventory):
                print(f"     Inventory {inv_idx+1}: width={inv_item.get('width', 'N/A')}\", id={inv_item.get('id', 'N/A')}")
            
            total_order_quantity = sum(orders.values())
            print(f"   📊 Total order quantity for this spec: {total_order_quantity} rolls")
            
            # First, try to fulfill orders using available inventory
            orders_copy = orders.copy()
            inventory_used = []
            
            print(f"   🔄 DEBUG: Starting inventory fulfillment phase...")
            print(f"   📦 Orders copy before inventory: {orders_copy}")
            
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
                print(f"   🔪 DEBUG: Running cutting algorithm for remaining orders: {orders_copy}")
                used, pending, high_trims = self.match_combos(orders_copy, interactive)
                print(f"   📊 Cutting results: {len(used)} patterns used, {len(list(pending.keys()))} pending widths")
                
                # Process successful cutting patterns (each pattern = 1 individual 118" roll)
                for pattern_idx, (combo, trim) in enumerate(used):
                    individual_118_rolls_needed += 1
                    print(f"     Pattern {pattern_idx+1}: {combo} → trim={trim}\" (Roll #{individual_118_rolls_needed})")
                    
                    # Add cut rolls from this pattern
                    for width in combo:
                        cut_roll = {
                            'width': width,
                            'quantity': 1,
                            'gsm': spec['gsm'],
                            'bf': spec['bf'],
                            'shade': spec['shade'],
                            'source': 'cutting',
                            'individual_roll_number': individual_118_rolls_needed,
                            'trim_left': trim
                        }
                        cut_rolls_generated.append(cut_roll)
                        print(f"       Added cut roll: {width}\" from roll #{individual_118_rolls_needed}")
            else:
                print(f"   ✅ DEBUG: All orders fulfilled from inventory, no cutting needed")
                    
                    # Handle waste: 20-25" becomes inventory, >25" discarded
                if 20 <= trim <= 25:
                        inventory_remaining.append({
                            'width': trim,
                            'quantity': 1,
                            'gsm': spec['gsm'],
                            'bf': spec['bf'],
                            'shade': spec['shade'],
                            'source': 'waste',
                            'from_individual_roll': individual_118_rolls_needed
                        })
            
            # CORRECTED JUMBO ROLL CALCULATION: 1 Jumbo Roll = 3 individual 118" rolls
            # This is the critical fix from the implementation plan
            complete_jumbo_rolls = individual_118_rolls_needed // 3
            remaining_individual_rolls = individual_118_rolls_needed % 3
            
            # Only count complete jumbo rolls for procurement
            jumbo_rolls_needed += complete_jumbo_rolls
            
            # If there are remaining individual rolls, we need one more jumbo roll
            if remaining_individual_rolls > 0:
                jumbo_rolls_needed += 1
                
                # Calculate how many sets will be unused from this extra jumbo roll
                unused_sets_from_extra_jumbo = 3 - remaining_individual_rolls
                
                print(f"   📊 CORRECTED Jumbo calculation for spec {spec_key}:")
                print(f"     Individual 118\" rolls needed: {individual_118_rolls_needed}")
                print(f"     Complete jumbo rolls: {complete_jumbo_rolls}")
                print(f"     Remaining individual rolls: {remaining_individual_rolls}")
                print(f"     Extra jumbo roll needed: {'Yes' if remaining_individual_rolls > 0 else 'No'}")
                print(f"     Unused sets from extra jumbo: {unused_sets_from_extra_jumbo if remaining_individual_rolls > 0 else 0}")
                print(f"     Total jumbo rolls for this spec: {complete_jumbo_rolls + (1 if remaining_individual_rolls > 0 else 0)}")
                
                # The unused sets from the extra jumbo roll become available for future orders
                # This is more accurate than sending them to pending orders
                if unused_sets_from_extra_jumbo > 0:
                    print(f"   ✅ {unused_sets_from_extra_jumbo} sets from extra jumbo roll will be available for future orders")
                    # These don't go to pending orders - they're just extra capacity we'll have
            else:
                print(f"   📊 CORRECTED Jumbo calculation for spec {spec_key}:")
                print(f"     Individual 118\" rolls needed: {individual_118_rolls_needed}")
                print(f"     Complete jumbo rolls needed: {complete_jumbo_rolls}")
                print(f"     Perfect fit - no extra jumbo roll needed")
            
            # Add orders that couldn't be fulfilled to pending
            if orders_copy:
                for width, qty in pending.items():
                    new_pending_orders.append({
                        'width': width,
                        'quantity': qty,
                        'gsm': spec['gsm'],
                        'bf': spec['bf'],
                        'shade': spec['shade'],
                        'reason': 'waste_too_high'
                    })
                
                # Track high trim approvals
                for combo, trim in high_trims:
                    all_high_trims.append({
                        'combo': combo,
                        'trim': trim,
                        'waste_percentage': round((trim / JUMBO_WIDTH) * 100, 2),
                        'paper_spec': spec
                    })
            
            # Add remaining unused inventory back to inventory_remaining
            for inv_item in remaining_inventory:
                inventory_remaining.append({
                    'width': float(inv_item['width']),
                    'quantity': 1,
                    'gsm': spec['gsm'],
                    'bf': spec['bf'],
                    'shade': spec['shade'],
                    'source': 'unused_inventory',
                    'inventory_id': inv_item.get('id')
                })
        
        # Calculate summary statistics
        total_cut_rolls = len(cut_rolls_generated)
        total_inventory_created = len([inv for inv in inventory_remaining if inv['source'] == 'waste'])
        total_pending = sum(order['quantity'] for order in new_pending_orders)
        total_individual_118_rolls = len([roll for roll in cut_rolls_generated if roll['source'] == 'cutting'])
        
        # NEW FLOW: Return 4 distinct outputs
        return {
            'cut_rolls_generated': cut_rolls_generated,
            'jumbo_rolls_needed': jumbo_rolls_needed,  # CORRECTED: 1 jumbo roll = 3 sets of 118" rolls
            'pending_orders': new_pending_orders,
            'inventory_remaining': inventory_remaining,
            'summary': {
                'total_cut_rolls': total_cut_rolls,
                'total_individual_118_rolls': total_individual_118_rolls,
                'total_jumbo_rolls_needed': jumbo_rolls_needed,  # CORRECTED: Each jumbo roll produces 3×118" rolls
                'total_pending_orders': len(new_pending_orders),
                'total_pending_quantity': total_pending,
                'total_inventory_created': total_inventory_created,
                'specification_groups_processed': len(spec_groups),
                'high_trim_patterns': len(all_high_trims),
                'algorithm_note': 'CORRECTED: 1 jumbo roll = 3 individual 118" rolls, same paper specs only'
            },
            'high_trim_approved': all_high_trims
        }

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

    def process_inventory_input(self, inventory_items: List[Dict]) -> List[Dict]:
        """
        Process available inventory input to standardize format.
        Filters for 20-25" waste rolls only.
        
        Args:
            inventory_items: Raw inventory data
            
        Returns:
            Processed inventory items suitable for optimization
        """
        processed_items = []
        for item in inventory_items:
            width = float(item.get('width', 0))
            # Only include 20-25" rolls as per new flow
            if 20 <= width <= 25:
                processed_items.append({
                    'id': item.get('id', str(uuid.uuid4())),
                    'width': width,
                    'gsm': item.get('gsm', 90),
                    'bf': float(item.get('bf', 18.0)),
                    'shade': item.get('shade', 'white'),
                    'weight': item.get('weight', 0),
                    'location': item.get('location', 'warehouse')
                })
        return processed_items

    def generate_inventory_from_waste(self, waste_width: float, paper_spec: Dict, jumbo_number: int) -> Dict:
        """
        Generate inventory item from waste that falls in 20-25" range.
        
        Args:
            waste_width: Width of the waste piece
            paper_spec: Paper specification (GSM, BF, Shade)
            jumbo_number: Source jumbo roll number
            
        Returns:
            Inventory item dictionary
        """
        return {
            'id': f"waste_{jumbo_number}_{waste_width}",
            'width': waste_width,
            'gsm': paper_spec['gsm'],
            'bf': paper_spec['bf'],
            'shade': paper_spec['shade'],
            'source': 'waste',
            'from_jumbo': jumbo_number,
            'roll_type': 'cut',
            'status': 'available'
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

    def get_order_requirements_from_db(
        self,
        db: Session,
        order_ids: List[uuid.UUID]
    ) -> List[Dict]:
        """
        Fetch order requirements from database for testing purposes.
        
        Args:
            db: Database session
            order_ids: List of order IDs
            
        Returns:
            List of order requirements in optimizer format
        """
        order_requirements = []
        
        for order_id in order_ids:
            order = crud_operations.get_order(db, order_id)
            if not order:
                continue
                
            # Get paper specifications
            paper = crud_operations.get_paper(db, order.paper_id)
            if not paper:
                continue
            
            order_requirements.append({
                'width': float(order.width_inches),
                'quantity': order.quantity_rolls,
                'gsm': paper.gsm,
                'bf': paper.bf,
                'shade': paper.shade,
                'min_length': 1600,  # Default min length since OrderMaster doesn't have this field
                'order_id': str(order.id),
                'client_name': order.client.company_name if order.client else 'Unknown'
            })
        
        return order_requirements

    def test_algorithm_with_sample_data(self) -> Dict:
        """
        NEW FLOW: Test the algorithm with sample data demonstrating 3-input/4-output.
        This method is useful for testing the optimization logic with the new flow.
        
        Returns:
            Optimization result with sample data showing new flow
        """
        # Sample new orders
        new_orders = [
            {"width": 29.5, "quantity": 2, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1500},
            {"width": 32.5, "quantity": 3, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1600},
            {"width": 38, "quantity": 1, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1600},
        ]
        
        # Sample pending orders from previous cycles
        pending_orders = [
            {"width": 46, "quantity": 1, "gsm": 90, "bf": 18.0, "shade": "white", "min_length": 1600},
            {"width": 48, "quantity": 2, "gsm": 120, "bf": 18.0, "shade": "white", "min_length": 1600},
        ]
        
        # Sample available inventory (20-25" waste rolls)
        available_inventory = [
            {"id": "inv_1", "width": 22.5, "gsm": 90, "bf": 18.0, "shade": "white"},
            {"id": "inv_2", "width": 24, "gsm": 90, "bf": 18.0, "shade": "white"},
            {"id": "inv_3", "width": 23, "gsm": 120, "bf": 18.0, "shade": "white"},
        ]
        
        print("\n🧪 Testing NEW FLOW Algorithm with 3 inputs:")
        print(f"📦 New Orders: {len(new_orders)} items")
        print(f"⏳ Pending Orders: {len(pending_orders)} items")
        print(f"📋 Available Inventory: {len(available_inventory)} items")
        
        return self.optimize_with_new_algorithm(
            order_requirements=new_orders,
            pending_orders=pending_orders,
            available_inventory=available_inventory,
            interactive=False
        )

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
    
    print("\n✅ Jumbo Rolls Used:")
    for jumbo in result['jumbo_rolls_used']:
        widths = [roll['width'] for roll in jumbo['rolls']]
        print(f"Jumbo #{jumbo['jumbo_number']}: {tuple(widths)} → Trim Left: {jumbo['trim_left']}\"")
    
    if result['pending_orders']:
        print("\n⏳ Pending Rolls:")
        for pending in result['pending_orders']:
            print(f"• {pending['quantity']} roll(s) of size {pending['width']}\"")
    else:
        print("\n🎯 All rolls fulfilled!")
    
    if result['high_trim_approved']:
        print("\n📋 Approved High Trim Combos (6–20\"): ")
        for high_trim in result['high_trim_approved']:
            print(f"• {high_trim['combo']} → Trim: {high_trim['trim']}\"")
    
    print(f"\n📊 Summary:")
    print(f"Total Jumbos Used: {result['summary']['total_jumbos_used']}")
    print(f"Total Trim: {result['summary']['total_trim_inches']}\"")
    print(f"Overall Waste: {result['summary']['overall_waste_percentage']}%")
    
    return result

if __name__ == "__main__":
    test_optimizer()