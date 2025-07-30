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
# PAPER MASTER ENDPOINTS
# ============================================================================

@router.post("/papers", response_model=schemas.PaperMaster, tags=["Paper Master"])
def create_paper(paper: schemas.PaperMasterCreate, db: Session = Depends(get_db)):
    """Create a new paper specification in Paper Master"""
    try:
        logger.info(f"Creating paper with data: {paper.model_dump()}")
        
        # Validate required fields
        if not paper.name or not paper.name.strip():
            raise HTTPException(status_code=400, detail="Paper name is required")
        if paper.gsm <= 0:
            raise HTTPException(status_code=400, detail="GSM must be positive")
        if paper.bf <= 0:
            raise HTTPException(status_code=400, detail="BF must be positive")
        if not paper.shade or not paper.shade.strip():
            raise HTTPException(status_code=400, detail="Shade is required")
            
        return crud_operations.create_paper(db=db, paper=paper)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating paper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/papers", response_model=List[schemas.PaperMaster], tags=["Paper Master"])
def get_papers(
    skip: int = 0,
    limit: int = 100,
    status: str = "active",
    db: Session = Depends(get_db)
):
    """Get all paper specifications with pagination and status filter"""
    try:
        return crud_operations.get_papers(db=db, skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting papers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/papers/{paper_id}", response_model=schemas.PaperMaster, tags=["Paper Master"])
def get_paper(paper_id: UUID, db: Session = Depends(get_db)):
    """Get paper specification by ID"""
    paper = crud_operations.get_paper(db=db, paper_id=paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper

@router.get("/papers/search", response_model=Optional[schemas.PaperMaster], tags=["Paper Master"])
def search_paper_by_specs(
    gsm: int,
    bf: float,
    shade: str,
    db: Session = Depends(get_db)
):
    """Search for paper by specifications (GSM, BF, Shade)"""
    try:
        return crud_operations.get_paper_by_specs(db=db, gsm=gsm, bf=bf, shade=shade)
    except Exception as e:
        logger.error(f"Error searching paper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/papers/{paper_id}", response_model=schemas.PaperMaster, tags=["Paper Master"])
def update_paper(
    paper_id: UUID,
    paper_update: schemas.PaperMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update paper specification"""
    try:
        paper = crud_operations.update_paper(db=db, paper_id=paper_id, paper_update=paper_update)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        return paper
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating paper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/papers/{paper_id}", tags=["Paper Master"])
def delete_paper(paper_id: UUID, db: Session = Depends(get_db)):
    """Delete (deactivate) paper specification"""
    try:
        success = crud_operations.delete_paper(db=db, paper_id=paper_id)
        if not success:
            raise HTTPException(status_code=404, detail="Paper not found")
        return {"message": "Paper specification deactivated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting paper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/papers/debug/validation", tags=["Paper Master"])
def debug_paper_validation(db: Session = Depends(get_db)):
    """Debug endpoint to check paper validation and duplicates"""
    try:
        return crud_operations.debug_paper_validation(db=db)
    except Exception as e:
        logger.error(f"Error in paper debug validation: {e}")
        raise HTTPException(status_code=500, detail=str(e))