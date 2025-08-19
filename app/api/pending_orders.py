from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from uuid import UUID
import logging

from .base import get_db
from .. import crud_operations, schemas

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# PENDING ORDER ITEMS ENDPOINTS
# ============================================================================

@router.post("/pending-order-items", response_model=schemas.PendingOrderItem, tags=["Pending Order Items"])
def create_pending_order_item(pending: schemas.PendingOrderItemCreate, db: Session = Depends(get_db)):
    """Create a new pending order item"""
    try:
        return crud_operations.create_pending_order_item(db=db, pending_data=pending)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating pending order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-order-items", response_model=List[schemas.PendingOrderItem], tags=["Pending Order Items"])
def get_pending_order_items(
    skip: int = 0,
    limit: int = 100,
    status: str = "pending",
    db: Session = Depends(get_db)
):
    """Get all pending order items with pagination and status filter"""
    try:
        return crud_operations.get_pending_order_items(db=db, skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting pending order items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-order-items/summary", tags=["Pending Order Items"])
def get_pending_items_summary(db: Session = Depends(get_db)):
    """Get summary statistics for pending order items"""
    try:
        return crud_operations.get_pending_items_summary(db=db)
    except Exception as e:
        logger.error(f"Error getting pending items summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-order-items/debug", tags=["Pending Order Items"])
def debug_pending_items(db: Session = Depends(get_db)):
    """Debug endpoint to check pending items data"""
    try:
        return crud_operations.debug_pending_items(db=db)
    except Exception as e:
        logger.error(f"Error in pending items debug: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-order-items/consolidation", tags=["Pending Order Items"])
def get_consolidation_opportunities(db: Session = Depends(get_db)):
    """Get consolidation opportunities for pending items"""
    try:
        return crud_operations.get_consolidation_opportunities(db=db)
    except Exception as e:
        logger.error(f"Error getting consolidation opportunities: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/pending-order-items/roll-suggestions", tags=["Pending Order Items"])
def get_roll_suggestions(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Generate roll suggestions for completing target width rolls based on pending orders.
    Takes wastage parameter to calculate dynamic target width (119 - wastage).
    Returns suggestions showing existing width + needed width = target width.
    """
    try:
        wastage = request_data.get('wastage', 0)
        
        if not isinstance(wastage, (int, float)) or wastage < 0:
            raise HTTPException(
                status_code=400,
                detail="Wastage must be a non-negative number"
            )
        
        from ..services.pending_optimizer import PendingOptimizer
        optimizer = PendingOptimizer(db=db)
        return optimizer.get_roll_suggestions(wastage)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating roll suggestions: {e}")
        raise HTTPException(status_code=500, detail=str(e))