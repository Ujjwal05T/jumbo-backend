from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime
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
            logger.info(f"📝 Creating plan deletion log for plan {plan_frontend_id} ({plan_id})")

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

            logger.info(f"✅ Successfully created plan deletion log:")
            logger.info(f"   - Log ID: {log_entry.id}")
            logger.info(f"   - Plan: {plan_frontend_id} ({plan_id})")
            logger_info(f"   - Reason: {deletion_reason}")
            logger.info(f"   - Status: {success_status}")

            return log_entry

        except Exception as e:
            db.rollback()
            logger.error(f"❌ Failed to create plan deletion log: {e}")
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

            logger.info(f"📋 Found {len(logs)} deletion logs for plan {plan_id}")
            return logs

        except Exception as e:
            logger.error(f"❌ Failed to get deletion logs: {e}")
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

            logger.info(f"📋 Found {len(logs)} deletion logs by user {user_id}")
            return logs

        except Exception as e:
            logger.error(f"❌ Failed to get user deletion logs: {e}")
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

            logger.info(f"📋 Found {len(logs)} deletion logs with reason '{deletion_reason}'")
            return logs

        except Exception as e:
            logger.error(f"❌ Failed to get deletion logs by reason: {e}")
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

            logger.info(f"📋 Found {len(logs)} recent deletion logs")
            return logs

        except Exception as e:
            logger.error(f"❌ Failed to get recent deletion logs: {e}")
            return []

    def get_rollback_statistics(
        self,
        db: Session,
        *,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get rollback statistics for the last N days"""

        try:
            from datetime import timedelta

            cutoff_date = datetime.utcnow() - timedelta(days=days)

            total_rollbacks = db.query(models.PlanDeletionLog).filter(
                models.PlanDeletionLog.deleted_at >= cutoff_date,
                models.PlanDeletionLog.deletion_reason == "rollback"
            ).count()

            successful_rollbacks = db.query(models.PlanDeletionLog).filter(
                models.PlanDeletionLog.deleted_at >= cutoff_date,
                models.PlanDeletionLog.deletion_reason == "rollback",
                models.PlanDeletionLog.success_status == "success"
            ).count()

            failed_rollbacks = db.query(models.PlanDeletionLog).filter(
                models.PlanDeletionLog.deleted_at >= cutoff_date,
                models.PlanDeletionLog.deletion_reason == "rollback",
                models.PlanDeletionLog.success_status == "failed"
            ).count()

            # Calculate average rollback time
            avg_duration_result = db.query(
                models.PlanDeletionLog.rollback_duration_seconds
            ).filter(
                models.PlanDeletionLog.deleted_at >= cutoff_date,
                models.PlanDeletionLog.deletion_reason == "rollback",
                models.PlanDeletionLog.rollback_duration_seconds.isnot(None)
            ).first()

            avg_duration = float(avg_duration_result.rollback_duration_seconds) if avg_duration_result else 0

            return {
                "period_days": days,
                "total_rollbacks": total_rollbacks,
                "successful_rollbacks": successful_rollbacks,
                "failed_rollbacks": failed_rollbacks,
                "success_rate": (successful_rollbacks / total_rollbacks * 100) if total_rollbacks > 0 else 0,
                "average_duration_seconds": avg_duration,
                "most_common_reason": "rollback"
            }

        except Exception as e:
            logger.error(f"❌ Failed to get rollback statistics: {e}")
            return {}

plan_deletion_logs = CRUDPlanDeletionLog()