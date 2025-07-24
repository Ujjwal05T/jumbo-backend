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

from .. import models, schemas, crud

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
        interactive: bool = False
    ) -> Dict:
        """
        Use the new algorithm logic with existing input format.
        Groups orders by complete specification (GSM + Shade + BF) to ensure
        different paper types are not mixed in the same jumbo roll.
        
        Args:
            order_requirements: List of order dicts with width, quantity, etc.
            interactive: Whether to prompt user for high trim decisions
            
        Returns:
            Optimized cutting plan with jumbo rolls used and pending orders
        """
        # Group orders by complete specification (GSM + Shade + BF)
        spec_groups = {}
        for req in order_requirements:
            # Create unique key for paper specification
            spec_key = (req['gsm'], req['shade'], req['bf'])
            if spec_key not in spec_groups:
                spec_groups[spec_key] = {
                    'orders': {},
                    'spec': {'gsm': req['gsm'], 'shade': req['shade'], 'bf': req['bf']}
                }
            
            # Add width and quantity to this specification group
            width = float(req['width'])
            if width in spec_groups[spec_key]['orders']:
                spec_groups[spec_key]['orders'][width] += req['quantity']
            else:
                spec_groups[spec_key]['orders'][width] = req['quantity']
        
        # Process each specification group separately
        all_jumbo_rolls = []
        all_pending_orders = []
        all_high_trims = []
        jumbo_counter = 1
        
        for spec_key, group_data in spec_groups.items():
            orders = group_data['orders']
            spec = group_data['spec']
            
            print(f"\n🔧 Processing Paper Spec: GSM={spec['gsm']}, Shade={spec['shade']}, BF={spec['bf']}")
            print(f"   Orders: {orders}")
            
            # Run the matching algorithm for this specification group
            used, pending, high_trims = self.match_combos(orders, interactive)
            
            # Convert results back to detailed format for this group
            for combo, trim in used:
                roll_details = []
                for width in combo:
                    roll_details.append({
                        'width': width,
                        'gsm': spec['gsm'],
                        'bf': spec['bf'],
                        'shade': spec['shade'],
                        'min_length': next((req.get('min_length', 0) for req in order_requirements 
                                          if float(req['width']) == width and req['gsm'] == spec['gsm'] 
                                          and req['shade'] == spec['shade'] and req['bf'] == spec['bf']), 0)
                    })
                
                all_jumbo_rolls.append({
                    'jumbo_number': jumbo_counter,
                    'rolls': roll_details,
                    'trim_left': trim,
                    'waste_percentage': round((trim / JUMBO_WIDTH) * 100, 2),
                    'paper_spec': spec
                })
                jumbo_counter += 1
            
            # Add pending orders for this specification
            for width, qty in pending.items():
                all_pending_orders.append({
                    'width': width,
                    'quantity': qty,
                    'gsm': spec['gsm'],
                    'bf': spec['bf'],
                    'shade': spec['shade'],
                    'min_length': next((req.get('min_length', 0) for req in order_requirements 
                                      if float(req['width']) == width and req['gsm'] == spec['gsm'] 
                                      and req['shade'] == spec['shade'] and req['bf'] == spec['bf']), 0)
                })
            
            # Add high trim combos for this specification
            for combo, trim in high_trims:
                all_high_trims.append({
                    'combo': combo,
                    'trim': trim,
                    'waste_percentage': round((trim / JUMBO_WIDTH) * 100, 2),
                    'paper_spec': spec
                })
        
        # Calculate summary statistics
        total_trim = sum(jumbo['trim_left'] for jumbo in all_jumbo_rolls)
        total_jumbo_width = len(all_jumbo_rolls) * JUMBO_WIDTH
        overall_waste_percentage = (total_trim / total_jumbo_width * 100) if total_jumbo_width > 0 else 0
        
        all_fulfilled = len(all_pending_orders) == 0
        
        return {
            'jumbo_rolls_used': all_jumbo_rolls,
            'pending_orders': all_pending_orders,
            'high_trim_approved': all_high_trims,
            'summary': {
                'total_jumbos_used': len(all_jumbo_rolls),
                'total_trim_inches': round(total_trim, 2),
                'overall_waste_percentage': round(overall_waste_percentage, 2),
                'all_orders_fulfilled': all_fulfilled,
                'pending_rolls_count': sum(order['quantity'] for order in all_pending_orders),
                'specification_groups_processed': len(spec_groups)
            }
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
        return self.optimize_with_new_algorithm(order_requirements, interactive)

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
            order = crud.get_order(db, order_id)
            if not order:
                raise ValueError(f"Order with ID {order_id} not found")
            orders.append(order)
        
        # Convert orders to optimizer format
        order_requirements = []
        for order in orders:
            # Get paper specifications
            paper = crud.get_paper(db, order.paper_id)
            if not paper:
                raise ValueError(f"Paper not found for order {order.id}")
            
            order_requirements.append({
                'width': float(order.width),
                'quantity': order.quantity,
                'gsm': paper.gsm,
                'bf': paper.bf,
                'shade': paper.shade,
                'min_length': order.min_length or 0,
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
        
        return crud.create_plan(db, plan_data)

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
            order = crud.get_order(db, order_id)
            if not order:
                continue
                
            # Get paper specifications
            paper = crud.get_paper(db, order.paper_id)
            if not paper:
                continue
            
            order_requirements.append({
                'width': float(order.width),
                'quantity': order.quantity,
                'gsm': paper.gsm,
                'bf': paper.bf,
                'shade': paper.shade,
                'min_length': order.min_length or 0,
                'order_id': str(order.id),
                'client_name': order.client.name if order.client else 'Unknown'
            })
        
        return order_requirements

    def test_algorithm_with_sample_data(self) -> Dict:
        """
        Test the algorithm with sample data without affecting the database.
        This method is useful for testing the optimization logic.
        
        Returns:
            Optimization result with sample data
        """
        # Sample data for testing
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
        
        return self.optimize_with_new_algorithm(sample_orders, interactive=False)

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