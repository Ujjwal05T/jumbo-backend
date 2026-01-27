from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from uuid import UUID
import logging
import json

from .base import get_db
from .. import crud_operations, schemas
from ..idempotency import check_idempotency, store_idempotency_response

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# PLAN MASTER ENDPOINTS
# ============================================================================

@router.post("/plans", response_model=schemas.PlanMaster, tags=["Plan Master"])
def create_plan(
    request: Request,
    plan: schemas.PlanMasterCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")
):
    """Create a new cutting plan with idempotency support"""
    try:
        logger.info(f"API DEBUG: Plan creation request received for plan '{plan.name}' with {len(plan.pending_orders) if hasattr(plan, 'pending_orders') and plan.pending_orders else 0} pending orders")

        # Check for idempotency key
        if x_idempotency_key:
            logger.info(f"🔑 IDEMPOTENCY: Checking key: {x_idempotency_key}")

            # Check if we've seen this key before
            cached_response = check_idempotency(
                db=db,
                idempotency_key=x_idempotency_key,
                request_path="/plans",
                request_body=plan.model_dump() if hasattr(plan, 'model_dump') else plan.dict()
            )

            if cached_response:
                logger.info(f"✅ IDEMPOTENCY: Returning cached response for key: {x_idempotency_key}")
                return cached_response

        # Create the plan
        result = crud_operations.create_plan(db=db, plan_data=plan)

        # Store idempotency key with response if provided
        if x_idempotency_key:
            store_idempotency_response(
                db=db,
                idempotency_key=x_idempotency_key,
                request_path="/plans",
                response_body=result,
                request_body=plan.model_dump() if hasattr(plan, 'model_dump') else plan.dict()
            )

        return result

    except RequestValidationError as e:
        logger.error(f"❌ PLAN CREATE: Validation error: {e}")
        raise HTTPException(status_code=422, detail=f"Validation error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ PLAN CREATE: Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/plans", response_model=List[schemas.PlanMaster], tags=["Plan Master"])
def get_plans(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    client_id: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db)
):
    """Get all cutting plans with pagination and enhanced filtering"""
    try:
        from datetime import datetime
        from .. import models
        from sqlalchemy.orm import joinedload
        
        # Start with base query that includes user relationship
        query = db.query(models.PlanMaster).options(
            joinedload(models.PlanMaster.created_by)
        )
        
        # Apply status filter
        if status and status != "all":
            query = query.filter(models.PlanMaster.status == status)
        
        # Apply client filter
        if client_id and client_id != "all":
            # Join with plan_order_link to get orders, then filter by client
            query = query.join(models.PlanOrderLink).join(models.OrderMaster).filter(
                models.OrderMaster.client_id == client_id
            )
        
        # Apply date filters
        if date_from:
            try:
                date_from_obj = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                query = query.filter(models.PlanMaster.created_at >= date_from_obj)
            except ValueError:
                pass
        
        if date_to:
            try:
                date_to_obj = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                query = query.filter(models.PlanMaster.created_at <= date_to_obj)
            except ValueError:
                pass
        
        # Apply pagination and ordering
        plans = query.order_by(models.PlanMaster.created_at.desc()).offset(skip).limit(limit).all()
        
        return plans
    except Exception as e:
        logger.error(f"Error getting plans: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/plans/{plan_id}", response_model=schemas.PlanMaster, tags=["Plan Master"])
def get_plan(plan_id: UUID, db: Session = Depends(get_db)):
    """Get cutting plan by ID (optimized - only loads creator user)
    
    This endpoint is optimized for the plan details view by only loading
    the plan creator relationship, significantly reducing database load and data transfer.
    For operations that need full relationships (orders, inventory), use include_relationships=True.
    """
    # Use optimized version (include_relationships=False) for plan details API
    plan = crud_operations.get_plan(db=db, plan_id=plan_id, include_relationships=False)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan

@router.put("/plans/{plan_id}", response_model=schemas.PlanMaster, tags=["Plan Master"])
def update_plan(
    plan_id: UUID,
    plan_update: schemas.PlanMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update cutting plan"""
    try:
        plan = crud_operations.update_plan(db=db, plan_id=plan_id, plan_update=plan_update)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PLAN MANAGEMENT ENDPOINTS
# ============================================================================

@router.put("/plans/{plan_id}/status", response_model=schemas.PlanMaster, tags=["Plan Management"])
def update_plan_status(
    plan_id: str,
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Update plan status"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        new_status = request_data.get("status")
        
        updated_plan = crud_operations.update_plan_status(db=db, plan_id=plan_uuid, new_status=new_status)
        if not updated_plan:
            raise HTTPException(status_code=404, detail="Plan not found")
            
        return updated_plan
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except Exception as e:
        logger.error(f"Error updating plan status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/{plan_id}/execute", response_model=schemas.PlanMaster, tags=["Plan Management"])
def execute_cutting_plan(
    plan_id: str,
    db: Session = Depends(get_db)
):
    """Execute a cutting plan"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        
        executed_plan = crud_operations.execute_plan(db=db, plan_id=plan_uuid)
        if not executed_plan:
            raise HTTPException(status_code=404, detail="Plan not found")
            
        return executed_plan
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except Exception as e:
        logger.error(f"Error executing plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/{plan_id}/complete", response_model=schemas.PlanMaster, tags=["Plan Management"])
def complete_cutting_plan(
    plan_id: str,
    db: Session = Depends(get_db)
):
    """Mark cutting plan as completed"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        
        completed_plan = crud_operations.complete_plan(db=db, plan_id=plan_uuid)
        if not completed_plan:
            raise HTTPException(status_code=404, detail="Plan not found")
            
        return completed_plan
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except Exception as e:
        logger.error(f"Error completing plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/{plan_id}/start-production-with-backup", response_model=schemas.StartProductionResponse, tags=["Plan Management"])
def start_production_with_backup(
    plan_id: str,
    request_data: schemas.StartProductionRequest,
    db: Session = Depends(get_db)
):
    """Start production with automatic snapshot creation for rollback capability"""
    try:
        import uuid
        from datetime import datetime

        logger.info(f"🚀 Starting production with backup for plan {plan_id}")
        logger.info(f"   - User ID: {request_data.created_by_id}")
        logger.info(f"   - Request data keys: {list(request_data.model_dump().keys())}")

        plan_uuid = uuid.UUID(plan_id)

        # Create snapshot before execution
        snapshot = None
        try:
            logger.info(f"📸 Attempting to create snapshot for plan {plan_uuid}")
            snapshot = crud_operations.create_snapshot_for_plan(
                db=db,
                plan_id=plan_uuid,
                user_id=request_data.created_by_id
            )
            if snapshot:
                logger.info(f"✅ Created backup snapshot for plan {plan_id}")
                logger.info(f"   - Snapshot ID: {snapshot.id}")
                logger.info(f"   - Valid until: {snapshot.expires_at}")
            else:
                logger.warning(f"⚠️ Snapshot creation returned None for plan {plan_id}")
        except Exception as e:
            logger.error(f"❌ Failed to create snapshot for plan {plan_id}: {e}")
            logger.error(f"   - Exception type: {type(e).__name__}")
            logger.error(f"   - Exception message: {str(e)}")
            import traceback
            logger.error(f"   - Traceback: {traceback.format_exc()}")
            # Continue with production even if snapshot fails
            # But don't allow rollback later

        # Execute original production logic unchanged
        logger.info(f"🏭 Starting production execution for plan {plan_uuid}")
        result = crud_operations.start_production_for_plan(
            db=db,
            plan_id=plan_uuid,
            request_data=request_data.model_dump()
        )
        logger.info(f"✅ Production execution completed for plan {plan_id}")

        # Add rollback info to response
        minutes_remaining = 0
        if snapshot:
            minutes_remaining = int((snapshot.expires_at - datetime.utcnow()).total_seconds() / 60)
            logger.info(f"⏰ Rollback available for {minutes_remaining} minutes")

        result["rollback_info"] = {
            "rollback_available": snapshot is not None,
            "expires_at": snapshot.expires_at.isoformat() if snapshot else None,
            "minutes_remaining": minutes_remaining
        }

        logger.info(f"📋 Returning response with rollback info: {result['rollback_info']}")
        return result

    except ValueError as e:
        logger.error(f"❌ ValueError in start_production_with_backup: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Error starting production with backup: {e}")
        logger.error(f"   - Exception type: {type(e).__name__}")
        logger.error(f"   - Exception message: {str(e)}")
        import traceback
        logger.error(f"   - Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/{plan_id}/start-production", response_model=schemas.StartProductionResponse, tags=["Plan Management"])
def start_production(
    plan_id: str,
    request_data: schemas.StartProductionRequest,
    db: Session = Depends(get_db)
):
    """Start production for a plan - REDIRECTED TO ROLLBACK-ENABLED ENDPOINT"""
    try:
        import uuid
        from datetime import datetime

        logger.info(f"🔄 REDIRECTING OLD PRODUCTION ENDPOINT TO ROLLBACK-ENABLED VERSION for plan {plan_id}")
        logger.info(f"   - Automatically creating rollback snapshot")

        plan_uuid = uuid.UUID(plan_id)

        # Create snapshot before execution
        snapshot = None
        try:
            logger.info(f"📸 Creating snapshot for plan {plan_uuid}")
            snapshot = crud_operations.create_snapshot_for_plan(
                db=db,
                plan_id=plan_uuid,
                user_id=request_data.created_by_id
            )
            if snapshot:
                logger.info(f"✅ Created backup snapshot for plan {plan_id}")
            else:
                logger.warning(f"⚠️ Snapshot creation returned None for plan {plan_id}")
        except Exception as e:
            logger.error(f"❌ Failed to create snapshot for plan {plan_id}: {e}")

        # Execute production logic
        result = crud_operations.start_production_for_plan(db=db, plan_id=plan_uuid, request_data=request_data.model_dump())

        print(f"API DEBUG: CRUD result keys: {list(result.keys())}")
        print(f"API DEBUG: Has production_hierarchy: {'production_hierarchy' in result}")
        print(f"API DEBUG: Has created_inventory_details: {'created_inventory_details' in result}")

        # Add rollback info to response
        minutes_remaining = 0
        if snapshot:
            minutes_remaining = int((snapshot.expires_at - datetime.utcnow()).total_seconds() / 60)

        result["rollback_info"] = {
            "rollback_available": snapshot is not None,
            "expires_at": snapshot.expires_at.isoformat() if snapshot else None,
            "minutes_remaining": minutes_remaining,
            "note": "Redirected from old endpoint - rollback functionality automatically enabled"
        }

        return result

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except Exception as e:
        logger.error(f"Error starting production: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/plans/{plan_id}/order-items", response_model=List[schemas.PlanOrderItem], tags=["Plan Master"])
def get_plan_order_items(plan_id: UUID, db: Session = Depends(get_db)):
    """Get order items linked to a plan with estimated weights
    
    ⚠️ DEPRECATED: This endpoint is not used by the frontend (verified 0% usage).
    Consider removing in future cleanup to reduce API surface area.
    """
    try:
        from .. import models
        from sqlalchemy.orm import joinedload
        
        # Get the plan
        plan = db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get order items linked to this plan via plan_order_link
        order_items = db.query(models.OrderItem).join(
            models.PlanOrderLink, models.OrderItem.order_id == models.PlanOrderLink.order_id
        ).filter(
            models.PlanOrderLink.plan_id == plan_id
        ).options(
            joinedload(models.OrderItem.paper)
        ).all()
        
        # Calculate estimated weight for each order item
        result = []
        for item in order_items:
            # Get paper specifications
            paper = item.paper
            estimated_weight = item.quantity_rolls * 13 * item.width_inches
            
            result.append({
                "id": item.id,
                "frontend_id": item.frontend_id,
                "order_id": item.order_id,
                "width_inches": float(item.width_inches),
                "quantity_rolls": item.quantity_rolls,
                "estimated_weight_kg": round(estimated_weight, 2),
                "gsm": paper.gsm,
                "bf": float(paper.bf),
                "shade": paper.shade
            })
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plan order items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ROLLBACK ENDPOINTS
# ============================================================================

@router.get("/plans/{plan_id}/rollback-status", tags=["Plan Management"])
def get_rollback_status(
    plan_id: str,
    force: bool = False,
    db: Session = Depends(get_db)
):
    """Check if a plan can be rolled back"""
    try:
        import uuid
        from datetime import datetime
        from .. import models

        logger.info(f"🔍 Checking rollback status for plan {plan_id}, force={force}")

        plan_uuid = uuid.UUID(plan_id)

        # Check if snapshot exists and is valid
        snapshot = crud_operations.get_plan_snapshot(db=db, plan_id=plan_uuid)

        if not snapshot:
            return {
                "rollback_available": False,
                "reason": "No backup snapshot found",
                "suggestion": "Plan may be older than 10 minutes or backup was not created"
            }

        # Calculate remaining time
        remaining_minutes = int((snapshot.expires_at - datetime.utcnow()).total_seconds() / 60)

        # Validate safety (unless forced)
        safety_check = crud_operations.validate_rollback_safety(db=db, plan_id=plan_uuid)

        # Override safety check if forced
        if force:
            logger.warning(f"⚠️ FORCED ROLLBACK: Bypassing safety checks for plan {plan_id}")
            safety_check["safe"] = True
            safety_check["reason"] = "Safety checks bypassed (forced rollback)"
            safety_check["forced"] = True

        # Get plan status
        plan = db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_uuid).first()

        response = {
            "rollback_available": safety_check["safe"],
            "expires_at": snapshot.expires_at.isoformat(),
            "remaining_minutes": max(0, remaining_minutes),
            "created_at": snapshot.created_at.isoformat(),
            "safety_check": safety_check,
            "plan_status": plan.status if plan else None,
            "plan_name": plan.name if plan else None,
            "force_mode": force
        }

        logger.info(f"📊 Rollback status response: rollback_available={response['rollback_available']}, force={force}")
        return response

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error checking rollback status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/{plan_id}/rollback", response_model=dict, tags=["Plan Management"])
def rollback_plan(
    plan_id: str,
    request_data: dict = {"user_id": str},
    db: Session = Depends(get_db)
):
    """Rollback a plan execution"""
    try:
        import uuid

        plan_uuid = uuid.UUID(plan_id)
        user_uuid = uuid.UUID(request_data.get("user_id"))

        # Pre-flight safety check
        safety_check = crud_operations.validate_rollback_safety(db=db, plan_id=plan_uuid)
        if not safety_check["safe"]:
            raise HTTPException(
                status_code=400,
                detail=f"Rollback not safe: {safety_check['reason']}"
            )

        # Execute rollback
        result = crud_operations.execute_plan_rollback(
            db=db,
            plan_id=plan_uuid,
            user_id=user_uuid
        )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rolling back plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cleanup-expired-snapshots", tags=["System Maintenance"])
def cleanup_expired_snapshots_endpoint(
    db: Session = Depends(get_db)
):
    """Clean up expired snapshots (call this periodically)"""
    try:
        count = crud_operations.cleanup_expired_snapshots(db=db)
        return {
            "success": True,
            "cleaned_snapshots": count,
            "message": f"Cleaned up {count} expired snapshots"
        }
    except Exception as e:
        logger.error(f"Error cleaning up snapshots: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# MANUAL PLANNING ENDPOINTS
# ============================================================================

@router.post("/plans/manual/create", tags=["Manual Planning"])
def create_manual_plan(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Create a manual plan with inventory hierarchy.

    Expected request_data structure:
    {
        "wastage": 1,
        "planning_width": 123,
        "created_by_id": "uuid",
        "paper_specs": [
            {
                "gsm": 120,
                "bf": 90,
                "shade": "White",
                "jumbo_rolls": [
                    {
                        "jumbo_number": 1,
                        "roll_sets": [
                            {
                                "set_number": 1,
                                "cut_rolls": [
                                    {
                                        "width_inches": 72,
                                        "quantity": 2,
                                        "client_name": "Client A",
                                        "order_source": "Manual"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
    """
    try:
        logger.info("🔧 MANUAL PLAN API: Received manual plan creation request")
        logger.info(f"   - Wastage: {request_data.get('wastage')}")
        logger.info(f"   - Paper specs count: {len(request_data.get('paper_specs', []))}")

        result = crud_operations.create_manual_plan_with_inventory(
            db=db,
            manual_plan_data=request_data
        )

        logger.info(f"✅ MANUAL PLAN API: Successfully created manual plan {result.get('plan_frontend_id')}")
        return result

    except Exception as e:
        logger.error(f"❌ MANUAL PLAN API: Error creating manual plan: {e}")
        import traceback
        logger.error(f"   - Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))