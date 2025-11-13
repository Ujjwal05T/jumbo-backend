from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from datetime import datetime
from itertools import combinations_with_replacement, permutations
import uuid
import logging
import json
import math

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

            # Calculate total quantity for comprehensive tracking
            total_pending_quantity = sum(item.quantity_pending for item in pending_items)
            logger.info(f"📊 PROCESSING START: {len(pending_items)} items with total quantity {total_pending_quantity}")

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
            total_processed_items = 0
            unprocessed_item_details = []

            for spec_key, items in spec_groups.items():
                spec_quantity = sum(item.quantity_pending for item in items)
                logger.info(f"  → {spec_key[1]} {spec_key[0]}GSM BF{spec_key[2]}: {len(items)} items, {spec_quantity} total quantity")

                # Create jumbo rolls directly from items with improved capacity
                jumbo_rolls, processed_count, unprocessed_items = self._create_jumbo_rolls_directly_improved(items, target_width)

                # Track processing statistics
                total_processed_items += processed_count
                if unprocessed_items:
                    unprocessed_item_details.extend(unprocessed_items)

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
                        'processing_stats': {
                            'total_input_quantity': spec_quantity,
                            'processed_quantity': processed_count,
                            'unprocessed_quantity': len(unprocessed_items),
                            'processing_efficiency': round((processed_count / spec_quantity) * 100, 1) if spec_quantity > 0 else 0
                        },
                        'summary': {
                            'total_orders': len(set(item.original_order_id for item in items if item.original_order_id)),
                            'total_jumbo_rolls': len(jumbo_rolls),
                            'total_118_sets': sum(len(jr['sets']) for jr in jumbo_rolls),
                            'total_cuts': spec_cuts
                        }
                    }
                    spec_suggestions.append(spec_suggestion)
                else:
                    # No jumbo rolls could be created for this spec
                    logger.warning(f"⚠️ No jumbo rolls generated for spec {spec_key}: {spec_quantity} items remain unprocessed")
                    unprocessed_item_details.extend([{
                        'item_id': str(item.id),
                        'spec': spec_key,
                        'quantity': item.quantity_pending,
                        'reason': 'No feasible cutting patterns found'
                    } for item in items])

            # Comprehensive processing summary
            unprocessed_quantity = total_pending_quantity - total_processed_items
            processing_rate = round((total_processed_items / total_pending_quantity) * 100, 1) if total_pending_quantity > 0 else 0

            logger.info(f"📊 PROCESSING SUMMARY:")
            logger.info(f"  Input: {total_pending_quantity} items across {len(spec_groups)} specs")
            logger.info(f"  Processed: {total_processed_items} items ({processing_rate}%)")
            logger.info(f"  Unprocessed: {unprocessed_quantity} items")
            logger.info(f"  Generated: {len(spec_suggestions)} spec suggestions with {total_cuts} total cuts")

            if unprocessed_quantity > 0:
                logger.warning(f"⚠️ UNPROCESSED ITEMS: {unprocessed_quantity} items could not be processed")
                for item_detail in unprocessed_item_details[:5]:  # Log first 5 for brevity
                    logger.warning(f"    - Item {item_detail.get('item_id', 'Unknown')[:8]}: {item_detail.get('quantity', 0)} items, Reason: {item_detail.get('reason', 'Unknown')}")

            return {
                "status": "success",
                "target_width": target_width,
                "wastage": wastage,
                "spec_suggestions": spec_suggestions,
                "unprocessed_items": unprocessed_item_details,
                "summary": {
                    "total_pending_input": len(pending_items),
                    "total_input_quantity": total_pending_quantity,
                    "total_processed_quantity": total_processed_items,
                    "unprocessed_quantity": unprocessed_quantity,
                    "processing_rate": processing_rate,
                    "specs_processed": len(spec_suggestions),
                    "specs_with_unprocessed": len([s for s in spec_suggestions if s['processing_stats']['unprocessed_quantity'] > 0]),
                    "total_cuts": total_cuts
                }
            }

        except Exception as e:
            logger.error(f"Error generating roll suggestions: {e}")
            raise

    def _create_jumbo_rolls_directly_improved(self, items: List[models.PendingOrderItem], target_width: float) -> Tuple[List[Dict], int, List[Dict]]:
        """
        IMPROVED: Create jumbo rolls with dynamic capacity and enhanced algorithm.
        Returns: (jumbo_rolls, processed_count, unprocessed_items)
        """
        # Calculate dynamic capacity based on actual needs
        total_quantity = sum(item.quantity_pending for item in items)
        # Average 6 cuts per jumbo roll, no minimum constraint
        calculated_jumbo_rolls = max(1, math.ceil(total_quantity / 6))  # At least 1 jumbo roll
        max_jumbo_rolls = min(calculated_jumbo_rolls, 20)  # Safety cap to prevent infinite loops

        logger.info(f"🎯 CAPACITY CALCULATION: {total_quantity} items → {max_jumbo_rolls} jumbo rolls (capacity for up to {max_jumbo_rolls * 6} items)")
        logger.info(f"🎯 DEBUG: calculated_jumbo_rolls={calculated_jumbo_rolls}, max_jumbo_rolls={max_jumbo_rolls}")

      
        # Convert items to width-quantity pairs while preserving order info
        width_data = {}
        total_pieces_created = 0
        unprocessed_items = []

        for item in items:
            width = float(item.width_inches)
            if width not in width_data:
                width_data[width] = []

            # Store each individual piece with its order info
            pieces_for_item = []
            for _ in range(item.quantity_pending):
                piece_info = {
                    'order_frontend_id': item.original_order.frontend_id if item.original_order else 'Unknown',
                    'client_name': item.original_order.client.company_name if item.original_order and item.original_order.client else 'Unknown',
                    'item_id': str(item.id),
                    'original_quantity': item.quantity_pending
                }
                width_data[width].append(piece_info)
                pieces_for_item.append(piece_info)

            # Track original item for unprocessed reporting
            item.processed_pieces = 0
            item.total_pieces = item.quantity_pending
            item.piece_details = pieces_for_item

        logger.info(f"    📦 Width inventory: {[(w, len(pieces)) for w, pieces in width_data.items()]}")

        # Create jumbo rolls using improved optimization
        jumbo_rolls = []
        jumbo_number = 1
        processed_count = 0

        while any(len(pieces) > 0 for pieces in width_data.values()) and jumbo_number <= max_jumbo_rolls:
            remaining_pieces = sum(len(pieces) for pieces in width_data.values())
            width_breakdown = {w: len(pieces) for w, pieces in width_data.items() if len(pieces) > 0}
            logger.info(f"🔄 Starting JUMBO {jumbo_number}/{max_jumbo_rolls} with {remaining_pieces} pieces: {width_breakdown}")

            sets = []
            set_number = 1
            jumbo_processed_count = 0

            # Create up to 4 sets per jumbo
            for set_num in range(1, 5):
                logger.info(f"🔄 Creating SET {set_num} of jumbo {jumbo_number}")

                # Initialize variables for this set
                cuts = []
                cut_number = 1
                total_width = 0

                # Find best combination for this set
                best_combo = self._find_best_width_combination_with_piece_priority(width_data, target_width, set_number, jumbo_number)

                logger.info(f"🎯 SET {set_num}: Best combo found: {best_combo}")

                if not best_combo:
                    logger.warning(f"⚠️ No combo found for SET {set_num}, trying lenient search")
                    best_combo = self._find_best_width_combination_lenient(width_data, target_width, set_number, jumbo_number)

                    if not best_combo:
                        logger.warning(f"❌ No combo found even with lenient search for SET {set_num}")
                        logger.info(f"🛑 Stopping set creation at {len(sets)} sets")
                        break

                    logger.info(f"🎯 SET {set_num}: Lenient combo found: {best_combo}")

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
                                'item_id': piece_info['item_id'],
                                'description': f"{width}\" from {piece_info['order_frontend_id']} ({piece_info['client_name']})"
                            }
                            cuts.append(cut)
                            total_width += width
                            cut_number += 1
                            jumbo_processed_count += 1

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
                processed_count += jumbo_processed_count
                jumbo_number += 1

                logger.info(f"🎯 Jumbo {jumbo_number-1}: Created {len(sets)} sets with {jumbo_processed_count} cuts")

                # Check if we should continue to next jumbo
                remaining_after_jumbo = sum(len(pieces) for pieces in width_data.values())
                logger.info(f"🔄 Remaining pieces after jumbo {jumbo_number-1}: {remaining_after_jumbo}")

                if remaining_after_jumbo == 0:
                    logger.info(f"✅ All pieces processed, stopping at {jumbo_number-1} jumbo rolls")
                    break
            else:
                logger.warning(f"⚠️ No sets created for jumbo {jumbo_number}, trying to continue with next jumbo")
                # Don't break - try to continue to next jumbo roll
                jumbo_number += 1
                if jumbo_number > max_jumbo_rolls:
                    logger.warning(f"⚠️ Reached maximum jumbo roll limit ({max_jumbo_rolls}) without creating sets")
                    break
                continue

        # Identify unprocessed items and their reasons
        for item in items:
            if hasattr(item, 'piece_details'):
                processed_for_item = sum(1 for piece in item.piece_details if piece['item_id'] not in [cut['item_id'] for jumbo in jumbo_rolls for s in jumbo['sets'] for cut in s['cuts']])
                unprocessed_for_item = item.quantity_pending - processed_for_item

                if unprocessed_for_item > 0:
                    unprocessed_items.append({
                        'item_id': str(item.id),
                        'spec': (item.gsm, item.shade, float(item.bf)),
                        'quantity': unprocessed_for_item,
                        'reason': 'Capacity exceeded or no feasible pattern found',
                        'width_inches': float(item.width_inches)
                    })

        # Calculate remaining pieces that couldn't be processed
        remaining_pieces = sum(len(pieces) for pieces in width_data.values())
        if remaining_pieces > 0:
            logger.warning(f"⚠️ REMAINING PIECES: {remaining_pieces} pieces could not be processed in {jumbo_number-1} jumbo rolls")

            # Add details about remaining pieces
            for width, pieces in width_data.items():
                if pieces:
                    unprocessed_items.append({
                        'item_id': pieces[0]['item_id'],
                        'spec': 'unknown',
                        'quantity': len(pieces),
                        'reason': f'Width {width}" pieces remaining after jumbo roll limit',
                        'width_inches': width
                    })

        logger.info(f"📈 JUMBO PROCESSING: Created {len(jumbo_rolls)} jumbo rolls, processed {processed_count}/{total_quantity} pieces")

        return jumbo_rolls, processed_count, unprocessed_items

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

    def _find_best_width_combination_improved(self, width_data: Dict[float, List], target_width: float, set_number: int, jumbo_number: int) -> Dict[float, int]:
        """
        IMPROVED: Find best combination of available widths to minimize waste with enhanced logic.
        Features:
        - Increased combination limit (up to 15 pieces)
        - Better pattern recognition
        - Priority for smaller waste
        - Enhanced logging for debugging
        """
        available_widths = {w: len(pieces) for w, pieces in width_data.items() if len(pieces) > 0}

        if not available_widths:
            return {}

        total_available_pieces = sum(available_widths.values())
        logger.debug(f"🔍 COMBINATION SEARCH: Jumbo {jumbo_number}, Set {set_number}")
        logger.debug(f"    Available widths: {available_widths}")
        logger.debug(f"    Target width: {target_width}, Total pieces: {total_available_pieces}")

        best_combo = {}
        min_waste = float('inf')
        best_efficiency = 0

        # IMPROVED: Dynamic maximum pieces based on available pieces and target width
        # Small widths can have more pieces, large widths fewer pieces
        avg_width = sum(w * count for w, count in available_widths.items()) / total_available_pieces
        max_pieces_by_width = max(6, int(target_width / avg_width))
        max_combination_pieces = min(max_pieces_by_width, min(15, total_available_pieces))

        logger.debug(f"    Max pieces per combination: {max_combination_pieces} (based on avg width: {avg_width:.1f}\")")

        # Try combinations with increasing number of pieces
        for num_pieces in range(1, max_combination_pieces + 1):
            combo = self._try_combination_with_priority(available_widths, target_width, num_pieces)
            if combo:
                total_width = sum(w * count for w, count in combo.items())
                waste = target_width - total_width
                efficiency = (total_width / target_width) * 100

                # IMPROVED: Better scoring algorithm
                # Prefer combinations with higher efficiency and lower waste
                score = efficiency - (waste * 0.1)  # Small penalty for waste

                if waste >= 0 and score > (best_efficiency - (min_waste * 0.1)):
                    best_combo = combo
                    min_waste = waste
                    best_efficiency = efficiency

                    logger.debug(f"    ✓ New best combo ({num_pieces} pieces): {combo} → {total_width}\" used, {waste}\" waste, {efficiency:.1f}% efficiency")

                    # FIXED: Remove premature early termination to ensure better combinations are found
                    # Only terminate for truly exceptional combinations
                    if waste <= 0.5 and efficiency >= 98:
                        logger.debug(f"    🎯 Exceptional combination found, stopping search")
                        break
                    # Don't terminate early for moderate combinations - let better ones be found

        if best_combo:
            total_width = sum(w * count for w, count in best_combo.items())
            logger.debug(f"    ✅ FINAL: Selected combo with {len(best_combo)} widths, {sum(best_combo.values())} pieces")
            logger.debug(f"    ✅ FINAL: Width usage: {total_width}/{target_width} inches, waste: {min_waste}, efficiency: {best_efficiency:.1f}%")
        else:
            logger.debug(f"    ❌ No feasible combination found")

        return best_combo

    def _find_best_width_combination_with_piece_priority(self, width_data: Dict[float, List], target_width: float, set_number: int, jumbo_number: int) -> Dict[float, int]:
        """
        MODIFIED: Find combination that maximizes piece usage while maintaining efficiency.
        Prioritizes using more pieces over minimal waste to reduce number of sets.
        """
        available_widths = {w: len(pieces) for w, pieces in width_data.items() if len(pieces) > 0}

        if not available_widths:
            return {}

        total_available_pieces = sum(available_widths.values())
        logger.debug(f"🔍 PRIORITY COMBINATION SEARCH: Jumbo {jumbo_number}, Set {set_number}")
        logger.debug(f"    Available widths: {available_widths}")
        logger.debug(f"    Target width: {target_width}, Total pieces: {total_available_pieces}")

        best_combo = {}
        min_waste = float('inf')
        best_efficiency = 0
        max_pieces_used = 0

        # MODIFIED: Start with maximum pieces and work backwards
        avg_width = sum(w * count for w, count in available_widths.items()) / total_available_pieces
        max_possible_pieces = min(int(target_width / min(available_widths.keys())), total_available_pieces)
        max_combination_pieces = min(max_possible_pieces, min(15, total_available_pieces))

        logger.debug(f"    Max possible pieces: {max_combination_pieces} (based on min width: {min(available_widths.keys()):.1f}\")")

        # Try combinations starting from maximum pieces down to 1
        logger.info(f"    🔍 Testing combos from {max_combination_pieces} pieces down to 1")
        for num_pieces in range(max_combination_pieces, 0, -1):
            logger.info(f"    🎲 Testing {num_pieces}-piece combinations...")
            combo = self._try_combination_with_priority(available_widths, target_width, num_pieces)
            if combo:
                logger.info(f"    ✅ Found {num_pieces}-piece combo: {combo}")
            else:
                logger.info(f"    ❌ No {num_pieces}-piece combo found")

            if combo:
                total_width = sum(w * count for w, count in combo.items())
                waste = target_width - total_width
                efficiency = (total_width / target_width) * 100
                pieces_used = sum(combo.values())

                # FIXED: Priority = waste minimization, then piece usage
                # Primary goal: minimize waste, Secondary goal: use more pieces
                if waste >= 0 and waste < min_waste:
                    best_combo = combo
                    min_waste = waste
                    best_efficiency = efficiency
                    max_pieces_used = pieces_used

                    logger.debug(f"    ✓ New best combo (waste: {waste}\"): {combo} → {total_width}\" used, {efficiency:.1f}% efficiency")

                    # Early termination only for perfect fit
                    if waste <= 0.1:
                        logger.debug(f"    🎯 Perfect fit found, stopping search")
                        break

                # If same waste, prefer more pieces
                elif waste >= 0 and waste == min_waste and pieces_used > max_pieces_used:
                    best_combo = combo
                    max_pieces_used = pieces_used

                    logger.debug(f"    ✓ Better piece count (same waste {waste}\"): {combo} → {total_width}\" used, {efficiency:.1f}% efficiency")

        if best_combo:
            total_width = sum(w * count for w, count in best_combo.items())
            pieces_used = sum(best_combo.values())
            logger.debug(f"    ✅ PRIORITY FINAL: Selected combo with {pieces_used} pieces, {len(best_combo)} widths")
            logger.debug(f"    ✅ PRIORITY FINAL: Width usage: {total_width}/{target_width} inches, waste: {min_waste}, efficiency: {best_efficiency:.1f}%")
        else:
            logger.debug(f"    ❌ No feasible combination found")

        return best_combo

    def _try_combination_with_priority(self, available_widths: Dict[float, int], target_width: float, num_pieces: int) -> Dict[float, int]:
        """
        IMPROVED: Try to find combinations with priority for better patterns.
        Uses smarter enumeration and width prioritization.
        """
        from itertools import combinations_with_replacement

        widths = list(available_widths.keys())
        logger.debug(f"        📋 Available widths: {widths}")
        logger.debug(f"        🎯 Target width: {target_width}, pieces needed: {num_pieces}")

        # IMPROVED: Sort widths for better pattern generation
        # Prioritize widths that are divisors or have good combinations
        sorted_widths = sorted(widths, reverse=True)  # Start with larger widths

        # Create width combinations in order of priority
        combinations_to_try = []

        # Priority 1: Combinations with mixed sizes (usually more efficient)
        if num_pieces >= 3:
            mixed_combos = self._generate_mixed_combinations(sorted_widths, num_pieces)
            combinations_to_try.extend(mixed_combos)
            logger.debug(f"        🔀 Mixed combos generated: {len(mixed_combos)}")

        # Priority 2: Standard combinations with replacement
        for combo in combinations_with_replacement(sorted_widths, num_pieces):
            if combo not in combinations_to_try:
                combinations_to_try.append(combo)

        logger.debug(f"        🔢 Standard combos: {len([c for c in combinations_with_replacement(sorted_widths, num_pieces)])}")

        # Priority 3: Single width combinations (if many pieces of same size)
        if num_pieces <= 5:
            for width in widths:
                if available_widths[width] >= num_pieces:
                    single_combo = tuple([width] * num_pieces)
                    if single_combo not in combinations_to_try:
                        combinations_to_try.append(single_combo)
                        logger.debug(f"        🔷 Added single-width combo: {single_combo}")

        logger.debug(f"        📊 Total combinations to test: {len(combinations_to_try)}")
        logger.debug(f"        📝 First 5 combos: {combinations_to_try[:5]}")

        # FIXED: Test all combinations and return the best one (minimal waste)
        best_needed = {}
        best_waste = float('inf')
        best_total_width = 0

        for combo in combinations_to_try:
            # Count how many of each width we need
            needed = {}
            for width in combo:
                needed[width] = needed.get(width, 0) + 1

            # Check if we have enough of each width
            if all(available_widths.get(w, 0) >= needed.get(w, 0) for w in needed):
                total_width = sum(combo)
                if total_width <= target_width:
                    # FIXED: Accept any feasible combination, track best by waste
                    waste = target_width - total_width
                    efficiency = (total_width / target_width) * 100

                    logger.debug(f"        Feasible combo: {combo} → {total_width}\" ({efficiency:.1f}% eff, {waste}\" waste)")

                    # Track best combination (prioritize minimal waste)
                    if waste < best_waste:
                        best_needed = needed
                        best_waste = waste
                        best_total_width = total_width
                        logger.debug(f"        ★ New best (waste: {waste}\")")

        if best_needed:
            efficiency = (best_total_width / target_width) * 100
            logger.debug(f"        ✅ BEST combo selected: waste={best_waste}\", {efficiency:.1f}% eff")
        else:
            logger.debug(f"        ❌ No feasible combos found for {num_pieces} pieces")

        return best_needed

    def _generate_mixed_combinations(self, widths: List[float], num_pieces: int) -> List[Tuple[float, ...]]:
        """
        Generate mixed width combinations that typically have better efficiency.
        For example: [large, medium, small] instead of [large, large, large]
        """
        mixed_combos = []

        if num_pieces >= 3 and len(widths) >= 2:
            # Create combinations with different width patterns
            # Pattern: [largest, medium, smallest]
            for i in range(len(widths)):
                for j in range(len(widths)):
                    for k in range(len(widths)):
                        if i != j and j != k and i != k:  # All different widths
                            combo = (widths[i], widths[j], widths[k])
                            if len(set(combo)) == min(3, len(widths)):  # Ensure variety
                                mixed_combos.append(combo)
                                break  # Take one good pattern per largest width
                            if len(mixed_combos) >= 5:  # Limit mixed combos
                                return mixed_combos

        return mixed_combos

    def _find_best_width_combination_lenient(self, width_data: Dict[float, List], target_width: float, set_number: int, jumbo_number: int) -> Dict[float, int]:
        """
        LENIENT: Find combination with much more relaxed constraints.
        Used when the strict algorithm can't find any feasible combinations.
        """
        available_widths = {w: len(pieces) for w, pieces in width_data.items() if len(pieces) > 0}

        if not available_widths:
            return {}

        logger.debug(f"🔍 LENIENT SEARCH: Jumbo {jumbo_number}, Set {set_number}")
        logger.debug(f"    Available widths: {available_widths}")

        # LENIENT: Try individual pieces first
        for width in sorted(available_widths.keys(), reverse=True):
            if available_widths[width] > 0 and width <= target_width:
                logger.debug(f"    ✓ LENIENT: Single piece {width}\" (waste: {target_width - width}\")")
                return {width: 1}

        # LENIENT: Try simple pairs
        for width1 in sorted(available_widths.keys(), reverse=True):
            for width2 in sorted(available_widths.keys(), reverse=True):
                if (available_widths[width1] > 0 and
                    ((width1 == width2 and available_widths[width1] >= 2) or
                     (width1 != width2 and available_widths[width2] > 0))):

                    total_width = width1 + width2
                    if total_width <= target_width:
                        logger.debug(f"    ✓ LENIENT: Pair ({width1}\" + {width2}\" = {total_width}\", waste: {target_width - total_width})")
                        if width1 == width2:
                            return {width1: 2}
                        else:
                            return {width1: 1, width2: 1}

        logger.debug(f"    ❌ LENIENT: No combination found")
        return {}

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