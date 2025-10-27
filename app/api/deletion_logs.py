"""
Plan Deletion Logs API
API endpoints for accessing plan deletion audit logs
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_
from datetime import datetime, timedelta
from uuid import UUID
import json

from ..database import get_db
from .. import models
from ..crud import plan_deletion_logs

router = APIRouter()

def validate_uuid(uuid_string: str) -> UUID:
    """Validate and convert string to UUID"""
    try:
        return UUID(uuid_string)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid UUID format: {uuid_string}"
        )

@router.get("/deletion-logs/test", tags=["Deletion Logs"])
async def test_deletion_logs():
    """Test endpoint to verify CRUD module loading"""
    try:
        # Try to create a new instance directly
        from ..crud.plan_deletion_logs import CRUDPlanDeletionLog
        test_instance = CRUDPlanDeletionLog()

        # Test if the method exists on the new instance
        if hasattr(test_instance, 'get_deletion_logs'):
            return {"message": "CRUD module loaded successfully", "method_exists": True, "instance_method": True}
        else:
            available_methods = [m for m in dir(test_instance) if not m.startswith('_') and callable(getattr(test_instance, m))]
            return {"message": "CRUD module loaded but method missing", "method_exists": False, "available_methods": available_methods}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/deletion-logs", tags=["Deletion Logs"])
async def get_deletion_logs(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    plan_id: Optional[str] = Query(None, description="Filter by plan ID"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    deletion_reason: Optional[str] = Query(None, description="Filter by deletion reason"),
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    success_status: Optional[str] = Query(None, description="Filter by success status"),
    db: Session = Depends(get_db)
):
    """Get paginated plan deletion logs with optional filtering"""
    try:
        # Use direct import as workaround
        from ..crud.plan_deletion_logs import CRUDPlanDeletionLog
        crud_instance = CRUDPlanDeletionLog()

        result = crud_instance.get_deletion_logs(
            db=db,
            page=page,
            page_size=page_size,
            plan_id=plan_id,
            user_id=user_id,
            deletion_reason=deletion_reason,
            start_date=start_date,
            end_date=end_date,
            success_status=success_status
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/deletion-logs/plan/{plan_id}", tags=["Deletion Logs"])
async def get_deletion_logs_by_plan(
    plan_id: str,
    db: Session = Depends(get_db)
):
    """Get deletion logs for a specific plan"""
    try:
        # Validate UUID format
        validated_plan_id = validate_uuid(plan_id)
        logs = plan_deletion_logs.get_deletion_logs_by_plan(db, validated_plan_id)
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/deletion-logs/user/{user_id}", tags=["Deletion Logs"])
async def get_deletion_logs_by_user(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get deletion logs for a specific user"""
    try:
        # Validate UUID format
        validated_user_id = validate_uuid(user_id)
        logs = plan_deletion_logs.get_deletion_logs_by_user(db, validated_user_id)
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/deletion-logs/recent", tags=["Deletion Logs"])
async def get_recent_deletion_logs(
    limit: int = Query(10, ge=1, le=50, description="Number of recent logs to return"),
    db: Session = Depends(get_db)
):
    """Get recent plan deletion logs"""
    try:
        logs = plan_deletion_logs.get_recent_deletion_logs(db, limit)
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/deletion-logs/export", tags=["Deletion Logs"])
async def export_deletion_logs(
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    deletion_reason: Optional[str] = Query(None, description="Filter by deletion reason"),
    success_status: Optional[str] = Query(None, description="Filter by success status"),
    db: Session = Depends(get_db)
):
    """Export deletion logs as CSV"""
    try:
        # Get all logs matching the criteria (no pagination for export)
        result = plan_deletion_logs.get_deletion_logs(
            db=db,
            page=1,
            page_size=10000,  # Large number for export
            start_date=start_date,
            end_date=end_date,
            deletion_reason=deletion_reason,
            success_status=success_status
        )

        # Convert to CSV format
        logs = result['logs']

        # Create CSV headers
        headers = [
            "ID", "Plan ID", "Plan Frontend ID", "Plan Name", "Deleted At",
            "Deleted By", "Deletion Reason", "Success Status", "Error Message",
            "Rollback Duration (seconds)", "Inventory Deleted", "Wastage Deleted",
            "Wastage Restored", "Orders Restored", "Order Items Restored",
            "Pending Orders Deleted", "Pending Orders Restored", "Links Deleted"
        ]

        # Convert logs to CSV rows
        csv_rows = []
        for log in logs:
            rollback_stats = log.rollback_stats or {}
            row = [
                str(log.id),
                str(log.plan_id) if log.plan_id else "",
                log.plan_frontend_id,
                log.plan_name or "",
                log.deleted_at.isoformat() if log.deleted_at else "",
                log.deleted_by_user.name if log.deleted_by_user else "Unknown",
                log.deletion_reason,
                log.success_status,
                log.error_message or "",
                str(log.rollback_duration_seconds) if log.rollback_duration_seconds else "",
                str(rollback_stats.get('inventory_deleted', 0)),
                str(rollback_stats.get('wastage_deleted', 0)),
                str(rollback_stats.get('wastage_restored', 0)),
                str(rollback_stats.get('orders_restored', 0)),
                str(rollback_stats.get('order_items_restored', 0)),
                str(rollback_stats.get('pending_orders_deleted', 0)),
                str(rollback_stats.get('pending_orders_restored', 0)),
                str(rollback_stats.get('links_deleted', 0))
            ]
            csv_rows.append(row)

        # Create CSV content
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(csv_rows)

        # Return CSV response
        from fastapi.responses import Response

        csv_content = output.getvalue()
        output.close()

        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=plan_deletion_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/deletion-logs/{log_id}", tags=["Deletion Logs"])
async def get_deletion_log_by_id(
    log_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific deletion log by ID"""
    try:
        # Validate UUID format
        validated_log_id = validate_uuid(log_id)

        log = db.query(models.PlanDeletionLog).filter(
            models.PlanDeletionLog.id == validated_log_id
        ).first()

        if not log:
            raise HTTPException(status_code=404, detail="Deletion log not found")

        # Include user information
        log_data = {
            "id": log.id,
            "plan_id": log.plan_id,
            "plan_frontend_id": log.plan_frontend_id,
            "plan_name": log.plan_name,
            "deleted_at": log.deleted_at.isoformat() if log.deleted_at else None,
            "deleted_by_id": log.deleted_by_id,
            "deletion_reason": log.deletion_reason,
            "rollback_stats": log.rollback_stats,
            "rollback_duration_seconds": log.rollback_duration_seconds,
            "success_status": log.success_status,
            "error_message": log.error_message,
            "deleted_by_user": {
                "id": log.deleted_by_user.id if log.deleted_by_user else None,
                "name": log.deleted_by_user.name if log.deleted_by_user else None,
                "username": log.deleted_by_user.username if log.deleted_by_user else None,
            } if log.deleted_by_user else None
        }

        return log_data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))