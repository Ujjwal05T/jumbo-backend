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
        PHASE 1: Preview optimization on all pending orders without database changes.
        Uses direct combination generation instead of calling cutting optimizer.
        
        Returns:
            Dict containing:
            - remaining_pending: Orders that still can't be fulfilled
            - roll_combinations: Achievable combinations with their details
            - roll_suggestions: What rolls are needed to complete 118-inch rolls
            - summary: Statistics about the optimization
        """
        try:
            logger.info("🔍 PHASE 1: Starting pending order optimization preview")
            
            # Get pending orders with available quantity
            pending_items = self.db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem._status == "pending",
                models.PendingOrderItem.quantity_pending > 0
            ).all()
            
            logger.info(f"🔍 DEBUG: Found {len(pending_items)} pending items")
            for i, item in enumerate(pending_items):
                logger.info(f"  Item {i+1}: {item.frontend_id} - {float(item.width_inches)}\" x{item.quantity_pending} ({item.gsm}GSM {item.shade})")
            
            if not pending_items:
                logger.warning("❌ No pending orders found with status='pending' and quantity_pending > 0")
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
            
            logger.info(f"📊 Processing {len(pending_items)} pending order items")
            
            # Group by paper specifications
            spec_groups = self._group_by_specs(pending_items)
            logger.info(f"🔍 DEBUG: Created {len(spec_groups)} spec groups")
            
            # Generate combinations for each spec group
            roll_combinations = []
            remaining_pending = []
            
            for spec_key, items in spec_groups.items():
                logger.info(f"🔧 Processing spec group: {spec_key} with {len(items)} items")
                
                # Create width demand dictionary
                width_demand = {}
                for item in items:
                    width = float(item.width_inches)
                    width_demand[width] = width_demand.get(width, 0) + item.quantity_pending
                
                logger.info(f"  📋 Width demand: {width_demand}")
                logger.info(f"  📋 Unique widths: {list(width_demand.keys())}")
                
                # Generate combinations using cutting algorithm logic
                combos = self._generate_combos_for_spec(list(width_demand.keys()))
                logger.info(f"  🔧 Generated {len(combos)} possible combinations")
                
                # Match combinations to demand
                used_combos, remaining = self._match_combos_to_demand(width_demand, combos)
                logger.info(f"  ✅ Used {len(used_combos)} combinations, {len(remaining)} widths remaining")
                
                # Format for frontend
                spec_combinations = self._format_combinations(used_combos, spec_key, items[0])
                logger.info(f"  📊 Formatted {len(spec_combinations)} combinations for frontend")
                roll_combinations.extend(spec_combinations)
                
                # Track remaining unfulfilled orders
                if remaining:
                    remaining_spec = self._format_remaining(remaining, spec_key, items[0])
                    remaining_pending.extend(remaining_spec)
                    logger.info(f"  ❌ {len(remaining_spec)} orders could not be fulfilled")
            
            # Generate suggestions for remaining orders
            roll_suggestions = self._generate_roll_suggestions_v2(remaining_pending)
            
            logger.info(f"🔍 PENDING OPTIMIZER RESULTS:")
            logger.info(f"  Total input items: {len(pending_items)}")
            logger.info(f"  Combinations found: {len(roll_combinations)}")
            logger.info(f"  Remaining pending: {len(remaining_pending)}")
            logger.info(f"  Suggestions generated: {len(roll_suggestions)}")

            return {
                "status": "success",
                "remaining_pending": remaining_pending,
                "roll_combinations": roll_combinations,
                "roll_suggestions": roll_suggestions,
                "summary": {
                    "total_pending_input": len(pending_items),
                    "combinations_found": len(roll_combinations),
                    "remaining_pending": len(remaining_pending),
                    "suggested_rolls": len(roll_suggestions)
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
    
    def _group_by_specs(self, pending_items: List[models.PendingOrderItem]) -> Dict[Tuple, List[models.PendingOrderItem]]:
        """Group pending items by paper specifications."""
        spec_groups = {}
        for item in pending_items:
            spec_key = (item.gsm, item.shade, float(item.bf))
            if spec_key not in spec_groups:
                spec_groups[spec_key] = []
            spec_groups[spec_key].append(item)
        return spec_groups
    
    def _generate_combos_for_spec(self, widths: List[float]) -> List[Tuple[Tuple[float, ...], float]]:
        """Generate all valid combinations for given widths (reuse cutting optimizer logic)."""
        from itertools import product
        
        valid_combos = []
        MAX_ROLLS_PER_JUMBO = 5
        MAX_TRIM = 20
        JUMBO_WIDTH = 118
        
        logger.info(f"🔧 Generating combos for widths: {widths}")
        
        if not widths:
            logger.warning("❌ No widths provided for combination generation")
            return []
        
        # Generate combinations of 1 to 5 rolls
        for r in range(1, MAX_ROLLS_PER_JUMBO + 1):
            logger.debug(f"  🔧 Trying {r}-roll combinations...")
            combo_count = 0
            for combo in product(widths, repeat=r):
                total = sum(combo)
                trim = round(JUMBO_WIDTH - total, 2)
                if 0 <= trim <= MAX_TRIM:
                    valid_combos.append((tuple(sorted(combo)), trim))
                    combo_count += 1
                    logger.debug(f"    ✅ Valid combo: {tuple(sorted(combo))} → {total}\" used, {trim}\" trim")
                else:
                    logger.debug(f"    ❌ Invalid combo: {tuple(sorted(combo))} → {total}\" used, {trim}\" trim (outside 0-20\" range)")
            logger.info(f"  📊 Found {combo_count} valid {r}-roll combinations")
        
        # Sort by: fewer rolls first, then lower trim
        valid_combos.sort(key=lambda x: (len(x[0]), x[1]))
        logger.info(f"🔧 Generated {len(valid_combos)} total valid combinations")
        
        return valid_combos
    
    def _match_combos_to_demand(self, width_demand: Dict[float, int], combos: List[Tuple]) -> Tuple[List[Tuple], Dict[float, int]]:
        """Match combinations to demand, return used combos and remaining demand."""
        from collections import Counter, defaultdict
        
        demand_counter = Counter(width_demand)
        used_combos = []
        
        logger.info(f"🔧 Matching combos to demand: {dict(demand_counter)}")
        
        for combo, trim in combos:
            combo_counter = Counter(combo)
            applications = 0
            
            logger.debug(f"  🔍 Trying combo: {combo} (needs: {dict(combo_counter)})")
            logger.debug(f"    Current demand: {dict(demand_counter)}")
            
            # Check if we have enough demand for this combo
            can_apply = all(demand_counter[width] >= count for width, count in combo_counter.items())
            logger.debug(f"    Can apply combo? {can_apply}")
            
            # Apply this combo as many times as possible
            while all(demand_counter[width] >= count for width, count in combo_counter.items()):
                # Apply the combo
                for width in combo:
                    demand_counter[width] -= 1
                used_combos.append((combo, trim))
                applications += 1
                
                logger.debug(f"    ✅ Applied combo {combo} → remaining: {dict(demand_counter)}")
            
            if applications > 0:
                logger.info(f"  📊 Combo {combo} applied {applications} times, trim={trim}\"")
            else:
                logger.debug(f"    ❌ Could not apply combo {combo} - insufficient demand")
        
        # Convert remaining demand back to dict
        remaining_demand = {width: count for width, count in demand_counter.items() if count > 0}
        
        logger.info(f"🔧 Matching complete: {len(used_combos)} combos used, {len(remaining_demand)} widths remaining")
        
        return used_combos, remaining_demand
    
    def _format_combinations(self, used_combos: List[Tuple], spec_key: Tuple, sample_item: models.PendingOrderItem) -> List[Dict]:
        """Format combinations for frontend display."""
        combinations = []
        
        for i, (combo, trim) in enumerate(used_combos):
            combination_id = str(uuid.uuid4())
            
            # Count occurrences of each width in the combo
            width_counts = {}
            for width in combo:
                width_counts[width] = width_counts.get(width, 0) + 1
            
            # Create rolls list
            rolls = []
            for width, count in width_counts.items():
                rolls.append({
                    'width': width,
                    'quantity': count
                })
            
            combination = {
                'combination_id': combination_id,
                'paper_specs': {
                    'gsm': spec_key[0],
                    'shade': spec_key[1],
                    'bf': spec_key[2]
                },
                'rolls': rolls,
                'total_width': sum(combo),
                'trim': trim,
                'jumbo_width': 118
            }
            combinations.append(combination)
        
        return combinations
    
    def _format_remaining(self, remaining_demand: Dict[float, int], spec_key: Tuple, sample_item: models.PendingOrderItem) -> List[Dict]:
        """Format remaining unfulfilled orders."""
        remaining = []
        
        for width, quantity in remaining_demand.items():
            remaining.append({
                'width': width,
                'quantity': quantity,
                'gsm': spec_key[0],
                'shade': spec_key[1],
                'bf': spec_key[2],
                'reason': 'no_suitable_combination'
            })
        
        return remaining
    
    def _generate_roll_suggestions_v2(self, remaining_pending: List[Dict]) -> List[Dict]:
        """Generate practical suggestions using common roll sizes (29", 36", 42")."""
        suggestions = []
        
        # Common roll sizes to prioritize
        COMMON_SIZES = [29, 36, 42]
        
        # Group by paper specs
        spec_groups = {}
        for pending in remaining_pending:
            spec_key = (pending['gsm'], pending['shade'], pending['bf'])
            if spec_key not in spec_groups:
                spec_groups[spec_key] = []
            spec_groups[spec_key].append(pending)
        
        # Generate suggestions for each spec group
        for spec_key, pending_list in spec_groups.items():
            # Collect all widths and quantities for this spec
            pending_widths = {}
            for pending in pending_list:
                width = pending['width']
                pending_widths[width] = pending_widths.get(width, 0) + pending['quantity']
            
            # Generate practical combination suggestions
            practical_suggestions = self._generate_practical_combinations(pending_widths, spec_key)
            suggestions.extend(practical_suggestions)
        
        return suggestions
    
    def _generate_practical_combinations(self, pending_widths: Dict[float, int], spec_key: Tuple) -> List[Dict]:
        """Generate practical combinations using common roll sizes."""
        suggestions = []
        COMMON_SIZES = [29, 36, 42]
        
        # Try to combine existing widths with common sizes
        for existing_width, quantity in pending_widths.items():
            remaining_space = 118 - existing_width
            
            if remaining_space < 20:  # Too little space for meaningful combinations
                continue
            
            # Find practical combinations to fill the remaining space
            practical_combos = []
            
            # Strategy 1: Use single common size multiple times
            for common_size in COMMON_SIZES:
                if common_size <= remaining_space:
                    max_fits = int(remaining_space // common_size)
                    if max_fits > 0:
                        total_common = max_fits * common_size
                        trim = 118 - existing_width - total_common
                        
                        if 0 <= trim <= 20:  # Valid trim range
                            combo_desc = f"{existing_width}\" + {max_fits}×{common_size}\" = {existing_width + total_common}\" (trim: {trim}\")"
                            practical_combos.append({
                                'combination': [existing_width] + [common_size] * max_fits,
                                'description': combo_desc,
                                'trim': trim,
                                'priority': 1  # High priority for single common size
                            })
            
            # Strategy 2: Use 2 different common sizes
            for i, size1 in enumerate(COMMON_SIZES):
                for size2 in COMMON_SIZES[i:]:  # Avoid duplicates
                    if size1 + size2 <= remaining_space:
                        total_needed = size1 + size2
                        trim = 118 - existing_width - total_needed
                        
                        if 0 <= trim <= 20:
                            combo_desc = f"{existing_width}\" + {size1}\" + {size2}\" = {existing_width + total_needed}\" (trim: {trim}\")"
                            practical_combos.append({
                                'combination': [existing_width, size1, size2],
                                'description': combo_desc,
                                'trim': trim,
                                'priority': 2  # Medium priority for two sizes
                            })
            
            # Strategy 3: Use 3 different common sizes
            for size1 in COMMON_SIZES:
                for size2 in COMMON_SIZES:
                    for size3 in COMMON_SIZES:
                        if size1 + size2 + size3 <= remaining_space:
                            total_needed = size1 + size2 + size3
                            trim = 118 - existing_width - total_needed
                            
                            if 0 <= trim <= 20:
                                combo_desc = f"{existing_width}\" + {size1}\" + {size2}\" + {size3}\" = {existing_width + total_needed}\" (trim: {trim}\")"
                                practical_combos.append({
                                    'combination': [existing_width, size1, size2, size3],
                                    'description': combo_desc,
                                    'trim': trim,
                                    'priority': 3  # Lower priority for three sizes
                                })
            
            # Sort by priority (lower number = higher priority) then by trim
            practical_combos.sort(key=lambda x: (x['priority'], x['trim']))
            
            # Take best 3 suggestions for this width
            for combo in practical_combos[:3]:
                suggestion = {
                    'suggestion_id': str(uuid.uuid4()),
                    'paper_specs': {
                        'gsm': spec_key[0],
                        'shade': spec_key[1],
                        'bf': spec_key[2]
                    },
                    'existing_width': existing_width,
                    'existing_quantity': quantity,
                    'suggested_combination': combo['combination'],
                    'description': combo['description'],
                    'trim': combo['trim'],
                    'type': 'practical_combination'
                }
                suggestions.append(suggestion)
        
        return suggestions
    
    def accept_combinations(self, combinations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        PHASE 2: Accept selected roll combinations and execute database operations.
        Following main algorithm pattern with proper quantity tracking.
        
        Machine constraint: Only multiples of 3 combinations allowed (1 jumbo = 3 x 118" rolls).
        
        Args:
            combinations: List of combination objects with combination_id and other details
            
        Returns:
            Dict with plan ID, updated pending orders, and summary
        """
        try:
            logger.info(f"🎯 PHASE 2: Accepting {len(combinations)} roll combinations")
            
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
            
            # Create plan (following main algorithm pattern)
            plan_name = f"Pending Orders Plan {datetime.now().strftime('%Y%m%d_%H%M%S')}"
            plan = self._create_plan(combinations, plan_name)
            
            # Generate cut rolls and update quantities (following main algorithm pattern)
            cut_rolls_created = []
            resolved_pending_orders = []
            
            logger.info(f"🔧 Processing {len(combinations)} combinations for quantity updates...")
            
            for combo_idx, combo in enumerate(combinations):
                paper_specs = combo['paper_specs']
                logger.info(f"   Combo {combo_idx + 1}: {paper_specs['shade']} {paper_specs['gsm']}GSM")
                
                for roll_data in combo.get('rolls', []):
                    width = roll_data['width']
                    roll_quantity = roll_data.get('quantity', 1)
                    
                    logger.info(f"     Processing roll: {width}\" x{roll_quantity}")
                    
                    # Process each roll individually for quantity tracking
                    for _ in range(roll_quantity):
                        # Find source pending order
                        source_pending = self._find_source_pending_order(width, paper_specs)
                        
                        if source_pending:
                            # Create cut roll with tracking
                            cut_roll = self._create_cut_roll_with_tracking(
                                width, paper_specs, source_pending, plan.id
                            )
                            cut_rolls_created.append(cut_roll)
                            
                            # Update quantities (following main algorithm pattern)
                            resolved_info = self._update_pending_quantities(source_pending, 1)
                            resolved_pending_orders.append(resolved_info)
                        else:
                            logger.warning(f"No matching pending order found for {width}\" {paper_specs}")
            
            # Final commit
            self.db.commit()
            
            logger.info(f"✅ PHASE 2 COMPLETE:")
            logger.info(f"   Plan created: {plan.name}")
            logger.info(f"   Cut rolls created: {len(cut_rolls_created)}")
            logger.info(f"   Pending orders updated: {len(resolved_pending_orders)}")
            
            return {
                "status": "success",
                "plan_id": str(plan.id),
                "plan_name": plan_name,
                "resolved_pending_orders": resolved_pending_orders,
                "cut_rolls_created": len(cut_rolls_created),
                "summary": {
                    "combinations_accepted": len(combinations),
                    "pending_orders_updated": len(resolved_pending_orders),
                    "cut_rolls_created": len(cut_rolls_created),
                    "plan_created": True
                }
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error in Phase 2 - accepting combinations: {e}")
            raise
    
    def _create_plan(self, combinations: List[Dict], plan_name: str) -> models.PlanMaster:
        """Create plan master record following main algorithm pattern."""
        
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
        
        # Handle user ID
        user_id_to_use = self.user_id
        if user_id_to_use is None:
            # Try to get a system user
            system_user = self.db.query(models.UserMaster).filter(
                models.UserMaster.name == "System"
            ).first()
            
            if system_user:
                user_id_to_use = system_user.id
                logger.info(f"Using system user for pending orders plan: {system_user.id}")
            else:
                # Create a temporary system user
                system_user = models.UserMaster(
                    id=uuid.uuid4(),
                    name="System",
                    username="system",
                    password_hash="system_hash",
                    role="system",
                    status="active"
                )
                self.db.add(system_user)
                self.db.flush()
                user_id_to_use = system_user.id
                logger.info(f"Created temporary system user: {system_user.id}")
        
        # Create plan
        plan = models.PlanMaster(
            name=plan_name,
            cut_pattern=json.dumps(cut_rolls_generated),
            expected_waste_percentage=0,
            status=schemas.PlanStatus.PLANNED.value,
            created_by_id=user_id_to_use
        )
        
        self.db.add(plan)
        self.db.flush()  # Get plan ID
        
        logger.info(f"✅ Created plan: {plan_name} with ID {plan.id}")
        return plan
    
    def _find_source_pending_order(self, width: float, paper_specs: Dict) -> Optional[models.PendingOrderItem]:
        """Find a pending order that matches the specifications and has available quantity."""
        from decimal import Decimal
        
        width_decimal = Decimal(str(width))
        bf_decimal = Decimal(str(paper_specs['bf']))
        
        pending_order = self.db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.width_inches == width_decimal,
            models.PendingOrderItem.gsm == paper_specs['gsm'],
            models.PendingOrderItem.bf == bf_decimal,
            models.PendingOrderItem.shade == paper_specs['shade'],
            models.PendingOrderItem._status == "pending",
            models.PendingOrderItem.quantity_pending > 0
        ).order_by(models.PendingOrderItem.created_at).first()
        
        return pending_order
    
    def _create_cut_roll_with_tracking(self, width: float, paper_specs: Dict, source_pending: models.PendingOrderItem, plan_id: uuid.UUID) -> models.InventoryMaster:
        """Create cut roll inventory item following main algorithm pattern."""
        from ..services.barcode_generator import BarcodeGenerator
        
        # Find paper master
        paper = self.db.query(models.PaperMaster).filter(
            models.PaperMaster.gsm == paper_specs['gsm'],
            models.PaperMaster.bf == paper_specs['bf'],
            models.PaperMaster.shade == paper_specs['shade']
        ).first()
        
        if not paper:
            raise ValueError(f"No paper master found for {paper_specs}")
        
        # Generate barcode and QR code
        barcode_id = BarcodeGenerator.generate_cut_roll_barcode(self.db)
        qr_code = f"QR{plan_id.hex[:8].upper()}{barcode_id[-3:]}"
        
        # Create inventory item
        inventory_item = models.InventoryMaster(
            id=uuid.uuid4(),
            paper_id=paper.id,
            width_inches=width,
            weight_kg=0.1,  # Placeholder weight
            roll_type="cut",
            location="production_floor",
            status="cutting",
            qr_code=qr_code,
            barcode_id=barcode_id,
            production_date=datetime.utcnow(),
            allocated_to_order_id=source_pending.original_order_id,
            created_by_id=self.user_id,
            created_at=datetime.utcnow()
        )
        
        self.db.add(inventory_item)
        self.db.flush()
        
        # Create plan inventory link
        plan_inventory_link = models.PlanInventoryLink(
            id=uuid.uuid4(),
            plan_id=plan_id,
            inventory_id=inventory_item.id,
            quantity_used=1.0
        )
        
        self.db.add(plan_inventory_link)
        
        logger.debug(f"Created cut roll: {width}\" for pending order {source_pending.frontend_id}")
        return inventory_item
    
    def _update_pending_quantities(self, pending_item: models.PendingOrderItem, rolls_used: int) -> Dict:
        """Update pending order quantities following main algorithm pattern."""
        
        # Store old values for logging
        old_fulfilled = pending_item.quantity_fulfilled
        old_pending = pending_item.quantity_pending
        
        # Update pending order quantities
        pending_item.quantity_fulfilled += rolls_used
        pending_item.quantity_pending = max(0, old_pending - rolls_used)
        
        # Mark as resolved if fully fulfilled
        if pending_item.quantity_pending == 0:
            pending_item._status = "resolved"
            pending_item.resolved_at = datetime.utcnow()
        
        # Update original order item (following main algorithm pattern)
        if pending_item.original_order_id:
            original_order_item = self.db.query(models.OrderItem).filter(
                models.OrderItem.order_id == pending_item.original_order_id,
                models.OrderItem.width_inches == pending_item.width_inches,
                models.OrderItem.paper_id == self.db.query(models.PaperMaster).filter(
                    models.PaperMaster.gsm == pending_item.gsm,
                    models.PaperMaster.bf == pending_item.bf,
                    models.PaperMaster.shade == pending_item.shade
                ).first().id
            ).first()
            
            if original_order_item:
                # Update original order quantities - only decrement pending, fulfilled will be updated on QR scan
                original_order_item.quantity_in_pending = max(0, 
                    original_order_item.quantity_in_pending - rolls_used
                )
                
                logger.info(f"✅ Updated original order item {original_order_item.frontend_id}")
                logger.info(f"  quantity_fulfilled: unchanged (will be updated on QR scan)")
                logger.info(f"  quantity_in_pending: {original_order_item.quantity_in_pending + rolls_used} → {original_order_item.quantity_in_pending}")
        
        # Prepare return info
        status = "fully_resolved" if pending_item.quantity_pending == 0 else "partially_resolved"
        
        logger.info(f"✅ Updated pending order {pending_item.frontend_id}")
        logger.info(f"  quantity_fulfilled: {old_fulfilled} → {pending_item.quantity_fulfilled}")
        logger.info(f"  quantity_pending: {old_pending} → {pending_item.quantity_pending}")
        logger.info(f"  status: {status}")
        
        return {
            'pending_id': str(pending_item.id),
            'frontend_id': pending_item.frontend_id,
            'width': float(pending_item.width_inches),
            'quantity_resolved': rolls_used,
            'quantity_remaining': pending_item.quantity_pending,
            'paper_specs': {
                'gsm': pending_item.gsm,
                'shade': pending_item.shade,
                'bf': float(pending_item.bf)
            },
            'status': status
        }