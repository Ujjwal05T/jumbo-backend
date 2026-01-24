from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import logging

from ..database import get_db
from .. import models, schemas

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/quality-check", response_model=schemas.PaginatedQualityCheckResponse, tags=["Quality Check"])
def get_quality_checks(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=1000, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by barcode_id"),
    db: Session = Depends(get_db)
):
    """Get paginated list of quality check records"""
    try:
        # Start with base query
        query = db.query(models.QualityCheck)
        
        # Apply search filter
        if search:
            search_term = f"%{search.lower()}%"
            query = query.filter(
                models.QualityCheck.barcode_id.ilike(search_term)
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        items = query.order_by(models.QualityCheck.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
        
        # Calculate pagination info
        total_pages = (total + per_page - 1) // per_page
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages
        }
        
    except Exception as e:
        logger.error(f"Error getting quality checks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/quality-check/{quality_check_id}", response_model=schemas.QualityCheck, tags=["Quality Check"])
def get_quality_check(
    quality_check_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a specific quality check record by ID"""
    try:
        quality_check = db.query(models.QualityCheck).filter(
            models.QualityCheck.id == quality_check_id
        ).first()
        
        if not quality_check:
            raise HTTPException(status_code=404, detail="Quality check record not found")
        
        return quality_check
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting quality check: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/quality-check/barcode/{barcode_id}", response_model=schemas.QualityCheck, tags=["Quality Check"])
def get_quality_check_by_barcode(
    barcode_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific quality check record by barcode ID"""
    try:
        quality_check = db.query(models.QualityCheck).filter(
            models.QualityCheck.barcode_id == barcode_id
        ).first()
        
        if not quality_check:
            raise HTTPException(status_code=404, detail="Quality check record not found for this barcode")
        
        return quality_check
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting quality check by barcode: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/quality-check/bulk", response_model=List[schemas.QualityCheck], tags=["Quality Check"])
def get_quality_checks_by_barcodes(
    barcode_ids: List[str],
    db: Session = Depends(get_db)
):
    """Get quality check records for multiple barcode IDs"""
    try:
        if not barcode_ids:
            return []
        
        quality_checks = db.query(models.QualityCheck).filter(
            models.QualityCheck.barcode_id.in_(barcode_ids)
        ).all()
        
        return quality_checks
        
    except Exception as e:
        logger.error(f"Error getting quality checks by barcodes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/quality-check", response_model=schemas.QualityCheck, tags=["Quality Check"])
def create_quality_check(
    quality_check_data: schemas.QualityCheckCreate,
    db: Session = Depends(get_db)
):
    """Create a new quality check record"""
    try:
        # Check if barcode already exists
        existing = db.query(models.QualityCheck).filter(
            models.QualityCheck.barcode_id == quality_check_data.barcode_id
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Quality check record already exists for this barcode")
        
        # Create new quality check record
        quality_check = models.QualityCheck(**quality_check_data.model_dump())
        
        db.add(quality_check)
        db.commit()
        db.refresh(quality_check)
        
        logger.info(f"Created quality check record for barcode: {quality_check.barcode_id}")
        return quality_check
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating quality check: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/quality-check/{quality_check_id}", response_model=schemas.QualityCheck, tags=["Quality Check"])
def update_quality_check(
    quality_check_id: UUID,
    quality_check_update: schemas.QualityCheckUpdate,
    db: Session = Depends(get_db)
):
    """Update a quality check record"""
    try:
        quality_check = db.query(models.QualityCheck).filter(
            models.QualityCheck.id == quality_check_id
        ).first()

        if not quality_check:
            raise HTTPException(status_code=404, detail="Quality check record not found")

        # Update fields if provided
        update_data = quality_check_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(quality_check, field, value)

        db.commit()
        db.refresh(quality_check)
        
        logger.info(f"Updated quality check record: {quality_check_id}")
        return quality_check

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating quality check: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/quality-check/{quality_check_id}", tags=["Quality Check"])
def delete_quality_check(
    quality_check_id: UUID,
    db: Session = Depends(get_db)
):
    """Delete a quality check record"""
    try:
        quality_check = db.query(models.QualityCheck).filter(
            models.QualityCheck.id == quality_check_id
        ).first()

        if not quality_check:
            raise HTTPException(status_code=404, detail="Quality check record not found")

        db.delete(quality_check)
        db.commit()
        
        logger.info(f"Deleted quality check record: {quality_check_id}")
        return {"message": "Quality check record deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting quality check: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
