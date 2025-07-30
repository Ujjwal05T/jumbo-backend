from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
import logging

from .base import get_db
from .. import schemas
from ..services.cutting_optimizer import CuttingOptimizer

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# CUTTING ALGORITHM ENDPOINTS
# ============================================================================

@router.post("/cutting/generate-plan", response_model=Dict[str, Any], tags=["Cutting Algorithm"])
def generate_cutting_plan(
    request: schemas.CuttingPlanRequest,
    db: Session = Depends(get_db)
):
    """Generate cutting plan from roll specifications"""
    try:
        optimizer = CuttingOptimizer()
        
        # Convert request to optimizer format
        order_requirements = []
        for item in request.order_requirements:
            order_requirements.append({
                'width': float(item.width),
                'quantity': item.quantity,
                'gsm': item.gsm,
                'bf': float(item.bf),
                'shade': item.shade,
                'min_length': item.min_length
            })
        
        # Use the new 3-input/4-output algorithm
        result = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=request.pending_orders or [],
            available_inventory=request.available_inventory or [],
            interactive=False
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error generating cutting plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cutting/validate-plan", response_model=Dict[str, Any], tags=["Cutting Algorithm"])
def validate_cutting_plan(
    plan_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Validate a cutting plan against constraints"""
    try:
        # Validate jumbo roll width constraints
        jumbo_width = 118  # Default jumbo width
        validation_results = {
            "is_valid": True,
            "violations": [],
            "warnings": [],
            "summary": {}
        }
        
        total_waste = 0
        total_rolls = 0
        
        for jumbo in plan_data.get('jumbo_rolls_used', []):
            total_rolls += 1
            trim = jumbo.get('trim_left', 0)
            total_waste += trim
            
            # Check for excessive waste
            if trim > 20:
                validation_results["violations"].append({
                    "jumbo_number": jumbo.get('jumbo_number'),
                    "issue": f"Excessive waste: {trim}\" > 20\"",
                    "severity": "high"
                })
                validation_results["is_valid"] = False
            elif trim > 6:
                validation_results["warnings"].append({
                    "jumbo_number": jumbo.get('jumbo_number'),
                    "issue": f"High waste: {trim}\" > 6\"",
                    "severity": "medium"
                })
        
        # Calculate overall waste percentage
        if total_rolls > 0:
            avg_waste = total_waste / total_rolls
            waste_percentage = (avg_waste / jumbo_width) * 100
            validation_results["summary"] = {
                "total_jumbo_rolls": total_rolls,
                "average_waste_per_roll": round(avg_waste, 2),
                "overall_waste_percentage": round(waste_percentage, 2)
            }
        
        return validation_results
        
    except Exception as e:
        logger.error(f"Error validating cutting plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cutting/algorithms", response_model=Dict[str, Any], tags=["Cutting Algorithm"])
def get_cutting_algorithms():
    """Get information about available optimization algorithms and their parameters"""
    try:
        return {
            "available_algorithms": [
                {
                    "name": "3-input-4-output",
                    "description": "NEW FLOW: Optimizes cutting using new orders, pending orders, and available inventory",
                    "inputs": [
                        "order_requirements (new orders)",
                        "pending_orders (from previous cycles)",
                        "available_inventory (20-25\" waste rolls)"
                    ],
                    "outputs": [
                        "cut_rolls_generated",
                        "jumbo_rolls_needed",
                        "pending_orders",
                        "inventory_remaining"
                    ],
                    "parameters": {
                        "jumbo_width": 118,
                        "min_trim": 1,
                        "max_trim": 6,
                        "max_trim_with_confirmation": 20,
                        "max_rolls_per_jumbo": 5,
                        "waste_reuse_range": "20-25 inches"
                    },
                    "features": [
                        "Paper specification grouping (GSM + Shade + BF)",
                        "Corrected jumbo roll calculation (1 jumbo = 3 sets of 118\" rolls)",
                        "Waste recycling (20-25\" becomes inventory)",
                        "Interactive high-trim approval",
                        "Master-based architecture support"
                    ]
                }
            ],
            "constraints": {
                "jumbo_roll_width": "118 inches",
                "minimum_trim": "1 inch",
                "maximum_acceptable_trim": "6 inches",
                "maximum_trim_with_approval": "20 inches",
                "maximum_rolls_per_pattern": 5,
                "reusable_waste_range": "20-25 inches"
            },
            "algorithm_version": "2.0_corrected_jumbo_calculation",
            "last_updated": "2024-01-15"
        }
        
    except Exception as e:
        logger.error(f"Error getting algorithm information: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cutting/generate-with-selection", response_model=Dict[str, Any], tags=["Cutting Algorithm"])
def generate_plan_with_selection(
    request: schemas.CuttingPlanWithSelectionRequest,
    db: Session = Depends(get_db)
):
    """Generate plan with cut roll selection in one step"""
    try:
        optimizer = CuttingOptimizer()
        
        # First generate the cutting plan
        order_requirements = []
        for item in request.order_requirements:
            order_requirements.append({
                'width': float(item.width),
                'quantity': item.quantity,
                'gsm': item.gsm,
                'bf': float(item.bf),
                'shade': item.shade,
                'min_length': item.min_length
            })
        
        optimization_result = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=request.pending_orders or [],
            available_inventory=request.available_inventory or [],
            interactive=False
        )
        
        # Apply selection criteria if provided
        selected_cut_rolls = optimization_result['cut_rolls_generated']
        
        if hasattr(request, 'selection_criteria') and request.selection_criteria:
            criteria = request.selection_criteria
            
            # Filter by width range
            if criteria.get('min_width') or criteria.get('max_width'):
                min_w = criteria.get('min_width', 0)
                max_w = criteria.get('max_width', float('inf'))
                selected_cut_rolls = [
                    roll for roll in selected_cut_rolls 
                    if min_w <= roll['width'] <= max_w
                ]
            
            # Filter by paper specs
            if criteria.get('paper_specs'):
                allowed_specs = criteria['paper_specs']
                selected_cut_rolls = [
                    roll for roll in selected_cut_rolls
                    if any(
                        roll['gsm'] == spec['gsm'] and 
                        roll['bf'] == spec['bf'] and 
                        roll['shade'] == spec['shade']
                        for spec in allowed_specs
                    )
                ]
        
        return {
            "optimization_result": optimization_result,
            "selected_cut_rolls": selected_cut_rolls,
            "selection_summary": {
                "total_available": len(optimization_result['cut_rolls_generated']),
                "selected_count": len(selected_cut_rolls),
                "selection_applied": hasattr(request, 'selection_criteria') and bool(request.selection_criteria)
            }
        }
        
    except Exception as e:
        logger.error(f"Error generating plan with selection: {e}")
        raise HTTPException(status_code=500, detail=str(e))