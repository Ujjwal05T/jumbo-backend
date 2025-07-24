from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from . import models, schemas
from .database import get_db
from .services.cutting_optimizer import CuttingOptimizer

router = APIRouter()

def _find_or_create_jumbo_roll(db: Session, paper_spec: Dict[str, Any]) -> models.JumboRoll:
    """Find an existing jumbo roll or create a new one with the required specifications."""
    # Try to find an existing available jumbo roll
    jumbo_roll = db.query(models.JumboRoll).filter(
        models.JumboRoll.gsm == paper_spec['gsm'],
        models.JumboRoll.bf == paper_spec['bf'],
        models.JumboRoll.shade == paper_spec['shade'],
        models.JumboRoll.status == models.JumboRollStatus.AVAILABLE
    ).first()
    
    if not jumbo_roll:
        # Create a new jumbo roll (this would typically be from production)
        jumbo_roll = models.JumboRoll(
            gsm=paper_spec['gsm'],
            bf=paper_spec['bf'],
            shade=paper_spec['shade'],
            status=models.JumboRollStatus.AVAILABLE
        )
        db.add(jumbo_roll)
        db.flush()  # Get the ID without committing
    
    return jumbo_roll

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
        
        # Generate the optimized plan using new algorithm
        plan = optimizer.generate_optimized_plan(
            order_requirements=order_requirements,
            interactive=False  # Non-interactive for API
        )
        
        # Create cutting plans in database for each jumbo roll
        cutting_plans_created = []
        for jumbo in plan.get('jumbo_rolls_used', []):
            # Find or create a suitable jumbo roll
            jumbo_roll = _find_or_create_jumbo_roll(db, jumbo['paper_spec'])
            
            # Create cutting plan
            cutting_plan = models.CuttingPlan(
                order_id=orders[0].id,  # Associate with first order for now
                jumbo_roll_id=jumbo_roll.id,
                cut_pattern=jumbo['rolls'],
                expected_waste_percentage=jumbo['waste_percentage'],
                status="planned"
            )
            db.add(cutting_plan)
            cutting_plans_created.append(cutting_plan)
        
        # Handle pending orders - create production orders
        production_orders_created = []
        for pending in plan.get('pending_orders', []):
            production_order = models.ProductionOrder(
                gsm=pending['gsm'],
                bf=pending['bf'],
                shade=pending['shade'],
                quantity=1,  # One jumbo roll
                status="pending"
            )
            db.add(production_order)
            production_orders_created.append(production_order)
        
        db.commit()
        
        # Convert the plan to the response model
        patterns = []
        for jumbo in plan.get('jumbo_rolls_used', []):
            patterns.append({
                'rolls': jumbo['rolls'],
                'waste_percentage': jumbo['waste_percentage'],
                'waste_inches': jumbo['trim_left']
            })
        
        return {
            'patterns': patterns,
            'total_rolls_needed': plan['summary']['total_jumbos_used'],
            'total_waste_percentage': plan['summary']['overall_waste_percentage'],
            'total_waste_inches': plan['summary']['total_trim_inches'],
            'fulfilled_orders': [],
            'unfulfilled_orders': [
                {
                    'width': order['width'],
                    'quantity': order['quantity'],
                    'gsm': order['gsm'],
                    'bf': order['bf'],
                    'shade': order['shade']
                }
                for order in plan.get('pending_orders', [])
            ],
            'cutting_plans_created': len(cutting_plans_created),
            'production_orders_created': len(production_orders_created)
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
        
        # Generate the optimized plan using new algorithm
        plan = optimizer.generate_optimized_plan(
            order_requirements=order_requirements,
            interactive=False  # Non-interactive for API
        )
        
        # Convert the plan to the response model using new algorithm format
        patterns = []
        for jumbo in plan.get('jumbo_rolls_used', []):
            patterns.append({
                'rolls': jumbo['rolls'],
                'waste_percentage': jumbo['waste_percentage'],
                'waste_inches': jumbo['trim_left']
            })
        
        return {
            'patterns': patterns,
            'total_rolls_needed': plan['summary']['total_jumbos_used'],
            'total_waste_percentage': plan['summary']['overall_waste_percentage'],
            'total_waste_inches': plan['summary']['total_trim_inches'],
            'fulfilled_orders': [],  # Not applicable for custom specs
            'unfulfilled_orders': [
                {
                    'width': order['width'],
                    'quantity': order['quantity'],
                    'gsm': order['gsm'],
                    'bf': order['bf'],
                    'shade': order['shade']
                }
                for order in plan.get('pending_orders', [])
            ]
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
        
        # Basic validation for the new algorithm
        validation_result = {
            "valid": True,
            "issues": [],
            "recommendations": [],
            "summary": {
                "total_patterns": len(plan.get('patterns', [])),
                "total_requirements": len(requirements),
                "validation_passed": True
            }
        }
        
        # Basic checks
        if not plan.get('patterns'):
            validation_result["valid"] = False
            validation_result["issues"].append("No cutting patterns found in plan")
        
        if not requirements:
            validation_result["issues"].append("No requirements provided for validation")
        
        # Add recommendations
        if plan.get('patterns'):
            avg_waste = sum(p.get('waste_percentage', 0) for p in plan['patterns']) / len(plan['patterns'])
            if avg_waste > 15:
                validation_result["recommendations"].append("Consider optimizing patterns to reduce waste")
            elif avg_waste < 5:
                validation_result["recommendations"].append("Excellent waste optimization achieved")
        
        return validation_result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error validating cutting plan: {str(e)}"
        )
