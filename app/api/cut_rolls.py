from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from uuid import UUID
import logging

from .base import get_db
from .. import crud_operations, schemas

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# CUT ROLL PRODUCTION ENDPOINTS
# ============================================================================

@router.post("/cut-rolls/select", response_model=Dict[str, Any], tags=["Cut Roll Production"])
async def select_cut_rolls_for_production(
    request: Request,
    db: Session = Depends(get_db)
):
    """Select cut rolls from plan generation results for production"""
    try:
        # DEBUG: Log raw request data
        raw_body = await request.body()
        logger.info(f"🔍 DEBUG cut-rolls/select - Raw request body: {raw_body.decode()}")
        
        # Parse JSON manually to see structure
        import json
        try:
            request_data = json.loads(raw_body.decode())
            logger.info(f"🔍 DEBUG cut-rolls/select - Parsed JSON keys: {list(request_data.keys())}")
            logger.info(f"🔍 DEBUG cut-rolls/select - Full request data: {json.dumps(request_data, indent=2)}")
        except Exception as json_error:
            logger.error(f"❌ DEBUG cut-rolls/select - JSON parse error: {json_error}")
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {json_error}")
        
        # Try to validate with schema
        try:
            selection_request = schemas.CutRollSelectionRequest(**request_data)
            logger.info(f"✅ DEBUG cut-rolls/select - Schema validation successful")
        except Exception as validation_error:
            logger.error(f"❌ DEBUG cut-rolls/select - Schema validation error: {validation_error}")
            logger.error(f"❌ DEBUG cut-rolls/select - Expected schema: plan_id (optional), selected_rolls (list), created_by_id (required)")
            raise HTTPException(status_code=422, detail=f"Validation error: {validation_error}")
        selected_rolls = []
        inventory_items_created = []
        
        for roll_selection in selection_request.selected_rolls:
            # Create inventory item for each selected cut roll
            inventory_data = schemas.InventoryMasterCreate(
                paper_id=roll_selection.paper_id,
                width_inches=int(roll_selection.width_inches),
                weight_kg=0.1,  # Small placeholder weight (will be updated during production)
                roll_type="cut",
                location="production_floor",
                qr_code=roll_selection.qr_code,
                created_by_id=selection_request.created_by_id
            )
            
            inventory_item = crud_operations.create_inventory_item(db, inventory_data)
            inventory_items_created.append(inventory_item)
            
            selected_rolls.append({
                "inventory_id": str(inventory_item.id),
                "width_inches": float(inventory_item.width_inches),
                "paper_id": str(inventory_item.paper_id),
                "qr_code": inventory_item.qr_code,
                "status": inventory_item.status,
                "expected_pattern": roll_selection.cutting_pattern
            })
        
        # Update plan status if plan_id provided
        if selection_request.plan_id:
            plan = crud_operations.get_plan(db=db, plan_id=selection_request.plan_id)
            if plan and plan.status == "created":
                crud_operations.update_plan_status(db=db, plan_id=selection_request.plan_id, new_status="in_progress")
        
        # STEP 3: Update related orders to "in_process" when production starts
        # Find orders related to this plan and update their status
        if selection_request.plan_id:
            from .. import models
            # Get plan with order links
            plan_links = db.query(models.PlanOrderLink).filter(
                models.PlanOrderLink.plan_id == selection_request.plan_id
            ).all()
            
            order_ids = [link.order_id for link in plan_links]
            for order_id in order_ids:
                order = crud_operations.get_order(db, order_id)
                if order and order.status == "created":
                    # Update order status to in_process
                    order.status = "in_process"
                    logger.info(f"✅ Updated order {order_id} status to 'in_process' (Step 3: Start Production)")
                    
                    # Also update all order items to "in_process"
                    for order_item in order.order_items:
                        if order_item.item_status == "created":
                            order_item.item_status = "in_process"
                            order_item.started_production_at = db.func.now()
                            logger.info(f"✅ Updated order item {order_item.id} item_status to 'in_process' (Step 3: Start Production)")
            
            db.commit()
        
        return {
            "plan_id": str(selection_request.plan_id) if selection_request.plan_id else None,
            "selected_rolls": selected_rolls,
            "production_summary": {
                "total_rolls_selected": len(selected_rolls),
                "total_inventory_items_created": len(inventory_items_created),
                "production_status": "initiated",
                "next_steps": [
                    "Start cutting production",
                    "Update weights via QR code scanning",
                    "Move to warehouse when complete"
                ]
            },
            "message": f"Successfully selected {len(selected_rolls)} cut rolls for production"
        }
        
    except Exception as e:
        logger.error(f"Error selecting cut rolls for production: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cut-rolls/production/{plan_id}", response_model=Dict[str, Any], tags=["Cut Roll Production"])
def get_cut_roll_production_summary(plan_id: UUID, db: Session = Depends(get_db)):
    """Get summary of cut roll production for a specific plan"""
    try:
        # Get plan details
        plan = crud_operations.get_plan(db=db, plan_id=plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get inventory items associated with this plan (through plan inventory links)
        plan_inventory = []
        if hasattr(plan, 'plan_inventory'):
            plan_inventory = plan.plan_inventory
        
        # Get all cut roll inventory items with status related to this plan
        cut_roll_inventory = crud_operations.get_inventory_by_type(db=db, roll_type="cut", skip=0, limit=1000)
        
        # Filter items created around the same time as plan execution
        plan_related_items = []
        if plan.executed_at:
            for item in cut_roll_inventory:
                # Items created after plan execution are likely related
                if item.created_at >= plan.executed_at:
                    plan_related_items.append(item)
        
        # Group items by status
        status_breakdown = {}
        total_weight = 0
        total_rolls = 0
        
        for item in plan_related_items:
            status = item.status
            if status not in status_breakdown:
                status_breakdown[status] = {
                    "count": 0,
                    "total_weight": 0,
                    "widths": []
                }
            
            status_breakdown[status]["count"] += 1
            status_breakdown[status]["total_weight"] += item.weight_kg
            status_breakdown[status]["widths"].append(float(item.width_inches))
            
            total_weight += item.weight_kg
            total_rolls += 1
        
        # Get paper specifications
        paper_specs = {}
        for item in plan_related_items:
            if item.paper:
                spec_key = f"{item.paper.gsm}_{item.paper.bf}_{item.paper.shade}"
                if spec_key not in paper_specs:
                    paper_specs[spec_key] = {
                        "gsm": item.paper.gsm,
                        "bf": float(item.paper.bf),
                        "shade": item.paper.shade,
                        "roll_count": 0
                    }
                paper_specs[spec_key]["roll_count"] += 1
        
        return {
            "plan_id": str(plan.id),
            "plan_name": plan.name,
            "plan_status": plan.status,
            "executed_at": plan.executed_at.isoformat() if plan.executed_at else None,
            "production_summary": {
                "total_cut_rolls": total_rolls,
                "total_weight_kg": round(total_weight, 2),
                "average_weight_per_roll": round(total_weight / total_rolls, 2) if total_rolls > 0 else 0,
                "status_breakdown": status_breakdown,
                "paper_specifications": list(paper_specs.values())
            },
            "detailed_items": [
                {
                    "inventory_id": str(item.id),
                    "width_inches": float(item.width_inches),
                    "weight_kg": float(item.weight_kg),
                    "status": item.status,
                    "location": item.location,
                    "qr_code": item.qr_code,
                    "created_at": item.created_at.isoformat(),
                    "paper_specs": {
                        "gsm": item.paper.gsm,
                        "bf": float(item.paper.bf),
                        "shade": item.paper.shade
                    } if item.paper else None
                }
                for item in plan_related_items
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting production summary for plan {plan_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/cut-rolls/{inventory_id}/status", response_model=Dict[str, Any], tags=["Cut Roll Production"])
def update_cut_roll_status(
    inventory_id: UUID,
    status_update: schemas.InventoryStatusUpdate,
    db: Session = Depends(get_db)
):
    """Update cut roll status during production"""
    try:
        inventory_item = crud_operations.get_inventory_item(db=db, inventory_id=inventory_id)
        if not inventory_item:
            raise HTTPException(status_code=404, detail="Cut roll not found")
        
        if inventory_item.roll_type != "cut":
            raise HTTPException(status_code=400, detail="Item is not a cut roll")
        
        old_status = inventory_item.status
        updated_item = crud_operations.update_inventory_status(
            db=db, 
            inventory_id=inventory_id, 
            new_status=status_update.new_status
        )
        
        # Update location if provided
        if status_update.location:
            updated_item.location = status_update.location
            db.commit()
            db.refresh(updated_item)
        
        return {
            "inventory_id": str(updated_item.id),
            "qr_code": updated_item.qr_code,
            "status_change": {
                "old_status": old_status,
                "new_status": updated_item.status
            },
            "current_location": updated_item.location,
            "roll_details": {
                "width_inches": float(updated_item.width_inches),
                "weight_kg": float(updated_item.weight_kg),
                "roll_type": updated_item.roll_type
            },
            "updated_at": updated_item.updated_at.isoformat() if updated_item.updated_at else None,
            "message": f"Cut roll status updated from '{old_status}' to '{updated_item.status}'"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating cut roll status: {e}")
        raise HTTPException(status_code=500, detail=str(e))