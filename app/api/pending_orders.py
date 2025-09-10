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
    limit: int = 1000,
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

@router.post("/pending-orders/start-production", response_model=schemas.StartProductionResponse, tags=["Pending Order Items"])
def start_production_from_pending_orders(
    request_data: Dict[str, Any],  # Accept raw data to debug validation issues
    db: Session = Depends(get_db)
):
    """Start production from selected pending orders - same format as main planning"""
    try:
        # Debug: Log the incoming request data structure
        logger.info(f"🔍 RAW REQUEST DATA KEYS: {list(request_data.keys())}")
        logger.info(f"🔍 SELECTED CUT ROLLS COUNT: {len(request_data.get('selected_cut_rolls', []))}")
        
        if 'selected_cut_rolls' in request_data and len(request_data['selected_cut_rolls']) > 0:
            sample_roll = request_data['selected_cut_rolls'][0]
            logger.info(f"🔍 SAMPLE CUT ROLL KEYS: {list(sample_roll.keys())}")
            logger.info(f"🔍 SAMPLE VALUES: paper_id={sample_roll.get('paper_id')}, created_by_id={request_data.get('created_by_id')}")
        
        # Try to validate against schema and catch detailed errors
        try:
            validated_data = schemas.StartProductionRequest(**request_data)
            logger.info("✅ VALIDATION PASSED")
        except Exception as validation_error:
            logger.error(f"❌ VALIDATION ERROR: {str(validation_error)}")
            raise HTTPException(status_code=422, detail=f"Validation error: {str(validation_error)}")
        
        from .. import crud_operations
        return crud_operations.start_production_from_pending_orders(db=db, request_data=validated_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting production from pending orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))