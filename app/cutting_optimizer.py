from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from . import models, schemas
from .database import get_db
from .services.cutting_optimizer import CuttingOptimizer

router = APIRouter()

@router.post("/from-orders", response_model=schemas.OptimizedCuttingPlan)
async def generate_cutting_plan_from_orders(
    request: schemas.OrderCuttingPlanRequest,
    db: Session = Depends(get_db)
    ):
    """
    Generate an optimized cutting plan for the specified orders.
    
    This endpoint creates a cutting plan by considering existing inventory and optimizing
    for minimum waste, speed, or material usage.
    """
    try:
        # Initialize the cutting optimizer
        optimizer = CuttingOptimizer()
        
        # Get the orders from the database
        orders = db.query(models.Order).filter(
            models.Order.id.in_(request.order_ids),
            models.Order.status.in_(["pending", "processing"])
        ).all()
        
        if not orders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No valid orders found with the provided IDs"
            )
        
        # Convert orders to roll specifications
        order_requirements = []
        for order in orders:
            order_requirements.append({
                'order_id': str(order.id),
                'width': order.width_inches,
                'quantity': order.quantity_rolls,
                'gsm': order.gsm,
                'bf': order.bf,
                'shade': order.shade,
                'min_length': 1000  # Default minimum length in meters
            })
        
        # Get available inventory if needed
        available_inventory = []
        if request.consider_inventory:
            inventory_items = db.query(models.InventoryItem).filter(
                models.InventoryItem.status == "available"
            ).all()
            
            for item in inventory_items:
                roll = item.roll
                if roll:
                    available_inventory.append({
                        'id': str(item.id),
                        'width': roll.width_inches,
                        'length': 1000,  # Default length in meters
                        'gsm': roll.gsm,
                        'bf': roll.bf,
                        'shade': roll.shade,
                        'status': item.status
                    })
        
        # Generate the optimized plan
        plan = optimizer.generate_optimized_plan(
            order_requirements=order_requirements,
            available_inventory=available_inventory if request.consider_inventory else [],
            consider_standard_sizes=True
        )
        
        # Convert the plan to the response model
        return {
            'patterns': [
                {
                    'rolls': pattern,
                    'waste_percentage': optimizer.calculate_waste(pattern),
                    'waste_inches': optimizer.jumbo_roll_width - sum(pattern)
                }
                for pattern in plan.get('cutting_patterns', [])
            ],
            'total_rolls_needed': plan.get('rolls_used', 0),
            'total_waste_percentage': plan.get('waste_percentage', 0),
            'total_waste_inches': plan.get('waste_percentage', 0) * optimizer.jumbo_roll_width / 100,
            'fulfilled_orders': plan.get('fulfilled_orders', []),
            'unfulfilled_orders': plan.get('unfulfilled_orders', [])
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating cutting plan: {str(e)}"
        )

@router.post("/from-specs", response_model=schemas.OptimizedCuttingPlan)
async def generate_cutting_plan_from_specs(
    request: schemas.CustomCuttingPlanRequest
    ):
    """
    Generate an optimized cutting plan from custom roll specifications.
    
    This endpoint allows generating a cutting plan without requiring orders to exist in the system.
    It's useful for planning and what-if scenarios.
    """
    try:
        # Initialize the cutting optimizer with custom jumbo roll width
        optimizer = CuttingOptimizer(jumbo_roll_width=request.jumbo_roll_width)
        
        # Convert request to the format expected by the optimizer
        order_requirements = []
        for roll in request.rolls:
            order_requirements.append({
                'width': roll.width,
                'quantity': roll.quantity,
                'gsm': roll.gsm,
                'bf': roll.bf,
                'shade': roll.shade,
                'min_length': roll.min_length if hasattr(roll, 'min_length') else 1000
            })
        
        # Convert available inventory if provided
        available_inventory = []
        if request.available_inventory:
            for inv in request.available_inventory:
                available_inventory.append({
                    'id': str(inv.id),
                    'width': inv.width,
                    'length': inv.length or 1000,
                    'gsm': inv.gsm,
                    'bf': inv.bf,
                    'shade': inv.shade,
                    'status': inv.status
                })
        
        # Generate the optimized plan
        plan = optimizer.generate_optimized_plan(
            order_requirements=order_requirements,
            available_inventory=available_inventory,
            consider_standard_sizes=request.consider_standard_sizes
        )
        
        # Convert the plan to the response model
        return {
            'patterns': [
                {
                    'rolls': [
                        {
                            'width': width,
                            'gsm': next((r.get('gsm', 80) for r in order_requirements 
                                       if r['width'] == width), 80),
                            'bf': next((r.get('bf', 14.5) for r in order_requirements 
                                       if r['width'] == width), 14.5),
                            'shade': next((r.get('shade', 'white') for r in order_requirements 
                                       if r['width'] == width), 'white')
                        }
                    for width in pattern
                ] if isinstance(pattern, list) else pattern.get('rolls', []),
                'waste_percentage': optimizer.calculate_waste(pattern),
                'waste_inches': optimizer.jumbo_roll_width - (
                    sum(width for width in pattern) if isinstance(pattern, list) 
                    else sum(roll.get('width', 0) for roll in pattern.get('rolls', []))
                )
            }
            for pattern in plan.get('cutting_patterns', [])
        ],
        'total_rolls_needed': plan.get('rolls_used', 0),
        'total_waste_percentage': plan.get('waste_percentage', 0),
        'total_waste_inches': plan.get('waste_percentage', 0) * optimizer.jumbo_roll_width / 100,
        'fulfilled_orders': plan.get('fulfilled_orders', []),
        'unfulfilled_orders': plan.get('unfulfilled_orders', [])
    }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating cutting plan: {str(e)}"
        )

@router.post("/validate-plan", response_model=Dict[str, Any])
async def validate_cutting_plan(
    plan: Dict[str, Any]
):
    """
    Validate a cutting plan against business rules.
    
    This endpoint checks if a cutting plan is valid and provides feedback
    on any issues or potential improvements.
    """
    try:
        optimizer = CuttingOptimizer()
        
        # Extract requirements if available
        requirements = plan.get('requirements', [])
        available_inventory = plan.get('available_inventory', [])
        
        # Validate the plan
        validation_result = optimizer.validate_cutting_plan(
            plan=plan,
            requirements=requirements,
            available_inventory=available_inventory
        )
        
        return validation_result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error validating cutting plan: {str(e)}"
        )
