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
        Generate SIMPLIFIED paper spec-based roll suggestions for pending orders.
        Direct approach: Specs → Jumbo Rolls → Sets → Cuts (with order info).
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
                    "spec_suggestions": [],
                    "summary": {
                        "total_pending_input": 0,
                        "specs_processed": 0,
                        "total_cuts": 0
                    }
                }

            # Validate data integrity first
            self._validate_order_data_integrity(pending_items)

            # Simple grouping by paper specs only
            spec_groups = {}
            for item in pending_items:
                spec_key = (item.gsm, item.shade, float(item.bf))
                if spec_key not in spec_groups:
                    spec_groups[spec_key] = []
                spec_groups[spec_key].append(item)

            logger.info(f"📋 Processing {len(spec_groups)} paper specs with {len(pending_items)} total items")

            # Generate spec suggestions directly
            spec_suggestions = []
            total_cuts = 0

            for spec_key, items in spec_groups.items():
                logger.info(f"  → {spec_key[1]} {spec_key[0]}GSM BF{spec_key[2]}: {len(items)} items")

                # Create jumbo rolls directly from items
                jumbo_rolls = self._create_jumbo_rolls_directly(items, target_width)

                if jumbo_rolls:
                    # Validate cuts have proper order info
                    self._validate_cut_generation(jumbo_rolls)

                    # Count total cuts
                    spec_cuts = sum(len(s['cuts']) for jr in jumbo_rolls for s in jr['sets'])
                    total_cuts += spec_cuts

                    spec_suggestion = {
                        'spec_id': f"spec_{spec_key[0]}_{spec_key[1]}_{spec_key[2]}".replace(" ", "_"),
                        'paper_spec': {
                            'gsm': spec_key[0],
                            'shade': spec_key[1],
                            'bf': spec_key[2]
                        },
                        'target_width': target_width,
                        'jumbo_rolls': jumbo_rolls,
                        'pending_order_ids': [str(item.id) for item in items],
                        'summary': {
                            'total_orders': len(set(item.original_order_id for item in items if item.original_order_id)),
                            'total_jumbo_rolls': len(jumbo_rolls),
                            'total_118_sets': sum(len(jr['sets']) for jr in jumbo_rolls),
                            'total_cuts': spec_cuts
                        }
                    }
                    spec_suggestions.append(spec_suggestion)

            logger.info(f"📊 Generated {len(spec_suggestions)} spec suggestions with {total_cuts} total cuts")

            return {
                "status": "success",
                "target_width": target_width,
                "wastage": wastage,
                "spec_suggestions": spec_suggestions,
                "summary": {
                    "total_pending_input": len(pending_items),
                    "specs_processed": len(spec_suggestions),
                    "total_cuts": total_cuts
                }
            }

        except Exception as e:
            logger.error(f"Error generating roll suggestions: {e}")
            raise

    def _create_jumbo_rolls_directly(self, items: List[models.PendingOrderItem], target_width: float) -> List[Dict]:
        """Create jumbo rolls directly from pending items without complex re-validation."""
        # Convert items to width-quantity pairs while preserving order info
        width_data = {}
        for item in items:
            width = float(item.width_inches)
            if width not in width_data:
                width_data[width] = []

            # Store each individual piece with its order info
            for _ in range(item.quantity_pending):
                width_data[width].append({
                    'order_frontend_id': item.original_order.frontend_id if item.original_order else 'Unknown',
                    'client_name': item.original_order.client.company_name if item.original_order and item.original_order.client else 'Unknown',
                    'item_id': str(item.id)
                })

        logger.info(f"    📦 Width inventory: {[(w, len(pieces)) for w, pieces in width_data.items()]}")

        # Create jumbo rolls using optimization
        jumbo_rolls = []
        jumbo_number = 1

        while any(len(pieces) > 0 for pieces in width_data.values()) and jumbo_number <= 3:
            sets = []
            set_number = 1

            # Create up to 3 sets per jumbo
            for set_num in range(1, 4):
                cuts = []
                cut_number = 1
                total_width = 0

                # Find best combination for this set
                best_combo = self._find_best_width_combination(width_data, target_width)

                if not best_combo:
                    break

                # Create cuts from the combination
                for width, count in best_combo.items():
                    for i in range(count):
                        if width_data[width]:  # Still have pieces of this width
                            piece_info = width_data[width].pop(0)
                            cut = {
                                'cut_id': f"cut_{cut_number}",
                                'width_inches': width,
                                'uses_existing': True,
                                'used_widths': {str(width): 1},
                                'order_frontend_id': piece_info['order_frontend_id'],
                                'client_name': piece_info['client_name'],
                                'description': f"{width}\" from {piece_info['order_frontend_id']} ({piece_info['client_name']})"
                            }
                            cuts.append(cut)
                            total_width += width
                            cut_number += 1

                if cuts:
                    waste = target_width - total_width
                    roll_set = {
                        'set_id': f"set_{set_number}",
                        'set_number': set_number,
                        'target_width': target_width,
                        'cuts': cuts,
                        'manual_addition_available': waste > 20.0,
                        'summary': {
                            'total_cuts': len(cuts),
                            'using_existing_cuts': len(cuts),
                            'total_actual_width': total_width,
                            'total_waste': waste,
                            'efficiency': round((total_width / target_width) * 100, 1)
                        }
                    }
                    sets.append(roll_set)
                    set_number += 1
                else:
                    break

            if sets:
                jumbo_roll = {
                    'jumbo_id': f"jumbo_{jumbo_number}",
                    'jumbo_number': jumbo_number,
                    'target_width': target_width,
                    'sets': sets,
                    'summary': {
                        'total_sets': len(sets),
                        'total_cuts': sum(len(s['cuts']) for s in sets),
                        'using_existing_cuts': sum(len(s['cuts']) for s in sets),
                        'total_actual_width': sum(s['summary']['total_actual_width'] for s in sets),
                        'total_waste': sum(s['summary']['total_waste'] for s in sets),
                        'efficiency': round((sum(s['summary']['total_actual_width'] for s in sets) / (target_width * len(sets))) * 100, 1)
                    }
                }
                jumbo_rolls.append(jumbo_roll)
                jumbo_number += 1
            else:
                break

        return jumbo_rolls

    def _find_best_width_combination(self, width_data: Dict[float, List], target_width: float) -> Dict[float, int]:
        """Find best combination of available widths to minimize waste."""
        available_widths = {w: len(pieces) for w, pieces in width_data.items() if len(pieces) > 0}

        if not available_widths:
            return {}

        best_combo = {}
        min_waste = float('inf')

        # Try combinations with increasing number of pieces (up to 8)
        for num_pieces in range(1, min(9, sum(available_widths.values()) + 1)):
            combo = self._try_simple_combination(available_widths, target_width, num_pieces)
            if combo:
                total_width = sum(w * count for w, count in combo.items())
                waste = target_width - total_width

                if 0 <= waste < min_waste:
                    min_waste = waste
                    best_combo = combo

                    # If we found a very good fit, stop searching
                    if waste <= 2.0:
                        break

        return best_combo

    def _try_simple_combination(self, available_widths: Dict[float, int], target_width: float, num_pieces: int) -> Dict[float, int]:
        """Try to find a combination using exactly num_pieces."""
        from itertools import combinations_with_replacement

        widths = list(available_widths.keys())

        for combo in combinations_with_replacement(widths, num_pieces):
            # Count how many of each width we need
            needed = {}
            for width in combo:
                needed[width] = needed.get(width, 0) + 1

            # Check if we have enough of each width
            if all(available_widths.get(w, 0) >= needed.get(w, 0) for w in needed):
                total_width = sum(combo)
                if total_width <= target_width:
                    return needed

        return {}

    def _validate_order_data_integrity(self, items: List[models.PendingOrderItem]) -> None:
        """Validate that all items have proper order and client relationships."""
        missing_order_count = 0
        missing_client_count = 0

        for item in items:
            if not item.original_order:
                missing_order_count += 1
                logger.error(f"❌ CRITICAL: Item {item.id} missing original_order relationship")
            elif not item.original_order.client:
                missing_client_count += 1
                logger.error(f"❌ CRITICAL: Item {item.id} has order but missing client relationship")

        if missing_order_count > 0:
            raise ValueError(f"Data integrity error: {missing_order_count} items missing order relationships. Check database joins.")

        if missing_client_count > 0:
            raise ValueError(f"Data integrity error: {missing_client_count} items missing client relationships. Check database joins.")

        logger.info(f"✅ Data integrity validated: All {len(items)} items have proper relationships")

    def _validate_cut_generation(self, jumbo_rolls: List[Dict]) -> None:
        """Validate that all generated cuts have proper order information."""
        cuts_with_unknown = 0
        total_cuts = 0

        for jumbo in jumbo_rolls:
            for roll_set in jumbo['sets']:
                for cut in roll_set['cuts']:
                    total_cuts += 1
                    if (cut.get('order_frontend_id') == 'Unknown' or
                        cut.get('client_name') == 'Unknown' or
                        not cut.get('order_frontend_id') or
                        not cut.get('client_name')):
                        cuts_with_unknown += 1
                        logger.error(f"❌ Cut {cut.get('cut_id')} has unknown order data: "
                                   f"order='{cut.get('order_frontend_id')}', client='{cut.get('client_name')}'")

        if cuts_with_unknown > 0:
            raise ValueError(f"Cut generation failed: {cuts_with_unknown}/{total_cuts} cuts have missing order information. "
                           f"This indicates the new simplified approach has failed.")

        logger.info(f"✅ Cut validation passed: All {total_cuts} cuts have proper order information")