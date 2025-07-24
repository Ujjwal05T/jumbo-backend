from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional
import logging
import uuid
import json
from uuid import UUID
from datetime import datetime

from . import crud, schemas, models, database

# Set up logging
logger = logging.getLogger(__name__)

# Create tables on startup only if database engine is available
router = APIRouter()

from .cutting_optimizer import router as cutting_optimizer_router
router.include_router(cutting_optimizer_router, prefix="/cutting-optimization", tags=["cutting-optimization"])

# Try to create tables, but don't fail if database is not available
if database.engine is not None:
    try:
        models.Base.metadata.create_all(bind=database.engine)
        logger.info("Database tables created successfully")
    except SQLAlchemyError as e:
        logger.error(f"Failed to create database tables: {e}")
else:
    logger.warning("Database engine not available, skipping table creation")

# Dependency
def get_db():
    if database.SessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection not available. Please check server logs."
        )
    
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Authentication endpoints
@router.post("/register", response_model=schemas.AuthResponse)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check if user already exists
    db_user = crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(
            status_code=400,
            detail="Username already registered"
        )
    
    # Create new user
    db_user = crud.create_user(db=db, user=user)
    if not db_user:
        raise HTTPException(
            status_code=500,
            detail="Error creating user"
        )
    
    # Return success response with username
    return {
        "status": "success",
        "username": db_user.username
    }

@router.post("/login", response_model=schemas.AuthResponse)
def login_user(credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    # Authenticate user
    user = crud.authenticate_user(
        db=db, 
        username=credentials.username, 
        password=credentials.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Return success response with username
    return {
        "status": "success",
        "username": user.username
    }

# Order endpoints
@router.post("/orders", response_model=schemas.Order)
def create_order(order: schemas.OrderCreate, db: Session = Depends(get_db)):
    return crud.create_order(db=db, order=order)

@router.get("/orders", response_model=List[schemas.Order])
def read_orders(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    orders = crud.get_orders(db, skip=skip, limit=limit)
    return orders

@router.get("/orders/{order_id}", response_model=schemas.Order)
def read_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    db_order = crud.get_order(db, order_id=order_id)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@router.put("/orders/{order_id}", response_model=schemas.Order)
def update_order(order_id: uuid.UUID, order_update: schemas.OrderUpdate, db: Session = Depends(get_db)):
    db_order = crud.update_order(db=db, order_id=order_id, update=order_update)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@router.get("/orders/status/{status_value}", response_model=List[schemas.Order])
def read_orders_by_status(status_value: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    orders = crud.get_orders(db, skip=skip, limit=limit)
    return [order for order in orders if order.status == status_value]

@router.get("/orders/{order_id}/details", response_model=schemas.Order)
def read_order_details(order_id: uuid.UUID, db: Session = Depends(get_db)):
    db_order = crud.get_order_with_details(db, order_id=order_id)
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    if not crud.delete_order(db=db, order_id=order_id):
        raise HTTPException(status_code=404, detail="Order not found")
    return Response(status_code=204)

@router.put("/orders/{order_id}/deliver", response_model=schemas.Order)
async def mark_order_delivered(
    order_id: UUID,
    delivery_update: schemas.OrderDeliveryUpdate,
    db: Session = Depends(get_db),
):
    """
    Mark an order as delivered and update inventory
    
    Valid status transitions:
    - processing -> ready_for_delivery
    - ready_for_delivery -> in_transit
    - in_transit -> delivered
    - Any status -> cancelled (with appropriate validations)
    """
    return crud.update_order_delivery(
        db=db,
        order_id=order_id,
        delivery_update=delivery_update,
        user_id=None  # No user authentication for now
    )

@router.get("/orders/{order_id}/inventory-logs", response_model=List[schemas.InventoryLog])
async def get_order_inventory_logs(
    order_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get inventory logs for a specific order"""
    return crud.get_inventory_logs(
        db=db,
        order_id=order_id,
        skip=skip,
        limit=limit
    )

@router.post("/orders/{order_id}/fulfill")
async def fulfill_order(
    order_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Fulfill an order using the cutting optimizer.
    This will try to fulfill from inventory first, then create cutting plans.
    """
    from .services.order_fulfillment import OrderFulfillmentService
    
    fulfillment_service = OrderFulfillmentService(db)
    result = fulfillment_service.fulfill_order(order_id)
    
    return result

@router.get("/orders/pending", response_model=List[schemas.Order])
async def get_pending_orders(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all pending orders that need fulfillment"""
    return db.query(models.Order).filter(
        models.Order.status.in_(["pending", "partially_fulfilled"])
    ).order_by(models.Order.id).offset(skip).limit(limit).all()

@router.get("/production-orders")
async def get_production_orders(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get production orders with optional status filter"""
    try:
        query = db.query(models.ProductionOrder)
        
        if status:
            query = query.filter(models.ProductionOrder.status == status)
        
        production_orders = query.order_by(models.ProductionOrder.id).offset(skip).limit(limit).all()
        
        # Convert to dict format to avoid serialization issues
        return [
            {
                "id": str(order.id),
                "gsm": order.gsm,
                "bf": float(order.bf),
                "shade": order.shade,
                "quantity": order.quantity,
                "status": order.status,
                "created_at": order.created_at,
                "completed_at": order.completed_at,
                "order_id": str(order.order_id) if order.order_id else None
            }
            for order in production_orders
        ]
    except Exception as e:
        logger.error(f"Error getting production orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/production-orders/{production_order_id}/complete")
async def complete_production_order(
    production_order_id: UUID,
    db: Session = Depends(get_db)
):
    """Mark a production order as completed and create the jumbo roll"""
    production_order = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.id == production_order_id
    ).first()
    
    if not production_order:
        raise HTTPException(status_code=404, detail="Production order not found")
    
    # Create the jumbo roll
    jumbo_roll = models.JumboRoll(
        gsm=production_order.gsm,
        bf=production_order.bf,
        shade=production_order.shade,
        status=models.JumboRollStatus.AVAILABLE,
        production_order_id=production_order.id
    )
    db.add(jumbo_roll)
    
    # Update production order status
    production_order.status = models.ProductionOrderStatus.COMPLETED
    production_order.completed_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "message": "Production order completed",
        "jumbo_roll_id": str(jumbo_roll.id),
        "production_order_id": str(production_order.id)
    }

@router.get("/inventory/logs", response_model=List[schemas.InventoryLog])
async def get_all_inventory_logs(
    roll_id: Optional[UUID] = None,
    order_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Get inventory logs with optional filtering
    
    Parameters:
    - roll_id: Filter logs by roll ID
    - order_id: Filter logs by order ID
    - skip: Number of records to skip (for pagination)
    - limit: Maximum number of records to return (for pagination)
    """
    return crud.get_inventory_logs(
        db=db,
        roll_id=roll_id,
        order_id=order_id,
        skip=skip,
        limit=limit
    )

# Message parsing endpoints
@router.post("/messages/", response_model=schemas.ParsedMessage)
def create_parsed_message(message: schemas.ParsedMessageCreate, db: Session = Depends(get_db)):
    return crud.create_parsed_message(db=db, message=message)

@router.post("/messages/parse", response_model=schemas.ParsedMessage)
def parse_message(message: schemas.ParsedMessageCreate, db: Session = Depends(get_db)):
    # Add any message parsing logic here if needed
    return crud.create_parsed_message(db=db, message=message)

# Jumbo roll endpoints
@router.post("/jumbo-rolls/", response_model=schemas.JumboRoll)
def create_jumbo_roll(roll: schemas.JumboRollCreate, db: Session = Depends(get_db)):
    return crud.create_jumbo_roll(db=db, roll=roll)

@router.get("/jumbo-rolls/", response_model=List[schemas.JumboRoll])
def read_jumbo_rolls(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_jumbo_rolls(db=db, skip=skip, limit=limit)

@router.get("/jumbo-rolls/{roll_id}", response_model=schemas.JumboRoll)
def read_jumbo_roll(roll_id: uuid.UUID, db: Session = Depends(get_db)):
    db_roll = crud.get_jumbo_roll(db, roll_id=roll_id)
    if db_roll is None:
        raise HTTPException(status_code=404, detail="Jumbo roll not found")
    return db_roll

# Cut roll endpoints
@router.post("/cut-rolls/", response_model=schemas.CutRoll)
def create_cut_roll(roll: schemas.CutRollCreate, db: Session = Depends(get_db)):
    return crud.create_cut_roll(db=db, roll=roll)

@router.get("/cut-rolls/", response_model=List[schemas.CutRoll])
def read_cut_rolls(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_cut_rolls(db=db, skip=skip, limit=limit)

@router.post("/cutting-plans/{plan_id}/execute")
async def execute_cutting_plan(
    plan_id: UUID,
    db: Session = Depends(get_db)
):
    """Execute a cutting plan and create the actual cut rolls"""
    cutting_plan = db.query(models.CuttingPlan).filter(
        models.CuttingPlan.id == plan_id
    ).first()
    
    if not cutting_plan:
        raise HTTPException(status_code=404, detail="Cutting plan not found")
    
    if cutting_plan.status != models.CuttingPlanStatus.PLANNED:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot execute plan with status: {cutting_plan.status}"
        )
    
    try:
        # Update plan status
        cutting_plan.status = models.CuttingPlanStatus.IN_PROGRESS
        db.add(cutting_plan)
        
        # Create cut rolls from the plan
        cut_rolls_created = []
        for roll_spec in cutting_plan.cut_pattern:
            cut_roll = models.CutRoll(
                jumbo_roll_id=cutting_plan.jumbo_roll_id,
                width_inches=roll_spec['width'],
                gsm=roll_spec['gsm'],
                bf=roll_spec['bf'],
                shade=roll_spec['shade'],
                qr_code=crud.generate_qr_code(uuid.uuid4()),
                status="cut",
                order_id=cutting_plan.order_id
            )
            db.add(cut_roll)
            cut_rolls_created.append(cut_roll)
            
            # Create inventory item
            inventory_item = models.InventoryItem(
                roll_id=cut_roll.id,
                allocated_to_order_id=cutting_plan.order_id
            )
            db.add(inventory_item)
        
        # Update jumbo roll status
        jumbo_roll = cutting_plan.jumbo_roll
        jumbo_roll.status = models.JumboRollStatus.USED
        
        # Update cutting plan status
        cutting_plan.status = models.CuttingPlanStatus.COMPLETED
        cutting_plan.completed_at = datetime.utcnow()
        
        # Update order fulfillment
        order = cutting_plan.order
        order.quantity_fulfilled += len(cut_rolls_created)
        if order.quantity_fulfilled >= order.quantity_rolls:
            order.status = models.OrderStatus.COMPLETED
        else:
            order.status = models.OrderStatus.PARTIALLY_FULFILLED
        
        db.commit()
        
        return {
            "message": "Cutting plan executed successfully",
            "cutting_plan_id": str(cutting_plan.id),
            "cut_rolls_created": len(cut_rolls_created),
            "order_status": order.status
        }
        
    except Exception as e:
        db.rollback()
        cutting_plan.status = models.CuttingPlanStatus.FAILED
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cutting-plans")
async def get_cutting_plans(
    status: Optional[str] = None,
    order_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get cutting plans with optional filters"""
    query = db.query(models.CuttingPlan)
    
    if status:
        query = query.filter(models.CuttingPlan.status == status)
    if order_id:
        query = query.filter(models.CuttingPlan.order_id == order_id)
    
    return query.order_by(models.CuttingPlan.id).offset(skip).limit(limit).all()

# Workflow Management Endpoints
@router.post("/workflow/process-orders")
async def process_multiple_orders(
    order_ids: List[UUID],
    db: Session = Depends(get_db)
):
    """
    Process multiple orders together for optimal cutting plans.
    This is the main workflow entry point for batch processing.
    """
    from .services.workflow_manager import WorkflowManager
    
    workflow_manager = WorkflowManager(db)
    result = workflow_manager.process_multiple_orders(order_ids)
    
    return result

@router.get("/workflow/status")
async def get_workflow_status(db: Session = Depends(get_db)):
    """Get overall workflow status and recommendations"""
    from .services.workflow_manager import WorkflowManager
    
    workflow_manager = WorkflowManager(db)
    status = workflow_manager.get_workflow_status()
    
    return status

@router.get("/dashboard/metrics")
async def get_dashboard_metrics(db: Session = Depends(get_db)):
    """Get key metrics for the dashboard"""
    
    # Order metrics
    total_orders = db.query(models.Order).count()
    pending_orders = db.query(models.Order).filter(
        models.Order.status == models.OrderStatus.PENDING
    ).count()
    completed_orders = db.query(models.Order).filter(
        models.Order.status == models.OrderStatus.COMPLETED
    ).count()
    
    # Inventory metrics
    available_jumbos = db.query(models.JumboRoll).filter(
        models.JumboRoll.status == models.JumboRollStatus.AVAILABLE
    ).count()
    
    total_cut_rolls = db.query(models.CutRoll).count()
    available_cut_rolls = db.query(models.CutRoll).filter(
        models.CutRoll.status == "available"
    ).count()
    
    # Production metrics
    pending_production = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.status == models.ProductionOrderStatus.PENDING
    ).count()
    
    # Cutting plan metrics
    planned_cuts = db.query(models.CuttingPlan).filter(
        models.CuttingPlan.status == models.CuttingPlanStatus.PLANNED
    ).count()
    
    return {
        "orders": {
            "total": total_orders,
            "pending": pending_orders,
            "completed": completed_orders,
            "completion_rate": round((completed_orders / total_orders * 100) if total_orders > 0 else 0, 1)
        },
        "inventory": {
            "jumbo_rolls_available": available_jumbos,
            "cut_rolls_total": total_cut_rolls,
            "cut_rolls_available": available_cut_rolls
        },
        "production": {
            "pending_orders": pending_production
        },
        "cutting": {
            "plans_ready": planned_cuts
        }
    }

@router.get("/orders/consolidation-opportunities")
async def get_consolidation_opportunities(db: Session = Depends(get_db)):
    """
    Get pending orders that can be consolidated for better optimization.
    Groups orders by specifications to show batching opportunities.
    """
    from sqlalchemy import func
    
    # Get pending orders grouped by specifications
    pending_orders = db.query(
        models.Order.gsm,
        models.Order.shade,
        models.Order.bf,
        func.count(models.Order.id).label('order_count'),
        func.sum(models.Order.quantity_rolls - models.Order.quantity_fulfilled).label('total_quantity')
    ).filter(
        models.Order.status.in_([models.OrderStatus.PENDING, models.OrderStatus.PARTIALLY_FULFILLED]),
        models.Order.quantity_rolls > models.Order.quantity_fulfilled
    ).group_by(
        models.Order.gsm,
        models.Order.shade,
        models.Order.bf
    ).having(
        func.count(models.Order.id) > 1  # Only show groups with multiple orders
    ).all()
    
    consolidation_opportunities = []
    for group in pending_orders:
        # Get the actual orders in this group
        orders_in_group = db.query(models.Order).filter(
            models.Order.gsm == group.gsm,
            models.Order.shade == group.shade,
            models.Order.bf == group.bf,
            models.Order.status.in_([models.OrderStatus.PENDING, models.OrderStatus.PARTIALLY_FULFILLED]),
            models.Order.quantity_rolls > models.Order.quantity_fulfilled
        ).all()
        
        consolidation_opportunities.append({
            "specification": {
                "gsm": group.gsm,
                "shade": group.shade,
                "bf": float(group.bf)
            },
            "order_count": group.order_count,
            "total_quantity": int(group.total_quantity),
            "order_ids": [str(order.id) for order in orders_in_group],
            "potential_savings": "High" if group.total_quantity > 10 else "Medium" if group.total_quantity > 5 else "Low"
        })
    
    return {
        "consolidation_opportunities": consolidation_opportunities,
        "total_groups": len(consolidation_opportunities),
        "recommendation": "Process these groups together for optimal cutting plans and minimal waste"
    }

@router.post("/orders/consolidate-and-process")
async def consolidate_and_process_orders(
    specification: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Consolidate and process all pending orders with the given specification.
    """
    # Find all matching pending orders
    matching_orders = db.query(models.Order).filter(
        models.Order.gsm == specification.get('gsm'),
        models.Order.shade == specification.get('shade'),
        models.Order.bf == specification.get('bf'),
        models.Order.status.in_([models.OrderStatus.PENDING, models.OrderStatus.PARTIALLY_FULFILLED]),
        models.Order.quantity_rolls > models.Order.quantity_fulfilled
    ).all()
    
    if not matching_orders:
        raise HTTPException(
            status_code=404,
            detail="No matching pending orders found for the given specification"
        )
    
    # Process them together
    from .services.workflow_manager import WorkflowManager
    workflow_manager = WorkflowManager(db)
    
    order_ids = [order.id for order in matching_orders]
    result = workflow_manager.process_multiple_orders(order_ids)
    
    return {
        "message": f"Consolidated and processed {len(matching_orders)} orders",
        "specification": specification,
        "orders_processed": len(matching_orders),
        "result": result
    }

# Pending Order Management Endpoints
@router.get("/pending-items")
async def get_pending_items(
    status: Optional[str] = "pending",
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get pending order items with optional status filter."""
    query = db.query(models.PendingOrderItem)
    
    if status:
        query = query.filter(models.PendingOrderItem.status == status)
    
    items = query.order_by(models.PendingOrderItem.id).offset(skip).limit(limit).all()
    
    return {
        "pending_items": [
            {
                "id": str(item.id),
                "original_order_id": str(item.original_order_id),
                "specification": {
                    "width": item.width_inches,
                    "gsm": item.gsm,
                    "bf": float(item.bf),
                    "shade": item.shade
                },
                "quantity_pending": item.quantity_pending,
                "reason": item.reason,
                "status": item.status,
                "created_at": item.created_at,
                "production_order_id": str(item.production_order_id) if item.production_order_id else None
            }
            for item in items
        ],
        "total_count": len(items)
    }

@router.get("/pending-items/consolidation-opportunities")
async def get_pending_consolidation_opportunities(db: Session = Depends(get_db)):
    """Get pending items grouped by specification for consolidation."""
    from .services.pending_order_service import PendingOrderService
    
    pending_service = PendingOrderService(db)
    opportunities = pending_service.get_consolidation_opportunities()
    
    return {
        "consolidation_opportunities": opportunities,
        "total_opportunities": len(opportunities),
        "recommendation": "Create production orders for these specifications to resolve pending items"
    }

@router.get("/pending-items/summary")
async def get_pending_items_summary(db: Session = Depends(get_db)):
    """Get summary statistics for pending items."""
    from .services.pending_order_service import PendingOrderService
    
    pending_service = PendingOrderService(db)
    summary = pending_service.get_pending_summary()
    
    return summary

@router.post("/pending-items/{pending_item_id}/resolve")
async def resolve_pending_item(
    pending_item_id: UUID,
    jumbo_roll_id: UUID,
    db: Session = Depends(get_db)
):
    """Resolve a pending item when a suitable jumbo roll becomes available."""
    from .services.pending_order_service import PendingOrderService
    
    # Get the pending item
    pending_item = db.query(models.PendingOrderItem).filter(
        models.PendingOrderItem.id == pending_item_id
    ).first()
    
    if not pending_item:
        raise HTTPException(status_code=404, detail="Pending item not found")
    
    if pending_item.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resolve item with status: {pending_item.status}"
        )
    
    # Verify jumbo roll exists and matches specification
    jumbo_roll = db.query(models.JumboRoll).filter(
        models.JumboRoll.id == jumbo_roll_id,
        models.JumboRoll.gsm == pending_item.gsm,
        models.JumboRoll.shade == pending_item.shade,
        models.JumboRoll.bf == pending_item.bf,
        models.JumboRoll.status == models.JumboRollStatus.AVAILABLE
    ).first()
    
    if not jumbo_roll:
        raise HTTPException(
            status_code=400,
            detail="Jumbo roll not found or doesn't match pending item specification"
        )
    
    # Resolve the pending item
    pending_service = PendingOrderService(db)
    specification = {
        "gsm": pending_item.gsm,
        "shade": pending_item.shade,
        "bf": float(pending_item.bf)
    }
    
    resolved_items = pending_service.resolve_pending_items(specification, jumbo_roll_id)
    
    return {
        "message": f"Resolved {len(resolved_items)} pending items",
        "resolved_items": [str(item.id) for item in resolved_items],
        "jumbo_roll_id": str(jumbo_roll_id)
    }

@router.delete("/pending-items/cleanup")
async def cleanup_resolved_pending_items(
    days_old: int = 30,
    db: Session = Depends(get_db)
):
    """Clean up resolved pending items older than specified days."""
    from .services.pending_order_service import PendingOrderService
    
    pending_service = PendingOrderService(db)
    cleaned_count = pending_service.cleanup_resolved_items(days_old)
    
    return {
        "message": f"Cleaned up {cleaned_count} resolved pending items",
        "days_old": days_old
    }

# Database status endpoint
@router.get("/status/")
def check_db_status(db: Session = Depends(get_db)):
    try:
        # Try to execute a simple query that works with MSSQL
        result = db.execute("SELECT 1 as test_value").fetchone()
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat(),
            "test_query_result": result[0] if result else None
        }
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }