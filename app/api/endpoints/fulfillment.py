from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from .... import models, schemas
from ....database import get_db
from ....services.order_fulfillment import OrderFulfillmentService
from ....core.security import get_current_user

router = APIRouter()

@router.post("/orders/{order_id}/fulfill", response_model=schemas.FulfillmentResponse)
async def fulfill_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Fulfill an order by either:
    1. Allocating existing inventory, or
    2. Creating and executing a cutting plan, or
    3. Creating a production order if no suitable jumbo roll is available
    """
    service = OrderFulfillmentService(db, current_user.id)
    return service.fulfill_order(order_id)

@router.get("/cutting-plans/", response_model=List[schemas.CuttingPlan])
async def list_cutting_plans(
    order_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """List cutting plans with optional filtering"""
    query = db.query(models.CuttingPlan)
    
    if order_id:
        query = query.filter(models.CuttingPlan.order_id == order_id)
    if status:
        query = query.filter(models.CuttingPlan.status == status)
        
    return query.offset(skip).limit(limit).all()

@router.get("/cutting-plans/{plan_id}", response_model=schemas.CuttingPlanDetail)
async def get_cutting_plan(
    plan_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get detailed information about a specific cutting plan"""
    plan = db.query(models.CuttingPlan).filter(models.CuttingPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Cutting plan not found")
    
    # Get related cut rolls
    cut_rolls = db.query(models.CutRoll).filter(
        models.CutRoll.jumbo_roll_id == plan.jumbo_roll_id,
        models.CutRoll.order_id == plan.order_id
    ).all()
    
    return {
        "plan": plan,
        "cut_rolls": cut_rolls,
        "jumbo_roll": plan.jumbo_roll,
        "order": plan.order
    }

@router.post("/production-orders/", response_model=schemas.ProductionOrder)
async def create_production_order(
    production_order: schemas.ProductionOrderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Create a new production order for jumbo rolls"""
    db_production_order = models.ProductionOrder(
        **production_order.dict(),
        created_by_id=current_user.id,
        status="pending"
    )
    
    db.add(db_production_order)
    db.commit()
    db.refresh(db_production_order)
    
    return db_production_order

@router.get("/production-orders/", response_model=List[schemas.ProductionOrder])
async def list_production_orders(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """List production orders with optional status filter"""
    query = db.query(models.ProductionOrder)
    
    if status:
        query = query.filter(models.ProductionOrder.status == status)
        
    return query.offset(skip).limit(limit).all()

@router.post("/production-orders/{order_id}/complete", response_model=schemas.ProductionOrder)
async def complete_production_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Mark a production order as completed and create jumbo rolls"""
    # Get the production order
    production_order = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.id == order_id
    ).first()
    
    if not production_order:
        raise HTTPException(status_code=404, detail="Production order not found")
    
    if production_order.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending production orders can be completed")
    
    # Create jumbo rolls
    for _ in range(production_order.quantity):
        jumbo_roll = models.JumboRoll(
            width_inches=119,  # Standard width
            weight_kg=4500,    # Standard weight
            gsm=production_order.gsm,
            bf=production_order.bf,
            shade=production_order.shade,
            status="available",
            production_order_id=production_order.id,
            created_by_id=current_user.id
        )
        db.add(jumbo_roll)
    
    # Update production order status
    production_order.status = "completed"
    db.add(production_order)
    db.commit()
    
    # Try to fulfill any waiting orders
    if production_order.order_id:
        try:
            service = OrderFulfillmentService(db, current_user.id)
            service.fulfill_order(production_order.order_id)
        except Exception:
            # Log the error but don't fail the request
            pass
    
    return production_order
