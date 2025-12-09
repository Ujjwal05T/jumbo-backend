from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import logging

from .base import get_db
from .. import crud_operations, schemas

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# CLIENT MASTER ENDPOINTS
# ============================================================================

@router.post("/clients", response_model=schemas.ClientMaster, tags=["Client Master"])
def create_client(client: schemas.ClientMasterCreate, db: Session = Depends(get_db)):
    """Create a new client in Client Master"""
    try:
        return crud_operations.create_client(db=db, client_data=client)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating client: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/clients", response_model=List[schemas.ClientMaster], tags=["Client Master"])
def get_clients(
    skip: int = 0,
    limit: int = 1000,
    status: str = "active",
    db: Session = Depends(get_db)
):
    """Get all clients with pagination and status filter"""
    try:
        return crud_operations.get_clients(db=db, skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting clients: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/clients/{client_id}", response_model=schemas.ClientMaster, tags=["Client Master"])
def get_client(client_id: UUID, db: Session = Depends(get_db)):
    """Get client by ID"""
    client = crud_operations.get_client(db=db, client_id=client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client

@router.put("/clients/{client_id}", response_model=schemas.ClientMaster, tags=["Client Master"])
def update_client(
    client_id: UUID,
    client_update: schemas.ClientMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update client information"""
    try:
        client = crud_operations.update_client(db=db, client_id=client_id, client_update=client_update)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        return client
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating client: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/clients/{client_id}", tags=["Client Master"])
def delete_client(client_id: UUID, db: Session = Depends(get_db)):
    """Delete (deactivate) client"""
    try:
        success = crud_operations.delete_client(db=db, client_id=client_id)
        if not success:
            raise HTTPException(status_code=404, detail="Client not found")
        return {"message": "Client deactivated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting client: {e}")
        raise HTTPException(status_code=500, detail=str(e))