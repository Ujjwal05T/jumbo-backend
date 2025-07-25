from typing import Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
import logging

from .. import models, crud

logger = logging.getLogger(__name__)

class StatusService:
    """
    Service to handle status updates for master-based architecture models.
    Provides centralized status management for OrderMaster, PlanMaster, etc.
    """
    
    def __init__(self, db: Session, user_id: Optional[uuid.UUID] = None):
        self.db = db
        self.user_id = user_id

    def update_status(
        self,
        obj: Any,
        new_status: str,
        notes: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """
        Update the status of any master model that has a status field.
        
        Args:
            obj: Model instance to update (OrderMaster, PlanMaster, etc.)
            new_status: New status value
            notes: Optional notes about the status change
            commit: Whether to commit the transaction
        """
        model_type = obj.__class__.__name__
        old_status = getattr(obj, 'status', None)
        
        if not hasattr(obj, 'status'):
            raise ValueError(f"Model {model_type} does not have a status field")
        
        # Update the status
        setattr(obj, 'status', new_status)
        
        # Update timestamps if they exist
        if hasattr(obj, 'updated_at'):
            obj.updated_at = datetime.utcnow()
        
        # Log the status change
        logger.info(f"Status updated for {model_type} {obj.id}: {old_status} -> {new_status}")
        if notes:
            logger.info(f"Status change notes: {notes}")
        
        if commit:
            try:
                self.db.commit()
                logger.info(f"Status change committed for {model_type} {obj.id}")
            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to update status for {model_type} {obj.id}: {str(e)}")
                raise

    def update_order_status(
        self,
        order: models.OrderMaster,
        new_status: str,
        notes: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """
        Update order status with validation for OrderMaster.
        
        Args:
            order: OrderMaster instance
            new_status: New status value
            notes: Optional notes
            commit: Whether to commit
        """
        valid_statuses = ["pending", "processing", "partially_fulfilled", "completed", "cancelled"]
        
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid order status '{new_status}'. Must be one of: {valid_statuses}")
        
        self.update_status(order, new_status, notes, commit)

    def update_plan_status(
        self,
        plan: models.PlanMaster,
        new_status: str,
        notes: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """
        Update plan status with validation for PlanMaster.
        
        Args:
            plan: PlanMaster instance
            new_status: New status value
            notes: Optional notes
            commit: Whether to commit
        """
        valid_statuses = ["planned", "in_progress", "completed", "failed"]
        
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid plan status '{new_status}'. Must be one of: {valid_statuses}")
        
        # Set execution timestamp for in_progress
        if new_status == "in_progress" and not plan.executed_at:
            plan.executed_at = datetime.utcnow()
        
        # Set completion timestamp for completed
        if new_status == "completed" and not plan.completed_at:
            plan.completed_at = datetime.utcnow()
        
        self.update_status(plan, new_status, notes, commit)

    def update_inventory_status(
        self,
        inventory: models.InventoryMaster,
        new_status: str,
        notes: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """
        Update inventory status with validation for InventoryMaster.
        
        Args:
            inventory: InventoryMaster instance
            new_status: New status value
            notes: Optional notes
            commit: Whether to commit
        """
        valid_statuses = ["available", "allocated", "cutting", "used", "damaged"]
        
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid inventory status '{new_status}'. Must be one of: {valid_statuses}")
        
        self.update_status(inventory, new_status, notes, commit)

    def update_production_order_status(
        self,
        production_order: models.ProductionOrderMaster,
        new_status: str,
        notes: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """
        Update production order status with validation for ProductionOrderMaster.
        
        Args:
            production_order: ProductionOrderMaster instance
            new_status: New status value
            notes: Optional notes
            commit: Whether to commit
        """
        valid_statuses = ["pending", "in_progress", "completed", "cancelled"]
        
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid production order status '{new_status}'. Must be one of: {valid_statuses}")
        
        # Set timestamps based on status
        if new_status == "in_progress" and not production_order.started_at:
            production_order.started_at = datetime.utcnow()
        
        if new_status == "completed" and not production_order.completed_at:
            production_order.completed_at = datetime.utcnow()
        
        self.update_status(production_order, new_status, notes, commit)

    def create_pending_order(
        self,
        original_order: models.OrderMaster,
        quantity: int,
        reason: str = "insufficient_inventory",
        notes: Optional[str] = None
    ) -> models.PendingOrderMaster:
        """
        Create a pending order from an existing order using master architecture.
        
        Args:
            original_order: Original OrderMaster instance
            quantity: Quantity that couldn't be fulfilled
            reason: Reason for pending status
            notes: Optional notes
            
        Returns:
            Created PendingOrderMaster instance
        """
        if quantity <= 0:
            raise ValueError("Pending order quantity must be greater than 0")
        
        remaining_qty = original_order.quantity - (original_order.quantity_fulfilled or 0)
        if quantity > remaining_qty:
            raise ValueError("Pending quantity exceeds remaining order quantity")
        
        # Create pending order using master architecture
        pending_order = models.PendingOrderMaster(
            original_order_id=original_order.id,
            paper_id=original_order.paper_id,
            width=original_order.width_inches,
            quantity=quantity,
            min_length=original_order.min_length,
            reason=reason,
            status="pending",
            created_by_id=self.user_id or original_order.created_by_id
        )
        
        self.db.add(pending_order)
        
        # Update original order status
        if original_order.quantity_fulfilled is None:
            original_order.quantity_fulfilled = 0
        
        fulfilled_qty = original_order.quantity_fulfilled
        total_qty = original_order.quantity
        
        if fulfilled_qty >= total_qty:
            new_status = "completed"
        elif fulfilled_qty > 0:
            new_status = "partially_fulfilled"
        else:
            new_status = "pending"
        
        self.update_order_status(
            original_order,
            new_status,
            f"Created pending order for {quantity} units. {notes or ''}".strip(),
            commit=False
        )
        
        try:
            self.db.commit()
            logger.info(f"Created pending order {pending_order.id} from order {original_order.id}")
            return pending_order
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create pending order: {str(e)}")
            raise

    def bulk_update_order_statuses(
        self,
        order_status_updates: list[tuple[models.OrderMaster, str, Optional[str]]]
    ) -> None:
        """
        Bulk update multiple order statuses in a single transaction.
        
        Args:
            order_status_updates: List of tuples (order, new_status, notes)
        """
        try:
            for order, new_status, notes in order_status_updates:
                self.update_order_status(order, new_status, notes, commit=False)
            
            self.db.commit()
            logger.info(f"Bulk updated {len(order_status_updates)} order statuses")
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to bulk update order statuses: {str(e)}")
            raise

    def get_status_summary(self) -> dict:
        """
        Get a summary of statuses across all master tables.
        
        Returns:
            Dictionary with status counts for each master table
        """
        try:
            summary = {
                "orders": {},
                "plans": {},
                "inventory": {},
                "production_orders": {},
                "pending_orders": {}
            }
            
            # Order statuses
            order_statuses = self.db.query(
                models.OrderMaster.status,
                self.db.func.count(models.OrderMaster.id)
            ).group_by(models.OrderMaster.status).all()
            
            for status, count in order_statuses:
                summary["orders"][status] = count
            
            # Plan statuses
            plan_statuses = self.db.query(
                models.PlanMaster.status,
                self.db.func.count(models.PlanMaster.id)
            ).group_by(models.PlanMaster.status).all()
            
            for status, count in plan_statuses:
                summary["plans"][status] = count
            
            # Inventory statuses
            inventory_statuses = self.db.query(
                models.InventoryMaster.status,
                self.db.func.count(models.InventoryMaster.id)
            ).group_by(models.InventoryMaster.status).all()
            
            for status, count in inventory_statuses:
                summary["inventory"][status] = count
            
            # Production order statuses
            production_statuses = self.db.query(
                models.ProductionOrderMaster.status,
                self.db.func.count(models.ProductionOrderMaster.id)
            ).group_by(models.ProductionOrderMaster.status).all()
            
            for status, count in production_statuses:
                summary["production_orders"][status] = count
            
            # Pending order statuses
            pending_statuses = self.db.query(
                models.PendingOrderMaster.status,
                self.db.func.count(models.PendingOrderMaster.id)
            ).group_by(models.PendingOrderMaster.status).all()
            
            for status, count in pending_statuses:
                summary["pending_orders"][status] = count
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to get status summary: {str(e)}")
            raise

    def get_orders_by_status(self, status: str, limit: int = 100) -> list[models.OrderMaster]:
        """
        Get orders by status using master architecture.
        
        Args:
            status: Status to filter by
            limit: Maximum number of orders to return
            
        Returns:
            List of OrderMaster instances
        """
        return self.db.query(models.OrderMaster).filter(
            models.OrderMaster.status == status
        ).limit(limit).all()

    def get_plans_by_status(self, status: str, limit: int = 100) -> list[models.PlanMaster]:
        """
        Get plans by status using master architecture.
        
        Args:
            status: Status to filter by
            limit: Maximum number of plans to return
            
        Returns:
            List of PlanMaster instances
        """
        return self.db.query(models.PlanMaster).filter(
            models.PlanMaster.status == status
        ).limit(limit).all()