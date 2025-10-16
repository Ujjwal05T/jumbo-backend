from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, or_
from typing import Dict, Any, Optional
from uuid import UUID
import logging

from .base import get_db
from .. import models, schemas

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/track/roll/{identifier}", response_model=Dict[str, Any], tags=["Roll Tracking"])
def track_roll_comprehensive(
    identifier: str,
    db: Session = Depends(get_db)
):
    """
    Comprehensive roll tracking by barcode, QR code, or roll number
    Returns complete lifecycle information for a roll
    """
    try:
        # Find the inventory item (roll) by barcode, QR code, or frontend_id
        inventory_item = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.created_by)
        ).filter(
            or_(
                models.InventoryMaster.barcode_id == identifier,
                models.InventoryMaster.qr_code == identifier,
                models.InventoryMaster.frontend_id == identifier
            )
        ).first()

        if not inventory_item:
            raise HTTPException(status_code=404, detail="Roll not found. Please check the barcode/QR code and try again.")

        # Initialize result dictionary
        result = {
            "roll_info": {},
            "order_info": None,
            "plan_info": None,
            "dispatch_info": None,
            "production_info": None,
            "weight_info": {},
            "status_timeline": [],
            "related_rolls": []
        }

        # Basic roll information
        result["roll_info"] = {
            "inventory_id": str(inventory_item.id),
            "frontend_id": inventory_item.frontend_id,
            "barcode_id": inventory_item.barcode_id,
            "qr_code": inventory_item.qr_code,
            "width_inches": float(inventory_item.width_inches),
            "weight_kg": float(inventory_item.weight_kg),
            "roll_type": inventory_item.roll_type,
            "status": inventory_item.status,
            "location": inventory_item.location,
            "production_date": inventory_item.production_date.isoformat() if inventory_item.production_date else None,
            "is_wastage_roll": inventory_item.is_wastage_roll,
            "created_at": inventory_item.created_at.isoformat()
        }

        # Paper specifications
        if inventory_item.paper:
            result["roll_info"]["paper_specifications"] = {
                "paper_id": str(inventory_item.paper.id),
                "paper_frontend_id": inventory_item.paper.frontend_id,
                "name": inventory_item.paper.name,
                "gsm": inventory_item.paper.gsm,
                "bf": float(inventory_item.paper.bf),
                "shade": inventory_item.paper.shade,
                "type": inventory_item.paper.type
            }

        # Production information
        result["production_info"] = {
            "created_by": inventory_item.created_by.name if inventory_item.created_by else None,
            "created_by_role": inventory_item.created_by.role if inventory_item.created_by else None,
            "created_at": inventory_item.created_at.isoformat(),
            "jumbo_hierarchy": {
                "parent_jumbo_id": str(inventory_item.parent_jumbo_id) if inventory_item.parent_jumbo_id else None,
                "parent_jumbo_frontend_id": None,  # Will be loaded separately
                "parent_118_roll_id": str(inventory_item.parent_118_roll_id) if inventory_item.parent_118_roll_id else None,
                "parent_118_roll_frontend_id": None,  # Will be loaded separately
                "roll_sequence": inventory_item.roll_sequence,
                "individual_roll_number": inventory_item.individual_roll_number
            }
        }

        # Load parent relationships separately
        if inventory_item.parent_jumbo_id:
            parent_jumbo = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.id == inventory_item.parent_jumbo_id
            ).first()
            if parent_jumbo:
                result["production_info"]["jumbo_hierarchy"]["parent_jumbo_frontend_id"] = parent_jumbo.frontend_id

        if inventory_item.parent_118_roll_id:
            parent_118 = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.id == inventory_item.parent_118_roll_id
            ).first()
            if parent_118:
                result["production_info"]["jumbo_hierarchy"]["parent_118_roll_frontend_id"] = parent_118.frontend_id

        # Weight tracking information
        result["weight_info"] = {
            "current_weight_kg": float(inventory_item.weight_kg),
            "has_weight": inventory_item.weight_kg > 0.1,
            "weight_status": "measured" if inventory_item.weight_kg > 0.1 else "pending"
        }

        # Order information
        if inventory_item.allocated_to_order_id:
            order = db.query(models.OrderMaster).options(
                joinedload(models.OrderMaster.client)
            ).filter(
                models.OrderMaster.id == inventory_item.allocated_to_order_id
            ).first()

            if order:
                result["order_info"] = {
                    "order_id": str(order.id),
                    "order_frontend_id": order.frontend_id,
                    "status": order.status,
                    "priority": order.priority,
                    "payment_type": order.payment_type,
                    "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                    "created_at": order.created_at.isoformat(),
                    "client": {
                        "client_id": str(order.client.id) if order.client else None,
                        "client_name": order.client.company_name if order.client else None,
                        "contact_person": order.client.contact_person if order.client else None,
                        "phone": order.client.phone if order.client else None
                    } if order.client else None
                }

                # Find the specific order item that matches this roll
                if inventory_item.paper:
                    matching_order_item = db.query(models.OrderItem).filter(
                        models.OrderItem.order_id == order.id,
                        models.OrderItem.paper_id == inventory_item.paper_id,
                        models.OrderItem.width_inches == float(inventory_item.width_inches)
                    ).first()

                    if matching_order_item:
                        result["order_info"]["order_item"] = {
                            "order_item_id": str(matching_order_item.id),
                            "order_item_frontend_id": matching_order_item.frontend_id,
                            "quantity_rolls": matching_order_item.quantity_rolls,
                            "quantity_fulfilled": matching_order_item.quantity_fulfilled,
                            "quantity_kg": float(matching_order_item.quantity_kg),
                            "rate": float(matching_order_item.rate),
                            "item_status": matching_order_item.item_status,
                            "remaining_quantity": matching_order_item.remaining_quantity,
                            "is_fully_fulfilled": matching_order_item.is_fully_fulfilled
                        }

        # Plan information
        plan_link = db.query(models.PlanInventoryLink).options(
            joinedload(models.PlanInventoryLink.plan)
        ).filter(
            models.PlanInventoryLink.inventory_id == inventory_item.id
        ).first()

        if plan_link:
            plan = plan_link.plan
            result["plan_info"] = {
                "plan_id": str(plan.id),
                "plan_frontend_id": plan.frontend_id,
                "name": plan.name,
                "status": plan.status,
                "expected_waste_percentage": float(plan.expected_waste_percentage),
                "actual_waste_percentage": float(plan.actual_waste_percentage) if plan.actual_waste_percentage else None,
                "created_at": plan.created_at.isoformat(),
                "executed_at": plan.executed_at.isoformat() if plan.executed_at else None,
                "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
                "created_by": plan.created_by.name if plan.created_by else None
            }

        # Source tracking for pending orders
        if inventory_item.source_pending_id:
            pending_order = db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.id == inventory_item.source_pending_id
            ).first()

            if pending_order:
                result["pending_order_info"] = {
                    "pending_order_id": str(pending_order.id),
                    "pending_order_frontend_id": pending_order.frontend_id,
                    "status": pending_order.status,
                    "quantity_pending": pending_order.quantity_pending,
                    "quantity_fulfilled": pending_order.quantity_fulfilled,
                    "reason": pending_order.reason,
                    "original_order_id": str(pending_order.original_order_id),
                    "resolved_at": pending_order.resolved_at.isoformat() if pending_order.resolved_at else None
                }

        # Dispatch information
        dispatch_item = db.query(models.DispatchItem).options(
            joinedload(models.DispatchItem.dispatch_record).joinedload(models.DispatchRecord.client)
        ).filter(
            models.DispatchItem.inventory_id == inventory_item.id
        ).first()

        if dispatch_item:
            dispatch_record = dispatch_item.dispatch_record
            result["dispatch_info"] = {
                "dispatch_id": str(dispatch_record.id),
                "dispatch_frontend_id": dispatch_record.frontend_id,
                "dispatch_number": dispatch_record.dispatch_number,
                "reference_number": dispatch_record.reference_number,
                "vehicle_number": dispatch_record.vehicle_number,
                "driver_name": dispatch_record.driver_name,
                "driver_mobile": dispatch_record.driver_mobile,
                "dispatch_date": dispatch_record.dispatch_date.isoformat() if dispatch_record.dispatch_date else None,
                "status": dispatch_record.status,
                "client": {
                    "client_name": dispatch_record.client.company_name if dispatch_record.client else None
                } if dispatch_record.client else None
            }

        # Status timeline
        timeline = []
        timeline.append({
            "event": "Created",
            "timestamp": inventory_item.created_at.isoformat(),
            "description": f"Roll created with barcode {inventory_item.barcode_id}",
            "type": "production"
        })

        if inventory_item.production_date and inventory_item.production_date != inventory_item.created_at:
            timeline.append({
                "event": "Production",
                "timestamp": inventory_item.production_date.isoformat(),
                "description": "Roll entered production",
                "type": "production"
            })

        if inventory_item.weight_kg > 0.1:
            timeline.append({
                "event": "Weight Measured",
                "timestamp": inventory_item.created_at.isoformat(),  # Approximate
                "description": f"Weight recorded: {float(inventory_item.weight_kg)}kg",
                "type": "quality"
            })

        if inventory_item.status == "available":
            timeline.append({
                "event": "Available for Dispatch",
                "timestamp": inventory_item.created_at.isoformat(),  # Approximate
                "description": "Roll is ready for dispatch",
                "type": "status"
            })

        if result["dispatch_info"]:
            timeline.append({
                "event": "Dispatched",
                "timestamp": result["dispatch_info"]["dispatch_date"],
                "description": f"Dispatched via vehicle {result['dispatch_info']['vehicle_number']}",
                "type": "dispatch"
            })

        result["status_timeline"] = sorted(timeline, key=lambda x: x["timestamp"])

        # Related rolls (same parent jumbo or 118 roll)
        related_rolls = []

        # Find sibling rolls from same parent
        if inventory_item.parent_jumbo_id:
            sibling_rolls = db.query(models.InventoryMaster).options(
                joinedload(models.InventoryMaster.paper)
            ).filter(
                models.InventoryMaster.parent_jumbo_id == inventory_item.parent_jumbo_id,
                models.InventoryMaster.id != inventory_item.id
            ).all()

            for sibling in sibling_rolls[:5]:  # Limit to 5 related rolls
                related_rolls.append({
                    "inventory_id": str(sibling.id),
                    "frontend_id": sibling.frontend_id,
                    "barcode_id": sibling.barcode_id,
                    "width_inches": float(sibling.width_inches),
                    "weight_kg": float(sibling.weight_kg),
                    "status": sibling.status,
                    "relationship": "sibling_roll"
                })

        result["related_rolls"] = related_rolls

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracking roll {identifier}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/track/search", response_model=Dict[str, Any], tags=["Roll Tracking"])
def search_rolls(
    query: str = Query(..., min_length=1, description="Search query"),
    search_type: str = Query("all", description="Search type: barcode, qr, frontend_id, all"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results"),
    db: Session = Depends(get_db)
):
    """
    Search for rolls by various identifiers
    """
    try:
        # Build search conditions
        search_conditions = []

        if search_type == "all" or search_type == "barcode":
            search_conditions.append(models.InventoryMaster.barcode_id.like(f"%{query}%"))

        if search_type == "all" or search_type == "qr":
            search_conditions.append(models.InventoryMaster.qr_code.like(f"%{query}%"))

        if search_type == "all" or search_type == "frontend_id":
            search_conditions.append(models.InventoryMaster.frontend_id.like(f"%{query}%"))

        if not search_conditions:
            raise HTTPException(status_code=400, detail="Invalid search type")

        # Search with paper relationship
        rolls = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper)
        ).filter(
            or_(*search_conditions)
        ).limit(limit).all()

        results = []
        for roll in rolls:
            results.append({
                "inventory_id": str(roll.id),
                "frontend_id": roll.frontend_id,
                "barcode_id": roll.barcode_id,
                "qr_code": roll.qr_code,
                "width_inches": float(roll.width_inches),
                "weight_kg": float(roll.weight_kg),
                "roll_type": roll.roll_type,
                "status": roll.status,
                "location": roll.location,
                "paper_name": roll.paper.name if roll.paper else None,
                "created_at": roll.created_at.isoformat()
            })

        return {
            "query": query,
            "search_type": search_type,
            "results": results,
            "total": len(results)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching rolls: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/track/search-by-specs", response_model=Dict[str, Any], tags=["Roll Tracking"])
def search_rolls_by_specifications(
    width_inches: float = Query(..., description="Roll width in inches"),
    gsm: int = Query(..., description="Paper GSM (grams per square meter)"),
    bf: float = Query(..., description="Paper Burst Factor"),
    shade: str = Query(..., description="Paper shade/color"),
    tolerance: float = Query(0.1, description="Tolerance for width matching"),
    limit: int = Query(20, ge=1, le=50, description="Maximum results"),
    db: Session = Depends(get_db)
):
    """
    Search for rolls by physical specifications (width, GSM, BF, shade)
    Returns rolls that match the specified criteria within tolerance
    """
    try:
        # Calculate width tolerance range
        min_width = width_inches - tolerance
        max_width = width_inches + tolerance

        logger.info(f"🔍 Searching rolls by specs: width={width_inches}\" (±{tolerance}), gsm={gsm}, bf={bf}, shade={shade}")

        # Build base query with paper relationship
        query = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper)
        ).filter(
            models.InventoryMaster.width_inches >= min_width,
            models.InventoryMaster.width_inches <= max_width
        )

        # Add paper specifications filters
        if gsm:
            query = query.filter(models.PaperMaster.gsm == gsm)
        if bf:
            query = query.filter(models.PaperMaster.bf == bf)
        if shade:
            query = query.filter(
                func.lower(models.PaperMaster.shade) == func.lower(shade.strip())
            )

        # Execute query with limit
        rolls = query.limit(limit).all()

        logger.info(f"🔍 Found {len(rolls)} rolls matching specifications")

        results = []
        for roll in rolls:
            # Calculate width difference for display
            width_diff = abs(float(roll.width_inches) - width_inches)

            # Get order information
            order_info = None
            if roll.allocated_to_order_id:
                order = db.query(models.OrderMaster).filter(
                    models.OrderMaster.id == roll.allocated_to_order_id
                ).first()
                if order:
                    order_info = {
                        "order_id": str(order.id),
                        "order_frontend_id": order.frontend_id,
                        "status": order.status
                    }

            # Get plan information
            plan_info = None
            plan_link = db.query(models.PlanInventoryLink).options(
                joinedload(models.PlanInventoryLink.plan)
            ).filter(
                models.PlanInventoryLink.inventory_id == roll.id
            ).first()
            if plan_link and plan_link.plan:
                plan = plan_link.plan
                plan_info = {
                    "plan_id": str(plan.id),
                    "plan_frontend_id": plan.frontend_id,
                    "status": plan.status,
                    "name": plan.name
                }

            result_data = {
                "inventory_id": str(roll.id),
                "frontend_id": roll.frontend_id,
                "barcode_id": roll.barcode_id,
                "qr_code": roll.qr_code,
                "width_inches": float(roll.width_inches),
                "weight_kg": float(roll.weight_kg),
                "roll_type": roll.roll_type,
                "status": roll.status,
                "location": roll.location,
                "paper_name": roll.paper.name if roll.paper else None,
                "paper_specifications": {
                    "gsm": roll.paper.gsm if roll.paper else None,
                    "bf": float(roll.paper.bf) if roll.paper else None,
                    "shade": roll.paper.shade if roll.paper else None,
                    "type": roll.paper.type if roll.paper else None
                } if roll.paper else None,
                "created_at": roll.created_at.isoformat(),
                "width_difference": round(width_diff, 2),  # How close the match is
                "match_score": calculate_match_score(float(roll.width_inches), width_inches, tolerance),
                "order_info": order_info,
                "plan_info": plan_info
            }
            results.append(result_data)

        # Sort by match score (best matches first)
        results.sort(key=lambda x: x["match_score"], reverse=True)

        return {
            "search_criteria": {
                "width_inches": width_inches,
                "gsm": gsm,
                "bf": bf,
                "shade": shade,
                "tolerance": tolerance
            },
            "results": results,
            "total": len(results),
            "message": f"Found {len(results)} rolls matching the specifications"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching rolls by specifications: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def calculate_match_score(roll_width: float, target_width: float, tolerance: float) -> float:
    """
    Calculate match score based on how close the roll width is to target
    Returns score between 0 and 1, where 1 is perfect match
    """
    width_diff = abs(roll_width - target_width)
    if width_diff == 0:
        return 1.0
    elif width_diff <= tolerance:
        return 1.0 - (width_diff / tolerance) * 0.5  # Penalty for difference
    else:
        return 0.0