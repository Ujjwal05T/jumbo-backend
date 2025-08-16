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