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