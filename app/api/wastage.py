from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from uuid import UUID
import logging

from ..database import get_db
from .. import models, schemas
from ..services.barcode_generator import BarcodeGenerator

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/wastage", response_model=schemas.PaginatedWastageResponse, tags=["Wastage Inventory"])
def get_wastage_inventory(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by frontend_id, barcode_id, or paper specs"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: Session = Depends(get_db)
):
    """Get paginated list of wastage inventory items"""
    try:
        # Start with base query including paper relationship
        query = db.query(models.WastageInventory).options(
            joinedload(models.WastageInventory.paper)
        )
        
        # Apply search filter
        if search:
            search_term = f"%{search.lower()}%"
            query = query.filter(
                models.WastageInventory.frontend_id.ilike(search_term) |
                models.WastageInventory.barcode_id.ilike(search_term)
            )
        
        # Apply status filter
        if status:
            query = query.filter(models.WastageInventory.status == status)
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        items = query.order_by(models.WastageInventory.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
        
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
        logger.error(f"Error getting wastage inventory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/wastage/{wastage_id}", response_model=schemas.WastageInventory, tags=["Wastage Inventory"])
def get_wastage_item(
    wastage_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a specific wastage inventory item by ID"""
    try:
        wastage_item = db.query(models.WastageInventory).options(
            joinedload(models.WastageInventory.paper)
        ).filter(models.WastageInventory.id == wastage_id).first()
        
        if not wastage_item:
            raise HTTPException(status_code=404, detail="Wastage item not found")
        
        return wastage_item
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting wastage item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/wastage/{wastage_id}/status", response_model=schemas.WastageInventory, tags=["Wastage Inventory"])
def update_wastage_status(
    wastage_id: UUID,
    status_update: Dict[str, str],
    db: Session = Depends(get_db)
):
    """Update the status of a wastage inventory item"""
    try:
        wastage_item = db.query(models.WastageInventory).filter(
            models.WastageInventory.id == wastage_id
        ).first()
        
        if not wastage_item:
            raise HTTPException(status_code=404, detail="Wastage item not found")
        
        # Update status
        new_status = status_update.get("status")
        if new_status:
            wastage_item.status = new_status
            wastage_item.updated_at = func.now()
        
        db.commit()
        db.refresh(wastage_item)
        
        return wastage_item
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating wastage status: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/wastage/stats/summary", response_model=Dict[str, Any], tags=["Wastage Inventory"])
def get_wastage_summary(db: Session = Depends(get_db)):
    """Get summary statistics for wastage inventory"""
    try:
        from sqlalchemy import func
        
        # Get basic counts
        total_rolls = db.query(models.WastageInventory).count()
        
        # Get total width
        total_width_result = db.query(func.sum(models.WastageInventory.width_inches)).scalar()
        total_width_inches = float(total_width_result) if total_width_result else 0.0
        
        # Get average width
        avg_width_result = db.query(func.avg(models.WastageInventory.width_inches)).scalar()
        avg_width_inches = float(avg_width_result) if avg_width_result else 0.0
        
        # Get available count
        available_rolls = db.query(models.WastageInventory).filter(
            models.WastageInventory.status == 'available'
        ).count()
        
        # Get used count
        used_rolls = db.query(models.WastageInventory).filter(
            models.WastageInventory.status == 'used'
        ).count()
        
        return {
            "total_rolls": total_rolls,
            "total_width_inches": total_width_inches,
            "avg_width_inches": avg_width_inches,
            "available_rolls": available_rolls,
            "used_rolls": used_rolls
        }
        
    except Exception as e:
        logger.error(f"Error getting wastage summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/wastage/{wastage_id}", tags=["Wastage Inventory"])
def delete_wastage_item(
    wastage_id: UUID,
    db: Session = Depends(get_db)
):
    """Delete a wastage inventory item"""
    try:
        wastage_item = db.query(models.WastageInventory).filter(
            models.WastageInventory.id == wastage_id
        ).first()
        
        if not wastage_item:
            raise HTTPException(status_code=404, detail="Wastage item not found")
        
        db.delete(wastage_item)
        db.commit()
        
        return {"message": "Wastage item deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting wastage item: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/wastage", response_model=schemas.WastageInventory, tags=["Wastage Inventory"])
def create_manual_wastage(
    wastage_data: schemas.WastageInventoryCreate,
    db: Session = Depends(get_db)
):
    """Create a manual wastage inventory item (Stock)"""
    try:
        # Validate that the paper exists
        paper = db.query(models.PaperMaster).filter(
            models.PaperMaster.id == wastage_data.paper_id
        ).first()

        if not paper:
            raise HTTPException(status_code=404, detail="Paper master record not found")

        # Generate barcode ID
        barcode_id = BarcodeGenerator.generate_wastage_barcode(db)

        # Create wastage inventory record
        wastage_item = models.WastageInventory(
            width_inches=wastage_data.width_inches,
            paper_id=wastage_data.paper_id,
            weight_kg=wastage_data.weight_kg or 0.0,
            reel_no=wastage_data.reel_no,
            source_plan_id=wastage_data.source_plan_id,
            source_jumbo_roll_id=wastage_data.source_jumbo_roll_id,
            individual_roll_number=wastage_data.individual_roll_number,
            status=wastage_data.status or "available",
            location=wastage_data.location or "WASTE_STORAGE",
            notes=wastage_data.notes,
            barcode_id=barcode_id
        )

        db.add(wastage_item)
        db.commit()
        db.refresh(wastage_item)

        logger.info(f"✅ MANUAL WASTAGE CREATED: {wastage_item.frontend_id} - {wastage_item.width_inches}\" {paper.shade} paper")

        return wastage_item

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating manual wastage: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/wastage/papers", response_model=List[schemas.PaperMaster], tags=["Wastage Inventory"])
def get_papers_for_wastage(db: Session = Depends(get_db)):
    """Get all active paper masters for wastage creation dropdown"""
    try:
        papers = db.query(models.PaperMaster).filter(
            models.PaperMaster.status == "active"
        ).order_by(models.PaperMaster.name).all()

        return papers

    except Exception as e:
        logger.error(f"Error getting papers for wastage: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/wastage/test-data", response_model=List[schemas.WastageInventory], tags=["Wastage Inventory"])
def create_test_wastage_data(db: Session = Depends(get_db)):
    """Create some test wastage data for development purposes"""
    try:
        # Get a sample paper record
        sample_paper = db.query(models.PaperMaster).first()
        if not sample_paper:
            raise HTTPException(status_code=400, detail="No paper master records found. Create papers first.")
        
        # Get a sample plan
        sample_plan = db.query(models.PlanMaster).first()
        if not sample_plan:
            raise HTTPException(status_code=400, detail="No plan records found. Create a plan first.")
        
        test_wastage_data = [
            {"width_inches": 12.5, "notes": "Test wastage 1"},
            {"width_inches": 15.0, "notes": "Test wastage 2"},
            {"width_inches": 18.5, "notes": "Test wastage 3"},
            {"width_inches": 10.2, "notes": "Test wastage 4"},
            {"width_inches": 20.0, "notes": "Test wastage 5"},
        ]
        
        created_wastage = []
        
        for i, wastage_data in enumerate(test_wastage_data):
            # Generate barcode
            barcode_id = BarcodeGenerator.generate_wastage_barcode(db)
            
            # Create wastage item
            wastage_item = models.WastageInventory(
                width_inches=wastage_data["width_inches"],
                paper_id=sample_paper.id,
                weight_kg=0.0,
                source_plan_id=sample_plan.id,
                status="available",
                location="WASTE_STORAGE",
                notes=wastage_data["notes"],
                barcode_id=barcode_id
            )
            
            db.add(wastage_item)
            db.flush()  # Get the frontend_id
            created_wastage.append(wastage_item)
        
        db.commit()
        
        # Refresh to get the relationships
        for item in created_wastage:
            db.refresh(item)
        
        return created_wastage
        
    except Exception as e:
        logger.error(f"Error creating test wastage data: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/wastage/search", response_model=List[schemas.WastageInventory], tags=["Wastage Inventory"])
def search_wastage(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(50, ge=1, le=100, description="Number of results to return"),
    db: Session = Depends(get_db)
):
    """Search wastage inventory by frontend_id, barcode_id, or paper specs"""
    try:
        query = db.query(models.WastageInventory).options(
            joinedload(models.WastageInventory.paper)
        )
        
        search_term = f"%{q.lower()}%"
        query = query.filter(
            models.WastageInventory.frontend_id.ilike(search_term) |
            models.WastageInventory.barcode_id.ilike(search_term)
        )
        
        results = query.limit(limit).all()
        return results
        
    except Exception as e:
        logger.error(f"Error searching wastage: {e}")
        raise HTTPException(status_code=500, detail=str(e))