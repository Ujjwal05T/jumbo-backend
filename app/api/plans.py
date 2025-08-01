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
# PLAN MASTER ENDPOINTS
# ============================================================================

@router.post("/plans", response_model=schemas.PlanMaster, tags=["Plan Master"])
def create_plan(plan: schemas.PlanMasterCreate, db: Session = Depends(get_db)):
    """Create a new cutting plan"""
    try:
        return crud_operations.create_plan(db=db, plan_data=plan)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating plan: {e}")
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
    """Get cutting plan by ID"""
    plan = crud_operations.get_plan(db=db, plan_id=plan_id)
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

@router.post("/plans/{plan_id}/start-production", response_model=schemas.StartProductionResponse, tags=["Plan Management"])
def start_production(
    plan_id: str,
    request_data: schemas.StartProductionRequest,
    db: Session = Depends(get_db)
):
    """Start production for a plan - NEW FLOW"""
    try:
        import uuid
        from datetime import datetime
        
        plan_uuid = uuid.UUID(plan_id)
        result = crud_operations.start_production_for_plan(db=db, plan_id=plan_uuid, request_data=request_data.model_dump())
        
        return result
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except Exception as e:
        logger.error(f"Error starting production: {e}")
        raise HTTPException(status_code=500, detail=str(e))