"""
Inventory Items API endpoints
Handles CRUD operations for imported inventory items with filtering and pagination
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional
from datetime import datetime, date

from ..database import get_db
from ..models import InventoryItem
from ..schemas import (
    InventoryItem as InventoryItemSchema,
    InventoryItemCreate,
    InventoryItemUpdate,
    PaginatedInventoryItemsResponse
)

router = APIRouter()

@router.get("/", response_model=PaginatedInventoryItemsResponse)
def get_inventory_items(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=1000, description="Items per page"),
    search: Optional[str] = Query(None, description="Search in reel_no, size, grade"),
    gsm: Optional[int] = Query(None, description="Filter by GSM"),
    bf: Optional[int] = Query(None, description="Filter by BF"),
    grade: Optional[str] = Query(None, description="Filter by grade"),
    start_date: Optional[date] = Query(None, description="Filter by stock date (start)"),
    end_date: Optional[date] = Query(None, description="Filter by stock date (end)"),
    min_weight: Optional[float] = Query(None, description="Minimum weight filter"),
    max_weight: Optional[float] = Query(None, description="Maximum weight filter"),
    db: Session = Depends(get_db)
):
    """Get paginated list of inventory items with optional filters"""
    
    query = db.query(InventoryItem)
    
    # Apply filters
    filters = []
    
    # Search filter
    if search:
        search_filter = or_(
            InventoryItem.reel_no.ilike(f"%{search}%"),
            InventoryItem.size.ilike(f"%{search}%"),
            InventoryItem.grade.ilike(f"%{search}%")
        )
        filters.append(search_filter)
    
    # Numeric filters
    if gsm is not None:
        filters.append(InventoryItem.gsm == gsm)
    
    if bf is not None:
        filters.append(InventoryItem.bf == bf)
    
    if grade:
        filters.append(InventoryItem.grade.ilike(f"%{grade}%"))
    
    # Date range filter
    if start_date:
        filters.append(InventoryItem.stock_date >= start_date)
    
    if end_date:
        filters.append(InventoryItem.stock_date <= end_date)
    
    # Weight range filter
    if min_weight is not None:
        filters.append(InventoryItem.weight_kg >= min_weight)
    
    if max_weight is not None:
        filters.append(InventoryItem.weight_kg <= max_weight)
    
    # Apply all filters
    if filters:
        query = query.filter(and_(*filters))
    
    # Order by stock_id descending (newest first)
    query = query.order_by(InventoryItem.stock_id.desc())
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * per_page
    items = query.offset(offset).limit(per_page).all()
    
    # Calculate total pages
    total_pages = (total + per_page - 1) // per_page
    
    return PaginatedInventoryItemsResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages
    )

@router.get("/stats")
def get_inventory_stats(db: Session = Depends(get_db)):
    """Get inventory statistics"""
    
    stats = db.query(
        func.count(InventoryItem.stock_id).label('total_items'),
        func.sum(InventoryItem.weight_kg).label('total_weight'),
        func.avg(InventoryItem.weight_kg).label('avg_weight'),
        func.count(func.distinct(InventoryItem.gsm)).label('unique_gsm'),
        func.count(func.distinct(InventoryItem.bf)).label('unique_bf'),
        func.count(func.distinct(InventoryItem.grade)).label('unique_grades')
    ).first()
    
    # Get date range
    date_range = db.query(
        func.min(InventoryItem.stock_date).label('earliest_date'),
        func.max(InventoryItem.stock_date).label('latest_date')
    ).first()
    
    return {
        "total_items": stats.total_items or 0,
        "total_weight_kg": float(stats.total_weight or 0),
        "average_weight_kg": float(stats.avg_weight or 0),
        "unique_gsm_values": stats.unique_gsm or 0,
        "unique_bf_values": stats.unique_bf or 0,
        "unique_grades": stats.unique_grades or 0,
        "date_range": {
            "earliest": date_range.earliest_date,
            "latest": date_range.latest_date
        }
    }

@router.get("/filters")
def get_filter_options(db: Session = Depends(get_db)):
    """Get available filter options for dropdowns"""
    
    gsm_options = db.query(InventoryItem.gsm).distinct().filter(
        InventoryItem.gsm.is_not(None)
    ).order_by(InventoryItem.gsm).all()
    
    bf_options = db.query(InventoryItem.bf).distinct().filter(
        InventoryItem.bf.is_not(None)
    ).order_by(InventoryItem.bf).all()
    
    grade_options = db.query(InventoryItem.grade).distinct().filter(
        InventoryItem.grade.is_not(None)
    ).order_by(InventoryItem.grade).all()
    
    return {
        "gsm_options": [item.gsm for item in gsm_options],
        "bf_options": [item.bf for item in bf_options],
        "grade_options": [item.grade for item in grade_options]
    }

@router.get("/{stock_id}", response_model=InventoryItemSchema)
def get_inventory_item(stock_id: int, db: Session = Depends(get_db)):
    """Get a single inventory item by ID"""
    
    item = db.query(InventoryItem).filter(InventoryItem.stock_id == stock_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    
    return item

@router.put("/{stock_id}", response_model=InventoryItemSchema)
def update_inventory_item(
    stock_id: int,
    item_update: InventoryItemUpdate,
    db: Session = Depends(get_db)
):
    """Update an inventory item"""
    
    db_item = db.query(InventoryItem).filter(InventoryItem.stock_id == stock_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    
    # Update fields
    update_data = item_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_item, field, value)
    
    db.commit()
    db.refresh(db_item)
    
    return db_item

@router.delete("/{stock_id}")
def delete_inventory_item(stock_id: int, db: Session = Depends(get_db)):
    """Delete an inventory item"""
    
    db_item = db.query(InventoryItem).filter(InventoryItem.stock_id == stock_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    
    db.delete(db_item)
    db.commit()
    
    return {"message": "Inventory item deleted successfully"}

@router.post("/", response_model=InventoryItemSchema)
def create_inventory_item(item: InventoryItemCreate, db: Session = Depends(get_db)):
    """Create a new inventory item"""
    
    db_item = InventoryItem(
        **item.model_dump(),
        record_imported_at=datetime.utcnow()
    )
    
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    
    return db_item