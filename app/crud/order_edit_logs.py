"""
CRUD operations for Order Edit Logs
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from datetime import datetime, date
import json

from ..models import OrderEditLog, OrderMaster, UserMaster
from .base import CRUDBase


class CRUDOrderEditLog(CRUDBase[OrderEditLog, None, None]):

    def create_log(
        self,
        db: Session,
        *,
        order_id: str,
        edited_by_id: str,
        action: str,
        field_name: Optional[str] = None,
        old_value: Optional[Any] = None,
        new_value: Optional[Any] = None,
        description: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> OrderEditLog:
        """
        Create a new order edit log entry
        """
        # Convert values to strings for storage
        old_value_str = None
        new_value_str = None

        if old_value is not None:
            if isinstance(old_value, (dict, list)):
                old_value_str = json.dumps(old_value)
            else:
                old_value_str = str(old_value)

        if new_value is not None:
            if isinstance(new_value, (dict, list)):
                new_value_str = json.dumps(new_value)
            else:
                new_value_str = str(new_value)

        log_entry = OrderEditLog(
            order_id=order_id,
            edited_by_id=edited_by_id,
            action=action,
            field_name=field_name,
            old_value=old_value_str,
            new_value=new_value_str,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent
        )

        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry

    def get_logs_by_order(
        self,
        db: Session,
        *,
        order_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[OrderEditLog]:
        """
        Get all edit logs for a specific order
        """
        return (
            db.query(OrderEditLog)
            .filter(OrderEditLog.order_id == order_id)
            .order_by(desc(OrderEditLog.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_logs_with_details(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        order_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Get edit logs with order and user details, with optional filters
        """
        query = (
            db.query(OrderEditLog, OrderMaster, UserMaster)
            .join(OrderMaster, OrderEditLog.order_id == OrderMaster.id)
            .join(UserMaster, OrderEditLog.edited_by_id == UserMaster.id)
        )

        # Apply filters
        filters = []
        if order_id:
            filters.append(OrderEditLog.order_id == order_id)
        if user_id:
            filters.append(OrderEditLog.edited_by_id == user_id)
        if action:
            filters.append(OrderEditLog.action == action)
        if start_date:
            filters.append(OrderEditLog.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            filters.append(OrderEditLog.created_at <= datetime.combine(end_date, datetime.max.time()))

        if filters:
            query = query.filter(and_(*filters))

        results = (
            query
            .order_by(desc(OrderEditLog.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Format the results
        formatted_results = []
        for log, order, user in results:
            formatted_results.append({
                "id": str(log.id),
                "frontend_id": log.frontend_id,
                "order_id": str(log.order_id),
                "order_frontend_id": order.frontend_id,
                "edited_by_id": str(log.edited_by_id),
                "edited_by_name": user.name,
                "edited_by_username": user.username,
                "action": log.action,
                "field_name": log.field_name,
                "old_value": log.old_value,
                "new_value": log.new_value,
                "description": log.description,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "order_details": {
                    "frontend_id": order.frontend_id,
                    "client_id": str(order.client_id) if order.client_id else None,
                    "status": order.status,
                    "priority": order.priority,
                    "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None
                }
            })

        return formatted_results

    def get_recent_logs(
        self,
        db: Session,
        *,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get recent edit logs for dashboard/activity feed
        """
        return self.get_logs_with_details(db, skip=0, limit=limit)

    def get_logs_count(
        self,
        db: Session,
        *,
        order_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> int:
        """
        Get count of logs matching filters
        """
        query = db.query(OrderEditLog)

        # Apply filters
        filters = []
        if order_id:
            filters.append(OrderEditLog.order_id == order_id)
        if user_id:
            filters.append(OrderEditLog.edited_by_id == user_id)
        if action:
            filters.append(OrderEditLog.action == action)
        if start_date:
            filters.append(OrderEditLog.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            filters.append(OrderEditLog.created_at <= datetime.combine(end_date, datetime.max.time()))

        if filters:
            query = query.filter(and_(*filters))

        return query.count()

    def get_unique_actions(self, db: Session) -> List[str]:
        """
        Get list of unique actions for filtering
        """
        results = db.query(OrderEditLog.action).distinct().all()
        return [result[0] for result in results if result[0]]


# Create instance
order_edit_log = CRUDOrderEditLog(OrderEditLog)