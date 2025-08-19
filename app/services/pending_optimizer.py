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
    
    def get_roll_suggestions(self, wastage: float) -> Dict[str, Any]:
        """
        Generate roll suggestions for completing target width rolls based on pending orders.
        
        Args:
            wastage: Amount to subtract from 119 inches for target width calculation
            
        Returns:
            Dict containing:
            - target_width: Calculated target width (119 - wastage)
            - wastage: Input wastage amount
            - roll_suggestions: Suggestions for completing target width rolls
            - summary: Statistics about unique widths and suggestions
        """
        try:
            # Calculate target width
            target_width = 119 - wastage
            logger.info(f"🎯 Generating roll suggestions for target width: {target_width}\" (119 - {wastage} wastage)")
            
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
                    "roll_suggestions": [],
                    "summary": {
                        "total_pending_input": 0,
                        "unique_widths": 0,
                        "suggested_rolls": 0
                    }
                }
            
            # Group by paper specifications and get unique widths
            spec_groups = self._group_by_specs(pending_items)
            logger.info(f"🔍 Created {len(spec_groups)} spec groups")
            
            # Generate suggestions for unique widths
            roll_suggestions = self._generate_simple_suggestions(spec_groups, target_width)
            
            # Count unique widths across all spec groups
            unique_widths = set()
            for items in spec_groups.values():
                for item in items:
                    unique_widths.add(float(item.width_inches))
            
            logger.info(f"🎯 ROLL SUGGESTIONS RESULTS:")
            logger.info(f"  Total input items: {len(pending_items)}")
            logger.info(f"  Unique widths: {len(unique_widths)}")
            logger.info(f"  Suggestions generated: {len(roll_suggestions)}")
            logger.info(f"  Target width: {target_width}\"")

            return {
                "status": "success",
                "target_width": target_width,
                "wastage": wastage,
                "roll_suggestions": roll_suggestions,
                "summary": {
                    "total_pending_input": len(pending_items),
                    "unique_widths": len(unique_widths),
                    "suggested_rolls": len(roll_suggestions)
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating roll suggestions: {e}")
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
    
    def _generate_simple_suggestions(self, spec_groups: Dict, target_width: float) -> List[Dict]:
        """Generate simple suggestions for completing target width rolls using actual pending widths."""
        suggestions = []
        
        # Generate suggestions for each spec group
        for spec_key, items in spec_groups.items():
            # Get unique widths for this spec group
            unique_widths = set()
            for item in items:
                unique_widths.add(float(item.width_inches))
            
            # Create suggestions for each unique width
            for width in unique_widths:
                if width < target_width:  # Only suggest for widths that need completion
                    needed_width = target_width - width
                    
                    suggestion = {
                        'suggestion_id': str(uuid.uuid4()),
                        'paper_specs': {
                            'gsm': spec_key[0],
                            'shade': spec_key[1],
                            'bf': spec_key[2]
                        },
                        'existing_width': width,
                        'needed_width': needed_width,
                        'description': f"{width}\" + {needed_width}\" = {target_width}\""
                    }
                    suggestions.append(suggestion)
                    
                    logger.info(f"  💡 Suggestion: {width}\" + {needed_width}\" = {target_width}\" for {spec_key[1]} {spec_key[0]}GSM")
        
        return suggestions
    
    # Removed complex practical combinations method - using simple suggestions
    
    # All complex optimization and acceptance methods removed - now only providing simple suggestions