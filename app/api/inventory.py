from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from uuid import UUID
import logging
from datetime import datetime

from .base import get_db
from .. import crud_operations, schemas, models
from ..services.id_generator import FrontendIDGenerator
from ..services.barcode_generator import BarcodeGenerator

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# INVENTORY MASTER ENDPOINTS
# ============================================================================

@router.post("/inventory", response_model=schemas.InventoryMaster, tags=["Inventory Master"])
def create_inventory_item(inventory: schemas.InventoryMasterCreate, db: Session = Depends(get_db)):
    """Create a new inventory item"""
    try:
        return crud_operations.create_inventory_item(db=db, inventory=inventory)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating inventory item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory", response_model=List[schemas.InventoryMaster], tags=["Inventory Master"])
def get_inventory_items(
    skip: int = 0,
    limit: int = 100,
    roll_type: str = None,
    status: str = "available",
    db: Session = Depends(get_db)
):
    """Get all inventory items with pagination and filters"""
    try:
        return crud_operations.get_inventory_items(db=db, skip=skip, limit=limit, roll_type=roll_type, status=status)
    except Exception as e:
        logger.error(f"Error getting inventory items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory/{inventory_id}", response_model=schemas.InventoryMaster, tags=["Inventory Master"])
def get_inventory_item(inventory_id: UUID, db: Session = Depends(get_db)):
    """Get inventory item by ID"""
    item = crud_operations.get_inventory_item(db=db, inventory_id=inventory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item

@router.put("/inventory/{inventory_id}", response_model=schemas.InventoryMaster, tags=["Inventory Master"])
def update_inventory_item(
    inventory_id: UUID,
    inventory_update: schemas.InventoryMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update inventory item"""
    try:
        item = crud_operations.update_inventory_item(db=db, inventory_id=inventory_id, inventory_update=inventory_update)
        if not item:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        return item
    except Exception as e:
        logger.error(f"Error updating inventory item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory/jumbo-rolls", response_model=List[schemas.InventoryMaster], tags=["Inventory Master"])
def get_jumbo_rolls(
    skip: int = 0,
    limit: int = 100,
    status: str = "available",
    db: Session = Depends(get_db)
):
    """Get jumbo rolls with pagination"""
    try:
        return crud_operations.get_inventory_by_type(db=db, roll_type="jumbo", skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting jumbo rolls: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory/cut-rolls", response_model=List[schemas.InventoryMaster], tags=["Inventory Master"])
def get_cut_rolls(
    skip: int = 0,
    limit: int = 100,
    status: str = "available",
    db: Session = Depends(get_db)
):
    """Get cut rolls with pagination"""
    try:
        return crud_operations.get_inventory_by_type(db=db, roll_type="cut", skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting cut rolls: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory/available/{paper_id}", response_model=List[schemas.InventoryMaster], tags=["Inventory Master"])
def get_available_inventory(
    paper_id: UUID,
    roll_type: str = None,
    db: Session = Depends(get_db)
):
    """Get available inventory for specific paper specification"""
    try:
        return crud_operations.get_available_inventory_by_paper(db=db, paper_id=paper_id, roll_type=roll_type)
    except Exception as e:
        logger.error(f"Error getting available inventory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/inventory/{inventory_id}/status", response_model=schemas.InventoryMaster, tags=["Inventory Management"])
def update_inventory_status(
    inventory_id: str,
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Update inventory item status"""
    try:
        import uuid
        inventory_uuid = uuid.UUID(inventory_id)
        new_status = request_data.get("status")

        if not new_status:
            raise HTTPException(status_code=400, detail="Status is required")

        updated_item = crud_operations.update_inventory_status(db=db, inventory_id=inventory_uuid, new_status=new_status)
        if not updated_item:
            raise HTTPException(status_code=404, detail="Inventory item not found")

        return updated_item
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid inventory ID format")
    except Exception as e:
        logger.error(f"Error updating inventory status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# MANUAL CUT ROLL ENDPOINTS
# ============================================================================

@router.post("/manual-cut-rolls", tags=["Manual Cut Rolls"])
def create_manual_cut_roll(
    roll_data: schemas.ManualCutRollCreate,
    db: Session = Depends(get_db)
):
    """Create a manual cut roll entry"""
    try:
        # Validate client exists
        client = crud_operations.get_client(db, roll_data.client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # Validate paper exists
        paper = crud_operations.get_paper(db, roll_data.paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        # Generate unique barcode_id in CR_08000-09000 range
        barcode_id = BarcodeGenerator.generate_manual_cut_roll_barcode(db)

        # Generate frontend_id (MCR format for internal tracking)
        frontend_id = FrontendIDGenerator.generate_frontend_id("manual_cut_roll", db)

        # Create manual cut roll record
        manual_roll = models.ManualCutRoll(
            frontend_id=frontend_id,
            barcode_id=barcode_id,
            client_id=roll_data.client_id,
            paper_id=roll_data.paper_id,
            reel_number=roll_data.reel_number,
            width_inches=float(roll_data.width_inches),
            weight_kg=float(roll_data.weight_kg),
            status="available",
            location="MANUAL_STORAGE",
            created_by_id=roll_data.created_by_id,
            created_at=datetime.utcnow()
        )

        db.add(manual_roll)
        db.commit()
        db.refresh(manual_roll)

        logger.info(f"Created manual cut roll {frontend_id} for client {client.company_name}")

        return {
            "message": "Manual cut roll created successfully",
            "manual_cut_roll_id": str(manual_roll.id),
            "frontend_id": manual_roll.frontend_id,
            "barcode_id": manual_roll.barcode_id,
            "client_name": client.company_name,
            "paper_spec": f"{paper.gsm}gsm, {paper.bf}bf, {paper.shade}",
            "reel_number": manual_roll.reel_number,
            "width_inches": float(manual_roll.width_inches),
            "weight_kg": float(manual_roll.weight_kg),
            "status": manual_roll.status
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating manual cut roll: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/manual-cut-rolls", tags=["Manual Cut Rolls"])
def get_manual_cut_rolls(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    client_id: str = None,
    db: Session = Depends(get_db)
):
    """Get all manual cut rolls with optional filters"""
    try:
        query = db.query(models.ManualCutRoll)

        if status:
            query = query.filter(models.ManualCutRoll.status == status)

        if client_id:
            import uuid
            query = query.filter(models.ManualCutRoll.client_id == uuid.UUID(client_id))

        manual_rolls = query.offset(skip).limit(limit).all()

        return {
            "manual_cut_rolls": [
                {
                    "id": str(roll.id),
                    "frontend_id": roll.frontend_id,
                    "barcode_id": roll.barcode_id,
                    "client_id": str(roll.client_id),
                    "client_name": roll.client.company_name if roll.client else "N/A",
                    "paper_id": str(roll.paper_id),
                    "paper_spec": f"{roll.paper.gsm}gsm, {roll.paper.bf}bf, {roll.paper.shade}" if roll.paper else "N/A",
                    "reel_number": roll.reel_number,
                    "width_inches": float(roll.width_inches),
                    "weight_kg": float(roll.weight_kg),
                    "status": roll.status,
                    "location": roll.location,
                    "created_at": roll.created_at.isoformat() if roll.created_at else None,
                    "created_by": roll.created_by.username if roll.created_by else "N/A"
                }
                for roll in manual_rolls
            ],
            "total": query.count()
        }

    except Exception as e:
        logger.error(f"Error getting manual cut rolls: {e}")
        raise HTTPException(status_code=500, detail=str(e))