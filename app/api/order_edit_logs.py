"""
API endpoints for Order Edit Logs
"""
from datetime import date
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..crud.order_edit_logs import order_edit_log

router = APIRouter()


@router.get("/order-edit-logs", response_model=Dict[str, Any])
async def get_order_edit_logs(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    order_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Get order edit logs with pagination and filtering
    """
    try:
        # Get logs with details
        logs = order_edit_log.get_logs_with_details(
            db,
            skip=skip,
            limit=limit,
            order_id=order_id,
            user_id=user_id,
            action=action,
            start_date=start_date,
            end_date=end_date
        )

        # Get total count for pagination
        total_count = order_edit_log.get_logs_count(
            db,
            order_id=order_id,
            user_id=user_id,
            action=action,
            start_date=start_date,
            end_date=end_date
        )

        return {
            "logs": logs,
            "total_count": total_count,
            "skip": skip,
            "limit": limit,
            "has_more": total_count > (skip + limit)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching order edit logs: {str(e)}")


@router.get("/order-edit-logs/order/{order_id}", response_model=List[Dict[str, Any]])
async def get_order_edit_logs_by_order(
    order_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    Get edit logs for a specific order
    """
    try:
        logs = order_edit_log.get_logs_with_details(
            db,
            skip=skip,
            limit=limit,
            order_id=order_id
        )
        return logs

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching order edit logs: {str(e)}")


@router.get("/order-edit-logs/recent", response_model=List[Dict[str, Any]])
async def get_recent_order_edit_logs(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Get recent order edit logs for dashboard/activity feed
    """
    try:
        logs = order_edit_log.get_recent_logs(db, limit=limit)
        return logs

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching recent order edit logs: {str(e)}")


@router.get("/order-edit-logs/actions", response_model=List[str])
async def get_order_edit_log_actions(
    db: Session = Depends(get_db)
):
    """
    Get list of unique actions for filtering
    """
    try:
        actions = order_edit_log.get_unique_actions(db)
        return actions

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching order edit log actions: {str(e)}")


# Helper function to create log entries (used by other API endpoints)
def create_order_edit_log(
    db: Session,
    order_id: str,
    edited_by_id: str,
    action: str,
    field_name: Optional[str] = None,
    old_value: Optional[Any] = None,
    new_value: Optional[Any] = None,
    description: Optional[str] = None,
    request: Optional[Request] = None
):
    """
    Helper function to create order edit log entries
    """
    ip_address = None
    user_agent = None

    if request:
        # Get IP address from request
        ip_address = request.client.host if request.client else None

        # Get user agent from headers
        user_agent = request.headers.get("user-agent")

    return order_edit_log.create_log(
        db,
        order_id=order_id,
        edited_by_id=edited_by_id,
        action=action,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        description=description,
        ip_address=ip_address,
        user_agent=user_agent
    )