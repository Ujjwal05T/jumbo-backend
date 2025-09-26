from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import logging

from .base import get_db
from .. import crud_operations, schemas

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# MATERIAL MASTER ENDPOINTS
# ============================================================================

@router.post("/materials", response_model=schemas.MaterialMaster, tags=["Material Master"])
def create_material(material: schemas.MaterialMasterCreate, db: Session = Depends(get_db)):
    """Create a new material in Material Master"""
    try:
        return crud_operations.create_material(db=db, material_data=material)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating material: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/materials", response_model=List[schemas.MaterialMaster], tags=["Material Master"])
def get_materials(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all materials with pagination"""
    try:
        return crud_operations.get_materials(db=db, skip=skip, limit=limit)
    except Exception as e:
        logger.error(f"Error getting materials: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/materials/{material_id}", response_model=schemas.MaterialMaster, tags=["Material Master"])
def get_material(material_id: UUID, db: Session = Depends(get_db)):
    """Get material by ID"""
    material = crud_operations.get_material(db=db, material_id=material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    return material

@router.put("/materials/{material_id}", response_model=schemas.MaterialMaster, tags=["Material Master"])
def update_material(
    material_id: UUID,
    material_update: schemas.MaterialMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update material information"""
    try:
        material = crud_operations.update_material(db=db, material_id=material_id, material_update=material_update)
        if not material:
            raise HTTPException(status_code=404, detail="Material not found")
        return material
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating material: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/materials/{material_id}", tags=["Material Master"])
def delete_material(material_id: UUID, db: Session = Depends(get_db)):
    """Delete material"""
    try:
        success = crud_operations.delete_material(db=db, material_id=material_id)
        if not success:
            raise HTTPException(status_code=404, detail="Material not found")
        return {"message": "Material deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting material: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# INWARD CHALLAN ENDPOINTS
# ============================================================================

@router.post("/inward-challans", response_model=schemas.InwardChallan, tags=["Inward Challan"])
def create_inward_challan(challan: schemas.InwardChallanCreate, db: Session = Depends(get_db)):
    """Create a new inward challan"""
    try:
        return crud_operations.create_inward_challan(db=db, challan_data=challan)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating inward challan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inward-challans", response_model=List[schemas.InwardChallan], tags=["Inward Challan"])
def get_inward_challans(
    skip: int = 0,
    limit: int = 100,
    material_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """Get all inward challans with pagination and optional material filter"""
    try:
        return crud_operations.get_inward_challans(db=db, skip=skip, limit=limit, material_id=material_id)
    except Exception as e:
        logger.error(f"Error getting inward challans: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inward-challans/{challan_id}", response_model=schemas.InwardChallan, tags=["Inward Challan"])
def get_inward_challan(challan_id: UUID, db: Session = Depends(get_db)):
    """Get inward challan by ID"""
    challan = crud_operations.get_inward_challan(db=db, challan_id=challan_id)
    if not challan:
        raise HTTPException(status_code=404, detail="Inward challan not found")
    return challan

@router.put("/inward-challans/{challan_id}", response_model=schemas.InwardChallan, tags=["Inward Challan"])
def update_inward_challan(
    challan_id: UUID,
    challan_update: schemas.InwardChallanUpdate,
    db: Session = Depends(get_db)
):
    """Update inward challan information"""
    try:
        challan = crud_operations.update_inward_challan(db=db, challan_id=challan_id, challan_update=challan_update)
        if not challan:
            raise HTTPException(status_code=404, detail="Inward challan not found")
        return challan
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating inward challan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/inward-challans/{challan_id}", tags=["Inward Challan"])
def delete_inward_challan(challan_id: UUID, db: Session = Depends(get_db)):
    """Delete inward challan"""
    try:
        success = crud_operations.delete_inward_challan(db=db, challan_id=challan_id)
        if not success:
            raise HTTPException(status_code=404, detail="Inward challan not found")
        return {"message": "Inward challan deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting inward challan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# OUTWARD CHALLAN ENDPOINTS
# ============================================================================

@router.post("/outward-challans", response_model=schemas.OutwardChallan, tags=["Outward Challan"])
def create_outward_challan(challan: schemas.OutwardChallanCreate, db: Session = Depends(get_db)):
    """Create a new outward challan"""
    try:
        return crud_operations.create_outward_challan(db=db, challan_data=challan)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating outward challan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/outward-challans", response_model=List[schemas.OutwardChallan], tags=["Outward Challan"])
def get_outward_challans(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all outward challans with pagination"""
    try:
        return crud_operations.get_outward_challans(db=db, skip=skip, limit=limit)
    except Exception as e:
        logger.error(f"Error getting outward challans: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/outward-challans/{challan_id}", response_model=schemas.OutwardChallan, tags=["Outward Challan"])
def get_outward_challan(challan_id: UUID, db: Session = Depends(get_db)):
    """Get outward challan by ID"""
    challan = crud_operations.get_outward_challan(db=db, challan_id=challan_id)
    if not challan:
        raise HTTPException(status_code=404, detail="Outward challan not found")
    return challan

@router.put("/outward-challans/{challan_id}", response_model=schemas.OutwardChallan, tags=["Outward Challan"])
def update_outward_challan(
    challan_id: UUID,
    challan_update: schemas.OutwardChallanUpdate,
    db: Session = Depends(get_db)
):
    """Update outward challan information"""
    try:
        challan = crud_operations.update_outward_challan(db=db, challan_id=challan_id, challan_update=challan_update)
        if not challan:
            raise HTTPException(status_code=404, detail="Outward challan not found")
        return challan
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating outward challan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/outward-challans/{challan_id}", tags=["Outward Challan"])
def delete_outward_challan(challan_id: UUID, db: Session = Depends(get_db)):
    """Delete outward challan"""
    try:
        success = crud_operations.delete_outward_challan(db=db, challan_id=challan_id)
        if not success:
            raise HTTPException(status_code=404, detail="Outward challan not found")
        return {"message": "Outward challan deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting outward challan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# SERIAL NUMBER ENDPOINTS
# ============================================================================

@router.get("/inward-challans/next-serial", tags=["Inward Challan"])
def get_next_inward_serial(db: Session = Depends(get_db)):
    """Get next available serial number for inward challans"""
    try:
        next_serial = crud_operations.get_next_inward_serial(db=db)
        return {"next_serial": next_serial}
    except Exception as e:
        logger.error(f"Error getting next inward serial: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/outward-challans/next-serial", tags=["Outward Challan"])
def get_next_outward_serial(db: Session = Depends(get_db)):
    """Get next available serial number for outward challans"""
    try:
        next_serial = crud_operations.get_next_outward_serial(db=db)
        return {"next_serial": next_serial}
    except Exception as e:
        logger.error(f"Error getting next outward serial: {e}")
        raise HTTPException(status_code=500, detail=str(e))