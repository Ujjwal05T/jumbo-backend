from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc
from typing import Dict, List, Any
import logging
from datetime import datetime, timedelta

from .base import get_db
from .. import models, schemas, crud_operations

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/dashboard/summary", tags=["Dashboard"])
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    Get comprehensive dashboard summary with all key metrics
    """
    try:
        # Orders Summary
        total_orders = db.query(models.OrderMaster).count()
        pending_orders = db.query(models.OrderMaster).filter(
            models.OrderMaster.status == schemas.OrderStatus.CREATED.value
        ).count()
        processing_orders = db.query(models.OrderMaster).filter(
            models.OrderMaster.status == schemas.OrderStatus.IN_PROCESS.value
        ).count()
        completed_orders = db.query(models.OrderMaster).filter(
            models.OrderMaster.status == schemas.OrderStatus.COMPLETED.value
        ).count()
        
        # Pending Order Items Summary
        pending_items = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "pending"
        ).count()
        pending_quantity = db.query(func.sum(models.PendingOrderItem.quantity_pending)).filter(
            models.PendingOrderItem.status == "pending"
        ).scalar() or 0
        
        high_priority_pending = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "pending",
            models.PendingOrderItem.created_at < datetime.utcnow() - timedelta(days=3)
        ).count()
        
        # Plans Summary
        total_plans = db.query(models.PlanMaster).count()
        planned_status = db.query(models.PlanMaster).filter(
            models.PlanMaster.status == schemas.PlanStatus.PLANNED.value
        ).count()
        in_progress_plans = db.query(models.PlanMaster).filter(
            models.PlanMaster.status == schemas.PlanStatus.IN_PROGRESS.value
        ).count()
        completed_plans = db.query(models.PlanMaster).filter(
            models.PlanMaster.status == schemas.PlanStatus.COMPLETED.value
        ).count()
        
        # Inventory Summary
        available_inventory = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.status == schemas.InventoryStatus.AVAILABLE.value
        ).count()
        jumbo_rolls = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.roll_type == schemas.RollType.JUMBO.value,
            models.InventoryMaster.status == schemas.InventoryStatus.AVAILABLE.value
        ).count()
        cut_rolls = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.roll_type == schemas.RollType.CUT.value,
            models.InventoryMaster.status == schemas.InventoryStatus.AVAILABLE.value
        ).count()
        
        # Production Orders Summary
        total_production = db.query(models.ProductionOrderMaster).count()
        pending_production = db.query(models.ProductionOrderMaster).filter(
            models.ProductionOrderMaster.status == schemas.ProductionOrderStatus.PENDING.value
        ).count()
        in_progress_production = db.query(models.ProductionOrderMaster).filter(
            models.ProductionOrderMaster.status == schemas.ProductionOrderStatus.IN_PROGRESS.value
        ).count()
        completed_production = db.query(models.ProductionOrderMaster).filter(
            models.ProductionOrderMaster.status == schemas.ProductionOrderStatus.COMPLETED.value
        ).count()
        
        # Recent Activity (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_orders = db.query(models.OrderMaster).filter(
            models.OrderMaster.created_at >= week_ago
        ).count()
        recent_plans = db.query(models.PlanMaster).filter(
            models.PlanMaster.created_at >= week_ago
        ).count()
        recent_production = db.query(models.ProductionOrderMaster).filter(
            models.ProductionOrderMaster.created_at >= week_ago
        ).count()
        
        # Paper Types Summary
        paper_types = db.query(models.PaperMaster).count()
        
        # Client Summary
        total_clients = db.query(models.ClientMaster).count()
        active_clients = db.query(func.count(func.distinct(models.OrderMaster.client_id))).filter(
            models.OrderMaster.created_at >= week_ago
        ).scalar() or 0
        
        return {
            "status": "success",
            "summary": {
                "orders": {
                    "total": total_orders,
                    "pending": pending_orders,
                    "processing": processing_orders,
                    "completed": completed_orders,
                    "completion_rate": round((completed_orders / max(total_orders, 1)) * 100, 1)
                },
                "pending_items": {
                    "total_items": pending_items,
                    "total_quantity": int(pending_quantity),
                    "high_priority": high_priority_pending,
                    "avg_wait_time": 0  # Will calculate this later
                },
                "plans": {
                    "total": total_plans,
                    "planned": planned_status,
                    "in_progress": in_progress_plans,
                    "completed": completed_plans,
                    "success_rate": round((completed_plans / max(total_plans, 1)) * 100, 1)
                },
                "inventory": {
                    "total_available": available_inventory,
                    "jumbo_rolls": jumbo_rolls,
                    "cut_rolls": cut_rolls,
                    "utilization_rate": 0  # Will calculate this later
                },
                "production": {
                    "total": total_production,
                    "pending": pending_production,
                    "in_progress": in_progress_production,
                    "completed": completed_production,
                    "efficiency": round((completed_production / max(total_production, 1)) * 100, 1)
                },
                "activity": {
                    "recent_orders": recent_orders,
                    "recent_plans": recent_plans,
                    "recent_production": recent_production,
                    "total_clients": total_clients,
                    "active_clients": active_clients,
                    "paper_types": paper_types
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting dashboard summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/recent-activity", tags=["Dashboard"])
def get_recent_activity(limit: int = 10, db: Session = Depends(get_db)):
    """
    Get recent activity across all modules
    """
    try:
        activities = []
        
        # Recent Orders
        recent_orders = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client)
        ).order_by(desc(models.OrderMaster.created_at)).limit(5).all()
        
        for order in recent_orders:
            try:
                activities.append({
                    "id": str(order.id),
                    "type": "order",
                    "title": f"New Order Created",
                    "description": f"Order for {order.client.company_name if order.client else 'Unknown Client'}",
                    "timestamp": order.created_at.isoformat(),
                    "status": order.status,
                    "icon": "package"
                })
            except Exception as e:
                logger.warning(f"Error processing order activity {order.id}: {e}")
                continue
        
        # Recent Plans
        recent_plans = db.query(models.PlanMaster).order_by(desc(models.PlanMaster.created_at)).limit(5).all()
        
        for plan in recent_plans:
            try:
                activities.append({
                    "id": str(plan.id),
                    "type": "plan",
                    "title": f"Cutting Plan Created",
                    "description": plan.name or f"Plan {plan.id}",
                    "timestamp": plan.created_at.isoformat(),
                    "status": plan.status,
                    "icon": "scissors"
                })
            except Exception as e:
                logger.warning(f"Error processing plan activity {plan.id}: {e}")
                continue
        
        # Recent Production Orders
        recent_production = db.query(models.ProductionOrderMaster).order_by(desc(models.ProductionOrderMaster.created_at)).limit(5).all()
        
        for prod in recent_production:
            try:
                activities.append({
                    "id": str(prod.id),
                    "type": "production",
                    "title": f"Production Order Created",
                    "description": f"Quantity: {prod.quantity}",
                    "timestamp": prod.created_at.isoformat(),
                    "status": prod.status,
                    "icon": "factory"
                })
            except Exception as e:
                logger.warning(f"Error processing production activity {prod.id}: {e}")
                continue
        
        # Sort by timestamp descending and limit
        activities.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {
            "status": "success",
            "activities": activities[:limit]
        }
        
    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/alerts", tags=["Dashboard"])
def get_dashboard_alerts(db: Session = Depends(get_db)):
    """
    Get system alerts and notifications
    """
    try:
        alerts = []
        
        # High priority pending orders
        high_priority = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "pending",
            models.PendingOrderItem.created_at < datetime.utcnow() - timedelta(days=3)
        ).count()
        
        if high_priority > 0:
            alerts.append({
                "id": "high_priority_pending",
                "type": "warning",
                "title": "High Priority Pending Orders",
                "message": f"{high_priority} pending orders waiting 3+ days",
                "action": "View Pending Orders",
                "link": "/masters/pending-orders"
            })
        
        # Low inventory warning
        low_inventory = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.status == schemas.InventoryStatus.AVAILABLE.value,
            models.InventoryMaster.roll_type == schemas.RollType.JUMBO.value
        ).count()
        
        if low_inventory < 5:
            alerts.append({
                "id": "low_inventory",
                "type": "error",
                "title": "Low Inventory Alert",
                "message": f"Only {low_inventory} jumbo rolls available",
                "action": "Check Inventory",
                "link": "/masters/inventory"
            })
        
        # Stalled plans
        stalled_plans = db.query(models.PlanMaster).filter(
            models.PlanMaster.status == schemas.PlanStatus.PLANNED.value,
            models.PlanMaster.created_at < datetime.utcnow() - timedelta(days=2)
        ).count()
        
        if stalled_plans > 0:
            alerts.append({
                "id": "stalled_plans",
                "type": "info",
                "title": "Plans Awaiting Execution",
                "message": f"{stalled_plans} plans ready for production",
                "action": "View Plans",
                "link": "/masters/plans"
            })
        
        return {
            "status": "success",
            "alerts": alerts
        }
        
    except Exception as e:
        logger.error(f"Error getting dashboard alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))