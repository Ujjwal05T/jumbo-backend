from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, Date
from typing import Optional, List
from uuid import UUID
from datetime import datetime, date
import logging

from ..database import get_db
from .. import models, schemas

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/production-data/by-date", response_model=schemas.ProductionData, tags=["Production Data"])
def get_production_data_by_date(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    db: Session = Depends(get_db)
):
    """Get production data for a specific date"""
    try:
        # Parse the date string
        try:
            query_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        # Query for exact date match (ignoring time component)
        production_data = db.query(models.ProductionData).filter(
            func.cast(models.ProductionData.date, Date) == query_date
        ).first()

        if not production_data:
            raise HTTPException(status_code=404, detail="No production data found for this date")

        return production_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting production data by date: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/production-data/report", tags=["Production Data"])
def get_production_data_report(
    from_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    to_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    columns: Optional[str] = Query(None, description="Comma-separated list of column names to include"),
    db: Session = Depends(get_db)
):
    """Get production data report with date range filtering and column selection"""
    try:
        # Parse dates
        try:
            start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(to_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        # Validate date range
        if start_date > end_date:
            raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

        # Query data within date range
        query = db.query(models.ProductionData).filter(
            func.cast(models.ProductionData.date, Date) >= start_date,
            func.cast(models.ProductionData.date, Date) <= end_date
        ).order_by(models.ProductionData.date)

        production_data = query.all()

        # Define all available columns
        all_columns = [
            "date", "production", "electricity", "coal", "bhushi", "dispatch_ton",
            "po_ton", "waste", "starch", "guar_gum", "pac", "rct", "s_seizing",
            "d_former", "sodium_silicate", "enzyme", "dsr", "ret_aid", "colour_dye"
        ]

        # Parse selected columns
        selected_columns = None
        if columns:
            selected_columns = [col.strip() for col in columns.split(",")]
            # Validate columns
            invalid_columns = [col for col in selected_columns if col not in all_columns]
            if invalid_columns:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid column names: {', '.join(invalid_columns)}"
                )
        else:
            # If no columns specified, return all
            selected_columns = all_columns

        # Build response with selected columns
        result = []
        for record in production_data:
            row = {}
            for col in selected_columns:
                if col == "date":
                    row[col] = record.date.isoformat()
                else:
                    row[col] = getattr(record, col)
            result.append(row)

        return {
            "from_date": from_date,
            "to_date": to_date,
            "columns": selected_columns,
            "count": len(result),
            "data": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating production data report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/production-data", response_model=schemas.ProductionData, tags=["Production Data"])
def create_or_update_production_data(
    production_data: schemas.ProductionDataCreate,
    db: Session = Depends(get_db)
):
    """Create or update production data for a specific date (upsert operation)"""
    try:
        # Extract date without time component
        query_date = production_data.date.date()

        # Check if data already exists for this date
        existing_data = db.query(models.ProductionData).filter(
            func.cast(models.ProductionData.date, Date) == query_date
        ).first()

        if existing_data:
            # Update existing record
            update_data = production_data.model_dump(exclude={'date'})
            for field, value in update_data.items():
                setattr(existing_data, field, value)

            existing_data.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(existing_data)

            logger.info(f"Updated production data for date: {query_date}")
            return existing_data
        else:
            # Create new record
            new_data = models.ProductionData(**production_data.model_dump())
            db.add(new_data)
            db.commit()
            db.refresh(new_data)

            logger.info(f"Created production data for date: {query_date}")
            return new_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating/updating production data: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/production-data/{production_data_id}", response_model=schemas.ProductionData, tags=["Production Data"])
def get_production_data(
    production_data_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a specific production data record by ID"""
    try:
        production_data = db.query(models.ProductionData).filter(
            models.ProductionData.id == production_data_id
        ).first()

        if not production_data:
            raise HTTPException(status_code=404, detail="Production data record not found")

        return production_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting production data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/production-data/{production_data_id}", response_model=schemas.ProductionData, tags=["Production Data"])
def update_production_data(
    production_data_id: UUID,
    production_data_update: schemas.ProductionDataUpdate,
    db: Session = Depends(get_db)
):
    """Update a production data record"""
    try:
        production_data = db.query(models.ProductionData).filter(
            models.ProductionData.id == production_data_id
        ).first()

        if not production_data:
            raise HTTPException(status_code=404, detail="Production data record not found")

        # Update fields if provided
        update_data = production_data_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(production_data, field, value)

        production_data.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(production_data)

        logger.info(f"Updated production data record: {production_data_id}")
        return production_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating production data: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/production-data/{production_data_id}", tags=["Production Data"])
def delete_production_data(
    production_data_id: UUID,
    db: Session = Depends(get_db)
):
    """Delete a production data record"""
    try:
        production_data = db.query(models.ProductionData).filter(
            models.ProductionData.id == production_data_id
        ).first()

        if not production_data:
            raise HTTPException(status_code=404, detail="Production data record not found")

        db.delete(production_data)
        db.commit()

        logger.info(f"Deleted production data record: {production_data_id}")
        return {"message": "Production data record deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting production data: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
