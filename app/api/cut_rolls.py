from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Any
from uuid import UUID
import logging

from .base import get_db
from .. import crud_operations, schemas
from ..services.barcode_generator import BarcodeGenerator

router = APIRouter()
logger = logging.getLogger(__name__)

def _get_jumbo_roll_info(inventory_item):
    """
    Helper function to get jumbo roll information for cut rolls.
    Cut rolls -> 118" rolls -> jumbo rolls (indirect relationship only)
    """
    jumbo_roll_id = None
    jumbo_roll_frontend_id = None
    jumbo_roll_uuid = None
    
    try:
        # For cut rolls: Traverse via 118" roll (Cut Roll → 118" Roll → Jumbo Roll)
        if hasattr(inventory_item, 'parent_118_roll_id') and inventory_item.parent_118_roll_id:
            if hasattr(inventory_item, 'parent_118_roll') and inventory_item.parent_118_roll:
                parent_118_roll = inventory_item.parent_118_roll
                
                if hasattr(parent_118_roll, 'parent_jumbo_id') and parent_118_roll.parent_jumbo_id:
                    if hasattr(parent_118_roll, 'parent_jumbo') and parent_118_roll.parent_jumbo:
                        jumbo_roll = parent_118_roll.parent_jumbo
                        jumbo_roll_uuid = parent_118_roll.parent_jumbo_id
                        jumbo_roll_id = str(parent_118_roll.parent_jumbo_id)
                        jumbo_roll_frontend_id = getattr(jumbo_roll, 'frontend_id', None)
    except Exception as e:
        logger.error(f"Error in _get_jumbo_roll_info for item {inventory_item.id}: {e}")
    
    return {
        "jumbo_roll_id": jumbo_roll_id,
        "jumbo_roll_frontend_id": jumbo_roll_frontend_id,
        "actual_parent_jumbo_id": str(jumbo_roll_uuid) if jumbo_roll_uuid else None
    }

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
            # Generate barcode for this cut roll
            barcode_id = BarcodeGenerator.generate_cut_roll_barcode(db)
            
            # Create inventory item for each selected cut roll
            inventory_data = schemas.InventoryMasterCreate(
                paper_id=roll_selection.paper_id,
                width_inches=float(roll_selection.width_inches),
                weight_kg=0.1,  # Small placeholder weight (will be updated during production)
                roll_type="cut",
                location="production_floor",
                qr_code=roll_selection.qr_code,
                barcode_id=barcode_id,
                created_by_id=selection_request.created_by_id
            )
            
            inventory_item = crud_operations.create_inventory_item(db, inventory_data)
            inventory_items_created.append(inventory_item)
            
            selected_rolls.append({
                "inventory_id": str(inventory_item.id),
                "width_inches": float(inventory_item.width_inches),
                "paper_id": str(inventory_item.paper_id),
                "qr_code": inventory_item.qr_code,
                "barcode_id": inventory_item.barcode_id,
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
                            order_item.started_production_at = func.now()
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
    """Get summary of cut roll production for a specific plan using InventoryMaster"""
    try:
        from .. import models
        from sqlalchemy.orm import joinedload, selectinload

        # Get plan details with optimized loading
        plan = db.query(models.PlanMaster).options(
            selectinload(models.PlanMaster.plan_orders)
                .joinedload(models.PlanOrderLink.order)
                .joinedload(models.OrderMaster.client)
        ).filter(models.PlanMaster.id == plan_id).first()

        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        logger.info(f"🔍 Getting cut roll summary for plan {plan_id}")

        # Get cut rolls with all needed relationships in one query
        all_cut_rolls_raw = db.query(models.InventoryMaster).join(
            models.PlanInventoryLink,
            models.InventoryMaster.id == models.PlanInventoryLink.inventory_id
        ).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.allocated_order)
                .joinedload(models.OrderMaster.client),
            joinedload(models.InventoryMaster.parent_118_roll)
                .joinedload(models.InventoryMaster.parent_jumbo)
        ).filter(
            models.PlanInventoryLink.plan_id == plan_id,
            models.InventoryMaster.roll_type == "cut"
        ).all()

        if not all_cut_rolls_raw:
            logger.warning(f"🚨 NO INVENTORY LINKS FOUND for plan {plan_id}! Plan should have PlanInventoryLink records.")
            logger.warning(f"🚨 This plan will show NO ITEMS until proper inventory links are created.")
            logger.warning(f"🚨 Time-based fallback is DISABLED to prevent showing wrong items.")
        

        # Pre-compute client fallback from plan orders (already loaded)
        fallback_client = "Unknown Client"
        fallback_order_date = None
        if plan.plan_orders:
            for plan_order in plan.plan_orders:
                if plan_order.order and plan_order.order.client:
                    fallback_client = plan_order.order.client.company_name
                    fallback_order_date = plan_order.order.created_at.isoformat()
                    break

        # Build cut rolls list with optimized data access
        all_cut_rolls = []
        seen_ids = set()

        for item in all_cut_rolls_raw:
            if item.id in seen_ids:
                continue
            seen_ids.add(item.id)

            # Get client info (already loaded via joinedload)
            if item.allocated_order and item.allocated_order.client:
                client_name = item.allocated_order.client.company_name
                order_date = item.allocated_order.created_at.isoformat()
            else:
                client_name = fallback_client
                order_date = fallback_order_date

            # Get jumbo roll info (already loaded via joinedload)
            jumbo_roll_id = None
            jumbo_roll_frontend_id = None
            actual_parent_jumbo_id = None

            if item.parent_118_roll and item.parent_118_roll.parent_jumbo:
                jumbo = item.parent_118_roll.parent_jumbo
                jumbo_roll_id = str(item.parent_118_roll.parent_jumbo_id)
                jumbo_roll_frontend_id = getattr(jumbo, 'frontend_id', None)
                actual_parent_jumbo_id = str(item.parent_118_roll.parent_jumbo_id)

            all_cut_rolls.append({
                "inventory_id": str(item.id),
                "qr_code": item.qr_code or f"QR{str(item.id)[:8].upper()}",
                "barcode_id": item.barcode_id or f"CR_{str(item.id)[:5].upper()}",
                "width_inches": float(item.width_inches),
                "weight_kg": float(item.weight_kg),
                "status": item.status,
                "location": item.location or "warehouse",
                "created_at": item.created_at,
                "paper_specs": {
                    "gsm": item.paper.gsm,
                    "bf": float(item.paper.bf),
                    "shade": item.paper.shade
                } if item.paper else None,
                "client_name": client_name,
                "order_date": order_date,
                "individual_roll_number": item.individual_roll_number,
                "parent_118_roll_id": str(item.parent_118_roll_id) if item.parent_118_roll_id else None,
                "roll_sequence": item.roll_sequence,
                "is_wastage_roll": item.is_wastage_roll,
                "jumbo_roll_id": jumbo_roll_id,
                "jumbo_roll_frontend_id": jumbo_roll_frontend_id,
                "actual_parent_jumbo_id": actual_parent_jumbo_id
            })
        

        # Compute aggregations in single pass
        status_breakdown = {}
        paper_specs = {}
        client_info = {}
        total_weight = 0
        total_rolls = len(all_cut_rolls)

        for item in all_cut_rolls:
            # Status breakdown
            status = item["status"]
            if status not in status_breakdown:
                status_breakdown[status] = {"count": 0, "total_weight": 0, "widths": []}
            status_breakdown[status]["count"] += 1
            status_breakdown[status]["total_weight"] += item["weight_kg"]
            status_breakdown[status]["widths"].append(item["width_inches"])
            total_weight += item["weight_kg"]

            # Paper specs (non-wastage only)
            if item["paper_specs"] and not item["is_wastage_roll"]:
                spec_key = f"{item['paper_specs']['gsm']}_{item['paper_specs']['bf']}_{item['paper_specs']['shade']}"
                if spec_key not in paper_specs:
                    paper_specs[spec_key] = {
                        "gsm": item["paper_specs"]["gsm"],
                        "bf": item["paper_specs"]["bf"],
                        "shade": item["paper_specs"]["shade"],
                        "roll_count": 0
                    }
                paper_specs[spec_key]["roll_count"] += 1

        # Extract client info from already-loaded plan orders
        if plan.plan_orders:
            for link in plan.plan_orders:
                if link.order and link.order.client:
                    client_info[str(link.order.id)] = {
                        "client_name": link.order.client.company_name,
                        "order_date": link.order.created_at.isoformat()
                    }

        # Get wastage allocations with optimized single query
        wastage_items = []
        if plan.wastage_allocations:
            import json
            try:
                wastage_allocations = json.loads(plan.wastage_allocations)
                if wastage_allocations and isinstance(wastage_allocations, list):
                    # Track seen wastage IDs to ensure uniqueness (keep first occurrence only)
                    seen_wastage_ids = set()
                    unique_wastage_allocations = []
                    
                    for alloc in wastage_allocations:
                        wid = alloc.get("wastage_id")
                        if wid:
                            wid_str = str(wid)
                            if wid_str not in seen_wastage_ids:
                                seen_wastage_ids.add(wid_str)
                                unique_wastage_allocations.append(alloc)
                    
                    # Use only unique wastage allocations
                    wastage_allocations = unique_wastage_allocations
                    
                    wastage_ids = [
                        UUID(alloc["wastage_id"]) if isinstance(alloc["wastage_id"], str) else alloc["wastage_id"]
                        for alloc in wastage_allocations if alloc.get("wastage_id")
                    ]
                    order_ids = [
                        UUID(alloc["order_id"]) if isinstance(alloc["order_id"], str) else alloc["order_id"]
                        for alloc in wastage_allocations if alloc.get("order_id")
                    ]

                    if wastage_ids:
                        # Single query for wastage with paper
                        wastage_records = db.query(models.WastageInventory).options(
                            joinedload(models.WastageInventory.paper)
                        ).filter(models.WastageInventory.id.in_(wastage_ids)).all()
                        wastage_map = {str(w.id): w for w in wastage_records}

                        # Single query for orders with clients
                        orders = db.query(models.OrderMaster).options(
                            joinedload(models.OrderMaster.client)
                        ).filter(models.OrderMaster.id.in_(order_ids)).all() if order_ids else []
                        order_client_map = {str(o.id): o.client.company_name for o in orders if o.client}

                        # Build wastage items
                        for alloc in wastage_allocations:
                            wid = str(alloc.get("wastage_id", ""))
                            if wid in wastage_map:
                                w = wastage_map[wid]
                                oid = str(alloc.get("order_id", ""))
                                wastage_items.append({
                                    "id": str(w.id),
                                    "frontend_id": w.frontend_id,
                                    "barcode_id": w.barcode_id,
                                    "width_inches": float(w.width_inches),
                                    "weight_kg": float(w.weight_kg),
                                    "reel_no": w.reel_no,
                                    "status": w.status,
                                    "location": w.location,
                                    "paper_specs": {
                                        "gsm": w.paper.gsm,
                                        "bf": float(w.paper.bf),
                                        "shade": w.paper.shade
                                    } if w.paper else None,
                                    "created_at": w.created_at.isoformat() if w.created_at else None,
                                    "client_name": order_client_map.get(oid, "Unknown Client"),
                                    "quantity_reduced": alloc.get("quantity_reduced", 1)
                                })
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to parse wastage_allocations for plan {plan_id}: {str(e)}")

        # Convert datetime objects to ISO format strings for JSON serialization
        detailed_items = []
        for item in all_cut_rolls:
            detailed_item = dict(item)  # Make a copy
            # Convert datetime to string
            if hasattr(detailed_item.get("created_at"), 'isoformat'):
                detailed_item["created_at"] = detailed_item["created_at"].isoformat()
            elif detailed_item.get("created_at"):
                detailed_item["created_at"] = str(detailed_item["created_at"])
            detailed_items.append(detailed_item)

        response_data = {
            "plan_id": str(plan.id),
            "plan_name": plan.name,
            "plan_status": plan.status,
            "executed_at": plan.executed_at.isoformat() if plan.executed_at else None,
            "production_summary": {
                "total_cut_rolls": total_rolls,
                "total_weight_kg": round(total_weight, 2),
                "average_weight_per_roll": round(total_weight / total_rolls, 2) if total_rolls > 0 else 0,
                "status_breakdown": status_breakdown,
                "paper_specifications": list(paper_specs.values()),
                "client_orders": list(client_info.values())
            },
            "wastage_allocations": wastage_items,
            "detailed_items": detailed_items
        }

        logger.info(f"✅ Returning production summary with {len(detailed_items)} items")
        return response_data
        
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
            "barcode_id": updated_item.barcode_id,
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

@router.post("/cut-rolls/create-sample-data/{plan_id}", response_model=Dict[str, Any], tags=["Cut Roll Production"])
def create_sample_cut_roll_data(plan_id: UUID, db: Session = Depends(get_db)):
    """Create sample cut roll inventory data for testing"""
    try:
        from .. import models
        import uuid
        from datetime import datetime
        
        # Get plan
        plan = crud_operations.get_plan(db=db, plan_id=plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get first available paper, client, and user for sample data
        paper = db.query(models.PaperMaster).first()
        client = db.query(models.ClientMaster).first()
        order = db.query(models.OrderMaster).first()
        user = db.query(models.UserMaster).first()
        
        if not all([paper, user]):
            raise HTTPException(status_code=400, detail="Missing required master data (paper or user)")
        
        # Update plan executed_at if not set (for time-based linking)
        if not plan.executed_at:
            plan.executed_at = datetime.utcnow()
            db.commit()
        
        # Create sample cut roll inventory records
        sample_rolls = []
        widths = [12, 18, 24, 30, 36]
        statuses = ["available", "cutting", "available", "allocated", "available"]
        locations = ["warehouse_a", "production_floor", "warehouse_b", "cutting_section", "quality_check"]
        
        for i in range(10):  # Create 10 sample rolls
            qr_code = f"QR{plan_id.hex[:8].upper()}{i+1:03d}"
            barcode_id = BarcodeGenerator.generate_cut_roll_barcode(db)
            width = widths[i % len(widths)]
            status = statuses[i % len(statuses)]
            location = locations[i % len(locations)]
            
            # Create inventory item
            inventory_item = models.InventoryMaster(
                id=uuid.uuid4(),
                paper_id=paper.id,
                width_inches=width,
                weight_kg=width * 13.5,  # Approximate weight calculation
                roll_type="cut",
                location=location,
                status=status,
                qr_code=qr_code,
                barcode_id=barcode_id,
                production_date=datetime.utcnow(),
                allocated_to_order_id=order.id if order else None,
                created_by_id=user.id,
                created_at=datetime.utcnow()
            )
            
            db.add(inventory_item)
            
            # Create plan inventory link
            plan_inventory_link = models.PlanInventoryLink(
                id=uuid.uuid4(),
                plan_id=plan_id,
                inventory_id=inventory_item.id,
                quantity_used=1.0  # One roll used
            )
            
            db.add(plan_inventory_link)
            
            sample_rolls.append({
                "inventory_id": str(inventory_item.id),
                "qr_code": qr_code,
                "barcode_id": barcode_id,
                "width_inches": width,
                "weight_kg": width * 13.5,
                "status": status,
                "location": location
            })
        
        db.commit()
        
        return {
            "message": f"Created {len(sample_rolls)} sample cut rolls for plan {plan_id}",
            "plan_id": str(plan_id),
            "sample_rolls": sample_rolls,
            "note": "Cut rolls created in InventoryMaster with PlanInventoryLink connections"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating sample cut roll data: {e}")
        raise HTTPException(status_code=500, detail=str(e))