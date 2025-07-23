from typing import List, Tuple, Dict, Optional, Set, Union, Any
import json
from dataclasses import dataclass
from enum import Enum

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

class CuttingOptimizer:
    def __init__(self, jumbo_roll_width: int = 119):
        """
        Initialize the cutting optimizer with configuration.
        
        Args:
            jumbo_roll_width: Width of jumbo rolls in inches (default: 119)
        """
        self.jumbo_roll_width = jumbo_roll_width
        self.standard_widths = [36, 42, 48, 55, 60]  # Common standard sizes in inches
    
    def calculate_waste(self, pattern: List[Union[Dict[str, Any], int]]) -> float:
        """
        Calculate the waste percentage for a given cutting pattern.
        
        Args:
            pattern: List of roll specifications (either dict with 'width' or int)
    
        Returns:
            Waste percentage (0-100)
        """
        if not pattern:
            return 100.0  # 100% waste if no rolls in pattern
    
        total_used = 0
        for item in pattern:
            if isinstance(item, dict):
                total_used += item.get('width', 0)
            else:
                # Assume it's a number if not a dict
                total_used += item
    
        if total_used == 0:
            return 100.0
    
        waste = self.jumbo_roll_width - total_used
        waste_percentage = (waste / self.jumbo_roll_width) * 100
        return round(waste_percentage, 2)

    def generate_optimized_plan(
        self,
        order_requirements: List[Dict],
        available_inventory: List[Dict],
        consider_standard_sizes: bool = True
    ) -> Dict:
        """
        Generate an optimized cutting plan considering inventory and standard sizes.
        
        Args:
            order_requirements: List of dicts with 'width', 'quantity', 'gsm', 'bf', 'shade'
            available_inventory: List of available cut rolls with specifications
            consider_standard_sizes: Whether to consider standard sizes for optimization
            
        Returns:
            Dictionary containing optimized cutting plan
        """
        self._validate_order_requirements(order_requirements)
        
        # First, try to fulfill from existing inventory
        plan = self._fulfill_from_inventory(order_requirements, available_inventory)
        remaining_requirements = self._get_remaining_requirements(order_requirements, plan['fulfilled_orders'])
        
        if remaining_requirements:
            # Generate new cutting patterns for remaining requirements
            cutting_plan = self._generate_cutting_plan_with_standard_sizes(
                remaining_requirements,
                consider_standard_sizes
            )
            plan.update({
                'cutting_patterns': cutting_plan['patterns'],
                'waste_percentage': cutting_plan['waste_percentage'],
                'rolls_used': cutting_plan['rolls_used']
            })
        
        return plan
    
    def _validate_order_requirements(self, order_requirements: List[Dict]):
        """Validate order requirements before processing."""
        if not order_requirements:
            raise ValueError("No order requirements provided")
            
        for req in order_requirements:
            if not all(k in req for k in ['width', 'quantity', 'gsm', 'bf', 'shade']):
                raise ValueError("Missing required fields in order requirements")
            if req['width'] > self.jumbo_roll_width:
                raise ValueError(f"Order width {req['width']} exceeds jumbo roll width {self.jumbo_roll_width}")
    
    def _fulfill_from_inventory(
        self,
        order_requirements: List[Dict],
        available_inventory: List[Dict],
        strict_matching: bool = True
    ) -> Dict:
        """
        Fulfill orders from available inventory.
        
        Args:
            order_requirements: List of order requirements
            available_inventory: List of available cut rolls
            strict_matching: If True, requires exact GSM, BF, and Shade matches
            
        Returns:
            Dictionary with fulfilled orders and remaining inventory
        """
        fulfilled = []
        remaining_inventory = available_inventory.copy()
        
        for req in order_requirements:
            req_width = req['width']
            req_quantity = req['quantity']
            
            for inv in remaining_inventory[:]:
                if inv['status'] != CutRollStatus.AVAILABLE.value:
                    continue
                    
                # Check specifications match
                if strict_matching:
                    if not all(inv.get(k) == req[k] for k in ['gsm', 'bf', 'shade']):
                        continue
                
                # Check if inventory item can be used
                if inv['width'] == req_width and inv['length'] >= req.get('min_length', 0):
                    fulfilled.append({
                        'order_id': req.get('order_id'),
                        'width': req_width,
                        'quantity': 1,
                        'inventory_id': inv['id'],
                        'spec_match': True
                    })
                    req_quantity -= 1
                    remaining_inventory.remove(inv)
                    
                    if req_quantity <= 0:
                        break
            
            # If we still need more, check for larger rolls that can be cut down
            if req_quantity > 0:
                for inv in sorted(remaining_inventory, key=lambda x: x['width']):
                    if inv['width'] > req_width and inv['status'] == CutRollStatus.AVAILABLE.value:
                        if not strict_matching or all(inv.get(k) == req[k] for k in ['gsm', 'bf', 'shade']):
                            # Calculate how many we can get from this roll
                            possible = min(req_quantity, inv['width'] // req_width)
                            if possible > 0:
                                fulfilled.append({
                                    'order_id': req.get('order_id'),
                                    'width': req_width,
                                    'quantity': possible,
                                    'inventory_id': inv['id'],
                                    'spec_match': True,
                                    'needs_cutting': True
                                })
                                req_quantity -= possible
                                
                                if req_quantity <= 0:
                                    break
        
        return {
            'fulfilled_orders': fulfilled,
            'remaining_inventory': remaining_inventory,
            'inventory_fulfillment_ratio': len(fulfilled) / len(order_requirements) if order_requirements else 0
        }
    
    def _generate_cutting_plan_with_standard_sizes(
        self,
        requirements: List[Dict],
        consider_standard_sizes: bool = True
    ) -> Dict:
        """
        Generate cutting plan considering standard sizes to minimize waste.
        """
        # Flatten requirements
        all_widths = []
        for req in requirements:
            all_widths.extend([req['width']] * req['quantity'])
        
        if not all_widths:
            return {"patterns": [], "waste_percentage": 0, "rolls_used": 0}
        
        # Sort in descending order for FFD
        all_widths.sort(reverse=True)
        patterns = []
        
        while all_widths:
            current_roll = []
            remaining_width = self.jumbo_roll_width
            i = 0
            
            while i < len(all_widths):
                if all_widths[i] <= remaining_width:
                    current_roll.append(all_widths[i])
                    remaining_width -= all_widths[i]
                    all_widths.pop(i)
                else:
                    i += 1
            
            # If we have remaining space, try to fill with standard sizes
            if consider_standard_sizes and remaining_width > 0:
                self._fill_with_standard_sizes(current_roll, remaining_width)
            
            patterns.append(current_roll)
        
        # Calculate waste
        total_used = sum(sum(pattern) for pattern in patterns)
        total_rolls = len(patterns)
        total_possible = total_rolls * self.jumbo_roll_width
        waste_percentage = ((total_possible - total_used) / total_possible) * 100 if total_possible > 0 else 0
        
        return {
            "patterns": patterns,
            "waste_percentage": round(waste_percentage, 2),
            "rolls_used": total_rolls
        }
    
    def _fill_with_standard_sizes(self, pattern: List[int], remaining_width: int):
        """Try to fill remaining width with standard sizes."""
        for std_width in sorted([w for w in self.standard_widths if w <= remaining_width], reverse=True):
            if std_width <= remaining_width:
                pattern.append(std_width)
                remaining_width -= std_width
                
                # If we can't fit any more standard sizes, break
                if remaining_width < min(self.standard_widths, default=0):
                    break
    
    def validate_cutting_plan(
        self,
        plan: Dict,
        requirements: List[Dict],
        available_inventory: List[Dict] = None
    ) -> Dict:
        """
        Comprehensive validation of a cutting plan.
        
        Args:
            plan: The cutting plan to validate
            requirements: Original order requirements
            available_inventory: Optional inventory to check against
            
        Returns:
            Dict with validation results
        """
        errors = []
        warnings = []
        
        # Check required fields
        required_fields = ['patterns', 'waste_percentage', 'rolls_used']
        for field in required_fields:
            if field not in plan:
                errors.append(f"Missing required field: {field}")
        
        # Validate patterns
        if 'patterns' in plan:
            for i, pattern in enumerate(plan['patterns']):
                if not isinstance(pattern, list):
                    errors.append(f"Pattern {i} is not a list")
                    continue
                    
                pattern_width = sum(pattern)
                if pattern_width > self.jumbo_roll_width:
                    errors.append(f"Pattern {i} exceeds jumbo roll width: {pattern_width} > {self.jumbo_roll_width}")
        
        # Check if all requirements are met
        if requirements:
            req_map = {(r['width'], r['gsm'], r['bf'], r['shade']): r['quantity'] for r in requirements}
            fulfilled = plan.get('fulfilled_orders', [])
            
            for item in fulfilled:
                key = (item['width'], item['gsm'], item['bf'], item['shade'])
                if key in req_map:
                    req_map[key] -= item['quantity']
            
            for (width, gsm, bf, shade), remaining in req_map.items():
                if remaining > 0:
                    warnings.append(f"{remaining} rolls of {width}x{gsm}/{bf}/{shade} not fulfilled")
        
        # Validate against inventory if provided
        if available_inventory is not None and 'fulfilled_orders' in plan:
            inv_map = {inv['id']: inv for inv in available_inventory}
            for item in plan['fulfilled_orders']:
                if 'inventory_id' in item and item['inventory_id'] not in inv_map:
                    errors.append(f"Referenced inventory ID {item['inventory_id']} not found")
        
        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
    
    def get_standard_sizes(self) -> List[int]:
        """Get the list of standard roll widths."""
        return sorted(self.standard_widths)
    
    def set_standard_sizes(self, sizes: List[int]):
        """Update the list of standard roll widths."""
        if not all(isinstance(s, (int, float)) and s > 0 for s in sizes):
            raise ValueError("All standard sizes must be positive numbers")
        self.standard_widths = sorted(set(int(s) for s in sizes))
    
    def _get_remaining_requirements(
        self,
        original_requirements: List[Dict],
        fulfilled_orders: List[Dict]
    ) -> List[Dict]:
        """Calculate remaining requirements after fulfillment."""
        if not fulfilled_orders:
            return original_requirements.copy()
            
        # Create a map of requirements
        req_map = {}
        for req in original_requirements:
            key = (req['width'], req['gsm'], req['bf'], req['shade'])
            req_map[key] = req.get('quantity', 0)
        
        # Subtract fulfilled quantities
        for item in fulfilled_orders:
            key = (item['width'], item['gsm'], item['bf'], item['shade'])
            if key in req_map:
                req_map[key] -= item.get('quantity', 0)
        
        # Convert back to requirement format
        remaining = []
        for (width, gsm, bf, shade), quantity in req_map.items():
            if quantity > 0:
                remaining.append({
                    'width': width,
                    'gsm': gsm,
                    'bf': bf,
                    'shade': shade,
                    'quantity': quantity
                })
        
        return remaining
