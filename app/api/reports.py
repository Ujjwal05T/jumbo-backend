from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, and_, or_, text, case
from typing import Dict, List, Any, Optional
import logging
import uuid
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