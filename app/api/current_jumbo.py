from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel
import logging

from .base import get_db
from .. import models, schemas


class JumboWeightUpdate(BaseModel):
    weight_kg: float

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# CURRENT JUMBO ROLL ENDPOINTS
# ============================================================================

@router.post("/current-jumbo", response_model=Dict[str, Any], tags=["Current Jumbo Roll"])
def set_current_jumbo_roll(
    jumbo_barcode_id: str,
    db: Session = Depends(get_db)
):
    """Set the current active jumbo roll in production"""
    try:
        # Validate that the jumbo roll barcode exists in inventory
        jumbo_roll = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.barcode_id == jumbo_barcode_id,
            models.InventoryMaster.roll_type == "jumbo"
        ).first()

        if not jumbo_roll:
            raise HTTPException(
                status_code=404,
                detail=f"Jumbo roll with barcode '{jumbo_barcode_id}' not found in inventory"
            )

        # Create new record (keeps all history, does NOT delete old records)
        new_current = models.CurrentJumboRoll(
            jumbo_barcode_id=jumbo_barcode_id
        )
        db.add(new_current)
        db.commit()
        db.refresh(new_current)

        logger.info(f"✅ Set current jumbo roll to: {jumbo_barcode_id}")

        return {
            "id": str(new_current.id),
            "jumbo_barcode_id": new_current.jumbo_barcode_id,
            "created_at": new_current.created_at.isoformat(),
            "updated_at": None,
            "message": f"Current jumbo roll set to {jumbo_barcode_id}",
            "action": "created"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting current jumbo roll: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current-jumbo", response_model=Dict[str, Any], tags=["Current Jumbo Roll"])
def get_current_jumbo_roll(db: Session = Depends(get_db)):
    """Get the most recently added jumbo roll from history"""
    try:
        # Get the latest record by created_at timestamp
        current_jumbo = db.query(models.CurrentJumboRoll).order_by(
            models.CurrentJumboRoll.created_at.desc()
        ).first()

        if not current_jumbo:
            return {
                "current_jumbo": None,
                "message": "No current jumbo roll set"
            }

        # Get full jumbo roll details from inventory
        jumbo_roll = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.barcode_id == current_jumbo.jumbo_barcode_id
        ).first()

        return {
            "current_jumbo": {
                "id": str(current_jumbo.id),
                "jumbo_barcode_id": current_jumbo.jumbo_barcode_id,
                "created_at": current_jumbo.created_at.isoformat(),
                "updated_at": current_jumbo.updated_at.isoformat() if current_jumbo.updated_at else None,
                "jumbo_details": {
                    "id": str(jumbo_roll.id) if jumbo_roll else None,
                    "width_inches": float(jumbo_roll.width_inches) if jumbo_roll else None,
                    "weight_kg": float(jumbo_roll.weight_kg) if jumbo_roll else None,
                    "status": jumbo_roll.status if jumbo_roll else None,
                    "location": jumbo_roll.location if jumbo_roll else None
                } if jumbo_roll else None
            },
            "message": "Current jumbo roll retrieved successfully"
        }

    except Exception as e:
        logger.error(f"Error getting current jumbo roll: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# JUMBO ROLL LOOKUP + WEIGHT UPDATE
# ============================================================================

@router.get("/jumbo-rolls/{barcode_id}", response_model=Dict[str, Any], tags=["Jumbo Roll Weight"])
def get_jumbo_roll_by_barcode(barcode_id: str, db: Session = Depends(get_db)):
    """Look up a jumbo roll by its barcode ID (JR_xxxxx)."""
    roll = db.query(models.InventoryMaster).filter(
        models.InventoryMaster.barcode_id == barcode_id,
        models.InventoryMaster.roll_type == "jumbo"
    ).first()

    if not roll:
        raise HTTPException(status_code=404, detail=f"Jumbo roll '{barcode_id}' not found")

    paper = roll.paper
    return {
        "id": str(roll.id),
        "barcode_id": roll.barcode_id,
        "width_inches": float(roll.width_inches),
        "weight_kg": float(roll.weight_kg),
        "status": roll.status,
        "location": roll.location,
        "paper_specs": {
            "gsm": paper.gsm,
            "bf": float(paper.bf),
            "shade": paper.shade,
        } if paper else None,
        "created_at": roll.created_at.isoformat(),
        "updated_at": roll.updated_at.isoformat() if roll.updated_at else None,
    }


@router.put("/jumbo-rolls/{barcode_id}/weight", response_model=Dict[str, Any], tags=["Jumbo Roll Weight"])
def update_jumbo_roll_weight(barcode_id: str, body: JumboWeightUpdate, db: Session = Depends(get_db)):
    """Update the weight of a jumbo roll."""
    if body.weight_kg <= 0:
        raise HTTPException(status_code=400, detail="Weight must be greater than 0")

    roll = db.query(models.InventoryMaster).filter(
        models.InventoryMaster.barcode_id == barcode_id,
        models.InventoryMaster.roll_type == "jumbo"
    ).first()

    if not roll:
        raise HTTPException(status_code=404, detail=f"Jumbo roll '{barcode_id}' not found")

    old_weight = float(roll.weight_kg)
    roll.weight_kg = body.weight_kg
    roll.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(roll)

    logger.info(f"✅ Jumbo roll {barcode_id} weight updated: {old_weight}kg → {body.weight_kg}kg")

    return {
        "barcode_id": barcode_id,
        "old_weight_kg": old_weight,
        "new_weight_kg": float(roll.weight_kg),
        "message": f"Weight updated from {old_weight}kg to {body.weight_kg}kg",
    }
