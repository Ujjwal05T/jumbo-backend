from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, timedelta
import json
import logging

from .. import models

logger = logging.getLogger(__name__)

class CRUDPlanDeletionLog:
    def create_deletion_log(
        self,
        db: Session,
        *,
        plan_id: UUID,
        plan_frontend_id: str,
        plan_name: str,
        user_id: UUID,
        deletion_reason: str = "rollback",
        rollback_stats: Optional[Dict[str, Any]] = None,
        rollback_duration_seconds: Optional[float] = None,
        success_status: str = "success",
        error_message: Optional[str] = None
    ) -> models.PlanDeletionLog:
        """Create a plan deletion log entry"""

        try:
            logger.info(f"Creating plan deletion log for plan {plan_frontend_id} ({plan_id})")

            log_entry = models.PlanDeletionLog(
                plan_id=plan_id,
                plan_frontend_id=plan_frontend_id,
                plan_name=plan_name,
                deleted_by_id=user_id,
                deletion_reason=deletion_reason,
                rollback_stats=rollback_stats,
                rollback_duration_seconds=rollback_duration_seconds,
                success_status=success_status,
                error_message=error_message
            )

            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)

            logger.info(f"Successfully created plan deletion log:")
            logger.info(f"   - Log ID: {log_entry.id}")
            logger.info(f"   - Plan: {plan_frontend_id} ({plan_id})")
            logger.info(f"   - Reason: {deletion_reason}")
            logger.info(f"   - Status: {success_status}")

            return log_entry

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create plan deletion log: {e}")
            raise

    def get_deletion_logs_by_plan(
        self,
        db: Session,
        *,
        plan_id: UUID
    ) -> list[models.PlanDeletionLog]:
        """Get all deletion logs for a specific plan"""

        try:
            logs = db.query(models.PlanDeletionLog).filter(
                models.PlanDeletionLog.plan_id == plan_id
            ).order_by(
                models.PlanDeletionLog.deleted_at.desc()
            ).all()

            logger.info(f"Found {len(logs)} deletion logs for plan {plan_id}")
            return logs

        except Exception as e:
            logger.error(f"Failed to get deletion logs: {e}")
            return []

    def get_deletion_logs_by_user(
        self,
        db: Session,
        *,
        user_id: UUID,
        limit: int = 50
    ) -> list[models.PlanDeletionLog]:
        """Get deletion logs created by a specific user"""

        try:
            logs = db.query(models.PlanDeletionLog).filter(
                models.PlanDeletionLog.deleted_by_id == user_id
            ).order_by(
                models.PlanDeletionLog.deleted_at.desc()
            ).limit(limit).all()

            logger.info(f"Found {len(logs)} deletion logs by user {user_id}")
            return logs

        except Exception as e:
            logger.error(f"Failed to get user deletion logs: {e}")
            return []

    def get_deletion_logs_by_reason(
        self,
        db: Session,
        *,
        deletion_reason: str,
        limit: int = 50
    ) -> list[models.PlanDeletionLog]:
        """Get deletion logs filtered by reason"""

        try:
            logs = db.query(models.PlanDeletionLog).filter(
                models.PlanDeletionLog.deletion_reason == deletion_reason
            ).order_by(
                models.PlanDeletionLog.deleted_at.desc()
            ).limit(limit).all()

            logger.info(f"Found {len(logs)} deletion logs with reason '{deletion_reason}'")
            return logs

        except Exception as e:
            logger.error(f"Failed to get deletion logs by reason: {e}")
            return []

    def get_recent_deletion_logs(
        self,
        db: Session,
        *,
        limit: int = 100
    ) -> list[models.PlanDeletionLog]:
        """Get recent deletion logs across all users"""

        try:
            logs = db.query(models.PlanDeletionLog).order_by(
                models.PlanDeletionLog.deleted_at.desc()
            ).limit(limit).all()

            logger.info(f"Found {len(logs)} recent deletion logs")
            return logs

        except Exception as e:
            logger.error(f"Failed to get recent deletion logs: {e}")
            return []

    def get_deletion_logs(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        plan_id: Optional[str] = None,
        user_id: Optional[str] = None,
        deletion_reason: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        success_status: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get paginated deletion logs with filtering"""

        try:
            # Build base query
            query = db.query(models.PlanDeletionLog).join(
                models.UserMaster, models.PlanDeletionLog.deleted_by_id == models.UserMaster.id
            )

            # Apply filters
            filters = []

            if plan_id:
                # Search by plan frontend ID (string search) or plan_id (exact match)
                filters.append(
                    or_(
                        models.PlanDeletionLog.plan_frontend_id.ilike(f"%{plan_id}%"),
                        models.PlanDeletionLog.plan_name.ilike(f"%{plan_id}%"),
                        models.PlanDeletionLog.plan_id == plan_id if self._is_valid_uuid(plan_id) else False
                    )
                )

            if user_id:
                filters.append(models.PlanDeletionLog.deleted_by_id == user_id)

            if deletion_reason:
                filters.append(models.PlanDeletionLog.deletion_reason == deletion_reason)

            if success_status:
                filters.append(models.PlanDeletionLog.success_status == success_status)

            if start_date:
                try:
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    filters.append(models.PlanDeletionLog.deleted_at >= start_dt)
                except ValueError:
                    logger.warning(f"Invalid start_date format: {start_date}")

            if end_date:
                try:
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                    # Add one day to include the end date
                    end_dt = end_dt + timedelta(days=1)
                    filters.append(models.PlanDeletionLog.deleted_at < end_dt)
                except ValueError:
                    logger.warning(f"Invalid end_date format: {end_date}")

            # Apply filters to query
            if filters:
                query = query.filter(and_(*filters))

            # Get total count
            total_count = query.count()

            # Apply pagination and ordering
            offset = (page - 1) * page_size
            logs = query.order_by(desc(models.PlanDeletionLog.deleted_at)).offset(offset).limit(page_size).all()

            # Convert to dict format
            logs_data = []
            for log in logs:
                log_dict = {
                    "id": str(log.id),
                    "plan_id": str(log.plan_id) if log.plan_id else None,
                    "plan_frontend_id": log.plan_frontend_id,
                    "plan_name": log.plan_name,
                    "deleted_at": log.deleted_at.isoformat() if log.deleted_at else None,
                    "deleted_by_id": str(log.deleted_by_id),
                    "deletion_reason": log.deletion_reason,
                    "rollback_stats": log.rollback_stats,
                    "rollback_duration_seconds": log.rollback_duration_seconds,
                    "success_status": log.success_status,
                    "error_message": log.error_message,
                    "deleted_by_user": {
                        "id": str(log.deleted_by.id),
                        "name": log.deleted_by.name,
                        "username": log.deleted_by.username
                    } if log.deleted_by else None
                }
                logs_data.append(log_dict)

            total_pages = (total_count + page_size - 1) // page_size

            logger.info(f"Retrieved {len(logs)} deletion logs (page {page} of {total_pages})")

            return {
                "logs": logs_data,
                "total_count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }

        except Exception as e:
            logger.error(f"Failed to get deletion logs: {e}")
            raise

    def _is_valid_uuid(self, uuid_string: str) -> bool:
        """Check if a string is a valid UUID"""
        try:
            UUID(uuid_string)
            return True
        except ValueError:
            return False

plan_deletion_logs = CRUDPlanDeletionLog()