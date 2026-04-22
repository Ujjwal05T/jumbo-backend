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
        else:
            # By default, exclude deleted plans unless explicitly requested
            query = query.filter(models.PlanMaster.status != "deleted")
        
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

@router.get("/plans/summary-list", tags=["Plan Master"])
def get_plans_summary_list(
    status: str = None,
    db: Session = Depends(get_db)
):
    """Get all plans with completeness status for the plan dashboard dropdown.
    A plan is 'complete' when all its cut rolls have status available or used (weight updated).
    """
    try:
        from .. import models

        query = db.query(models.PlanMaster)
        if status and status != "all":
            query = query.filter(models.PlanMaster.status == status)
        else:
            query = query.filter(models.PlanMaster.status != "deleted")

        plans = query.order_by(models.PlanMaster.created_at.desc()).all()

        result = []
        for plan in plans:
            cut_rolls = db.query(models.InventoryMaster).join(
                models.PlanInventoryLink,
                models.InventoryMaster.id == models.PlanInventoryLink.inventory_id
            ).filter(
                models.PlanInventoryLink.plan_id == plan.id,
                models.InventoryMaster.roll_type == "cut",
                models.InventoryMaster.is_wastage_roll == False
            ).all()

            total = len(cut_rolls)
            weight_updated = sum(1 for r in cut_rolls if float(r.weight_kg) > 1)
            is_complete = total > 0 and weight_updated == total

            result.append({
                "id": str(plan.id),
                "frontend_id": plan.frontend_id,
                "name": plan.name,
                "status": plan.status,
                "created_at": plan.created_at.isoformat(),
                "total_rolls": total,
                "weight_updated_rolls": weight_updated,
                "is_complete": is_complete,
            })

        return result
    except Exception as e:
        logger.error(f"Error getting plans summary list: {e}")
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

@router.get("/plans/{plan_id}/dashboard", tags=["Plan Master"])
def get_plan_dashboard(plan_id: UUID, db: Session = Depends(get_db)):
    """Get plan dashboard: per-roll stats grouped by jumbo, with completeness flags.
    Status mapping:
      available  -> Stock (weight updated)
      cutting    -> Planned (not yet weight updated)
      used       -> Billed (weight updated)
      allocated  -> Allocated
      damaged    -> Damaged
    """
    try:
        from .. import models
        from sqlalchemy.orm import joinedload

        plan = db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        # Load all non-wastage cut rolls for this plan with relationships
        cut_rolls = db.query(models.InventoryMaster).join(
            models.PlanInventoryLink,
            models.InventoryMaster.id == models.PlanInventoryLink.inventory_id
        ).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.allocated_order)
                .joinedload(models.OrderMaster.client),
            joinedload(models.InventoryMaster.manual_client),
            joinedload(models.InventoryMaster.parent_118_roll)
                .joinedload(models.InventoryMaster.parent_jumbo)
        ).filter(
            models.PlanInventoryLink.plan_id == plan_id,
            models.InventoryMaster.roll_type == "cut",
            models.InventoryMaster.is_wastage_roll == False
        ).all()

        # Status counts
        total = len(cut_rolls)
        planned_count    = sum(1 for r in cut_rolls if r.status == "cutting")
        stock_count      = sum(1 for r in cut_rolls if r.status == "available")
        dispatched_count = sum(1 for r in cut_rolls if r.status == "used")
        billed_count     = sum(1 for r in cut_rolls if r.status == "billed")
        allocated_count  = sum(1 for r in cut_rolls if r.status == "allocated")
        damaged_count    = sum(1 for r in cut_rolls if r.status == "damaged")
        removed_count    = sum(1 for r in cut_rolls if r.status == "REMOVED_BY_ABHISHEK_SIR")
        weight_updated_count = stock_count + dispatched_count + billed_count + removed_count
        is_complete = total > 0 and weight_updated_count == total

        # Weight totals
        total_weight      = sum(float(r.weight_kg) for r in cut_rolls)
        stock_kg          = sum(float(r.weight_kg) for r in cut_rolls if r.status == "available")
        dispatched_kg     = sum(float(r.weight_kg) for r in cut_rolls if r.status == "used")
        billed_kg         = sum(float(r.weight_kg) for r in cut_rolls if r.status == "billed")
        planned_kg        = sum(float(r.weight_kg) for r in cut_rolls if r.status == "cutting")
        weight_updated_kg = stock_kg + dispatched_kg + billed_kg

        # Group by jumbo roll
        jumbo_groups: Dict[str, Any] = {}
        ungrouped = []

        for roll in cut_rolls:
            jumbo_id = None
            jumbo_barcode = None
            if roll.parent_118_roll and roll.parent_118_roll.parent_jumbo:
                j = roll.parent_118_roll.parent_jumbo
                jumbo_id = str(j.id)
                jumbo_barcode = j.barcode_id or f"JR_{str(j.id)[:5].upper()}"

            client_name = None
            order_frontend_id = None
            if roll.allocated_order:
                order_frontend_id = roll.allocated_order.frontend_id
                if roll.allocated_order.client:
                    client_name = roll.allocated_order.client.company_name
            if not client_name and roll.manual_client:
                client_name = roll.manual_client.company_name

            roll_data = {
                "id": str(roll.id),
                "barcode_id": roll.barcode_id or f"CR_{str(roll.id)[:5].upper()}",
                "width_inches": float(roll.width_inches),
                "weight_kg": float(roll.weight_kg),
                "status": roll.status,
                "client_name": client_name or "Unknown",
                "order_frontend_id": order_frontend_id,
                "paper_specs": {
                    "gsm": roll.paper.gsm if roll.paper else 0,
                    "bf": float(roll.paper.bf) if roll.paper else 0,
                    "shade": roll.paper.shade if roll.paper else "",
                } if roll.paper else None,
                "is_weight_updated": float(roll.weight_kg) > 2 or roll.status == "REMOVED_BY_ABHISHEK_SIR",
                "set_barcode": roll.parent_118_roll.barcode_id if roll.parent_118_roll else None,
            }

            if jumbo_id:
                if jumbo_id not in jumbo_groups:
                    j_roll = roll.parent_118_roll.parent_jumbo
                    jumbo_groups[jumbo_id] = {
                        "jumbo_barcode": jumbo_barcode,
                        "jumbo_weight_kg": float(j_roll.weight_kg) if j_roll.weight_kg else None,
                        "rolls": [],
                    }
                jumbo_groups[jumbo_id]["rolls"].append(roll_data)
            else:
                ungrouped.append(roll_data)

        # Build final list with per-group summaries
        final_groups = []
        for jid, group in jumbo_groups.items():
            rolls = group["rolls"]
            g_wu = sum(1 for r in rolls if r["is_weight_updated"])
            total_cut_weight = sum(r["weight_kg"] for r in rolls if r["weight_kg"] > 1)
            final_groups.append({
                "jumbo_id": jid,
                "jumbo_barcode": group["jumbo_barcode"],
                "jumbo_weight_kg": group.get("jumbo_weight_kg"),
                "rolls": rolls,
                "summary": {
                    "total": len(rolls),
                    "weight_updated": g_wu,
                    "is_complete": len(rolls) > 0 and g_wu == len(rolls),
                    "total_cut_weight_kg": round(total_cut_weight, 2),
                },
            })

        if ungrouped:
            g_wu = sum(1 for r in ungrouped if r["is_weight_updated"])
            final_groups.append({
                "jumbo_id": "ungrouped",
                "jumbo_barcode": "Ungrouped",
                "rolls": ungrouped,
                "summary": {
                    "total": len(ungrouped),
                    "weight_updated": g_wu,
                    "is_complete": len(ungrouped) > 0 and g_wu == len(ungrouped),
                },
            })

        return {
            "plan_id": str(plan.id),
            "plan_frontend_id": plan.frontend_id,
            "plan_name": plan.name,
            "plan_status": plan.status,
            "created_at": plan.created_at.isoformat(),
            "executed_at": plan.executed_at.isoformat() if plan.executed_at else None,
            "is_complete": is_complete,
            "summary": {
                "total_rolls": total,
                "planned": planned_count,
                "stock": stock_count,
                "weight_updated": weight_updated_count,
                "dispatched": dispatched_count,
                "billed": billed_count,
                "allocated": allocated_count,
                "damaged": damaged_count,
                "removed": removed_count,
                "total_weight_kg": round(total_weight, 2),
                "weight_updated_kg": round(weight_updated_kg, 2),
                "dispatched_kg": round(dispatched_kg, 2),
                "billed_kg": round(billed_kg, 2),
                "stock_kg": round(stock_kg, 2),
                "planned_kg": round(planned_kg, 2),
            },
            "jumbo_groups": final_groups,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plan dashboard for {plan_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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

# ============================================================================
# HYBRID PLANNING ENDPOINTS (MUST BE BEFORE PARAMETERIZED ROUTES)
# ============================================================================

@router.post("/plans/hybrid/start-production", tags=["Hybrid Planning"])
def start_hybrid_production(
    request_data: schemas.HybridStartProductionRequest,
    db: Session = Depends(get_db)
):
    """
    Start production from hybrid planning (combines auto-generated and manual rolls).

    This endpoint:
    1. Captures pre-execution state for rollback snapshot
    2. Creates a plan with the hybrid structure
    3. Creates inventory hierarchy (jumbo -> 118" intermediate -> cut rolls)
    4. Links algorithm rolls to original orders
    5. Creates manual rolls without order linkage
    6. Creates pending items from orphaned rolls
    7. Updates order statuses and fulfillment
    8. Creates a rollback snapshot (10-minute window)

    Returns production hierarchy, summary, and rollback_info.
    """
    try:
        from datetime import datetime
        from uuid import UUID as _UUID
        from .. import models

        logger.info("🎯 HYBRID PLAN API: Received hybrid start production request")
        logger.info(f"   - Planning width: {request_data.planning_width}")
        logger.info(f"   - Wastage: {request_data.wastage}")
        logger.info(f"   - Paper specs: {len(request_data.paper_specs)}")
        logger.info(f"   - Order IDs: {len(request_data.order_ids)}")
        logger.info(f"   - Orphaned rolls: {len(request_data.orphaned_rolls)}")

        # ── 1. Capture pre-execution state ─────────────────────────────────
        pre_snapshot_time = datetime.utcnow()

        # Collect every order ID that execution will modify, from three sources:
        #   a) algorithm orders (request_data.order_ids)
        #   b) manual_order cuts — each cut references an existing order whose
        #      quantity_fulfilled / item_status / order.status gets updated
        #      (crud/plans.py create_hybrid_production ~L2173)
        #   c) wastage_allocations — each allocation increments quantity_fulfilled
        #      and sets item_status on the allocated order item
        #      (crud/plans.py create_hybrid_production ~L2526)
        seen_order_ids: set = set()
        all_order_ids_to_capture: list = []

        for oid_str in request_data.order_ids:
            if oid_str and oid_str not in seen_order_ids:
                seen_order_ids.add(oid_str)
                all_order_ids_to_capture.append(oid_str)

        for spec in request_data.paper_specs:
            for jumbo in spec.jumbos:
                for roll_set in jumbo.sets:
                    for cut in roll_set.cuts:
                        if cut.source == "manual_order" and cut.order_id and cut.order_id not in seen_order_ids:
                            seen_order_ids.add(cut.order_id)
                            all_order_ids_to_capture.append(cut.order_id)

        for alloc in request_data.wastage_allocations:
            oid_str = alloc.get("order_id")
            if oid_str and oid_str not in seen_order_ids:
                seen_order_ids.add(oid_str)
                all_order_ids_to_capture.append(oid_str)

        affected_orders = []
        affected_order_items = []

        for oid_str in all_order_ids_to_capture:
            try:
                oid = _UUID(oid_str)
            except ValueError:
                continue
            order = db.query(models.OrderMaster).filter(models.OrderMaster.id == oid).first()
            if not order:
                continue
            affected_orders.append({
                "id": str(order.id),
                "frontend_id": order.frontend_id,
                "status": order.status,
                "created_at": order.created_at.isoformat(),
                "started_production_at": order.started_production_at.isoformat() if order.started_production_at else None,
                "moved_to_warehouse_at": order.moved_to_warehouse_at.isoformat() if order.moved_to_warehouse_at else None,
                "dispatched_at": order.dispatched_at.isoformat() if order.dispatched_at else None,
            })
            for item in order.order_items:
                affected_order_items.append({
                    "id": str(item.id),
                    "frontend_id": item.frontend_id,
                    "order_id": str(item.order_id),
                    "width_inches": float(item.width_inches),
                    "quantity_rolls": item.quantity_rolls,
                    "quantity_fulfilled": item.quantity_fulfilled,
                    "quantity_in_pending": item.quantity_in_pending,
                    "item_status": item.item_status,
                    "created_at": item.created_at.isoformat(),
                })

        # Capture all current pending orders
        affected_pending_orders = []
        all_pending = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem._status == "pending"
        ).all()
        for pending in all_pending:
            affected_pending_orders.append({
                "id": str(pending.id),
                "frontend_id": pending.frontend_id,
                "original_order_id": str(pending.original_order_id),
                "width_inches": float(pending.width_inches),
                "quantity_pending": pending.quantity_pending,
                "quantity_fulfilled": pending.quantity_fulfilled or 0,
                "status": pending._status,
                "reason": pending.reason,
                "created_at": pending.created_at.isoformat(),
            })

        pre_execution_data = {
            "snapshot_time": pre_snapshot_time.isoformat(),
            "affected_orders": affected_orders,
            "affected_order_items": affected_order_items,
            "affected_pending_orders": affected_pending_orders,
            "table_counts": {
                "orders": db.query(models.OrderMaster).count(),
                "order_items": db.query(models.OrderItem).count(),
                "inventory_master": db.query(models.InventoryMaster).count(),
                "pending_order_items": db.query(models.PendingOrderItem).count(),
                "wastage_inventory": db.query(models.WastageInventory).count(),
            },
            # plan_id and plan_details are filled in after execution
        }

        logger.info(f"📸 HYBRID PLAN API: Pre-execution state captured at {pre_snapshot_time}")
        logger.info(f"   - Orders: {len(affected_orders)}, Items: {len(affected_order_items)}, Pending: {len(affected_pending_orders)}")

        # ── 2. Execute hybrid production ────────────────────────────────────
        result = crud_operations.create_hybrid_production(
            db=db,
            hybrid_data=request_data.model_dump()
        )

        logger.info(f"✅ HYBRID PLAN API: Successfully created hybrid production")
        logger.info(f"   - Plan ID: {result.get('plan_frontend_id')}")
        logger.info(f"   - Jumbos created: {result.get('summary', {}).get('jumbos_created', 0)}")
        logger.info(f"   - Cut rolls created: {result.get('summary', {}).get('cut_rolls_created', 0)}")

        # ── 3. Create rollback snapshot using pre-execution data ────────────
        plan_snapshot = None
        try:
            plan_id_str = result.get("plan_id")
            if plan_id_str:
                plan_uuid = _UUID(plan_id_str)

                # Fill in plan details now that we have the plan_id
                pre_execution_data["plan_id"] = str(plan_uuid)
                pre_execution_data["plan_details"] = {
                    "id": str(plan_uuid),
                    "name": result.get("plan_frontend_id", ""),
                    "status": "in_progress",
                    "created_at": pre_snapshot_time.isoformat(),
                }

                plan_snapshot = crud_operations.create_snapshot_for_hybrid_plan(
                    db=db,
                    plan_id=plan_uuid,
                    user_id=_UUID(request_data.created_by_id),
                    pre_execution_data=pre_execution_data,
                )
                logger.info(f"📸 HYBRID PLAN API: Rollback snapshot created, expires {plan_snapshot.expires_at}")
            else:
                logger.warning("⚠️ HYBRID PLAN API: No plan_id in result, cannot create snapshot")
        except Exception as snap_err:
            logger.error(f"❌ HYBRID PLAN API: Failed to create rollback snapshot: {snap_err}")
            # Non-fatal — production succeeded, rollback just won't be available

        # ── 4. Attach rollback_info to response ─────────────────────────────
        if plan_snapshot:
            minutes_remaining = int(
                (plan_snapshot.expires_at - datetime.utcnow()).total_seconds() / 60
            )
            result["rollback_info"] = {
                "rollback_available": True,
                "expires_at": plan_snapshot.expires_at.isoformat(),
                "minutes_remaining": minutes_remaining,
                "plan_id": result.get("plan_id"),
            }
        else:
            result["rollback_info"] = {
                "rollback_available": False,
                "reason": "Snapshot creation failed",
            }

        return result

    except Exception as e:
        logger.error(f"❌ HYBRID PLAN API: Error starting hybrid production: {e}")
        import traceback
        logger.error(f"   - Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/gsm-wise/start-production", tags=["GSM-Wise Planning"])
def start_gsm_wise_production(
    request_data: schemas.HybridStartProductionRequest,
    db: Session = Depends(get_db)
):
    """
    Start production from GSM-wise planning (paper spec driven, same structure as hybrid).
    """
    try:
        from datetime import datetime
        from uuid import UUID as _UUID
        from .. import models

        logger.info("🎯 GSM-WISE PLAN API: Received start production request")

        pre_snapshot_time = datetime.utcnow()

        # Collect all order IDs: from top-level order_ids AND from cut-level order_id in paper_specs
        all_order_id_strs = set(request_data.order_ids or [])
        for spec in (request_data.paper_specs or []):
            spec_dict = spec if isinstance(spec, dict) else spec.model_dump()
            for jumbo in (spec_dict.get('jumbos') or []):
                for roll_set in (jumbo.get('sets') or []):
                    for cut in (roll_set.get('cuts') or []):
                        if cut.get('order_id'):
                            all_order_id_strs.add(cut['order_id'])

        affected_orders = []
        affected_order_items = []
        seen_order_ids = set()

        for oid_str in all_order_id_strs:
            try:
                oid = _UUID(oid_str)
            except ValueError:
                continue
            if oid in seen_order_ids:
                continue
            seen_order_ids.add(oid)
            order = db.query(models.OrderMaster).filter(models.OrderMaster.id == oid).first()
            if not order:
                continue
            affected_orders.append({
                "id": str(order.id),
                "frontend_id": order.frontend_id,
                "status": order.status,
                "created_at": order.created_at.isoformat(),
                "started_production_at": order.started_production_at.isoformat() if order.started_production_at else None,
                "moved_to_warehouse_at": order.moved_to_warehouse_at.isoformat() if order.moved_to_warehouse_at else None,
                "dispatched_at": order.dispatched_at.isoformat() if order.dispatched_at else None,
            })
            for item in order.order_items:
                affected_order_items.append({
                    "id": str(item.id),
                    "frontend_id": item.frontend_id,
                    "order_id": str(item.order_id),
                    "width_inches": float(item.width_inches),
                    "quantity_rolls": item.quantity_rolls,
                    "quantity_fulfilled": item.quantity_fulfilled,
                    "quantity_in_pending": item.quantity_in_pending,
                    "item_status": item.item_status,
                    "created_at": item.created_at.isoformat(),
                })
                logger.info(f"📸 GSM-WISE SNAPSHOT: {item.frontend_id} width={item.width_inches}\" qty_fulfilled={item.quantity_fulfilled}/{item.quantity_rolls}")

        affected_pending_orders = []
        all_pending = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem._status == "pending"
        ).all()
        for pending in all_pending:
            affected_pending_orders.append({
                "id": str(pending.id),
                "frontend_id": pending.frontend_id,
                "original_order_id": str(pending.original_order_id),
                "width_inches": float(pending.width_inches),
                "quantity_pending": pending.quantity_pending,
                "quantity_fulfilled": pending.quantity_fulfilled or 0,
                "status": pending._status,
                "reason": pending.reason,
                "created_at": pending.created_at.isoformat(),
            })

        pre_execution_data = {
            "snapshot_time": pre_snapshot_time.isoformat(),
            "affected_orders": affected_orders,
            "affected_order_items": affected_order_items,
            "affected_pending_orders": affected_pending_orders,
            "table_counts": {
                "orders": db.query(models.OrderMaster).count(),
                "order_items": db.query(models.OrderItem).count(),
                "inventory_master": db.query(models.InventoryMaster).count(),
                "pending_order_items": db.query(models.PendingOrderItem).count(),
                "wastage_inventory": db.query(models.WastageInventory).count(),
            },
        }

        result = crud_operations.create_gsm_wise_production(
            db=db,
            hybrid_data=request_data.model_dump()
        )

        logger.info(f"✅ GSM-WISE PLAN API: Successfully created production")

        plan_snapshot = None
        try:
            plan_id_str = result.get("plan_id")
            if plan_id_str:
                plan_uuid = _UUID(plan_id_str)
                pre_execution_data["plan_id"] = str(plan_uuid)
                pre_execution_data["plan_details"] = {
                    "id": str(plan_uuid),
                    "name": result.get("plan_frontend_id", ""),
                    "status": "in_progress",
                    "created_at": pre_snapshot_time.isoformat(),
                }
                plan_snapshot = crud_operations.create_snapshot_for_hybrid_plan(
                    db=db,
                    plan_id=plan_uuid,
                    user_id=_UUID(request_data.created_by_id),
                    pre_execution_data=pre_execution_data,
                )
        except Exception as snap_err:
            logger.error(f"❌ GSM-WISE PLAN API: Failed to create rollback snapshot: {snap_err}")

        if plan_snapshot:
            minutes_remaining = int(
                (plan_snapshot.expires_at - datetime.utcnow()).total_seconds() / 60
            )
            result["rollback_info"] = {
                "rollback_available": True,
                "expires_at": plan_snapshot.expires_at.isoformat(),
                "minutes_remaining": minutes_remaining,
                "plan_id": result.get("plan_id"),
            }
        else:
            result["rollback_info"] = {"rollback_available": False, "reason": "Snapshot creation failed"}

        return result

    except Exception as e:
        logger.error(f"❌ GSM-WISE PLAN API: Error starting production: {e}")
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


@router.delete("/plans/manual/{plan_id}", tags=["Manual Planning"])
def delete_manual_plan(plan_id: str, db: Session = Depends(get_db)):
    """
    Delete a manual plan by removing its inventory hierarchy and marking the plan as deleted.
    Handles self-referential FK constraints on InventoryMaster by nullifying parents before deletion.
    """
    try:
        import uuid
        from .. import models

        plan_uuid = uuid.UUID(plan_id)

        plan = db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_uuid).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        # Get cut rolls linked via PlanInventoryLink
        links = db.query(models.PlanInventoryLink).filter(
            models.PlanInventoryLink.plan_id == plan_uuid
        ).all()
        cut_roll_ids = {link.inventory_id for link in links}

        # Walk up to find parent 118" and jumbo rolls
        roll_118_ids = set()
        jumbo_ids = set()
        if cut_roll_ids:
            cut_rolls = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.id.in_(cut_roll_ids)
            ).all()
            for cr in cut_rolls:
                if cr.parent_118_roll_id:
                    roll_118_ids.add(cr.parent_118_roll_id)
                if cr.parent_jumbo_id:
                    jumbo_ids.add(cr.parent_jumbo_id)

        # Also find 118" rolls' parent jumbos (in case cut rolls only have parent_118_roll_id)
        if roll_118_ids:
            rolls_118 = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.id.in_(roll_118_ids)
            ).all()
            for r in rolls_118:
                if r.parent_jumbo_id:
                    jumbo_ids.add(r.parent_jumbo_id)

        all_inventory_ids = cut_roll_ids | roll_118_ids | jumbo_ids

        # Delete plan inventory links FIRST (before inventory, to avoid FK constraint)
        db.query(models.PlanInventoryLink).filter(
            models.PlanInventoryLink.plan_id == plan_uuid
        ).delete(synchronize_session=False)

        if all_inventory_ids:
            # Nullify self-referential FKs to avoid constraint errors between inventory records
            db.query(models.InventoryMaster).filter(
                models.InventoryMaster.id.in_(all_inventory_ids)
            ).update(
                {"parent_jumbo_id": None, "parent_118_roll_id": None},
                synchronize_session=False
            )
            # Delete all inventory records
            db.query(models.InventoryMaster).filter(
                models.InventoryMaster.id.in_(all_inventory_ids)
            ).delete(synchronize_session=False)

        # Step 4: Soft-delete the plan
        plan.is_deleted = True
        plan.status = "deleted"

        db.commit()

        logger.info(f"🗑️ MANUAL PLAN DELETE: Plan {plan.frontend_id} deleted — {len(all_inventory_ids)} inventory records removed ({len(jumbo_ids)} jumbos, {len(roll_118_ids)} 118\" rolls, {len(cut_roll_ids)} cut rolls)")
        return {"success": True, "plan_id": plan_id, "inventory_deleted": len(all_inventory_ids)}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ MANUAL PLAN DELETE: Error deleting plan {plan_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))