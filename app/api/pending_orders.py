from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from uuid import UUID
import logging

from .base import get_db
from .. import crud_operations, schemas
from ..idempotency import check_idempotency, store_idempotency_response

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
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")
):
    """
    Generate roll suggestions for completing target width rolls based on pending orders.
    Takes wastage parameter to calculate dynamic target width (124 - wastage).
    Returns suggestions showing existing width + needed width = target width.
    """
    try:
        # Check for idempotency key
        if x_idempotency_key:
            logger.info(f"🔑 IDEMPOTENCY: Checking key for roll suggestions: {x_idempotency_key}")

            # Check if we've seen this key before
            cached_response = check_idempotency(
                db=db,
                idempotency_key=x_idempotency_key,
                request_path="/pending-order-items/roll-suggestions",
                request_body=request_data
            )

            if cached_response:
                logger.info(f"✅ IDEMPOTENCY: Returning cached suggestions for key: {x_idempotency_key}")
                return cached_response

        wastage = request_data.get('wastage', 0)

        if not isinstance(wastage, (int, float)) or wastage < 0:
            raise HTTPException(
                status_code=400,
                detail="Wastage must be a non-negative number"
            )

        from ..services.pending_optimizer import PendingOptimizer
        optimizer = PendingOptimizer(db=db)
        result = optimizer.get_roll_suggestions(wastage)

        # Store idempotency key with response if provided
        if x_idempotency_key:
            store_idempotency_response(
                db=db,
                idempotency_key=x_idempotency_key,
                request_path="/pending-order-items/roll-suggestions",
                response_body=result,
                request_body=request_data
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating roll suggestions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/pending-orders/start-production", response_model=schemas.StartProductionResponse, tags=["Pending Order Items"])
def start_production_from_pending_orders(
    request_data: Dict[str, Any],  # Accept raw data to debug validation issues
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")
):
    """Start production from selected pending orders - same format as main planning"""
    try:
        # Check for idempotency key
        if x_idempotency_key:
            logger.info(f"🔑 IDEMPOTENCY: Checking key for start production: {x_idempotency_key}")

            # Check if we've seen this key before
            cached_response = check_idempotency(
                db=db,
                idempotency_key=x_idempotency_key,
                request_path="/pending-orders/start-production",
                request_body=request_data
            )

            if cached_response:
                logger.info(f"✅ IDEMPOTENCY: Returning cached production start for key: {x_idempotency_key}")
                return cached_response

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
        result = crud_operations.start_production_from_pending_orders(db=db, request_data=validated_data)

        # Store idempotency key with response if provided
        if x_idempotency_key:
            store_idempotency_response(
                db=db,
                idempotency_key=x_idempotency_key,
                request_path="/pending-orders/start-production",
                response_body=result,
                request_body=request_data
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting production from pending orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PENDING ORDER ALLOCATION MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/pending-order-items/{item_id}", response_model=schemas.PendingOrderItem, tags=["Pending Order Management"])
def get_pending_order_item_details(item_id: UUID, db: Session = Depends(get_db)):
    """Get detailed information about a specific pending order item"""
    try:
        return crud_operations.get_pending_order_item_with_details(db=db, item_id=item_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pending order item details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-order-items/{item_id}/available-orders", tags=["Pending Order Management"])
def get_available_orders_for_allocation(item_id: UUID, db: Session = Depends(get_db)):
    """Get list of available orders that can receive this pending order item allocation"""
    try:
        return crud_operations.get_available_orders_for_pending_allocation(db=db, item_id=item_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting available orders for allocation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/pending-order-items/{item_id}/allocate", tags=["Pending Order Management"])
def allocate_pending_order_to_order(
    item_id: UUID,
    allocation_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Allocate pending order item to a specific order (quantity-wise transfer)"""
    try:
        target_order_id = allocation_data.get("target_order_id")
        quantity_to_transfer = allocation_data.get("quantity_to_transfer")
        created_by_id = allocation_data.get("created_by_id")

        if not target_order_id:
            raise HTTPException(status_code=400, detail="target_order_id is required")
        if not quantity_to_transfer or quantity_to_transfer <= 0:
            raise HTTPException(status_code=400, detail="quantity_to_transfer must be greater than 0")
        if not created_by_id:
            raise HTTPException(status_code=400, detail="created_by_id is required")

        return crud_operations.allocate_pending_order_to_order(
            db=db,
            item_id=item_id,
            target_order_id=target_order_id,
            quantity_to_transfer=quantity_to_transfer,
            created_by_id=created_by_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error allocating pending order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/pending-order-items/{item_id}/transfer", tags=["Pending Order Management"])
def transfer_pending_order_between_orders(
    item_id: UUID,
    transfer_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Transfer pending order item from one order to another (quantity-wise)"""
    try:
        source_order_id = transfer_data.get("source_order_id")
        target_order_id = transfer_data.get("target_order_id")
        quantity_to_transfer = transfer_data.get("quantity_to_transfer")
        created_by_id = transfer_data.get("created_by_id")

        if not source_order_id:
            raise HTTPException(status_code=400, detail="source_order_id is required")
        if not target_order_id:
            raise HTTPException(status_code=400, detail="target_order_id is required")
        if not quantity_to_transfer or quantity_to_transfer <= 0:
            raise HTTPException(status_code=400, detail="quantity_to_transfer must be greater than 0")
        if not created_by_id:
            raise HTTPException(status_code=400, detail="created_by_id is required")

        return crud_operations.transfer_pending_order_between_orders(
            db=db,
            item_id=item_id,
            source_order_id=source_order_id,
            target_order_id=target_order_id,
            quantity_to_transfer=quantity_to_transfer,
            created_by_id=created_by_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transferring pending order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/pending-order-items/{item_id}/cancel", tags=["Pending Order Management"])
def cancel_pending_order_item(
    item_id: UUID,
    cancel_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Cancel/delete a pending order item by setting quantity to 0 and status to cancelled.
    This removes it from pending lists and algorithms without physical deletion.
    """
    try:
        cancelled_by_id = cancel_data.get("cancelled_by_id")

        if not cancelled_by_id:
            raise HTTPException(status_code=400, detail="cancelled_by_id is required")

        return crud_operations.cancel_pending_order_item(
            db=db,
            item_id=item_id,
            cancelled_by_id=cancelled_by_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling pending order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/pending-order-items/client-suggestions", tags=["Pending Order Items"])
def get_client_suggestions_for_manual_cuts(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Get client suggestions for manual cuts based on latest 50 orders.
    Returns clients who frequently order widths that fit the available waste space.
    """
    try:
        available_waste = request_data.get('available_waste', 0)
        paper_specs = request_data.get('paper_specs', {})

        if not isinstance(available_waste, (int, float)) or available_waste <= 0:
            raise HTTPException(
                status_code=400,
                detail="Available waste must be a positive number"
            )

        # Validate paper specs
        required_specs = ['gsm', 'bf', 'shade']
        if not all(spec in paper_specs for spec in required_specs):
            raise HTTPException(
                status_code=400,
                detail=f"Paper specs must include: {', '.join(required_specs)}"
            )

        from sqlalchemy import text
        from datetime import datetime, timedelta

        # Debug logging
        logger.info(f"🔍 Client suggestions request: available_waste={available_waste}, paper_specs={paper_specs}")

        # Query latest 100 orders and find client width patterns (any status)
        query = text("""
            WITH latest_orders AS (
                SELECT TOP 100 o.id
                FROM order_master o
                ORDER BY o.created_at DESC
            )
            SELECT TOP 20
                c.id as client_id,
                c.company_name,
                oi.width_inches,
                COUNT(*) as frequency,
                MAX(o.created_at) as last_ordered
            FROM order_master o
            JOIN order_item oi ON o.id = oi.order_id
            JOIN paper_master p ON oi.paper_id = p.id
            JOIN client_master c ON o.client_id = c.id
            JOIN latest_orders lo ON o.id = lo.id
            WHERE
                oi.width_inches <= :available_waste
                AND p.gsm = :gsm
                AND p.bf = :bf
                AND p.shade = :shade
            GROUP BY c.id, c.company_name, oi.width_inches
            HAVING COUNT(*) >= 1
            ORDER BY frequency DESC, last_ordered DESC
        """)

        result = db.execute(query, {
            'available_waste': available_waste,
            'gsm': paper_specs['gsm'],
            'bf': paper_specs['bf'],
            'shade': paper_specs['shade']
        })

        rows = result.fetchall()

        logger.info(f"🔍 Query returned {len(rows)} rows")
        if rows:
            for row in rows[:3]:  # Log first 3 rows for debugging
                logger.info(f"🔍 Sample row: client={row.company_name}, width={row.width_inches}, frequency={row.frequency}")

        if not rows:
            return {
                "status": "no_suggestions",
                "available_waste": available_waste,
                "paper_specs": paper_specs,
                "suggestions": [],
                "message": f"No recent orders found for {paper_specs['gsm']}GSM {paper_specs['bf']}BF {paper_specs['shade']} with width ≤ {available_waste}\""
            }

        # Group suggestions by client
        suggestions_by_client = {}
        for row in rows:
            client_id = str(row.client_id)
            if client_id not in suggestions_by_client:
                suggestions_by_client[client_id] = {
                    "client_id": client_id,
                    "client_name": row.company_name,
                    "suggested_widths": []
                }

            suggestions_by_client[client_id]["suggested_widths"].append({
                "width": float(row.width_inches),
                "frequency": row.frequency,
                "last_ordered": row.last_ordered.isoformat() if row.last_ordered else None,
                "days_ago": (datetime.now() - row.last_ordered).days if row.last_ordered else None
            })

        # Convert to sorted list
        suggestions = list(suggestions_by_client.values())

        # Sort clients by total frequency and most recent order
        suggestions.sort(key=lambda x: (
            sum(w['frequency'] for w in x['suggested_widths']),
            max(w['last_ordered'] for w in x['suggested_widths'])
        ), reverse=True)

        # Limit to top 10 clients
        suggestions = suggestions[:10]

        return {
            "status": "success",
            "available_waste": available_waste,
            "paper_specs": paper_specs,
            "suggestions": suggestions,
            "summary": {
                "total_clients": len(suggestions),
                "latest_orders_analyzed": 100,
                "total_matches": len(rows)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting client suggestions: {e}")
        raise HTTPException(status_code=500, detail=str(e))