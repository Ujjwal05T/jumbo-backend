from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, and_, or_, text, case
from typing import Dict, List, Any, Optional
import logging
import uuid
import json
from datetime import datetime, timedelta

from .base import get_db
from .. import models, schemas

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/reports/paper-wise", tags=["Reports"])
def get_paper_wise_report(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Order status filter"),
    db: Session = Depends(get_db)
):
    """
    Get paper-wise analysis report grouped by paper name.
    Shows total orders, quantities, and values for each paper type.
    """
    try:
        # Build base query
        query = db.query(
            models.PaperMaster.name.label('paper_name'),
            models.PaperMaster.gsm.label('gsm'),
            models.PaperMaster.bf.label('bf'),
            models.PaperMaster.shade.label('shade'),
            models.PaperMaster.type.label('paper_type'),
            func.count(models.OrderMaster.id).label('total_orders'),
            func.sum(models.OrderItem.quantity_rolls).label('total_quantity_rolls'),
            func.sum(models.OrderItem.quantity_kg).label('total_quantity_kg'),
            func.sum(models.OrderItem.amount).label('total_value'),
            func.count(func.distinct(models.ClientMaster.id)).label('unique_clients'),
            # Order completion metrics
            func.sum(case((models.OrderMaster.status == 'completed', 1), else_=0)).label('completed_orders'),
            func.sum(case(
                (and_(models.OrderItem.quantity_fulfilled > 0, 
                      models.OrderItem.quantity_fulfilled < models.OrderItem.quantity_rolls), 1), 
                else_=0
            )).label('partially_completed_items'),
            func.sum(models.OrderItem.quantity_fulfilled).label('total_quantity_fulfilled')
        ).select_from(
            models.PaperMaster
        ).join(
            models.OrderItem, models.OrderItem.paper_id == models.PaperMaster.id
        ).join(
            models.OrderMaster, models.OrderMaster.id == models.OrderItem.order_id
        ).join(
            models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
        )
        
        # Apply filters
        filters = []
        
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                filters.append(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")
        
        if status:
            filters.append(models.OrderMaster.status == status)
        
        if filters:
            query = query.filter(and_(*filters))
        
        # Group by paper and order by total value
        results = query.group_by(
            models.PaperMaster.id,
            models.PaperMaster.name,
            models.PaperMaster.gsm,
            models.PaperMaster.bf,
            models.PaperMaster.shade,
            models.PaperMaster.type
        ).order_by(desc('total_value')).all()
        
        # Format results
        paper_analysis = []
        for result in results:
            total_orders = result.total_orders or 0
            completed_orders = result.completed_orders or 0
            total_quantity_rolls = result.total_quantity_rolls or 0
            total_quantity_fulfilled = result.total_quantity_fulfilled or 0
            
            paper_analysis.append({
                "paper_name": result.paper_name,
                "gsm": result.gsm,
                "bf": float(result.bf) if result.bf else 0,
                "shade": result.shade,
                "paper_type": result.paper_type,
                "total_orders": total_orders,
                "total_quantity_rolls": total_quantity_rolls,
                "total_quantity_kg": float(result.total_quantity_kg) if result.total_quantity_kg else 0,
                "total_value": float(result.total_value) if result.total_value else 0,
                "unique_clients": result.unique_clients,
                "avg_order_value": float(result.total_value / max(total_orders, 1)) if result.total_value else 0,
                # Completion metrics
                "completed_orders": completed_orders,
                "pending_orders": total_orders - completed_orders,
                "completion_rate": float(completed_orders / max(total_orders, 1) * 100),
                "total_quantity_fulfilled": total_quantity_fulfilled,
                "fulfillment_rate": float(total_quantity_fulfilled / max(total_quantity_rolls, 1) * 100),
                "partially_completed_items": result.partially_completed_items or 0
            })
        
        # Calculate summary
        total_orders = sum(item["total_orders"] for item in paper_analysis)
        total_value = sum(item["total_value"] for item in paper_analysis)
        total_quantity = sum(item["total_quantity_kg"] for item in paper_analysis)
        
        return {
            "status": "success",
            "data": paper_analysis,
            "summary": {
                "total_papers": len(paper_analysis),
                "total_orders": total_orders,
                "total_value": total_value,
                "total_quantity_kg": total_quantity,
                "avg_value_per_paper": total_value / max(len(paper_analysis), 1)
            },
            "filters_applied": {
                "start_date": start_date,
                "end_date": end_date,
                "status": status
            }
        }
        
    except Exception as e:
        logger.error(f"Error in paper-wise report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/client-wise", tags=["Reports"])
def get_client_wise_report(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Order status filter"),
    db: Session = Depends(get_db)
):
    """
    Get client-wise analysis report grouped by client company name.
    Shows total orders, quantities, and values for each client.
    """
    try:
        # Build base query
        query = db.query(
            models.ClientMaster.company_name.label('client_name'),
            models.ClientMaster.frontend_id.label('client_id'),
            models.ClientMaster.gst_number.label('gst_number'),
            models.ClientMaster.contact_person.label('contact_person'),
            func.count(models.OrderMaster.id).label('total_orders'),
            func.sum(models.OrderItem.quantity_rolls).label('total_quantity_rolls'),
            func.sum(models.OrderItem.quantity_kg).label('total_quantity_kg'),
            func.sum(models.OrderItem.amount).label('total_value'),
            func.count(func.distinct(models.PaperMaster.id)).label('unique_papers'),
            func.max(models.OrderMaster.created_at).label('last_order_date'),
            func.min(models.OrderMaster.created_at).label('first_order_date'),
            # Order completion metrics
            func.sum(case((models.OrderMaster.status == 'completed', 1), else_=0)).label('completed_orders'),
            func.sum(case(
                (and_(models.OrderItem.quantity_fulfilled > 0, 
                      models.OrderItem.quantity_fulfilled < models.OrderItem.quantity_rolls), 1), 
                else_=0
            )).label('partially_completed_items'),
            func.sum(models.OrderItem.quantity_fulfilled).label('total_quantity_fulfilled')
        ).select_from(
            models.ClientMaster
        ).join(
            models.OrderMaster, models.OrderMaster.client_id == models.ClientMaster.id
        ).join(
            models.OrderItem, models.OrderItem.order_id == models.OrderMaster.id
        ).join(
            models.PaperMaster, models.PaperMaster.id == models.OrderItem.paper_id
        )
        
        # Apply filters
        filters = []
        
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                filters.append(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")
        
        if status:
            filters.append(models.OrderMaster.status == status)
        
        if filters:
            query = query.filter(and_(*filters))
        
        # Group by client and order by total value
        results = query.group_by(
            models.ClientMaster.id,
            models.ClientMaster.company_name,
            models.ClientMaster.frontend_id,
            models.ClientMaster.gst_number,
            models.ClientMaster.contact_person
        ).order_by(desc('total_value')).all()
        
        # Format results
        client_analysis = []
        for result in results:
            total_orders = result.total_orders or 0
            completed_orders = result.completed_orders or 0
            total_quantity_rolls = result.total_quantity_rolls or 0
            total_quantity_fulfilled = result.total_quantity_fulfilled or 0
            
            client_analysis.append({
                "client_name": result.client_name,
                "client_id": result.client_id,
                "gst_number": result.gst_number,
                "contact_person": result.contact_person,
                "total_orders": total_orders,
                "total_quantity_rolls": total_quantity_rolls,
                "total_quantity_kg": float(result.total_quantity_kg) if result.total_quantity_kg else 0,
                "total_value": float(result.total_value) if result.total_value else 0,
                "unique_papers": result.unique_papers,
                "avg_order_value": float(result.total_value / max(total_orders, 1)) if result.total_value else 0,
                "last_order_date": result.last_order_date.isoformat() if result.last_order_date else None,
                "first_order_date": result.first_order_date.isoformat() if result.first_order_date else None,
                # Completion metrics
                "completed_orders": completed_orders,
                "pending_orders": total_orders - completed_orders,
                "completion_rate": float(completed_orders / max(total_orders, 1) * 100),
                "total_quantity_fulfilled": total_quantity_fulfilled,
                "fulfillment_rate": float(total_quantity_fulfilled / max(total_quantity_rolls, 1) * 100),
                "partially_completed_items": result.partially_completed_items or 0
            })
        
        # Calculate summary
        total_orders = sum(item["total_orders"] for item in client_analysis)
        total_value = sum(item["total_value"] for item in client_analysis)
        total_quantity = sum(item["total_quantity_kg"] for item in client_analysis)
        
        return {
            "status": "success",
            "data": client_analysis,
            "summary": {
                "total_clients": len(client_analysis),
                "total_orders": total_orders,
                "total_value": total_value,
                "total_quantity_kg": total_quantity,
                "avg_value_per_client": total_value / max(len(client_analysis), 1)
            },
            "filters_applied": {
                "start_date": start_date,
                "end_date": end_date,
                "status": status
            }
        }
        
    except Exception as e:
        logger.error(f"Error in client-wise report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/date-wise", tags=["Reports"])
def get_date_wise_report(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    group_by: str = Query("day", description="Grouping: day, week, month"),
    status: Optional[str] = Query(None, description="Order status filter"),
    db: Session = Depends(get_db)
):
    """
    Get date-wise analysis report grouped by time periods.
    Shows trends in orders, quantities, and values over time.
    """
    try:
        # Set default date range if not provided
        if not start_date:
            start_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Parse dates
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date + " 23:59:59")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Build date grouping expression - SQL Server compatible
        if group_by == "day":
            # SQL Server: Convert to date (removes time portion)
            date_group = func.convert(text('date'), models.OrderMaster.created_at)
        elif group_by == "week":
            # SQL Server: Get start of week (Monday)
            date_group = func.dateadd(text('day'), 
                                    1 - func.datepart(text('weekday'), models.OrderMaster.created_at),
                                    func.convert(text('date'), models.OrderMaster.created_at))
        elif group_by == "month":
            # SQL Server: Get first day of month
            date_group = func.datefromparts(func.year(models.OrderMaster.created_at), 
                                          func.month(models.OrderMaster.created_at), 
                                          1)
        else:
            raise HTTPException(status_code=400, detail="Invalid group_by. Use: day, week, month")
        
        # Build query
        query = db.query(
            date_group.label('date_period'),
            func.count(models.OrderMaster.id).label('total_orders'),
            func.sum(models.OrderItem.quantity_rolls).label('total_quantity_rolls'),
            func.sum(models.OrderItem.quantity_kg).label('total_quantity_kg'),
            func.sum(models.OrderItem.amount).label('total_value'),
            func.count(func.distinct(models.ClientMaster.id)).label('unique_clients'),
            func.count(func.distinct(models.PaperMaster.id)).label('unique_papers'),
            # Order completion metrics
            func.sum(case((models.OrderMaster.status == 'completed', 1), else_=0)).label('completed_orders'),
            func.sum(case(
                (and_(models.OrderItem.quantity_fulfilled > 0, 
                      models.OrderItem.quantity_fulfilled < models.OrderItem.quantity_rolls), 1), 
                else_=0
            )).label('partially_completed_items'),
            func.sum(models.OrderItem.quantity_fulfilled).label('total_quantity_fulfilled')
        ).select_from(
            models.OrderMaster
        ).join(
            models.OrderItem, models.OrderItem.order_id == models.OrderMaster.id
        ).join(
            models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
        ).join(
            models.PaperMaster, models.PaperMaster.id == models.OrderItem.paper_id
        ).filter(
            models.OrderMaster.created_at >= start_dt,
            models.OrderMaster.created_at <= end_dt
        )
        
        # Apply status filter
        if status:
            query = query.filter(models.OrderMaster.status == status)
        
        # Group by date and order by date
        results = query.group_by(date_group).order_by(date_group).all()
        
        # Format results
        date_analysis = []
        for result in results:
            total_orders = result.total_orders or 0
            completed_orders = result.completed_orders or 0
            total_quantity_rolls = result.total_quantity_rolls or 0
            total_quantity_fulfilled = result.total_quantity_fulfilled or 0
            
            date_analysis.append({
                "date_period": result.date_period.isoformat() if result.date_period else None,
                "total_orders": total_orders,
                "total_quantity_rolls": total_quantity_rolls,
                "total_quantity_kg": float(result.total_quantity_kg) if result.total_quantity_kg else 0,
                "total_value": float(result.total_value) if result.total_value else 0,
                "unique_clients": result.unique_clients,
                "unique_papers": result.unique_papers,
                "avg_order_value": float(result.total_value / max(total_orders, 1)) if result.total_value else 0,
                # Completion metrics
                "completed_orders": completed_orders,
                "pending_orders": total_orders - completed_orders,
                "completion_rate": float(completed_orders / max(total_orders, 1) * 100),
                "total_quantity_fulfilled": total_quantity_fulfilled,
                "fulfillment_rate": float(total_quantity_fulfilled / max(total_quantity_rolls, 1) * 100),
                "partially_completed_items": result.partially_completed_items or 0
            })
        
        # Calculate summary and trends
        total_orders = sum(item["total_orders"] for item in date_analysis)
        total_value = sum(item["total_value"] for item in date_analysis)
        total_quantity = sum(item["total_quantity_kg"] for item in date_analysis)
        
        # Calculate growth trend (compare first and last periods)
        growth_trend = {}
        if len(date_analysis) >= 2:
            first_period = date_analysis[0]
            last_period = date_analysis[-1]
            
            if first_period["total_value"] > 0:
                value_growth = ((last_period["total_value"] - first_period["total_value"]) / first_period["total_value"]) * 100
            else:
                value_growth = 0
            
            if first_period["total_orders"] > 0:
                order_growth = ((last_period["total_orders"] - first_period["total_orders"]) / first_period["total_orders"]) * 100
            else:
                order_growth = 0
            
            growth_trend = {
                "value_growth_percent": round(value_growth, 2),
                "order_growth_percent": round(order_growth, 2)
            }
        
        return {
            "status": "success",
            "data": date_analysis,
            "summary": {
                "total_periods": len(date_analysis),
                "total_orders": total_orders,
                "total_value": total_value,
                "total_quantity_kg": total_quantity,
                "avg_value_per_period": total_value / max(len(date_analysis), 1),
                "growth_trend": growth_trend
            },
            "filters_applied": {
                "start_date": start_date,
                "end_date": end_date,
                "group_by": group_by,
                "status": status
            }
        }
        
    except Exception as e:
        logger.error(f"Error in date-wise report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/summary", tags=["Reports"])
def get_reports_summary(db: Session = Depends(get_db)):
    """
    Get overall reports summary with key metrics for all report types.
    """
    try:
        # Get counts for each dimension
        total_papers = db.query(func.count(func.distinct(models.PaperMaster.id))).join(
            models.OrderItem, models.OrderItem.paper_id == models.PaperMaster.id
        ).scalar() or 0
        
        total_clients = db.query(func.count(func.distinct(models.ClientMaster.id))).join(
            models.OrderMaster, models.OrderMaster.client_id == models.ClientMaster.id
        ).scalar() or 0
        
        # Date range of orders
        date_range = db.query(
            func.min(models.OrderMaster.created_at),
            func.max(models.OrderMaster.created_at)
        ).first()
        
        # Overall totals
        overall_totals = db.query(
            func.count(models.OrderMaster.id),
            func.sum(models.OrderItem.quantity_rolls),
            func.sum(models.OrderItem.quantity_kg),
            func.sum(models.OrderItem.amount),
            # Completion metrics
            func.sum(case((models.OrderMaster.status == 'completed', 1), else_=0)),
            func.sum(models.OrderItem.quantity_fulfilled)
        ).join(
            models.OrderItem, models.OrderItem.order_id == models.OrderMaster.id
        ).first()
        
        return {
            "status": "success",
            "summary": {
                "dimensions": {
                    "total_papers_with_orders": total_papers,
                    "total_clients_with_orders": total_clients,
                    "date_range": {
                        "from": date_range[0].isoformat() if date_range[0] else None,
                        "to": date_range[1].isoformat() if date_range[1] else None
                    }
                },
                "overall_totals": {
                    "total_orders": overall_totals[0] or 0,
                    "total_quantity_rolls": overall_totals[1] or 0,
                    "total_quantity_kg": float(overall_totals[2]) if overall_totals[2] else 0,
                    "total_value": float(overall_totals[3]) if overall_totals[3] else 0,
                    # Completion metrics
                    "completed_orders": overall_totals[4] or 0,
                    "pending_orders": (overall_totals[0] or 0) - (overall_totals[4] or 0),
                    "total_quantity_fulfilled": overall_totals[5] or 0,
                    "overall_completion_rate": float((overall_totals[4] or 0) / max(overall_totals[0] or 1, 1) * 100),
                    "overall_fulfillment_rate": float((overall_totals[5] or 0) / max(overall_totals[1] or 1, 1) * 100)
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error in reports summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ORDER ANALYSIS REPORTS - Individual order tracking and analysis
# ============================================================================

@router.get("/reports/order-analysis/status-distribution", tags=["Order Analysis"])
def get_order_status_distribution(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    db: Session = Depends(get_db)
):
    """
    Get order status distribution - count of orders by status
    """
    try:
        # Build base query
        query = db.query(
            models.OrderMaster.status,
            func.count(models.OrderMaster.id).label('order_count'),
            func.sum(case((models.OrderMaster.delivery_date < func.getdate(), 1), else_=0)).label('overdue_count')
        ).select_from(models.OrderMaster)

        # Apply filters
        filters = []
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                filters.append(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        if client_id:
            try:
                client_uuid = uuid.UUID(client_id)
                filters.append(models.OrderMaster.client_id == client_uuid)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid client ID format")

        if filters:
            query = query.filter(and_(*filters))

        results = query.group_by(models.OrderMaster.status).all()

        status_data = []
        total_orders = 0
        total_overdue = 0

        for result in results:
            order_count = result.order_count or 0
            overdue_count = result.overdue_count or 0

            status_data.append({
                "status": result.status,
                "order_count": order_count,
                "overdue_count": overdue_count,
                "percentage": 0  # Will calculate after getting total
            })
            total_orders += order_count
            total_overdue += overdue_count

        # Calculate percentages
        for item in status_data:
            item["percentage"] = round((item["order_count"] / max(total_orders, 1)) * 100, 2)

        return {
            "status": "success",
            "data": status_data,
            "summary": {
                "total_orders": total_orders,
                "total_overdue": total_overdue
            }
        }

    except Exception as e:
        logger.error(f"Error in order status distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-analysis/fulfillment-progress", tags=["Order Analysis"])
def get_order_fulfillment_progress(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    limit: int = Query(100, description="Limit number of orders returned"),
    db: Session = Depends(get_db)
):
    """
    Get orders with completion percentages and fulfillment metrics
    """
    try:
        # Build base query
        query = db.query(
            models.OrderMaster.frontend_id.label('order_id'),
            models.ClientMaster.company_name.label('client_name'),
            models.OrderMaster.status.label('order_status'),
            models.OrderMaster.priority,
            models.OrderMaster.delivery_date,
            models.OrderMaster.created_at,
            func.count(models.OrderItem.id).label('total_items'),
            func.sum(models.OrderItem.quantity_rolls).label('total_quantity_ordered'),
            func.sum(models.OrderItem.quantity_fulfilled).label('total_quantity_fulfilled'),
            func.sum(models.OrderItem.quantity_in_pending).label('total_quantity_pending'),
            func.sum(models.OrderItem.amount).label('total_value')
        ).select_from(
            models.OrderMaster
        ).join(
            models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
        ).join(
            models.OrderItem, models.OrderItem.order_id == models.OrderMaster.id
        )

        # Apply filters
        filters = []
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                filters.append(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        if status:
            filters.append(models.OrderMaster.status == status)

        if filters:
            query = query.filter(and_(*filters))

        # Group by order and order by created date
        results = query.group_by(
            models.OrderMaster.id,
            models.OrderMaster.frontend_id,
            models.ClientMaster.company_name,
            models.OrderMaster.status,
            models.OrderMaster.priority,
            models.OrderMaster.delivery_date,
            models.OrderMaster.created_at
        ).order_by(desc(models.OrderMaster.created_at)).limit(limit).all()

        # Format results
        fulfillment_data = []
        for result in results:
            total_ordered = result.total_quantity_ordered or 0
            total_fulfilled = result.total_quantity_fulfilled or 0
            total_pending = result.total_quantity_pending or 0

            remaining_to_plan = max(0, total_ordered - total_fulfilled - total_pending)
            fulfillment_percentage = round((total_fulfilled / max(total_ordered, 1)) * 100, 2)

            # Determine if overdue
            is_overdue = (result.delivery_date and
                         result.delivery_date < datetime.utcnow() and
                         result.order_status != 'completed')

            fulfillment_data.append({
                "order_id": result.order_id,
                "client_name": result.client_name,
                "order_status": result.order_status,
                "priority": result.priority,
                "delivery_date": result.delivery_date.isoformat() if result.delivery_date else None,
                "created_at": result.created_at.isoformat(),
                "total_items": result.total_items,
                "total_quantity_ordered": total_ordered,
                "total_quantity_fulfilled": total_fulfilled,
                "total_quantity_pending": total_pending,
                "remaining_to_plan": remaining_to_plan,
                "fulfillment_percentage": fulfillment_percentage,
                "total_value": float(result.total_value) if result.total_value else 0,
                "is_overdue": is_overdue
            })

        return {
            "status": "success",
            "data": fulfillment_data,
            "summary": {
                "total_orders_returned": len(fulfillment_data),
                "avg_fulfillment_rate": round(sum(item["fulfillment_percentage"] for item in fulfillment_data) / max(len(fulfillment_data), 1), 2),
                "overdue_orders": sum(1 for item in fulfillment_data if item["is_overdue"])
            }
        }

    except Exception as e:
        logger.error(f"Error in order fulfillment progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-analysis/timeline", tags=["Order Analysis"])
def get_order_timeline_analysis(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(100, description="Limit number of orders returned"),
    db: Session = Depends(get_db)
):
    """
    Get order timeline analysis with production milestones
    """
    try:
        # Build query with timeline fields
        query = db.query(
            models.OrderMaster.frontend_id.label('order_id'),
            models.ClientMaster.company_name.label('client_name'),
            models.OrderMaster.status,
            models.OrderMaster.created_at,
            models.OrderMaster.started_production_at,
            models.OrderMaster.moved_to_warehouse_at,
            models.OrderMaster.dispatched_at,
            models.OrderMaster.delivery_date
        ).select_from(
            models.OrderMaster
        ).join(
            models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
        )

        # Apply filters
        filters = []
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                filters.append(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        if filters:
            query = query.filter(and_(*filters))

        results = query.order_by(desc(models.OrderMaster.created_at)).limit(limit).all()

        # Calculate timeline metrics
        timeline_data = []
        total_cycle_times = []

        for result in results:
            # Calculate durations
            days_to_production = None
            days_in_production = None
            days_in_warehouse = None
            total_cycle_time = None

            if result.started_production_at:
                days_to_production = (result.started_production_at - result.created_at).days

            if result.started_production_at and result.moved_to_warehouse_at:
                days_in_production = (result.moved_to_warehouse_at - result.started_production_at).days

            if result.moved_to_warehouse_at and result.dispatched_at:
                days_in_warehouse = (result.dispatched_at - result.moved_to_warehouse_at).days

            if result.dispatched_at:
                total_cycle_time = (result.dispatched_at - result.created_at).days
                total_cycle_times.append(total_cycle_time)

            timeline_data.append({
                "order_id": result.order_id,
                "client_name": result.client_name,
                "status": result.status,
                "created_at": result.created_at.isoformat(),
                "started_production_at": result.started_production_at.isoformat() if result.started_production_at else None,
                "moved_to_warehouse_at": result.moved_to_warehouse_at.isoformat() if result.moved_to_warehouse_at else None,
                "dispatched_at": result.dispatched_at.isoformat() if result.dispatched_at else None,
                "delivery_date": result.delivery_date.isoformat() if result.delivery_date else None,
                "days_to_production": days_to_production,
                "days_in_production": days_in_production,
                "days_in_warehouse": days_in_warehouse,
                "total_cycle_time": total_cycle_time
            })

        # Calculate averages
        avg_cycle_time = round(sum(total_cycle_times) / max(len(total_cycle_times), 1), 1) if total_cycle_times else 0

        return {
            "status": "success",
            "data": timeline_data,
            "summary": {
                "total_orders_analyzed": len(timeline_data),
                "completed_orders": len(total_cycle_times),
                "avg_cycle_time_days": avg_cycle_time,
                "min_cycle_time_days": min(total_cycle_times) if total_cycle_times else 0,
                "max_cycle_time_days": max(total_cycle_times) if total_cycle_times else 0
            }
        }

    except Exception as e:
        logger.error(f"Error in order timeline analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-analysis/pending-orders", tags=["Order Analysis"])
def get_pending_orders_analysis(
    reason: Optional[str] = Query(None, description="Filter by pending reason"),
    limit: int = Query(100, description="Limit number of orders returned"),
    db: Session = Depends(get_db)
):
    """
    Get orders with items in pending state and reasons
    """
    try:
        # Debug: Log the actual SQL being generated
        logger.info("Starting pending orders query...")

        # Simple query that matches your working SQL exactly
        query = db.query(
            models.OrderMaster.id.label('order_id_uuid'),
            models.OrderMaster.frontend_id.label('order_id'),
            models.ClientMaster.company_name.label('client_name'),
            models.OrderMaster.status.label('order_status'),
            func.count(models.PendingOrderItem.id).label('pending_items_count'),
            func.sum(models.PendingOrderItem.quantity_pending).label('total_pending_quantity'),
            func.min(models.PendingOrderItem.created_at).label('first_pending_date'),
            func.max(models.PendingOrderItem.created_at).label('latest_pending_date')
        ).join(
            models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
        ).join(
            models.PendingOrderItem, models.PendingOrderItem.original_order_id == models.OrderMaster.id
        ).filter(
            models.PendingOrderItem._status == 'pending'
        ).group_by(
            models.OrderMaster.id,
            models.OrderMaster.frontend_id,
            models.ClientMaster.company_name,
            models.OrderMaster.status
        ).order_by(desc('total_pending_quantity'))

        # Debug: Print the actual SQL
        logger.info(f"Generated SQL: {str(query.statement.compile(compile_kwargs={'literal_binds': True}))}")

        # Apply reason filter if specified
        if reason:
            query = query.filter(models.PendingOrderItem.reason == reason)
            logger.info(f"Applied reason filter: {reason}")

        # Execute query and get results
        results = query.limit(limit).all()
        logger.info(f"Query returned {len(results)} results")

        # Get reasons separately for each order
        pending_data = []
        for result in results:
            # Get distinct reasons for this order from PendingOrderItem
            reasons_query = db.query(func.distinct(models.PendingOrderItem.reason)).filter(
                models.PendingOrderItem.original_order_id == result.order_id_uuid,
                models.PendingOrderItem._status == 'pending'
            )

            if reason:
                reasons_query = reasons_query.filter(models.PendingOrderItem.reason == reason)

            reasons = [r[0] for r in reasons_query.all()]

            # If no reasons from PendingOrderItem, it means this is from OrderItem.quantity_in_pending
            if not reasons:
                # Check if this order has OrderItems with quantity_in_pending > 0
                has_pending_items = db.query(models.OrderItem).filter(
                    models.OrderItem.order_id == result.order_id_uuid,
                    models.OrderItem.quantity_in_pending > 0
                ).first()

                if has_pending_items:
                    reasons = ['Order items pending fulfillment']

            pending_reasons = ', '.join(reasons) if reasons else 'Unknown'

            pending_data.append({
                "order_id": result.order_id,
                "client_name": result.client_name,
                "order_status": result.order_status,
                "pending_items_count": result.pending_items_count,
                "total_pending_quantity": result.total_pending_quantity,
                "pending_reasons": pending_reasons,
                "first_pending_date": result.first_pending_date.isoformat() if result.first_pending_date else None,
                "latest_pending_date": result.latest_pending_date.isoformat() if result.latest_pending_date else None,
                "days_pending": (datetime.utcnow() - result.first_pending_date).days if result.first_pending_date else 0
            })

        # Get summary by reason
        reason_summary = db.query(
            models.PendingOrderItem.reason,
            func.count(func.distinct(models.PendingOrderItem.original_order_id)).label('affected_orders'),
            func.sum(models.PendingOrderItem.quantity_pending).label('total_quantity')
        ).filter(
            models.PendingOrderItem.status == 'pending'
        ).group_by(
            models.PendingOrderItem.reason
        ).all()

        reasons_data = [
            {
                "reason": r.reason,
                "affected_orders": r.affected_orders,
                "total_quantity": r.total_quantity
            } for r in reason_summary
        ]

        return {
            "status": "success",
            "data": pending_data,
            "reasons_summary": reasons_data,
            "summary": {
                "total_orders_with_pending": len(pending_data),
                "total_pending_quantity": sum(item["total_pending_quantity"] for item in pending_data),
                "unique_reasons": len(reasons_data)
            }
        }

    except Exception as e:
        logger.error(f"Error in pending orders analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-analysis/dispatch-tracking", tags=["Order Analysis"])
def get_dispatch_tracking_analysis(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(100, description="Limit number of dispatches returned"),
    db: Session = Depends(get_db)
):
    """
    Get orders that have been dispatched with tracking information
    """
    try:
        # Query dispatched orders
        query = db.query(
            models.OrderMaster.frontend_id.label('order_id'),
            models.ClientMaster.company_name.label('client_name'),
            models.OrderMaster.status,
            models.DispatchRecord.frontend_id.label('dispatch_id'),
            models.DispatchRecord.vehicle_number,
            models.DispatchRecord.driver_name,
            models.DispatchRecord.driver_mobile,
            models.DispatchRecord.dispatch_date,
            models.DispatchRecord.dispatch_number,
            models.DispatchRecord.total_items.label('dispatched_items'),
            models.DispatchRecord.total_weight_kg.label('dispatched_weight'),
            models.DispatchRecord.status.label('dispatch_status')
        ).select_from(
            models.OrderMaster
        ).join(
            models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
        ).join(
            models.DispatchRecord, models.DispatchRecord.primary_order_id == models.OrderMaster.id
        ).filter(
            models.OrderMaster.dispatched_at.isnot(None)
        )

        # Apply filters
        filters = []
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(models.DispatchRecord.dispatch_date >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                filters.append(models.DispatchRecord.dispatch_date <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        if filters:
            query = query.filter(and_(*filters))

        results = query.order_by(desc(models.DispatchRecord.dispatch_date)).limit(limit).all()

        # Format results
        dispatch_data = []
        for result in results:
            dispatch_data.append({
                "order_id": result.order_id,
                "client_name": result.client_name,
                "order_status": result.status,
                "dispatch_id": result.dispatch_id,
                "vehicle_number": result.vehicle_number,
                "driver_name": result.driver_name,
                "driver_mobile": result.driver_mobile,
                "dispatch_date": result.dispatch_date.isoformat() if result.dispatch_date else None,
                "dispatch_number": result.dispatch_number,
                "dispatched_items": result.dispatched_items,
                "dispatched_weight": float(result.dispatched_weight) if result.dispatched_weight else 0,
                "dispatch_status": result.dispatch_status
            })

        return {
            "status": "success",
            "data": dispatch_data,
            "summary": {
                "total_dispatches": len(dispatch_data),
                "total_items_dispatched": sum(item["dispatched_items"] for item in dispatch_data),
                "total_weight_dispatched": sum(item["dispatched_weight"] for item in dispatch_data)
            }
        }

    except Exception as e:
        logger.error(f"Error in dispatch tracking analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-analysis/overdue-orders", tags=["Order Analysis"])
def get_overdue_orders_analysis(
    limit: int = Query(100, description="Limit number of orders returned"),
    db: Session = Depends(get_db)
):
    """
    Get orders that are past their delivery date and not completed
    """
    try:
        # Query overdue orders
        query = db.query(
            models.OrderMaster.frontend_id.label('order_id'),
            models.ClientMaster.company_name.label('client_name'),
            models.OrderMaster.status,
            models.OrderMaster.priority,
            models.OrderMaster.delivery_date,
            models.OrderMaster.created_at,
            func.sum(models.OrderItem.quantity_rolls).label('total_quantity_ordered'),
            func.sum(models.OrderItem.quantity_fulfilled).label('total_quantity_fulfilled'),
            func.sum(models.OrderItem.amount).label('total_value')
        ).select_from(
            models.OrderMaster
        ).join(
            models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
        ).join(
            models.OrderItem, models.OrderItem.order_id == models.OrderMaster.id
        ).filter(
            models.OrderMaster.delivery_date < func.getdate(),
            models.OrderMaster.status != 'completed'
        )

        results = query.group_by(
            models.OrderMaster.id,
            models.OrderMaster.frontend_id,
            models.ClientMaster.company_name,
            models.OrderMaster.status,
            models.OrderMaster.priority,
            models.OrderMaster.delivery_date,
            models.OrderMaster.created_at
        ).order_by(models.OrderMaster.delivery_date).limit(limit).all()

        # Format results
        overdue_data = []
        for result in results:
            total_ordered = result.total_quantity_ordered or 0
            total_fulfilled = result.total_quantity_fulfilled or 0

            days_overdue = (datetime.utcnow().date() - result.delivery_date.date()).days if result.delivery_date else 0
            fulfillment_percentage = round((total_fulfilled / max(total_ordered, 1)) * 100, 2)

            overdue_data.append({
                "order_id": result.order_id,
                "client_name": result.client_name,
                "status": result.status,
                "priority": result.priority,
                "delivery_date": result.delivery_date.isoformat() if result.delivery_date else None,
                "created_at": result.created_at.isoformat(),
                "days_overdue": days_overdue,
                "total_quantity_ordered": total_ordered,
                "total_quantity_fulfilled": total_fulfilled,
                "fulfillment_percentage": fulfillment_percentage,
                "total_value": float(result.total_value) if result.total_value else 0
            })

        return {
            "status": "success",
            "data": overdue_data,
            "summary": {
                "total_overdue_orders": len(overdue_data),
                "avg_days_overdue": round(sum(item["days_overdue"] for item in overdue_data) / max(len(overdue_data), 1), 1),
                "total_overdue_value": sum(item["total_value"] for item in overdue_data)
            }
        }

    except Exception as e:
        logger.error(f"Error in overdue orders analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-analysis/detailed-breakdown", tags=["Order Analysis"])
def get_detailed_order_breakdown(
    order_id: Optional[str] = Query(None, description="Specific order ID to analyze"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, description="Limit number of orders returned"),
    db: Session = Depends(get_db)
):
    """
    Get detailed item-level breakdown for orders
    """
    try:
        # Get orders first, then their items separately for better control
        orders_query = db.query(
            models.OrderMaster.id.label('order_uuid'),
            models.OrderMaster.frontend_id.label('order_id'),
            models.ClientMaster.company_name.label('client_name'),
            models.OrderMaster.status.label('order_status'),
            models.OrderMaster.created_at,
            models.OrderMaster.delivery_date
        ).join(
            models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
        )

        # Apply filters to orders
        filters = []
        if order_id:
            filters.append(models.OrderMaster.frontend_id == order_id)

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                filters.append(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        if filters:
            orders_query = orders_query.filter(and_(*filters))

        # Get orders
        orders = orders_query.order_by(desc(models.OrderMaster.created_at)).limit(limit).all()

        # Now get items for each order
        breakdown_data = []
        for order in orders:
            # Get items for this order
            items_query = db.query(
                models.OrderItem.frontend_id.label('item_id'),
                models.PaperMaster.name.label('paper_name'),
                models.PaperMaster.gsm,
                models.PaperMaster.bf,
                models.PaperMaster.shade,
                models.OrderItem.width_inches,
                models.OrderItem.quantity_rolls.label('ordered_quantity'),
                models.OrderItem.quantity_fulfilled,
                models.OrderItem.quantity_in_pending,
                models.OrderItem.item_status,
                models.OrderItem.rate,
                models.OrderItem.amount
            ).join(
                models.PaperMaster, models.PaperMaster.id == models.OrderItem.paper_id
            ).filter(
                models.OrderItem.order_id == order.order_uuid
            ).order_by(models.OrderItem.width_inches).all()

            # Format items
            formatted_items = []
            total_ordered = 0
            total_fulfilled = 0
            total_pending = 0
            total_value = 0

            for item in items_query:
                remaining_to_plan = max(0, item.ordered_quantity - item.quantity_fulfilled - item.quantity_in_pending)
                fulfillment_percentage = round((item.quantity_fulfilled / max(item.ordered_quantity, 1)) * 100, 2)

                formatted_item = {
                    "item_id": item.item_id,
                    "paper_name": item.paper_name,
                    "gsm": item.gsm,
                    "bf": float(item.bf) if item.bf else 0,
                    "shade": item.shade,
                    "width_inches": float(item.width_inches) if item.width_inches else 0,
                    "ordered_quantity": item.ordered_quantity,
                    "quantity_fulfilled": item.quantity_fulfilled,
                    "quantity_in_pending": item.quantity_in_pending,
                    "remaining_to_plan": remaining_to_plan,
                    "item_status": item.item_status,
                    "fulfillment_percentage": fulfillment_percentage,
                    "rate": float(item.rate) if item.rate else 0,
                    "amount": float(item.amount) if item.amount else 0
                }

                formatted_items.append(formatted_item)
                total_ordered += item.ordered_quantity
                total_fulfilled += item.quantity_fulfilled
                total_pending += item.quantity_in_pending
                total_value += float(item.amount) if item.amount else 0

            # Calculate overall fulfillment
            overall_fulfillment = round((total_fulfilled / max(total_ordered, 1)) * 100, 2)

            # Add order with its items
            breakdown_data.append({
                "order_id": order.order_id,
                "client_name": order.client_name,
                "order_status": order.order_status,
                "created_at": order.created_at.isoformat(),
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "total_items": len(formatted_items),
                "total_ordered": total_ordered,
                "total_fulfilled": total_fulfilled,
                "total_pending": total_pending,
                "total_value": total_value,
                "overall_fulfillment": overall_fulfillment,
                "items": formatted_items
            })

        return {
            "status": "success",
            "data": breakdown_data,
            "summary": {
                "total_orders_analyzed": len(breakdown_data),
                "total_items_analyzed": sum(order["total_items"] for order in breakdown_data),
                "avg_items_per_order": round(sum(order["total_items"] for order in breakdown_data) / max(len(breakdown_data), 1), 2)
            }
        }

    except Exception as e:
        logger.error(f"Error in detailed order breakdown: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-analysis/orders-list", tags=["Order Analysis"])
def get_orders_list(
    start_date: str = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date filter (YYYY-MM-DD)"),
    status: str = Query("all", description="Order status filter"),
    db: Session = Depends(get_db)
):
    """
    Get list of all orders with key details for the order analysis table.
    Supports filtering by date range and status.
    """
    try:
        logger.info(f"Getting orders list with filters: start_date={start_date}, end_date={end_date}, status={status}")

        # Build base query
        query = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.order_items)
        )

        # Apply date filters
        if start_date:
            query = query.filter(models.OrderMaster.created_at >= start_date)
        if end_date:
            query = query.filter(models.OrderMaster.created_at <= end_date)

        # Apply status filter
        if status and status != "all":
            query = query.filter(models.OrderMaster.status == status)

        # Get orders
        orders = query.order_by(models.OrderMaster.created_at.desc()).all()

        orders_data = []
        for order in orders:
            # Calculate fulfillment metrics
            total_ordered = sum(item.quantity_rolls for item in order.order_items)
            total_fulfilled = sum(item.quantity_fulfilled for item in order.order_items)
            fulfillment_percentage = (total_fulfilled / max(total_ordered, 1)) * 100

            # Calculate total value
            total_value = sum(item.amount for item in order.order_items)

            # Check if overdue
            is_overdue = False
            if order.delivery_date and order.status != 'completed':
                is_overdue = order.delivery_date < datetime.utcnow()

            orders_data.append({
                "order_id": order.frontend_id,
                "client_name": order.client.company_name if order.client else "Unknown",
                "status": order.status,
                "priority": order.priority,
                "fulfillment_percentage": round(fulfillment_percentage, 1),
                "total_quantity_ordered": total_ordered,
                "total_quantity_fulfilled": total_fulfilled,
                "total_value": float(total_value),
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "is_overdue": is_overdue,
                "created_at": order.created_at.isoformat()
            })

        logger.info(f"Successfully retrieved {len(orders_data)} orders")
        return orders_data

    except Exception as e:
        logger.error(f"Error getting orders list: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-analysis/order-details/{order_id}", tags=["Order Analysis"])
def get_order_complete_details(
    order_id: str,
    db: Session = Depends(get_db)
):
    """
    Get complete detailed breakdown for a specific order including:
    - Order basic info and timeline
    - All order items with status
    - Pending order items with reasons
    - Production orders linked to this order
    - Inventory allocation details
    - Dispatch information
    - Complete order journey tracking
    """
    try:
        # Get the main order
        order = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.created_by),
            joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
        ).filter(models.OrderMaster.frontend_id == order_id).first()

        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

        # Build comprehensive order details
        order_details = {
            "order_info": {
                "id": str(order.id),
                "frontend_id": order.frontend_id,
                "status": order.status,
                "priority": order.priority,
                "payment_type": order.payment_type,
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "created_at": order.created_at.isoformat(),
                "updated_at": order.updated_at.isoformat() if order.updated_at else None,
                "started_production_at": order.started_production_at.isoformat() if order.started_production_at else None,
                "moved_to_warehouse_at": order.moved_to_warehouse_at.isoformat() if order.moved_to_warehouse_at else None,
                "dispatched_at": order.dispatched_at.isoformat() if order.dispatched_at else None,
                "is_overdue": order.delivery_date < datetime.utcnow() if order.delivery_date and order.status != 'completed' else False,
                "days_since_creation": (datetime.utcnow() - order.created_at).days,
                "total_quantity_ordered": order.total_quantity_ordered,
                "total_quantity_fulfilled": order.total_quantity_fulfilled,
                "remaining_quantity": order.remaining_quantity,
                "is_fully_fulfilled": order.is_fully_fulfilled
            },
            "client_info": {
                "company_name": order.client.company_name,
                "contact_person": order.client.contact_person,
                "phone": order.client.phone,
                "email": order.client.email,
                "address": order.client.address,
                "gst_number": order.client.gst_number,
            } if order.client else None,
            "created_by": {
                "name": order.created_by.name,
                "contact": order.created_by.contact
            } if order.created_by else None
        }

        # Get order items with detailed status
        order_items = []
        total_value = 0
        for item in order.order_items:
            remaining_to_plan = max(0, item.quantity_rolls - item.quantity_fulfilled - item.quantity_in_pending)
            fulfillment_percentage = round((item.quantity_fulfilled / max(item.quantity_rolls, 1)) * 100, 2)

            item_data = {
                "id": str(item.id),
                "frontend_id": item.frontend_id,
                "paper": {
                    "name": item.paper.name,
                    "gsm": item.paper.gsm,
                    "bf": float(item.paper.bf) if item.paper.bf else 0,
                    "shade": item.paper.shade,
                    "paper_type": item.paper.type
                } if item.paper else None,
                "width_inches": float(item.width_inches),
                "quantity_rolls": item.quantity_rolls,
                "quantity_kg": float(item.quantity_kg),
                "rate": float(item.rate),
                "amount": float(item.amount),
                "quantity_fulfilled": item.quantity_fulfilled,
                "quantity_in_pending": item.quantity_in_pending,
                "remaining_to_plan": remaining_to_plan,
                "item_status": item.item_status,
                "fulfillment_percentage": fulfillment_percentage,
                "started_production_at": item.started_production_at.isoformat() if item.started_production_at else None,
                "moved_to_warehouse_at": item.moved_to_warehouse_at.isoformat() if item.moved_to_warehouse_at else None,
                "dispatched_at": item.dispatched_at.isoformat() if item.dispatched_at else None,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat() if item.updated_at else None
            }
            order_items.append(item_data)
            total_value += float(item.amount)

        order_details["order_items"] = order_items
        order_details["order_info"]["total_value"] = total_value

        # Get pending order items with reasons
        pending_items = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.original_order_id == order.id,
            models.PendingOrderItem._status == 'pending'
        ).all()

        pending_data = []
        for pending in pending_items:
            # Try to find matching paper for paper_name
            paper = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == pending.gsm,
                models.PaperMaster.bf == pending.bf,
                models.PaperMaster.shade == pending.shade
            ).first()

            pending_data.append({
                "id": str(pending.id),
                "frontend_id": pending.frontend_id,
                "paper_name": paper.name if paper else f"{pending.gsm}GSM {pending.bf}BF {pending.shade}",
                "width_inches": float(pending.width_inches),
                "gsm": pending.gsm,
                "bf": float(pending.bf),
                "shade": pending.shade,
                "quantity_rolls": pending.quantity_pending,
                "quantity_pending": pending.quantity_pending,
                "quantity_fulfilled": pending.quantity_fulfilled,
                "reason": pending.reason,
                "status": pending.status,
                "created_at": pending.created_at.isoformat(),
                "plan_generation_date": pending.plan_generation_date.isoformat() if pending.plan_generation_date else None,
                "included_in_plan_generation": pending.included_in_plan_generation,
                "generated_cut_rolls_count": pending.generated_cut_rolls_count
            })

        order_details["pending_items"] = pending_data

        # Get production orders related to this order
        production_orders = db.query(models.ProductionOrderMaster).join(
            models.PendingOrderItem,
            models.PendingOrderItem.production_order_id == models.ProductionOrderMaster.id
        ).filter(
            models.PendingOrderItem.original_order_id == order.id
        ).distinct().all()

        production_data = []
        for prod in production_orders:
            production_data.append({
                "id": str(prod.id),
                "frontend_id": prod.frontend_id,
                "status": prod.status,
                "total_quantity": prod.total_quantity,
                "produced_quantity": prod.produced_quantity,
                "remaining_quantity": prod.remaining_quantity,
                "expected_completion_date": prod.expected_completion_date.isoformat() if prod.expected_completion_date else None,
                "created_at": prod.created_at.isoformat(),
                "started_at": prod.started_at.isoformat() if prod.started_at else None,
                "completed_at": prod.completed_at.isoformat() if prod.completed_at else None
            })

        order_details["production_orders"] = production_data

        # Get inventory allocated to this order
        allocated_inventory = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper)
        ).filter(
            models.InventoryMaster.allocated_to_order_id == order.id
        ).all()

        inventory_data = []
        for inv in allocated_inventory:
            inventory_data.append({
                "id": str(inv.id),
                "frontend_id": inv.frontend_id,
                "paper": {
                    "name": inv.paper.name,
                    "gsm": inv.paper.gsm,
                    "bf": float(inv.paper.bf) if inv.paper.bf else 0,
                    "shade": inv.paper.shade
                } if inv.paper else None,
                "width_inches": float(inv.width_inches),
                "weight_kg": float(inv.weight_kg),
                "status": inv.status,
                "roll_type": inv.roll_type,
                "location": inv.location,
                "production_date": inv.production_date.isoformat() if inv.production_date else None,
                "created_at": inv.created_at.isoformat()
            })

        order_details["allocated_inventory"] = inventory_data

        # Get dispatch information
        dispatch_records = db.query(models.DispatchRecord).options(
            joinedload(models.DispatchRecord.dispatch_items).joinedload(models.DispatchItem.inventory)
        ).filter(
            models.DispatchRecord.primary_order_id == order.id
        ).all()

        dispatch_data = []
        for dispatch in dispatch_records:
            dispatch_items = []
            for d_item in dispatch.dispatch_items:
                dispatch_items.append({
                    "id": str(d_item.id),
                    "inventory_id": str(d_item.inventory_id),
                    "inventory_frontend_id": d_item.inventory.frontend_id if d_item.inventory else None,
                    "quantity_dispatched": d_item.quantity_dispatched,
                    "weight_kg": float(d_item.weight_kg) if d_item.weight_kg else 0
                })

            dispatch_data.append({
                "id": str(dispatch.id),
                "frontend_id": dispatch.frontend_id,
                "dispatch_number": dispatch.dispatch_number,
                "vehicle_number": dispatch.vehicle_number,
                "driver_name": dispatch.driver_name,
                "driver_mobile": dispatch.driver_mobile,
                "dispatch_date": dispatch.dispatch_date.isoformat() if dispatch.dispatch_date else None,
                "status": dispatch.status,
                "total_items": dispatch.total_items,
                "total_weight_kg": float(dispatch.total_weight_kg) if dispatch.total_weight_kg else 0,
                "reference_number": dispatch.reference_number,
                "payment_type": dispatch.payment_type,
                "created_at": dispatch.created_at.isoformat(),
                "dispatch_items": dispatch_items
            })

        order_details["dispatch_records"] = dispatch_data

        # Get plan information
        plan_links = db.query(models.PlanOrderLink).options(
            joinedload(models.PlanOrderLink.plan)
        ).filter(
            models.PlanOrderLink.order_id == order.id
        ).all()

        plan_data = []
        for plan_link in plan_links:
            if plan_link.plan:
                plan_data.append({
                    "id": str(plan_link.plan.id),
                    "frontend_id": plan_link.plan.frontend_id,
                    "name": plan_link.plan.name,
                    "status": plan_link.plan.status,
                    "expected_waste_percentage": float(plan_link.plan.expected_waste_percentage) if plan_link.plan.expected_waste_percentage else 0,
                    "actual_waste_percentage": float(plan_link.plan.actual_waste_percentage) if plan_link.plan.actual_waste_percentage else 0,
                    "created_at": plan_link.plan.created_at.isoformat(),
                    "executed_at": plan_link.plan.executed_at.isoformat() if plan_link.plan.executed_at else None,
                    "completed_at": plan_link.plan.completed_at.isoformat() if plan_link.plan.completed_at else None
                })

        order_details["linked_plans"] = plan_data

        # Calculate timeline metrics
        timeline_metrics = {
            "days_to_production": None,
            "days_in_production": None,
            "days_in_warehouse": None,
            "total_cycle_time": None,
            "days_until_delivery": None
        }

        if order.started_production_at:
            timeline_metrics["days_to_production"] = (order.started_production_at - order.created_at).days

        if order.started_production_at and order.moved_to_warehouse_at:
            timeline_metrics["days_in_production"] = (order.moved_to_warehouse_at - order.started_production_at).days

        if order.moved_to_warehouse_at and order.dispatched_at:
            timeline_metrics["days_in_warehouse"] = (order.dispatched_at - order.moved_to_warehouse_at).days

        if order.dispatched_at:
            timeline_metrics["total_cycle_time"] = (order.dispatched_at - order.created_at).days

        if order.delivery_date:
            timeline_metrics["days_until_delivery"] = (order.delivery_date - datetime.utcnow()).days

        order_details["timeline_metrics"] = timeline_metrics

        # Summary statistics
        summary = {
            "total_order_items": len(order_items),
            "total_pending_items": len(pending_data),
            "total_production_orders": len(production_data),
            "total_allocated_inventory": len(inventory_data),
            "total_dispatch_records": len(dispatch_data),
            "total_linked_plans": len(plan_data),
            "fulfillment_percentage": round((order.total_quantity_fulfilled / max(order.total_quantity_ordered, 1)) * 100, 2),
            "completion_status": {
                "is_production_started": order.started_production_at is not None,
                "is_in_warehouse": order.moved_to_warehouse_at is not None,
                "is_dispatched": order.dispatched_at is not None,
                "is_overdue": order_details["order_info"]["is_overdue"]
            }
        }

        order_details["summary"] = summary

        return {
            "status": "success",
            "data": order_details
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting complete order details for {order_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order/{order_id}/challan-with-dispatch", tags=["Reports"])
def get_order_with_dispatch_info(
    order_id: str,
    db: Session = Depends(get_db)
):
    """
    Get order data with associated dispatch information for challan generation.
    This endpoint combines order details with vehicle/dispatch information when available.
    """
    try:
        # Parse order ID
        try:
            order_uuid = uuid.UUID(order_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid order ID format")

        # Get order with all related data
        order = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
        ).filter(models.OrderMaster.id == order_uuid).first()

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Find related dispatch record using the connection path:
        # OrderMaster -> PlanOrderLink -> PlanInventoryLink -> InventoryMaster -> DispatchItem -> DispatchRecord
        dispatch_query = db.query(models.DispatchRecord).join(
            models.DispatchItem,
            models.DispatchItem.dispatch_record_id == models.DispatchRecord.id
        ).join(
            models.InventoryMaster,
            models.InventoryMaster.id == models.DispatchItem.inventory_id
        ).join(
            models.PlanInventoryLink,
            models.PlanInventoryLink.inventory_id == models.InventoryMaster.id
        ).join(
            models.PlanOrderLink,
            models.PlanOrderLink.plan_id == models.PlanInventoryLink.plan_id
        ).filter(
            models.PlanOrderLink.order_id == order_uuid
        ).distinct()

        # Get the first dispatch record (there might be multiple dispatches for one order)
        dispatch = dispatch_query.first()

        # Also check for direct relationship if primary_order_id is set
        if not dispatch:
            dispatch = db.query(models.DispatchRecord).filter(
                models.DispatchRecord.primary_order_id == order_uuid
            ).first()

        # Format order data
        order_data = {
            "id": str(order.id),
            "frontend_id": order.frontend_id,
            "client": {
                "company_name": order.client.company_name,
                "contact_person": order.client.contact_person,
                "address": order.client.address,
                "phone": order.client.phone,
                "email": order.client.email,
                "gst_number": order.client.gst_number,
            } if order.client else None,
            "payment_type": order.payment_type,
            "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
            "created_at": order.created_at.isoformat(),
            "status": order.status,
            "order_items": []
        }

        # Add order items
        for item in order.order_items or []:
            order_data["order_items"].append({
                "id": str(item.id),
                "paper": {
                    "name": item.paper.name if item.paper else None,
                    "gsm": item.paper.gsm if item.paper else None,
                    "bf": float(item.paper.bf) if item.paper and item.paper.bf else None,
                    "shade": item.paper.shade if item.paper else None,
                } if item.paper else None,
                "width_inches": float(item.width_inches) if item.width_inches else None,
                "quantity_rolls": item.quantity_rolls,
                "rate": float(item.rate) if item.rate else None,
                "amount": float(item.amount) if item.amount else None,
                "quantity_kg": float(item.quantity_kg) if item.quantity_kg else None,
            })

        # Format dispatch data if available
        dispatch_info = None
        if dispatch:
            dispatch_info = {
                "id": str(dispatch.id),
                "frontend_id": dispatch.frontend_id,
                "vehicle_number": dispatch.vehicle_number,
                "driver_name": dispatch.driver_name,
                "driver_mobile": dispatch.driver_mobile,
                "dispatch_date": dispatch.dispatch_date.isoformat() if dispatch.dispatch_date else None,
                "dispatch_number": dispatch.dispatch_number,
                "reference_number": dispatch.reference_number,
                "payment_type": dispatch.payment_type,
                "created_at": dispatch.created_at.isoformat()
            }

        return {
            "status": "success",
            "data": {
                "order": order_data,
                "dispatch": dispatch_info,
                "has_dispatch_info": dispatch is not None
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting order with dispatch info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ORDER ITEM TRACKING AND MISMATCH DETECTION SYSTEM
# ============================================================================

@router.get("/reports/order-tracking/{order_frontend_id}", tags=["Order Tracking"])
def get_order_item_tracking(
    order_frontend_id: str,
    db: Session = Depends(get_db)
):
    """
    Get comprehensive tracking information for all order items including:
    - Inventory allocations and locations
    - Production assignments
    - Dispatch records
    - Potential mismatches based on GSM, BF, Shade, Client patterns
    """
    try:
        # Get the order
        order = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
        ).filter(models.OrderMaster.frontend_id == order_frontend_id).first()

        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_frontend_id} not found")

        # Build comprehensive tracking data
        tracking_data = {
            "order_info": {
                "id": str(order.id),
                "frontend_id": order.frontend_id,
                "client_name": order.client.company_name if order.client else "Unknown",
                "status": order.status,
                "created_at": order.created_at.isoformat(),
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None
            },
            "order_items": [],
            "potential_mismatches": [],
            "summary": {}
        }

        total_mismatches = 0
        total_allocated_inventory = 0

        # Process each order item
        for item in order.order_items:
            item_data = {
                "id": str(item.id),
                "frontend_id": item.frontend_id,
                "paper_specs": {
                    "name": item.paper.name if item.paper else "Unknown",
                    "gsm": item.paper.gsm if item.paper else None,
                    "bf": float(item.paper.bf) if item.paper and item.paper.bf else None,
                    "shade": item.paper.shade if item.paper else None,
                    "type": item.paper.type if item.paper else None
                },
                "width_inches": float(item.width_inches),
                "quantity_ordered": item.quantity_rolls,
                "quantity_fulfilled": item.quantity_fulfilled,
                "quantity_pending": item.quantity_in_pending,
                "item_status": item.item_status,
                "allocated_inventory": [],
                "production_assignments": [],
                "dispatch_records": [],
                "potential_issues": []
            }

            # Get allocated inventory for this order item
            allocated_inventory = db.query(models.InventoryMaster).options(
                joinedload(models.InventoryMaster.paper)
            ).filter(
                models.InventoryMaster.allocated_to_order_id == order.id,
                models.InventoryMaster.width_inches == item.width_inches
            ).all()

            for inv in allocated_inventory:
                inv_data = {
                    "id": str(inv.id),
                    "frontend_id": inv.frontend_id,
                    "paper_specs": {
                        "name": inv.paper.name if inv.paper else "Unknown",
                        "gsm": inv.paper.gsm if inv.paper else None,
                        "bf": float(inv.paper.bf) if inv.paper and inv.paper.bf else None,
                        "shade": inv.paper.shade if inv.paper else None,
                        "type": inv.paper.type if inv.paper else None
                    },
                    "width_inches": float(inv.width_inches),
                    "weight_kg": float(inv.weight_kg) if inv.weight_kg else 0,
                    "status": inv.status,
                    "location": inv.location,
                    "roll_type": inv.roll_type,
                    "production_date": inv.production_date.isoformat() if inv.production_date else None,
                    "is_paper_match": True,
                    "is_width_match": True,
                    "mismatch_reasons": []
                }

                # Check for paper specification mismatches
                if item.paper and inv.paper:
                    if item.paper.gsm != inv.paper.gsm:
                        inv_data["is_paper_match"] = False
                        inv_data["mismatch_reasons"].append(f"GSM mismatch: Expected {item.paper.gsm}, Got {inv.paper.gsm}")

                    if item.paper.bf != inv.paper.bf:
                        inv_data["is_paper_match"] = False
                        inv_data["mismatch_reasons"].append(f"BF mismatch: Expected {item.paper.bf}, Got {inv.paper.bf}")

                    if item.paper.shade != inv.paper.shade:
                        inv_data["is_paper_match"] = False
                        inv_data["mismatch_reasons"].append(f"Shade mismatch: Expected {item.paper.shade}, Got {inv.paper.shade}")

                # Check for width mismatches
                width_tolerance = 0.1  # 0.1 inch tolerance
                if abs(float(item.width_inches) - float(inv.width_inches)) > width_tolerance:
                    inv_data["is_width_match"] = False
                    inv_data["mismatch_reasons"].append(f"Width mismatch: Expected {item.width_inches}\", Got {inv.width_inches}\"")

                if inv_data["mismatch_reasons"]:
                    item_data["potential_issues"].extend(inv_data["mismatch_reasons"])

                item_data["allocated_inventory"].append(inv_data)
                total_allocated_inventory += 1

            # Get production assignments through pending orders
            production_assignments = db.query(models.PendingOrderItem).options(
                joinedload(models.PendingOrderItem.production_order)
            ).filter(
                models.PendingOrderItem.original_order_id == order.id,
                models.PendingOrderItem.width_inches == item.width_inches
            ).all()

            for pending in production_assignments:
                prod_data = {
                    "id": str(pending.id),
                    "frontend_id": pending.frontend_id,
                    "production_order_id": str(pending.production_order_id) if pending.production_order_id else None,
                    "production_order_frontend_id": pending.production_order.frontend_id if pending.production_order else None,
                    "status": pending.status,
                    "quantity_pending": pending.quantity_pending,
                    "quantity_fulfilled": pending.quantity_fulfilled,
                    "reason": pending.reason,
                    "created_at": pending.created_at.isoformat(),
                    "paper_specs": {
                        "gsm": pending.gsm,
                        "bf": float(pending.bf),
                        "shade": pending.shade
                    },
                    "width_inches": float(pending.width_inches),
                    "mismatch_reasons": []
                }

                # Check for specification mismatches in production assignments
                if item.paper:
                    if item.paper.gsm != pending.gsm:
                        prod_data["mismatch_reasons"].append(f"GSM mismatch: Expected {item.paper.gsm}, Got {pending.gsm}")

                    if item.paper.bf != pending.bf:
                        prod_data["mismatch_reasons"].append(f"BF mismatch: Expected {item.paper.bf}, Got {pending.bf}")

                    if item.paper.shade != pending.shade:
                        prod_data["mismatch_reasons"].append(f"Shade mismatch: Expected {item.paper.shade}, Got {pending.shade}")

                if prod_data["mismatch_reasons"]:
                    item_data["potential_issues"].extend(prod_data["mismatch_reasons"])

                item_data["production_assignments"].append(prod_data)

            # Get dispatch records for this order item's inventory
            if item_data["allocated_inventory"]:
                inventory_ids = [inv["id"] for inv in item_data["allocated_inventory"]]
                dispatch_items = db.query(models.DispatchItem).options(
                    joinedload(models.DispatchItem.dispatch_record),
                    joinedload(models.DispatchItem.inventory)
                ).filter(
                    models.DispatchItem.inventory_id.in_([uuid.UUID(inv_id) for inv_id in inventory_ids])
                ).all()

                for dispatch_item in dispatch_items:
                    dispatch_data = {
                        "id": str(dispatch_item.id),
                        "dispatch_record_id": str(dispatch_item.dispatch_record_id),
                        "dispatch_frontend_id": dispatch_item.dispatch_record.frontend_id if dispatch_item.dispatch_record else None,
                        "inventory_id": str(dispatch_item.inventory_id),
                        "inventory_frontend_id": dispatch_item.inventory.frontend_id if dispatch_item.inventory else None,
                        "quantity_dispatched": dispatch_item.quantity_dispatched,
                        "weight_kg": float(dispatch_item.weight_kg) if dispatch_item.weight_kg else 0,
                        "dispatch_date": dispatch_item.dispatch_record.dispatch_date.isoformat() if dispatch_item.dispatch_record and dispatch_item.dispatch_record.dispatch_date else None,
                        "vehicle_number": dispatch_item.dispatch_record.vehicle_number if dispatch_item.dispatch_record else None,
                        "status": dispatch_item.dispatch_record.status if dispatch_item.dispatch_record else None
                    }
                    item_data["dispatch_records"].append(dispatch_data)

            # Count mismatches for this item
            if item_data["potential_issues"]:
                total_mismatches += len(item_data["potential_issues"])

            tracking_data["order_items"].append(item_data)

        # Detect broader potential mismatches across the system
        # Look for inventory allocated to other orders with same specifications
        if order.client and tracking_data["order_items"]:
            similar_allocations = db.query(models.InventoryMaster).options(
                joinedload(models.InventoryMaster.paper),
                joinedload(models.InventoryMaster.allocated_order).joinedload(models.OrderMaster.client)
            ).join(
                models.OrderMaster, models.OrderMaster.id == models.InventoryMaster.allocated_to_order_id
            ).join(
                models.ClientMaster, models.ClientMaster.id == models.OrderMaster.client_id
            ).filter(
                models.OrderMaster.id != order.id,  # Exclude current order
                models.ClientMaster.company_name == order.client.company_name
            ).all()

            for similar_inv in similar_allocations[:10]:  # Limit to first 10 for performance
                current_order_papers = [item.paper for item in order.order_items if item.paper]
                for order_paper in current_order_papers:
                    if (similar_inv.paper and
                        similar_inv.paper.gsm == order_paper.gsm and
                        similar_inv.paper.bf == order_paper.bf and
                        similar_inv.paper.shade == order_paper.shade):

                        potential_mismatch = {
                            "type": "potential_cross_order_mismatch",
                            "description": f"Inventory {similar_inv.frontend_id} with matching specs allocated to different order",
                            "inventory_id": str(similar_inv.id),
                            "inventory_frontend_id": similar_inv.frontend_id,
                            "allocated_to_order": similar_inv.allocated_order.frontend_id if similar_inv.allocated_order else None,
                            "allocated_to_client": similar_inv.allocated_order.client.company_name if similar_inv.allocated_order and similar_inv.allocated_order.client else None,
                            "paper_specs": {
                                "gsm": similar_inv.paper.gsm,
                                "bf": float(similar_inv.paper.bf) if similar_inv.paper.bf else None,
                                "shade": similar_inv.paper.shade
                            },
                            "width_inches": float(similar_inv.width_inches),
                            "weight_kg": float(similar_inv.weight_kg) if similar_inv.weight_kg else 0
                        }
                        tracking_data["potential_mismatches"].append(potential_mismatch)

        # Summary statistics
        tracking_data["summary"] = {
            "total_order_items": len(tracking_data["order_items"]),
            "total_allocated_inventory": total_allocated_inventory,
            "total_potential_issues": total_mismatches,
            "total_cross_order_matches": len(tracking_data["potential_mismatches"]),
            "items_with_issues": len([item for item in tracking_data["order_items"] if item["potential_issues"]]),
            "health_status": "CRITICAL" if total_mismatches > 5 else "WARNING" if total_mismatches > 0 else "HEALTHY"
        }

        return {
            "status": "success",
            "data": tracking_data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in order item tracking: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reports/order-tracking/fix-allocation", tags=["Order Tracking"])
def fix_inventory_allocation(
    correction_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Fix inventory allocation mismatches.
    Expected format:
    {
        "inventory_id": "uuid",
        "new_order_id": "frontend_id",
        "reason": "description of fix"
    }
    """
    try:
        inventory_id = correction_data.get("inventory_id")
        new_order_frontend_id = correction_data.get("new_order_id")
        reason = correction_data.get("reason", "Manual correction")

        if not inventory_id or not new_order_frontend_id:
            raise HTTPException(status_code=400, detail="inventory_id and new_order_id are required")

        # Get the inventory item
        inventory = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.id == uuid.UUID(inventory_id)
        ).first()

        if not inventory:
            raise HTTPException(status_code=404, detail="Inventory item not found")

        # Get the new order
        new_order = db.query(models.OrderMaster).filter(
            models.OrderMaster.frontend_id == new_order_frontend_id
        ).first()

        if not new_order:
            raise HTTPException(status_code=404, detail="Target order not found")

        # Store old allocation for logging
        old_order_id = inventory.allocated_to_order_id
        old_order = None
        if old_order_id:
            old_order = db.query(models.OrderMaster).filter(
                models.OrderMaster.id == old_order_id
            ).first()

        # Update the allocation
        inventory.allocated_to_order_id = new_order.id
        inventory.updated_at = datetime.utcnow()

        # Log the change
        logger.info(f"Inventory allocation fixed: {inventory.frontend_id} moved from order {old_order.frontend_id if old_order else 'None'} to {new_order.frontend_id}. Reason: {reason}")

        db.commit()

        return {
            "status": "success",
            "message": f"Inventory {inventory.frontend_id} successfully reallocated to order {new_order.frontend_id}",
            "old_allocation": old_order.frontend_id if old_order else None,
            "new_allocation": new_order.frontend_id,
            "reason": reason
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fixing inventory allocation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reports/order-tracking/batch-fix", tags=["Order Tracking"])
def batch_fix_allocations(
    batch_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Fix multiple inventory allocations in batch.
    Expected format:
    {
        "corrections": [
            {
                "inventory_id": "uuid",
                "new_order_id": "frontend_id",
                "reason": "description"
            }
        ]
    }
    """
    try:
        corrections = batch_data.get("corrections", [])
        if not corrections:
            raise HTTPException(status_code=400, detail="No corrections provided")

        results = []
        errors = []

        for correction in corrections:
            try:
                # Use the single fix function for each correction
                result = fix_inventory_allocation(correction, db)
                results.append({
                    "inventory_id": correction.get("inventory_id"),
                    "status": "success",
                    "result": result
                })
            except Exception as e:
                errors.append({
                    "inventory_id": correction.get("inventory_id"),
                    "status": "error",
                    "error": str(e)
                })

        return {
            "status": "batch_complete",
            "total_corrections": len(corrections),
            "successful": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors
        }

    except Exception as e:
        logger.error(f"Error in batch fix: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-tracking/system-health", tags=["Order Tracking"])
def get_system_allocation_health(
    limit: int = Query(100, description="Limit number of issues returned"),
    db: Session = Depends(get_db)
):
    """
    Get overall system health for inventory allocations and detect widespread mismatches.
    """
    try:
        health_data = {
            "overall_status": "HEALTHY",
            "total_issues": 0,
            "issue_categories": {
                "specification_mismatches": 0,
                "missing_allocations": 0,
                "duplicate_allocations": 0,
                "cross_client_issues": 0
            },
            "critical_issues": [],
            "recommendations": []
        }

        # Check for specification mismatches
        mismatched_allocations = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.allocated_order).joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
        ).filter(
            models.InventoryMaster.allocated_to_order_id.isnot(None)
        ).limit(limit).all()

        for inv in mismatched_allocations:
            if inv.allocated_order and inv.allocated_order.order_items and inv.paper:
                for order_item in inv.allocated_order.order_items:
                    if (order_item.paper and
                        abs(float(order_item.width_inches) - float(inv.width_inches)) <= 0.1):  # Same width

                        mismatches = []
                        if order_item.paper.gsm != inv.paper.gsm:
                            mismatches.append(f"GSM: {order_item.paper.gsm} vs {inv.paper.gsm}")
                        if order_item.paper.bf != inv.paper.bf:
                            mismatches.append(f"BF: {order_item.paper.bf} vs {inv.paper.bf}")
                        if order_item.paper.shade != inv.paper.shade:
                            mismatches.append(f"Shade: {order_item.paper.shade} vs {inv.paper.shade}")

                        if mismatches:
                            health_data["issue_categories"]["specification_mismatches"] += 1
                            health_data["critical_issues"].append({
                                "type": "specification_mismatch",
                                "inventory_id": str(inv.id),
                                "inventory_frontend_id": inv.frontend_id,
                                "order_id": inv.allocated_order.frontend_id,
                                "mismatches": mismatches,
                                "severity": "HIGH" if len(mismatches) > 1 else "MEDIUM"
                            })

        # Check for unallocated inventory that should be allocated
        unallocated_inventory = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.allocated_to_order_id.is_(None),
            models.InventoryMaster.status.in_(["available", "in_warehouse"])
        ).count()

        if unallocated_inventory > 0:
            health_data["issue_categories"]["missing_allocations"] = unallocated_inventory
            health_data["recommendations"].append(f"Review {unallocated_inventory} unallocated inventory items")

        # Calculate overall health
        total_issues = sum(health_data["issue_categories"].values())
        health_data["total_issues"] = total_issues

        if total_issues > 50:
            health_data["overall_status"] = "CRITICAL"
        elif total_issues > 10:
            health_data["overall_status"] = "WARNING"
        else:
            health_data["overall_status"] = "HEALTHY"

        # Add summary recommendations
        if health_data["issue_categories"]["specification_mismatches"] > 0:
            health_data["recommendations"].append("Run specification mismatch corrections")

        if total_issues == 0:
            health_data["recommendations"].append("System allocation health is optimal")

        return {
            "status": "success",
            "data": health_data
        }

    except Exception as e:
        logger.error(f"Error checking system health: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# CLIENT ORDERS WITH PLANS - New Feature
# ============================================================================

@router.get("/reports/client-orders-with-plans", tags=["Client Orders with Plans"])
def get_client_orders_with_plans(
    client_id: str = Query(..., description="Client ID to filter orders"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    Get orders for a specific client within a date range, including the plans where these orders were used.
    Shows the relationship between orders and production plans.
    """
    try:
        import uuid

        # Validate client_id
        try:
            client_uuid = uuid.UUID(client_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid client ID format")

        # Verify client exists
        client = db.query(models.ClientMaster).filter(models.ClientMaster.id == client_uuid).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # Build base query for orders
        query = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper),
            joinedload(models.OrderMaster.plan_orders).joinedload(models.PlanOrderLink.plan)
        ).filter(models.OrderMaster.client_id == client_uuid)

        # Apply date filters
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                query = query.filter(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                query = query.filter(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")

        # Get orders
        orders = query.order_by(models.OrderMaster.created_at.desc()).all()

        orders_data = []
        for order in orders:
            # Calculate order metrics
            total_ordered = sum(item.quantity_rolls for item in order.order_items)
            total_fulfilled = sum(item.quantity_fulfilled for item in order.order_items)
            total_value = sum(item.amount for item in order.order_items)
            fulfillment_percentage = (total_fulfilled / max(total_ordered, 1)) * 100

            # Get associated plans
            plans_data = []
            for plan_link in order.plan_orders:
                if plan_link.plan:
                    plan = plan_link.plan
                    # Handle JSON parsing safely
                    try:
                        cut_pattern = json.loads(plan.cut_pattern) if plan.cut_pattern else []
                    except (json.JSONDecodeError, TypeError):
                        cut_pattern = plan.cut_pattern if plan.cut_pattern else []

                    try:
                        wastage_allocations = json.loads(plan.wastage_allocations) if plan.wastage_allocations else []
                    except (json.JSONDecodeError, TypeError):
                        wastage_allocations = plan.wastage_allocations if plan.wastage_allocations else []

                    plans_data.append({
                        "plan_id": str(plan.id),
                        "plan_frontend_id": plan.frontend_id,
                        "name": plan.name,
                        "plan_status": plan.status,  # Correct field name
                        "created_at": plan.created_at.isoformat(),
                        "executed_at": plan.executed_at.isoformat() if plan.executed_at else None,
                        "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
                        "expected_waste_percentage": float(plan.expected_waste_percentage) if plan.expected_waste_percentage else 0,
                        "actual_waste_percentage": float(plan.actual_waste_percentage) if plan.actual_waste_percentage else None,
                        "cut_pattern": cut_pattern,
                        "wastage_allocations": wastage_allocations
                    })

            # Check if overdue
            is_overdue = False
            if order.delivery_date and order.status != 'completed':
                is_overdue = order.delivery_date < datetime.utcnow()

            order_data = {
                "order_id": str(order.id),
                "frontend_id": order.frontend_id,
                "status": order.status,
                "priority": order.priority,
                "payment_type": order.payment_type,
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "created_at": order.created_at.isoformat(),
                "is_overdue": is_overdue,
                "total_items": len(order.order_items),
                "total_quantity_ordered": total_ordered,
                "total_quantity_fulfilled": total_fulfilled,
                "fulfillment_percentage": round(fulfillment_percentage, 2),
                "total_value": float(total_value),
                "order_items": [
                    {
                        "id": str(item.id),
                        "paper": {
                            "name": item.paper.name if item.paper else "Unknown",
                            "gsm": item.paper.gsm if item.paper else 0,
                            "bf": float(item.paper.bf) if item.paper and item.paper.bf else 0,
                            "shade": item.paper.shade if item.paper else "Unknown"
                        },
                        "width_inches": float(item.width_inches),
                        "quantity_rolls": item.quantity_rolls,
                        "quantity_kg": float(item.quantity_kg),
                        "rate": float(item.rate),
                        "amount": float(item.amount),
                        "quantity_fulfilled": item.quantity_fulfilled,
                        "item_status": item.item_status
                    }
                    for item in order.order_items
                ],
                "associated_plans": plans_data,
                "total_plans": len(plans_data)
            }

            orders_data.append(order_data)

        # Calculate summary
        total_orders = len(orders_data)
        total_value = sum(order["total_value"] for order in orders_data)
        total_quantity = sum(order["total_quantity_ordered"] for order in orders_data)
        completed_orders = sum(1 for order in orders_data if order["status"] == "completed")
        orders_with_plans = sum(1 for order in orders_data if order["total_plans"] > 0)

        return {
            "status": "success",
            "client_info": {
                "id": str(client.id),
                "company_name": client.company_name,
                "contact_person": client.contact_person,
                "phone": client.phone,
                "gst_number": client.gst_number
            },
            "data": orders_data,
            "summary": {
                "total_orders": total_orders,
                "total_value": total_value,
                "total_quantity_ordered": total_quantity,
                "completed_orders": completed_orders,
                "pending_orders": total_orders - completed_orders,
                "completion_rate": round((completed_orders / max(total_orders, 1)) * 100, 2),
                "orders_with_plans": orders_with_plans,
                "orders_without_plans": total_orders - orders_with_plans,
                "plan_coverage_rate": round((orders_with_plans / max(total_orders, 1)) * 100, 2)
            },
            "filters_applied": {
                "client_id": client_id,
                "start_date": start_date,
                "end_date": end_date
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in client orders with plans: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ORDER PLAN EXECUTION REPORT - Merged Report (Order Status + Plan Linkage)
# ============================================================================

@router.get("/reports/order-plan-execution", tags=["Order Plan Execution"])
def get_order_plan_execution_report(
    client_id: Optional[str] = Query(None, description="Client ID to filter orders"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Order status filter (created, in_process, completed, cancelled)"),
    plan_status: Optional[str] = Query(None, description="Plan status filter (created, optimized, completed)"),
    include_unplanned: bool = Query(True, description="Include orders without production plans"),
    limit: int = Query(1000, description="Maximum number of orders to return"),
    db: Session = Depends(get_db)
):
    """
    Order-Plan Execution Report showing:
    For each order: total rolls | cuts | pending (with details) | plan frontend IDs (unique)
    """
    try:
        # Validate UUID if provided
        if client_id:
            try:
                uuid.UUID(client_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid client_id format")

        # Main query for orders
        query = db.query(
            models.OrderMaster.id.label('order_id'),
            models.OrderMaster.frontend_id.label('order_frontend_id'),
            models.OrderMaster.created_at.label('order_date'),
            models.OrderMaster.delivery_date,
            models.OrderMaster.status.label('order_status'),
            models.OrderMaster.priority,

            # Client information
            models.ClientMaster.id.label('client_id'),
            models.ClientMaster.company_name.label('client_name'),
            models.ClientMaster.gst_number.label('gstin'),
            models.ClientMaster.phone,
            models.ClientMaster.email,

            # Order item aggregations
            func.count(models.OrderItem.id).label('total_items'),
            func.sum(models.OrderItem.quantity_rolls).label('total_quantity_ordered'),
            func.sum(models.OrderItem.quantity_kg).label('total_weight_ordered'),
            func.sum(models.OrderItem.quantity_fulfilled).label('total_quantity_cut'),
            func.sum(models.OrderItem.amount).label('total_order_value'),

            # Calculate pending quantities (ordered - fulfilled)
            func.sum(models.OrderItem.quantity_rolls - models.OrderItem.quantity_fulfilled).label('total_quantity_pending')
        ).join(
            models.ClientMaster, models.OrderMaster.client_id == models.ClientMaster.id
        ).outerjoin(
            models.OrderItem, models.OrderMaster.id == models.OrderItem.order_id
        )

        # Build filters
        filters = []

        if client_id:
            filters.append(models.OrderMaster.client_id == client_id)

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                filters.append(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")

        if status:
            filters.append(models.OrderMaster.status == status)

        if filters:
            query = query.filter(and_(*filters))

        # Group by order and client
        orders_data = query.group_by(
            models.OrderMaster.id,
            models.OrderMaster.frontend_id,
            models.OrderMaster.created_at,
            models.OrderMaster.delivery_date,
            models.OrderMaster.status,
            models.OrderMaster.priority,
            models.ClientMaster.id,
            models.ClientMaster.company_name,
            models.ClientMaster.gst_number,
            models.ClientMaster.phone,
            models.ClientMaster.email
        ).order_by(desc(models.OrderMaster.created_at)).limit(limit).all()

        # Get order items for pending details
        order_ids = [order.order_id for order in orders_data]

        order_items_query = db.query(models.OrderItem).options(
            joinedload(models.OrderItem.paper)
        ).filter(models.OrderItem.order_id.in_(order_ids))

        order_items = order_items_query.all()

        # Group items by order
        items_by_order = {}
        for item in order_items:
            if item.order_id not in items_by_order:
                items_by_order[item.order_id] = []
            items_by_order[item.order_id].append(item)

        # Get pending items using PendingOrderItem (same as Client Order Analysis)
        pending_items_query = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.original_order_id.in_(order_ids),
            models.PendingOrderItem._status == 'pending'
        )

        pending_items = pending_items_query.all()

        # Group pending items by order
        pending_by_order = {}
        for item in pending_items:
            if item.original_order_id not in pending_by_order:
                pending_by_order[item.original_order_id] = []
            pending_by_order[item.original_order_id].append(item)

        # Get cut items using InventoryMaster (same as Client Order Analysis)
        inventory_items_query = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper)
        ).filter(
            models.InventoryMaster.allocated_to_order_id.in_(order_ids)
        )

        inventory_items = inventory_items_query.all()

        # Group inventory items by order
        cuts_by_order = {}
        for item in inventory_items:
            if item.allocated_to_order_id not in cuts_by_order:
                cuts_by_order[item.allocated_to_order_id] = []
            cuts_by_order[item.allocated_to_order_id].append(item)

        # Get production plans data
        plans_query = db.query(
            models.PlanMaster.id.label('plan_id'),
            models.PlanMaster.frontend_id.label('plan_frontend_id'),
            models.OrderMaster.id.label('order_id')
        ).join(
            models.PlanOrderLink, models.PlanMaster.id == models.PlanOrderLink.plan_id
        ).join(
            models.OrderMaster, models.PlanOrderLink.order_id == models.OrderMaster.id
        ).filter(
            models.OrderMaster.id.in_(order_ids)
        )

        if plan_status:
            plans_query = plans_query.filter(models.PlanMaster.status == plan_status)

        plans_data = plans_query.all()

        # Organize unique plan frontend IDs by order
        order_plans = {}
        for plan in plans_data:
            if plan.order_id not in order_plans:
                order_plans[plan.order_id] = set()
            order_plans[plan.order_id].add(plan.plan_frontend_id)

        # Build final results
        final_results = []
        for order in orders_data:
            # Skip unplanned orders if requested
            if not order_plans.get(order.order_id, set()) and not include_unplanned:
                continue

            # Get pending items using PendingOrderItem (same as Client Order Analysis)
            pending_items_for_order = pending_by_order.get(order.order_id, [])
            total_pending_rolls = sum(item.quantity_pending for item in pending_items_for_order)

            # Build pending details from PendingOrderItem
            pending_details = []
            for item in pending_items_for_order:
                pending_details.append({
                    'id': str(item.id),
                    'paper_name': f"{item.gsm}GSM",
                    'gsm': item.gsm,
                    'bf': float(item.bf),
                    'shade': item.shade,
                    'width_inches': float(item.width_inches),
                    'pending_quantity': item.quantity_pending,
                    'pending_weight': 0,  # Not available in PendingOrderItem
                    'rate': 0,  # Not available in PendingOrderItem
                    'pending_value': 0  # Not available in PendingOrderItem
                })

            # Get cuts using InventoryMaster (same as Client Order Analysis)
            cuts_for_order = cuts_by_order.get(order.order_id, [])
            total_cuts = len(cuts_for_order)  # Count of inventory items allocated to this order

            # Get unique plan frontend IDs
            unique_plan_ids = sorted(list(order_plans.get(order.order_id, set())))

            order_data = {
                'order_id': str(order.order_id),
                'order_frontend_id': order.order_frontend_id,
                'order_date': order.order_date.isoformat() if order.order_date else None,
                'delivery_date': order.delivery_date.isoformat() if order.delivery_date else None,
                'order_status': order.order_status,
                'priority': order.priority,
                'client_name': order.client_name,
                'client_phone': order.phone,
                'client_gstin': order.gstin,

                # Main metrics requested - using correct calculations
                'total_rolls': int(order.total_quantity_ordered or 0),
                'cuts': total_cuts,  # From InventoryMaster
                'pending': {
                    'total_rolls': total_pending_rolls,  # From PendingOrderItem
                    'details': pending_details
                },
                'plan_frontend_ids': unique_plan_ids,

                # Additional useful data
                'total_items': int(order.total_items or 0),
                'total_weight_ordered': float(order.total_weight_ordered or 0),
                'total_order_value': float(order.total_order_value or 0),
                'has_plan': len(unique_plan_ids) > 0,
                'is_overdue': order.delivery_date and order.delivery_date < datetime.utcnow() and order.order_status not in ['completed', 'cancelled']
            }

            final_results.append(order_data)

        # Calculate summary statistics
        total_orders = len(final_results)
        orders_with_plans = sum(1 for order in final_results if order['has_plan'])
        total_rolls = sum(order['total_rolls'] for order in final_results)
        total_cuts = sum(order['cuts'] for order in final_results)
        total_pending_rolls = sum(order['pending']['total_rolls'] for order in final_results)

        summary = {
            'total_orders': total_orders,
            'orders_with_plans': orders_with_plans,
            'orders_without_plans': total_orders - orders_with_plans,
            'plan_coverage_rate': round((orders_with_plans / max(total_orders, 1)) * 100, 2),
            'total_rolls': total_rolls,
            'total_cuts': total_cuts,
            'total_pending_rolls': total_pending_rolls,
            'fulfillment_rate': round((total_cuts / max(total_rolls, 1)) * 100, 2)
        }

        return {
            'success': True,
            'data': {
                'orders': final_results,
                'summary': summary,
                'filters_applied': {
                    'client_id': client_id,
                    'start_date': start_date,
                    'end_date': end_date,
                    'status': status,
                    'plan_status': plan_status,
                    'include_unplanned': include_unplanned,
                    'limit': limit
                }
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in order plan execution report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reports/order-plan-execution/export", tags=["Order Plan Execution"])
def export_order_plan_execution_report(
    client_id: Optional[str] = Query(None, description="Client ID to filter orders"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Order status filter (created, in_process, completed, cancelled)"),
    plan_status: Optional[str] = Query(None, description="Plan status filter (created, optimized, completed)"),
    include_unplanned: bool = Query(True, description="Include orders without production plans"),
    limit: int = Query(1000, description="Maximum number of orders to return"),
    db: Session = Depends(get_db)
):
    """
    Export Order-Plan Execution Report as PDF
    """
    try:
        # Get the data using the main report function
        result = get_order_plan_execution_report(
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
            plan_status=plan_status,
            include_unplanned=include_unplanned,
            limit=limit,
            db=db
        )

        if not result or not result.get('success') or not result.get('data'):
            raise HTTPException(status_code=404, detail="No data found for report")

        data = result['data']
        orders = data.get('orders', [])
        summary = data.get('summary', {})

        # Generate PDF
        from fastapi.responses import Response
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from io import BytesIO

        # Create PDF in memory
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
        elements = []
        styles = getSampleStyleSheet()

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            alignment=1,  # Center alignment
            spaceAfter=20
        )
        elements.append(Paragraph("Order-Plan Execution Report", title_style))

        # Report parameters
        params_text = f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        if client_id:
            params_text += f"\nClient ID: {client_id}"
        if start_date and end_date:
            params_text += f"\nDate Range: {start_date} to {end_date}"
        if status:
            params_text += f"\nOrder Status: {status}"
        if plan_status:
            params_text += f"\nPlan Status: {plan_status}"

        elements.append(Paragraph(params_text, styles['Normal']))
        elements.append(Spacer(1, 12))

        # Summary Section
        elements.append(Paragraph("Executive Summary", styles['Heading2']))

        summary_data = [
            ['Metric', 'Value'],
            ['Total Orders', str(summary.get('total_orders', 0))],
            ['Orders with Plans', f"{summary.get('orders_with_plans', 0)} ({summary.get('plan_coverage_rate', 0):.1f}%)"],
            ['Overall Fulfillment Rate', f"{summary.get('overall_fulfillment_rate', 0):.1f}%"],
            ['Overall Dispatch Rate', f"{summary.get('overall_dispatch_rate', 0):.1f}%"],
            ['Total Quantity Ordered', str(summary.get('total_quantity_ordered', 0))],
            ['Total Quantity Cut', str(summary.get('total_quantity_cut', 0))],
            ['Total Quantity Dispatched', str(summary.get('total_quantity_dispatched', 0))],
            ['Total Quantity Pending', str(summary.get('total_quantity_pending', 0))],
        ]

        summary_table = Table(summary_data, colWidths=[2.5*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))

        elements.append(summary_table)
        elements.append(Spacer(1, 20))

        # Detailed Orders Table
        elements.append(Paragraph("Detailed Orders and Plans", styles['Heading2']))

        if orders:
            # Prepare table data
            headers = [
                'Order ID', 'Client', 'Status', 'Priority',
                'Ordered', 'Pending', 'Cut', 'Dispatched',
                'Plan Coverage', 'Has Plan', 'Indicators'
            ]

            table_data = [headers]

            for order in orders:
                row = [
                    order.get('order_frontend_id', ''),
                    order.get('client', {}).get('name', ''),
                    order.get('order_status', '').replace('_', ' '),
                    order.get('priority', 'Normal'),
                    str(order.get('total_quantity_ordered', 0)),
                    str(order.get('total_quantity_pending', 0)),
                    str(order.get('total_quantity_cut', 0)),
                    str(order.get('total_quantity_dispatched', 0)),
                    f"{order.get('plan_coverage_percentage', 0):.1f}%",
                    'Yes' if order.get('has_plan') else 'No',
                ]

                # Add status indicators
                indicators = []
                if order.get('is_fully_planned'):
                    indicators.append('Planned')
                if order.get('is_fully_produced'):
                    indicators.append('Produced')
                if order.get('is_fully_dispatched'):
                    indicators.append('Dispatched')
                if order.get('is_overdue'):
                    indicators.append('Overdue')

                row.append(', '.join(indicators) if indicators else '-')
                table_data.append(row)

            # Create the table
            orders_table = Table(table_data, repeatRows=1)

            # Style the table
            table_style = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (4, 1), (7, -1), 'RIGHT'),  # Right align numeric columns
                ('ALIGN', (8, 1), (8, -1), 'CENTER'),  # Center align percentage
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ])

            # Add alternating row colors
            for i in range(1, len(table_data)):
                if i % 2 == 0:
                    table_style.add('BACKGROUND', (0, i), (-1, i), colors.lightgrey)

            orders_table.setStyle(table_style)
            elements.append(orders_table)
        else:
            elements.append(Paragraph("No orders found matching the selected criteria.", styles['Normal']))

        # Build PDF
        doc.build(elements)
        buffer.seek(0)

        # Return PDF response
        return Response(
            content=buffer.getvalue(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=order-plan-execution-{datetime.now().strftime('%Y-%m-%d')}.pdf"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting order plan execution report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CLIENT ORDER SUMMARY REPORT - New report for client order details
# ============================================================================

@router.get("/reports/client-order-summary", tags=["Client Order Summary"])
def get_client_order_summary(
    client_id: str = Query(..., description="Client ID (required)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Order status filter"),
    db: Session = Depends(get_db)
):
    """
    Client Order Summary Report

    Returns all orders for a specific client with:
    - Basic order details
    - Total cuts from InventoryMaster
    - Pending items from PendingOrderItem
    - Linked plan names
    - Fulfillment metrics
    """
    try:
        # Validate client_id
        try:
            client_uuid = uuid.UUID(client_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid client_id format")

        # Get client information
        client = db.query(models.ClientMaster).filter(
            models.ClientMaster.id == client_uuid
        ).first()

        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # Build orders query
        query = db.query(models.OrderMaster).filter(
            models.OrderMaster.client_id == client_uuid
        )

        # Apply filters
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                query = query.filter(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date + " 23:59:59")
                query = query.filter(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")

        if status:
            query = query.filter(models.OrderMaster.status == status)

        # Get orders
        orders = query.order_by(desc(models.OrderMaster.created_at)).all()

        # Get order IDs for batch queries
        order_ids = [order.id for order in orders]

        if not order_ids:
            return {
                "success": True,
                "data": {
                    "client": {
                        "id": str(client.id),
                        "company_name": client.company_name,
                        "gst_number": client.gst_number,
                        "contact_person": client.contact_person,
                        "phone": client.phone
                    },
                    "orders": [],
                    "summary": {
                        "total_orders": 0,
                        "total_rolls_ordered": 0,
                        "total_cuts": 0,
                        "total_pending_rolls": 0,
                        "avg_fulfillment_rate": 0
                    }
                }
            }

        # Get order items
        order_items_query = db.query(models.OrderItem).options(
            joinedload(models.OrderItem.paper)
        ).filter(models.OrderItem.order_id.in_(order_ids))
        order_items = order_items_query.all()

        # Group order items by order_id
        items_by_order = {}
        for item in order_items:
            if item.order_id not in items_by_order:
                items_by_order[item.order_id] = []
            items_by_order[item.order_id].append(item)

        # Get pending items from PendingOrderItem
        pending_items_query = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.original_order_id.in_(order_ids),
            models.PendingOrderItem._status == 'pending'
        )
        pending_items = pending_items_query.all()

        # Group pending items by order
        pending_by_order = {}
        for item in pending_items:
            if item.original_order_id not in pending_by_order:
                pending_by_order[item.original_order_id] = []
            pending_by_order[item.original_order_id].append(item)

        # Get cut rolls from InventoryMaster
        inventory_items_query = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper)
        ).filter(
            models.InventoryMaster.allocated_to_order_id.in_(order_ids)
        )
        inventory_items = inventory_items_query.all()

        # Group inventory items by order
        cuts_by_order = {}
        for item in inventory_items:
            if item.allocated_to_order_id not in cuts_by_order:
                cuts_by_order[item.allocated_to_order_id] = []
            cuts_by_order[item.allocated_to_order_id].append(item)

        # Get plan information
        plans_query = db.query(
            models.PlanMaster.id.label('plan_id'),
            models.PlanMaster.frontend_id.label('plan_frontend_id'),
            models.PlanMaster.name.label('plan_name'),
            models.PlanMaster.status.label('plan_status'),
            models.OrderMaster.id.label('order_id')
        ).join(
            models.PlanOrderLink, models.PlanMaster.id == models.PlanOrderLink.plan_id
        ).join(
            models.OrderMaster, models.PlanOrderLink.order_id == models.OrderMaster.id
        ).filter(
            models.OrderMaster.id.in_(order_ids)
        )
        plans_data = plans_query.all()

        # Organize plans by order (ensure uniqueness by plan_id)
        plans_by_order = {}
        for plan in plans_data:
            if plan.order_id not in plans_by_order:
                plans_by_order[plan.order_id] = {}
            # Use plan_id as key to ensure uniqueness
            plans_by_order[plan.order_id][str(plan.plan_id)] = plan

        # Build response for each order
        orders_response = []
        total_rolls_all = 0
        total_cuts_all = 0
        total_pending_all = 0

        for order in orders:
            # Get order items for this order
            order_items_list = items_by_order.get(order.id, [])
            total_rolls_ordered = sum(item.quantity_rolls for item in order_items_list)
            total_weight_ordered = sum(float(item.quantity_kg) for item in order_items_list)
            total_order_value = sum(float(item.amount) for item in order_items_list)
            total_fulfilled = sum(item.quantity_fulfilled for item in order_items_list)

            # Get pending items for this order
            pending_items_list = pending_by_order.get(order.id, [])
            pending_items_data = []
            total_pending_rolls = 0

            for pending in pending_items_list:
                total_pending_rolls += pending.quantity_pending
                pending_items_data.append({
                    "id": str(pending.id),
                    "frontend_id": pending.frontend_id,
                    "gsm": pending.gsm,
                    "bf": float(pending.bf),
                    "shade": pending.shade,
                    "width_inches": float(pending.width_inches),
                    "quantity_pending": pending.quantity_pending,
                    "reason": pending.reason,
                    "status": pending.status,
                    "created_at": pending.created_at.isoformat() if pending.created_at else None
                })

            # Get cut rolls count for this order
            cuts_list = cuts_by_order.get(order.id, [])
            total_cuts = len(cuts_list)

            # Get linked plans for this order (already unique from dictionary)
            plans_dict = plans_by_order.get(order.id, {})
            linked_plans_data = []
            for plan in plans_dict.values():
                linked_plans_data.append({
                    "plan_id": str(plan.plan_id),
                    "plan_frontend_id": plan.plan_frontend_id,
                    "plan_name": plan.plan_name,
                    "status": plan.plan_status
                })

            # Calculate fulfillment percentage
            fulfillment_percentage = round((total_fulfilled / max(total_rolls_ordered, 1)) * 100, 2)

            # Check if overdue
            is_overdue = order.delivery_date and order.delivery_date < datetime.utcnow() and order.status not in ['completed', 'cancelled']

            order_data = {
                "order_id": str(order.id),
                "order_frontend_id": order.frontend_id,
                "order_date": order.created_at.isoformat() if order.created_at else None,
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "status": order.status,
                "priority": order.priority,
                "payment_type": order.payment_type,

                # Main metrics
                "total_rolls_ordered": total_rolls_ordered,
                "total_cuts": total_cuts,
                "total_weight_ordered": total_weight_ordered,
                "total_order_value": total_order_value,

                # Pending items
                "pending_items_count": len(pending_items_data),
                "pending_items": pending_items_data,

                # Linked plans
                "linked_plans": linked_plans_data,

                # Calculated fields
                "fulfillment_percentage": fulfillment_percentage,
                "is_overdue": is_overdue
            }

            orders_response.append(order_data)

            # Update summary totals
            total_rolls_all += total_rolls_ordered
            total_cuts_all += total_cuts
            total_pending_all += total_pending_rolls

        # Calculate average fulfillment rate
        avg_fulfillment = 0
        if total_rolls_all > 0:
            avg_fulfillment = round((total_cuts_all / total_rolls_all) * 100, 2)

        return {
            "success": True,
            "data": {
                "client": {
                    "id": str(client.id),
                    "company_name": client.company_name,
                    "gst_number": client.gst_number,
                    "contact_person": client.contact_person,
                    "phone": client.phone
                },
                "orders": orders_response,
                "summary": {
                    "total_orders": len(orders_response),
                    "total_rolls_ordered": total_rolls_all,
                    "total_cuts": total_cuts_all,
                    "total_pending_rolls": total_pending_all,
                    "avg_fulfillment_rate": avg_fulfillment
                }
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in client order summary report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/client-order-summary/{order_frontend_id}/cut-rolls", tags=["Client Order Summary"])
def get_order_cut_rolls_details(
    order_frontend_id: str,
    include_dispatched: bool = Query(True, description="Include dispatched rolls"),
    db: Session = Depends(get_db)
):
    """
    Order Cut Rolls Details

    Returns detailed cut roll information for a specific order including:
    - Barcode IDs
    - Paper specifications
    - Status and location
    - Dispatch information
    - Mapping summary
    """
    try:
        # Find order by frontend_id
        order = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client)
        ).filter(
            models.OrderMaster.frontend_id == order_frontend_id
        ).first()

        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_frontend_id} not found")

        # Get cut rolls allocated to this order with plan information
        query = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.plan_inventory)
        ).filter(
            models.InventoryMaster.allocated_to_order_id == order.id
        )

        # Filter by dispatch status if needed
        if not include_dispatched:
            query = query.filter(models.InventoryMaster.status != 'dispatched')

        cut_rolls = query.order_by(models.InventoryMaster.created_at.desc()).all()

        # Get plan information for cut rolls
        cut_roll_ids = [roll.id for roll in cut_rolls]
        plan_info_map = {}

        if cut_roll_ids:
            plan_links = db.query(
                models.PlanInventoryLink.inventory_id,
                models.PlanMaster.frontend_id.label('plan_frontend_id')
            ).join(
                models.PlanMaster, models.PlanInventoryLink.plan_id == models.PlanMaster.id
            ).filter(
                models.PlanInventoryLink.inventory_id.in_(cut_roll_ids)
            ).all()

            for link in plan_links:
                if link.inventory_id not in plan_info_map:
                    plan_info_map[link.inventory_id] = []
                plan_info_map[link.inventory_id].append(link.plan_frontend_id)

        # Get dispatch information for cut rolls
        dispatched_inventory_ids = [roll.id for roll in cut_rolls if roll.status == 'dispatched']
        dispatch_info_map = {}

        if dispatched_inventory_ids:
            dispatch_items = db.query(models.DispatchItem).options(
                joinedload(models.DispatchItem.dispatch_record)
            ).filter(
                models.DispatchItem.inventory_id.in_(dispatched_inventory_ids)
            ).all()

            for d_item in dispatch_items:
                if d_item.inventory_id:
                    dispatch_info_map[d_item.inventory_id] = {
                        "dispatch_id": str(d_item.dispatch_record.id) if d_item.dispatch_record else None,
                        "dispatch_number": d_item.dispatch_record.dispatch_number if d_item.dispatch_record else None,
                        "dispatch_date": d_item.dispatch_record.dispatch_date.isoformat() if d_item.dispatch_record and d_item.dispatch_record.dispatch_date else None,
                        "vehicle_number": d_item.dispatch_record.vehicle_number if d_item.dispatch_record else None,
                        "driver_name": d_item.dispatch_record.driver_name if d_item.dispatch_record else None
                    }

        # Build cut rolls response
        cut_rolls_response = []
        status_count = {}
        width_count = {}
        total_weight = 0

        for roll in cut_rolls:
            # Get parent jumbo information and barcode
            # Handle both direct and indirect jumbo links (through 118" roll)
            parent_jumbo_info = None
            jumbo_barcode_id = None

            # First check for direct jumbo link
            if roll.parent_jumbo_id:
                parent_jumbo = db.query(models.InventoryMaster).filter(
                    models.InventoryMaster.id == roll.parent_jumbo_id
                ).first()
                if parent_jumbo:
                    jumbo_barcode_id = parent_jumbo.barcode_id
                    parent_jumbo_info = {
                        "id": str(parent_jumbo.id),
                        "frontend_id": parent_jumbo.frontend_id,
                        "barcode_id": parent_jumbo.barcode_id
                    }
            # If no direct jumbo, check through 118" roll
            elif roll.parent_118_roll_id:
                parent_118 = db.query(models.InventoryMaster).filter(
                    models.InventoryMaster.id == roll.parent_118_roll_id
                ).first()
                if parent_118 and parent_118.parent_jumbo_id:
                    # Get the jumbo roll from the 118" roll
                    parent_jumbo = db.query(models.InventoryMaster).filter(
                        models.InventoryMaster.id == parent_118.parent_jumbo_id
                    ).first()
                    if parent_jumbo:
                        jumbo_barcode_id = parent_jumbo.barcode_id
                        parent_jumbo_info = {
                            "id": str(parent_jumbo.id),
                            "frontend_id": parent_jumbo.frontend_id,
                            "barcode_id": parent_jumbo.barcode_id
                        }

            # Get plan frontend IDs for this cut roll
            plan_frontend_ids = plan_info_map.get(roll.id, [])

            # Get dispatch info
            dispatch_info = dispatch_info_map.get(roll.id, None)

            roll_data = {
                "id": str(roll.id),
                "frontend_id": roll.frontend_id,
                "barcode_id": roll.barcode_id,
                "plan_frontend_ids": plan_frontend_ids,  # NEW: Plan IDs
                "jumbo_barcode_id": jumbo_barcode_id,  # NEW: Jumbo barcode
                "width_inches": float(roll.width_inches),
                "weight_kg": float(roll.weight_kg),
                "roll_type": roll.roll_type,
                "status": roll.status,
                "location": roll.location,
                "production_date": roll.production_date.isoformat() if roll.production_date else None,
                "created_at": roll.created_at.isoformat() if roll.created_at else None,

                # Paper specifications
                "paper": {
                    "name": roll.paper.name if roll.paper else None,
                    "gsm": roll.paper.gsm if roll.paper else None,
                    "bf": float(roll.paper.bf) if roll.paper and roll.paper.bf else None,
                    "shade": roll.paper.shade if roll.paper else None,
                    "type": roll.paper.type if roll.paper else None
                } if roll.paper else None,

                # Tracking info
                "parent_jumbo": parent_jumbo_info,
                "roll_sequence": roll.roll_sequence,
                "individual_roll_number": roll.individual_roll_number,

                # Dispatch status
                "is_dispatched": roll.status == 'dispatched',
                "dispatch_info": dispatch_info
            }

            cut_rolls_response.append(roll_data)

            # Update summary counts
            status_count[roll.status] = status_count.get(roll.status, 0) + 1
            width_key = str(float(roll.width_inches))
            width_count[width_key] = width_count.get(width_key, 0) + 1
            total_weight += float(roll.weight_kg)

        # Build mapping summary
        mapping_summary = {
            "total_cut_rolls": len(cut_rolls_response),
            "by_status": status_count,
            "by_width": width_count,
            "total_weight_kg": round(total_weight, 2)
        }

        return {
            "success": True,
            "data": {
                "order_info": {
                    "order_id": str(order.id),
                    "order_frontend_id": order.frontend_id,
                    "client_name": order.client.company_name if order.client else None,
                    "order_date": order.created_at.isoformat() if order.created_at else None,
                    "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                    "status": order.status
                },
                "cut_rolls": cut_rolls_response,
                "mapping_summary": mapping_summary
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting cut rolls details for order {order_frontend_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CUT ROLLS WEIGHT UPDATE REPORT - New report for cut rolls with weight updates
# ============================================================================

@router.get("/reports/cut-rolls-weight-update", tags=["Cut Rolls Weight Report"])
def get_cut_rolls_weight_update_report(
    from_date: str = Query(..., description="From date (YYYY-MM-DD)"),
    to_date: str = Query(..., description="To date (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    Cut Rolls Weight Update Report

    Returns cut rolls that had their weight updated (status = AVAILABLE) within the specified date range:
    - Cut roll details with weight information
    - Parent 11-inch set roll information
    - Parent jumbo roll information
    - Associated plan information (plan frontend_id)
    - Paper specifications (GSM, BF, Shade)
    - Summary statistics
    """
    try:
        # Validate and parse the dates
        try:
            from_dt = datetime.fromisoformat(from_date)
            to_dt = datetime.fromisoformat(to_date)
            start_of_day = from_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        # Validate date range
        if start_of_day > end_of_day:
            raise HTTPException(status_code=400, detail="From date cannot be after to date")

        # Main query to get cut rolls with weight updates within the specified date range
        # We look for cut rolls where:
        # 1. roll_type = 'cut'
        # 2. status = 'AVAILABLE' (indicates weight was updated)
        # 3. updated_at falls within the date range
        query = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.parent_118_roll).joinedload(models.InventoryMaster.parent_jumbo),
            joinedload(models.InventoryMaster.plan_inventory).joinedload(models.PlanInventoryLink.plan)
        ).filter(
            and_(
                models.InventoryMaster.roll_type == 'cut',
                models.InventoryMaster.status == 'AVAILABLE',
                models.InventoryMaster.updated_at >= start_of_day,
                models.InventoryMaster.updated_at <= end_of_day
            )
        )

        cut_rolls = query.order_by(models.InventoryMaster.updated_at.desc()).all()

        if not cut_rolls:
            return {
                "success": True,
                "data": {
                    "cut_rolls": [],
                    "summary": {
                        "total_cut_rolls": 0,
                        "total_weight_kg": 0,
                        "unique_jumbo_rolls": 0,
                        "unique_118_rolls": 0,
                        "unique_plans": 0,
                        "unique_paper_types": 0,
                        "avg_weight_per_roll": 0,
                        "date_range": {
                            "from_date": from_date,
                            "to_date": to_date,
                            "start_time": start_of_day.isoformat(),
                            "end_time": end_of_day.isoformat()
                        }
                    }
                }
            }

        # Process cut rolls data
        cut_rolls_data = []
        jumbo_roll_ids = set()
        roll_118_ids = set()
        plan_ids = set()
        paper_type_ids = set()
        total_weight = 0

        for cut_roll in cut_rolls:
            # Get paper specifications
            paper = cut_roll.paper
            paper_specs = {
                "paper_name": paper.name if paper else "Unknown",
                "gsm": paper.gsm if paper else 0,
                "bf": float(paper.bf) if paper and paper.bf else 0,
                "shade": paper.shade if paper else "Unknown",
                "type": paper.type if paper else "Unknown"
            }

            # Get parent 11-inch roll information
            parent_118_roll = cut_roll.parent_118_roll
            parent_118_info = None
            parent_jumbo_info = None

            if parent_118_roll:
                parent_118_info = {
                    "id": str(parent_118_roll.id),
                    "frontend_id": parent_118_roll.frontend_id or "N/A",
                    "barcode_id": parent_118_roll.barcode_id or "N/A",
                    "width_inches": float(parent_118_roll.width_inches),
                    "weight_kg": float(parent_118_roll.weight_kg) if parent_118_roll.weight_kg else 0,
                    "roll_sequence": parent_118_roll.roll_sequence
                }
                roll_118_ids.add(str(parent_118_roll.id))

                # Get parent jumbo roll information
                parent_jumbo = parent_118_roll.parent_jumbo
                if parent_jumbo:
                    parent_jumbo_info = {
                        "id": str(parent_jumbo.id),
                        "frontend_id": parent_jumbo.frontend_id or "N/A",
                        "barcode_id": parent_jumbo.barcode_id or "N/A",
                        "width_inches": float(parent_jumbo.width_inches),
                        "weight_kg": float(parent_jumbo.weight_kg) if parent_jumbo.weight_kg else 0
                    }
                    jumbo_roll_ids.add(str(parent_jumbo.id))
                else:
                    # If no jumbo parent, check if 118 roll itself is a jumbo
                    if parent_118_roll.roll_type == 'jumbo':
                        parent_jumbo_info = {
                            "id": str(parent_118_roll.id),
                            "frontend_id": parent_118_roll.frontend_id or "N/A",
                            "barcode_id": parent_118_roll.barcode_id or "N/A",
                            "width_inches": float(parent_118_roll.width_inches),
                            "weight_kg": float(parent_118_roll.weight_kg) if parent_118_roll.weight_kg else 0
                        }
                        jumbo_roll_ids.add(str(parent_118_roll.id))

            # Get plan information
            plan_info = None
            if cut_roll.plan_inventory:
                for plan_link in cut_roll.plan_inventory:
                    if plan_link.plan:
                        plan_info = {
                            "id": str(plan_link.plan.id),
                            "frontend_id": plan_link.plan.frontend_id or "N/A",
                            "name": plan_link.plan.name or "Unnamed Plan",
                            "status": plan_link.plan.status,
                            "created_at": plan_link.plan.created_at.isoformat() if plan_link.plan.created_at else None
                        }
                        plan_ids.add(str(plan_link.plan.id))
                        break  # Take the first plan found

            # Get allocated order information
            order_info = None
            if cut_roll.allocated_to_order_id:
                order_info = {
                    "id": str(cut_roll.allocated_to_order_id),
                    "frontend_id": None  # Will be populated if we join with OrderMaster
                }

            # Compile cut roll data
            cut_roll_data = {
                "id": str(cut_roll.id),
                "frontend_id": cut_roll.frontend_id or "N/A",
                "barcode_id": cut_roll.barcode_id or "N/A",
                "width_inches": float(cut_roll.width_inches),
                "weight_kg": float(cut_roll.weight_kg) if cut_roll.weight_kg else 0,
                "location": cut_roll.location or "N/A",
                "status": cut_roll.status,
                "production_date": cut_roll.updated_at.isoformat() if cut_roll.updated_at else None,
                "roll_sequence": cut_roll.roll_sequence,
                "individual_roll_number": cut_roll.individual_roll_number,

                # Related data
                "paper_specs": paper_specs,
                "parent_118_roll": parent_118_info,
                "parent_jumbo_roll": parent_jumbo_info,
                "plan_info": plan_info,
                "allocated_order": order_info,

                # Source tracking
                "source_type": cut_roll.source_type,
                "is_wastage_roll": cut_roll.is_wastage_roll
            }

            cut_rolls_data.append(cut_roll_data)

            # Update summary statistics
            total_weight += float(cut_roll.weight_kg) if cut_roll.weight_kg else 0
            if paper:
                paper_type_ids.add(str(paper.id))

        # Calculate summary
        summary = {
            "total_cut_rolls": len(cut_rolls_data),
            "total_weight_kg": round(total_weight, 2),
            "unique_jumbo_rolls": len(jumbo_roll_ids),
            "unique_118_rolls": len(roll_118_ids),
            "unique_plans": len(plan_ids),
            "unique_paper_types": len(paper_type_ids),
            "avg_weight_per_roll": round(total_weight / max(len(cut_rolls_data), 1), 2),
            "date_range": {
                "from_date": from_date,
                "to_date": to_date,
                "start_time": start_of_day.isoformat(),
                "end_time": end_of_day.isoformat()
            }
        }

        return {
            "success": True,
            "data": {
                "cut_rolls": cut_rolls_data,
                "summary": summary
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in cut rolls weight update report: {e}")
        raise HTTPException(status_code=500, detail=str(e))