from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
import json
import logging

from .. import models
from .plan_deletion_logs import plan_deletion_logs

logger = logging.getLogger(__name__)

class CRUDPlanSnapshot:
    def create_snapshot(self, db: Session, *, plan_id: UUID, user_id: UUID) -> models.PlanSnapshot:
        """Create a snapshot of current database state before plan execution"""

        try:
            logger.info(f"📸 Starting snapshot creation for plan {plan_id} by user {user_id}")

            # Gather current state data
            snapshot_data = self._capture_current_state(db, plan_id)
            logger.info(f"📊 Captured snapshot data: {len(str(snapshot_data))} characters")

            # Create snapshot record
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            snapshot = models.PlanSnapshot(
                plan_id=plan_id,
                snapshot_data=snapshot_data,
                expires_at=expires_at,
                created_by_id=user_id
            )

            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)

            logger.info(f"✅ Successfully created snapshot for plan {plan_id}")
            logger.info(f"   - Snapshot ID: {snapshot.id}")
            logger.info(f"   - Plan ID: {snapshot.plan_id}")
            logger.info(f"   - Created at: {snapshot.created_at}")
            logger.info(f"   - Expires at: {snapshot.expires_at}")
            logger.info(f"   - Used: {snapshot.is_used}")

            return snapshot

        except Exception as e:
            db.rollback()
            logger.error(f"❌ Failed to create snapshot for plan {plan_id}: {e}")
            logger.error(f"   - Exception type: {type(e).__name__}")
            logger.error(f"   - Exception message: {str(e)}")
            import traceback
            logger.error(f"   - Traceback: {traceback.format_exc()}")
            raise

    def _capture_current_state(self, db: Session, plan_id: UUID) -> Dict[str, Any]:
        """Capture the current database state that might be affected by plan execution"""

        # Get plan details to understand what it will affect
        plan = db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_id).first()
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")

        # Get orders linked to this plan
        plan_order_links = db.query(models.PlanOrderLink).filter(
            models.PlanOrderLink.plan_id == plan_id
        ).all()

        plan_order_ids = [link.order_id for link in plan_order_links]

        snapshot_data = {
            "plan_id": str(plan_id),
            "snapshot_time": datetime.utcnow().isoformat(),
            "plan_details": {
                "id": str(plan.id),
                "name": plan.name,
                "status": plan.status,
                "created_at": plan.created_at.isoformat()
            },
            "affected_orders": [],
            "affected_order_items": [],
            "affected_pending_orders": [],
            "table_counts": {
                "orders": db.query(models.OrderMaster).count(),
                "order_items": db.query(models.OrderItem).count(),
                "inventory_master": db.query(models.InventoryMaster).count(),
                "pending_order_items": db.query(models.PendingOrderItem).count(),
                "wastage_inventory": db.query(models.WastageInventory).count()
            }
        }

        # Capture current state of orders that will be affected
        for link in plan_order_links:
            order = link.order
            if order:
                order_data = {
                    "id": str(order.id),
                    "frontend_id": order.frontend_id,
                    "status": order.status,
                    "created_at": order.created_at.isoformat(),
                    "started_production_at": order.started_production_at.isoformat() if order.started_production_at else None,
                    "moved_to_warehouse_at": order.moved_to_warehouse_at.isoformat() if order.moved_to_warehouse_at else None,
                    "dispatched_at": order.dispatched_at.isoformat() if order.dispatched_at else None
                }
                snapshot_data["affected_orders"].append(order_data)

                # Capture order items for these orders
                for item in order.order_items:
                    item_data = {
                        "id": str(item.id),
                        "frontend_id": item.frontend_id,
                        "order_id": str(item.order_id),
                        "width_inches": float(item.width_inches),
                        "quantity_rolls": item.quantity_rolls,
                        "quantity_fulfilled": item.quantity_fulfilled,
                        "quantity_in_pending": item.quantity_in_pending,
                        "item_status": item.item_status,
                        "created_at": item.created_at.isoformat()
                    }
                    snapshot_data["affected_order_items"].append(item_data)

        # Capture ALL pending orders that could potentially be fulfilled during plan execution
        # Solution 4: Complete Snapshot - Capture all pending orders, not just from plan's orders
        captured_pending_ids = set()

        # Get ALL pending orders that could be affected during plan execution
        all_pending_orders = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem._status == "pending"
        ).all()

        logger.info(f"Capturing ALL pending orders for comprehensive snapshot: {len(all_pending_orders)} total pending orders found")

        # Solution 5: Pre-Snapshot Detection - Capture pending orders created during plan creation
        # Look for pending orders created in the last 15 minutes before snapshot (during plan creation)
        snapshot_time = datetime.fromisoformat(snapshot_data["snapshot_time"])
        plan_creation_pending = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.created_at >= (snapshot_time - timedelta(minutes=15))
        ).filter(
            models.PendingOrderItem.created_at <= snapshot_time
        ).all()

        logger.info(f"Capturing pending orders created during plan creation (last 15 min): {len(plan_creation_pending)} pending orders found")

        # Combine all pending orders
        all_pending_to_capture = list(all_pending_orders) + plan_creation_pending

        for pending in all_pending_to_capture:
            # Skip if we've already captured this pending order
            if pending.id in captured_pending_ids:
                continue

            captured_pending_ids.add(pending.id)

            pending_data = {
                "id": str(pending.id),
                "frontend_id": pending.frontend_id,
                "original_order_id": str(pending.original_order_id),
                "width_inches": float(pending.width_inches),
                "quantity_pending": pending.quantity_pending,
                "quantity_fulfilled": pending.quantity_fulfilled or 0,
                "status": pending._status,
                "reason": pending.reason,
                "created_at": pending.created_at.isoformat()
            }
            snapshot_data["affected_pending_orders"].append(pending_data)

        logger.info(f"Captured snapshot for plan {plan_id}: "
                   f"{len(snapshot_data['affected_orders'])} orders, "
                   f"{len(snapshot_data['affected_order_items'])} items, "
                   f"{len(snapshot_data['affected_pending_orders'])} pending orders")

        return snapshot_data

    def get_snapshot(self, db: Session, *, plan_id: UUID) -> Optional[models.PlanSnapshot]:
        """Get a valid (non-expired) snapshot for a plan"""

        logger.info(f"🔍 Searching for snapshot for plan {plan_id}")
        current_time = datetime.utcnow()
        logger.info(f"   - Current time: {current_time}")

        # First, check if any snapshots exist for this plan
        all_snapshots = db.query(models.PlanSnapshot).filter(
            models.PlanSnapshot.plan_id == plan_id
        ).all()

        logger.info(f"   - Total snapshots found for plan: {len(all_snapshots)}")

        for snap in all_snapshots:
            logger.info(f"   - Snapshot {snap.id}:")
            logger.info(f"     * Created: {snap.created_at}")
            logger.info(f"     * Expires: {snap.expires_at}")
            logger.info(f"     * Used: {snap.is_used}")
            logger.info(f"     * Expired: {snap.expires_at <= current_time}")

        # Now search for valid snapshots
        snapshot = db.query(models.PlanSnapshot).filter(
            and_(
                models.PlanSnapshot.plan_id == plan_id,
                models.PlanSnapshot.expires_at > current_time,
                models.PlanSnapshot.is_used == False
            )
        ).first()

        if snapshot:
            logger.info(f"✅ Found valid snapshot for plan {plan_id}")
            logger.info(f"   - Snapshot ID: {snapshot.id}")
            logger.info(f"   - Expires at: {snapshot.expires_at}")
            logger.info(f"   - Time remaining: {(snapshot.expires_at - current_time).total_seconds() / 60:.1f} minutes")
        else:
            logger.warning(f"❌ No valid snapshot found for plan {plan_id}")
            if all_snapshots:
                logger.warning(f"   - {len(all_snapshots)} snapshots exist but none are valid")
                logger.warning(f"   - Possible reasons: expired, already used, or database filtering issue")

        return snapshot

    def validate_rollback_safety(self, db: Session, *, plan_id: UUID) -> Dict[str, Any]:
        """Check if it's safe to rollback a plan"""

        snapshot = self.get_snapshot(db, plan_id=plan_id)
        if not snapshot:
            return {
                "safe": False,
                "reason": "No valid snapshot found",
                "suggestion": "Snapshot may have expired (older than 10 minutes) or already used"
            }

        # Check time window
        if datetime.utcnow() > snapshot.expires_at:
            return {
                "safe": False,
                "reason": "10-minute rollback window has expired",
                "expired_at": snapshot.expires_at.isoformat()
            }

        # Check if other data changed since snapshot (use only execution window approach)
        snapshot_data = snapshot.snapshot_data

        # Find all inventory items created during plan execution window
        # This catches any inventory items created by the plan regardless of relationships
        execution_window_ids = []
        if snapshot_data and "snapshot_time" in snapshot_data:
            snapshot_time = datetime.fromisoformat(snapshot_data["snapshot_time"])

            # Find all inventory created between snapshot time and now (during plan execution)
            execution_window_items = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.created_at >= snapshot_time
            ).filter(
                models.InventoryMaster.created_at <= datetime.utcnow()
            ).all()

            execution_window_ids = [item.id for item in execution_window_items]

            logger.info(f"🔍 Safety check for plan {plan_id}:")
            logger.info(f"   - Execution window items: {len(execution_window_ids)}")

            # Debug: Show some details about the execution window items
            for item in execution_window_items[:3]:  # Show first 3 for debugging
                logger.info(f"   - Execution window item: {item.frontend_id} (ID: {item.id})")
                logger.info(f"     * Created at: {item.created_at}")
                logger.info(f"     * Status: {item.status}")

        # Find wastage items created during execution window (time-based approach)
        execution_wastage_ids = []
        if snapshot_data and "snapshot_time" in snapshot_data:
            snapshot_time = datetime.fromisoformat(snapshot_data["snapshot_time"])

            # Find all wastage items created during plan execution (only those created by this plan)
            execution_wastage_items = db.query(models.WastageInventory).filter(
                and_(
                    models.WastageInventory.created_at >= snapshot_time,
                    models.WastageInventory.source_plan_id == plan_id  # Only wastage created by this plan
                )
            ).all()

            execution_wastage_ids = [item.id for item in execution_wastage_items]
            logger.info(f"   - Wastage items created by plan during execution window: {len(execution_wastage_ids)}")

        # Find pending order items created during execution window (only those created by plan)
        execution_pending_ids = []
        if snapshot_data and "snapshot_time" in snapshot_data:
            snapshot_time = datetime.fromisoformat(snapshot_data["snapshot_time"])

            # Find all pending order items created during plan execution
            execution_pending_items = db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.created_at >= snapshot_time
            ).filter(
                models.PendingOrderItem.created_at <= datetime.utcnow()
            ).all()

            execution_pending_ids = [item.id for item in execution_pending_items]
            logger.info(f"   - Pending order items created by plan during execution window: {len(execution_pending_ids)}")

        # Find orders created during execution window (exclude from safety check)
        execution_order_ids = []
        if snapshot_data and "snapshot_time" in snapshot_data:
            snapshot_time = datetime.fromisoformat(snapshot_data["snapshot_time"])

            # Find all orders created during plan execution
            execution_orders = db.query(models.OrderMaster).filter(
                models.OrderMaster.created_at >= snapshot_time
            ).filter(
                models.OrderMaster.created_at <= datetime.utcnow()
            ).all()

            execution_order_ids = [order.id for order in execution_orders]
            logger.info(f"   - Orders created during execution window: {len(execution_order_ids)}")

        # Find order items created during execution window (exclude from safety check)
        execution_order_item_ids = []
        if snapshot_data and "snapshot_time" in snapshot_data:
            snapshot_time = datetime.fromisoformat(snapshot_data["snapshot_time"])

            # Find all order items created during plan execution
            execution_order_items = db.query(models.OrderItem).filter(
                models.OrderItem.created_at >= snapshot_time
            ).filter(
                models.OrderItem.created_at <= datetime.utcnow()
            ).all()

            execution_order_item_ids = [item.id for item in execution_order_items]
            logger.info(f"   - Order items created during execution window: {len(execution_order_item_ids)}")

        # Use execution window items as the plan inventory IDs
        all_plan_inventory_ids = execution_window_ids

        # Use execution window wastage as plan wastage items
        plan_wastage_ids = execution_wastage_ids

        # Count only items NOT created by this plan (FIXED - exclude execution window items)
        current_counts_excluding_plan = {
            "orders": db.query(models.OrderMaster).filter(
                models.OrderMaster.id.notin_(execution_order_ids)
            ).count(),
            "order_items": db.query(models.OrderItem).filter(
                models.OrderItem.id.notin_(execution_order_item_ids)
            ).count(),
            "inventory_master": db.query(models.InventoryMaster).filter(
                models.InventoryMaster.id.notin_(all_plan_inventory_ids)
            ).count(),
            "pending_order_items": db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.id.notin_(execution_pending_ids)
            ).count(),
            "wastage_inventory": db.query(models.WastageInventory).filter(
                models.WastageInventory.id.notin_(plan_wastage_ids)
            ).count()
        }

        snapshot_counts = snapshot_data["table_counts"]

        changes_detected = []
        for table, current_count in current_counts_excluding_plan.items():
            snapshot_count = snapshot_counts.get(table, 0)
            if current_count != snapshot_count:
                changes_detected.append(f"{table}: {snapshot_count} → {current_count}")
                logger.warning(f"   - {table} changed: {snapshot_count} → {current_count}")

        if changes_detected:
            return {
                "safe": False,
                "reason": "Database has been modified by other operations (excluding this plan's items)",
                "changes_detected": changes_detected,
                "suggestion": "These changes may be lost if rollback proceeds",
                "plan_items_excluded": {
                    "execution_window_count": len(execution_window_ids),
                    "execution_pending_count": len(execution_pending_ids),
                    "execution_wastage_count": len(execution_wastage_ids),
                    "execution_orders_count": len(execution_order_ids),
                    "execution_order_items_count": len(execution_order_item_ids),
                    "total_inventory_count": len(all_plan_inventory_ids),
                    "wastage_count": len(plan_wastage_ids)
                }
            }

        logger.info(f"✅ Safety check passed: No external changes detected")

        # Check for concurrent plan executions
        plan = db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_id).first()
        concurrent_plans = db.query(models.PlanMaster).filter(
            and_(
                models.PlanMaster.created_by_id == plan.created_by_id,
                models.PlanMaster.created_at >= snapshot.created_at,
                models.PlanMaster.id != plan_id,
                models.PlanMaster.status.in_(["in_progress", "completed"])
            )
        ).count()

        if concurrent_plans > 0:
            return {
                "safe": False,
                "reason": f"{concurrent_plans} other plans were executed during the same period",
                "suggestion": "Rollback may affect other plan executions"
            }

        return {
            "safe": True,
            "reason": "Rollback is safe to proceed",
            "snapshot_age_minutes": (datetime.utcnow() - snapshot.created_at).total_seconds() / 60
        }

    def execute_rollback(self, db: Session, *, plan_id: UUID, user_id: UUID) -> Dict[str, Any]:
        """Execute the actual rollback using snapshot data"""

        try:
            # Validate safety first
            safety_check = self.validate_rollback_safety(db, plan_id=plan_id)
            if not safety_check["safe"]:
                raise ValueError(f"Rollback not safe: {safety_check['reason']}")

            # Get snapshot
            snapshot = self.get_snapshot(db, plan_id=plan_id)
            if not snapshot:
                raise ValueError("No valid snapshot found for rollback")

            plan = db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_id).first()
            if not plan:
                raise ValueError("Plan not found")

            if plan.status != "in_progress":
                raise ValueError(f"Cannot rollback plan with status '{plan.status}'. Only 'in_progress' plans can be rolled back.")

            snapshot_data = snapshot.snapshot_data

            # Track rollback operations
            rollback_stats = {
                "inventory_deleted": 0,
                "wastage_deleted": 0,
                "wastage_restored": 0,
                "orders_restored": 0,
                "order_items_restored": 0,
                "pending_orders_deleted": 0,
                "pending_orders_restored": 0,
                "links_deleted": 0
            }

            # 1. Delete inventory created by this plan (via PlanInventoryLink)
            plan_inventory_links = db.query(models.PlanInventoryLink).filter(
                models.PlanInventoryLink.plan_id == plan_id
            ).all()

            for link in plan_inventory_links:
                if link.inventory:
                    db.delete(link.inventory)
                    rollback_stats["inventory_deleted"] += 1
                db.delete(link)
                rollback_stats["links_deleted"] += 1

            # 2. Handle wastage inventory - Find ALL wastage affected by plan
            if snapshot_data and "snapshot_time" in snapshot_data:
                snapshot_time = datetime.fromisoformat(snapshot_data["snapshot_time"])

                # Get current total wastage count for debugging
                current_wastage_count = db.query(models.WastageInventory).count()
                logger.info(f"Current wastage count before rollback: {current_wastage_count}")

                # Step 1: Find ALL wastage created during execution window (created by plan)
                created_wastage = db.query(models.WastageInventory).filter(
                    models.WastageInventory.created_at >= snapshot_time
                ).filter(
                    models.WastageInventory.created_at <= datetime.utcnow()
                ).all()

                logger.info(f"Found {len(created_wastage)} wastage records created during execution window")

                # Step 2: Find ALL wastage that was modified during execution window (possibly used by plan)
                # Look for wastage with status changes OR updates during execution window
                modified_wastage = db.query(models.WastageInventory).filter(
                    models.WastageInventory.updated_at >= snapshot_time
                ).filter(
                    models.WastageInventory.created_at < snapshot_time  # Existed before plan
                ).filter(
                    models.WastageInventory.status != "available"  # Status changed from available
                ).all()

                logger.info(f"Found {len(modified_wastage)} wastage records modified during execution window (existed before, status changed)")

                # Step 2a: Find wastage that was used to create inventory during plan execution
                # Look for inventory items created during execution that have wastage sources
                inventory_from_wastage = db.query(models.InventoryMaster).filter(
                    models.InventoryMaster.created_at >= snapshot_time
                ).filter(
                    models.InventoryMaster.wastage_source_order_id.isnot(None)  # Created from wastage order
                ).all()

                logger.info(f"Found {len(inventory_from_wastage)} inventory items created from wastage orders during execution window")

                # Step 2b: Find the actual wastage orders that were used as source
                wastage_orders_used = set()
                if inventory_from_wastage:
                    wastage_order_ids = [inv.wastage_source_order_id for inv in inventory_from_wastage]
                    wastage_orders_used.update(wastage_order_ids)

                logger.info(f"Found {len(wastage_orders_used)} unique wastage orders used as source for inventory")

                # Step 2c: Find wastage inventory items that correspond to those wastage orders
                wastage_from_used_orders = []
                if wastage_orders_used:
                    wastage_from_used_orders = db.query(models.WastageInventory).filter(
                        models.WastageInventory.id.in_(wastage_orders_used)
                    ).all()

                logger.info(f"Found {len(wastage_from_used_orders)} wastage inventory items that were used to create inventory")

                # Step 2d: Find wastage rolls created during execution (inventory items marked as wastage)
                wastage_rolls_created = db.query(models.InventoryMaster).filter(
                    models.InventoryMaster.created_at >= snapshot_time
                ).filter(
                    models.InventoryMaster.is_wastage_roll == True  # These are wastage inventory items
                ).all()

                logger.info(f"Found {len(wastage_rolls_created)} wastage rolls (inventory items) created during execution window")

                # Step 3: Look for wastage linked to the plan (additional catch)
                plan_linked_wastage = db.query(models.WastageInventory).filter(
                    models.WastageInventory.source_plan_id == plan_id
                ).all()

                logger.info(f"Found {len(plan_linked_wastage)} wastage records with explicit source_plan_id")

                # Step 4: Combine all wastage that needs processing
                wastage_to_delete = []
                wastage_to_restore = []
                processed_wastage_ids = set()  # Track to avoid duplicates

                # Process created wastage (always delete)
                for wastage in created_wastage:
                    if wastage.id not in processed_wastage_ids:
                        wastage_to_delete.append(wastage)
                        processed_wastage_ids.add(wastage.id)
                        logger.info(f"Will DELETE wastage {wastage.frontend_id} (created during execution)")

                # Process modified wastage (restore status)
                for wastage in modified_wastage:
                    if wastage.id not in processed_wastage_ids:
                        wastage_to_restore.append(wastage)
                        processed_wastage_ids.add(wastage.id)
                        logger.info(f"Will RESTORE wastage {wastage.frontend_id} (status changed from available to {wastage.status})")

                # Process wastage that was used to create inventory (restore status)
                for wastage in wastage_from_used_orders:
                    if wastage.id not in processed_wastage_ids:
                        wastage_to_restore.append(wastage)
                        processed_wastage_ids.add(wastage.id)
                        logger.info(f"Will RESTORE wastage {wastage.frontend_id} (used as source for inventory creation)")

                # Also process plan-linked wastage that wasn't caught above
                for wastage in plan_linked_wastage:
                    if wastage.id not in processed_wastage_ids:
                        if wastage.created_at >= snapshot_time:
                            wastage_to_delete.append(wastage)
                            processed_wastage_ids.add(wastage.id)
                            logger.info(f"Will DELETE plan-linked wastage {wastage.frontend_id} (created during execution)")
                        else:
                            wastage_to_restore.append(wastage)
                            processed_wastage_ids.add(wastage.id)
                            logger.info(f"Will RESTORE plan-linked wastage {wastage.frontend_id} (linked to plan)")

                # Also need to handle wastage rolls (inventory items marked as wastage)
                for wastage_roll in wastage_rolls_created:
                    logger.info(f"Will DELETE wastage roll {wastage_roll.frontend_id} (inventory item marked as wastage)")
                    # These are inventory items, not wastage inventory, so handle separately
                    db.delete(wastage_roll)
                    rollback_stats["wastage_deleted"] += 1

                logger.info(f"🗑️ Deleting {len(wastage_to_delete)} wastage records created by plan")
                logger.info(f"🔄 Restoring {len(wastage_to_restore)} wastage records used by plan")

                # Delete wastage created by plan
                for wastage in wastage_to_delete:
                    db.delete(wastage)
                    rollback_stats["wastage_deleted"] += 1

                # Restore wastage used by plan (set status back to available)
                for wastage in wastage_to_restore:
                    wastage.status = "available"
                    wastage.source_plan_id = None  # Remove plan association if it exists
                    rollback_stats["wastage_restored"] += 1
                    logger.info(f"Restored wastage {wastage.frontend_id} status to 'available'")

            else:
                # Fallback: Handle wastage with explicit source_plan_id
                wastage_from_plan = db.query(models.WastageInventory).filter(
                    models.WastageInventory.source_plan_id == plan_id
                ).all()

                for wastage in wastage_from_plan:
                    # Check if this wastage was created by the plan or just used by it
                    # If it was created recently, assume it was created by the plan
                    if wastage.created_at > (datetime.utcnow() - timedelta(hours=1)):
                        db.delete(wastage)  # Created by plan - delete
                        rollback_stats["wastage_deleted"] += 1
                    else:
                        # Existed before - just restore status
                        wastage.status = "available"
                        wastage.source_plan_id = None
                        rollback_stats["wastage_restored"] += 1

            # 3. Handle pending order items - Use comprehensive approach
            if snapshot_data and "snapshot_time" in snapshot_data:
                snapshot_time = datetime.fromisoformat(snapshot_data["snapshot_time"])

                # Get current total pending order count for debugging
                current_pending_count = db.query(models.PendingOrderItem).count()
                logger.info(f"Current pending order count before rollback: {current_pending_count}")

                # Step 1: Find ALL pending orders created during execution window
                execution_pending_orders = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.created_at >= snapshot_time
                ).filter(
                    models.PendingOrderItem.created_at <= datetime.utcnow()
                ).all()

                logger.info(f"Found {len(execution_pending_orders)} pending orders created during execution window")

                # Step 2: Find ALL pending orders modified during execution window (possibly used by plan)
                # Use available fields to detect changes: resolved_at, quantity_fulfilled, status
                modified_pending_orders = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.created_at < snapshot_time  # Existed before plan
                ).filter(
                    or_(
                        # Quantity was fulfilled (we can't easily detect when it changed, but we can check current state)
                        models.PendingOrderItem.quantity_fulfilled > 0,
                        # Status changed from pending
                        models.PendingOrderItem._status != "pending",
                        # Was resolved during execution (has resolved_at)
                        models.PendingOrderItem.resolved_at.isnot(None)
                    )
                ).all()

                logger.info(f"Found {len(modified_pending_orders)} pending orders that were likely modified during execution window (existed before, have changes)")

                # Step 2a: Also find pending orders that were resolved during execution window
                resolved_pending_orders = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.resolved_at >= snapshot_time
                ).filter(
                    models.PendingOrderItem.resolved_at <= datetime.utcnow()
                ).filter(
                    models.PendingOrderItem.created_at < snapshot_time  # Existed before plan
                ).all()

                logger.info(f"Found {len(resolved_pending_orders)} pending orders resolved during execution window")

                # Step 3: Debug what's in the snapshot data first
                logger.info(f"🔍 DEBUG: Analyzing snapshot data for pending orders")
                logger.info(f"   - Total pending orders in snapshot: {len(snapshot_data['affected_pending_orders'])}")

                # Show detailed snapshot data
                for i, pending_data in enumerate(snapshot_data["affected_pending_orders"]):
                    logger.info(f"   - Snapshot[{i}]: ID={pending_data['id']}, Frontend={pending_data.get('frontend_id', 'N/A')}")
                    logger.info(f"     * quantity_pending: {pending_data['quantity_pending']}")
                    logger.info(f"     * quantity_fulfilled: {pending_data['quantity_fulfilled']}")
                    logger.info(f"     * status: {pending_data['status']}")
                    logger.info(f"     * created_at: {pending_data['created_at']}")

                # Step 4: Identify plan creation pending orders vs normal pending orders
                # Plan creation pending orders were created in the 15 minutes before snapshot
                plan_creation_cutoff = snapshot_time - timedelta(minutes=15)
                plan_creation_pending_ids = set()
                normal_pending_ids = set()

                for pending_data in snapshot_data["affected_pending_orders"]:
                    pending_id = UUID(pending_data["id"])
                    created_at = datetime.fromisoformat(pending_data["created_at"])

                    if created_at >= plan_creation_cutoff:
                        # This pending order was created during plan creation - should be DELETED
                        plan_creation_pending_ids.add(pending_id)
                        logger.info(f"   🗑️ Marked for DELETION (plan creation): {pending_data.get('frontend_id', 'unknown')} (created: {created_at})")
                    else:
                        # This pending order existed before plan - should be RESTORED
                        normal_pending_ids.add(pending_id)
                        logger.info(f"   🔄 Marked for RESTORATION (existed before): {pending_data.get('frontend_id', 'unknown')} (created: {created_at})")

                logger.info(f"🔍 CLASSIFICATION: {len(plan_creation_pending_ids)} to delete (plan creation), {len(normal_pending_ids)} to restore (existed before)")

                # Step 5: Restore normal pending orders (existed before plan)
                restored_pending_ids = set()  # Use set to prevent duplicates
                processed_ids = set()  # Track which IDs we've already processed
                found_in_db_count = 0
                not_found_in_db_count = 0

                for pending_data in snapshot_data["affected_pending_orders"]:
                    pending_id = UUID(pending_data["id"])

                    # Only restore if it's a normal pending order (not plan creation)
                    if pending_id not in normal_pending_ids:
                        continue

                    # Skip if we've already processed this pending order
                    if pending_id in processed_ids:
                        logger.info(f"Skipping duplicate pending order {pending_data.get('frontend_id', 'unknown')} in snapshot data")
                        continue

                    processed_ids.add(pending_id)

                    pending = db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.id == pending_id
                    ).first()
                    if pending:
                        found_in_db_count += 1
                        logger.info(f"Restoring pending order {pending.frontend_id} from snapshot")
                        logger.info(f"  Before: quantity_pending={pending.quantity_pending}, quantity_fulfilled={pending.quantity_fulfilled}, status={pending._status}, resolved_at={pending.resolved_at}")

                        # Restore original state from snapshot
                        old_quantity_pending = pending.quantity_pending
                        old_quantity_fulfilled = pending.quantity_fulfilled
                        old_status = pending._status
                        old_resolved_at = pending.resolved_at

                        pending.quantity_pending = pending_data["quantity_pending"]
                        pending.quantity_fulfilled = pending_data["quantity_fulfilled"]
                        pending._status = pending_data["status"]
                        pending.resolved_at = None  # Clear resolution
                        restored_pending_ids.add(pending.id)
                        rollback_stats["pending_orders_restored"] += 1

                        logger.info(f"  After: quantity_pending={pending.quantity_pending} (was {old_quantity_pending})")
                        logger.info(f"         quantity_fulfilled={pending.quantity_fulfilled} (was {old_quantity_fulfilled})")
                        logger.info(f"         status={pending._status} (was {old_status})")
                        logger.info(f"         resolved_at={pending.resolved_at} (was {old_resolved_at})")
                    else:
                        not_found_in_db_count += 1
                        logger.error(f"❌ ERROR: Pending order {pending_id} ({pending_data.get('frontend_id', 'unknown')}) found in snapshot but NOT in database!")
                        logger.error(f"   Snapshot data: {pending_data}")

                logger.info(f"🔍 SUMMARY: Found {found_in_db_count} pending orders in DB, {not_found_in_db_count} not found")

                # Convert set to list for the next step
                restored_pending_ids = list(restored_pending_ids)

                # Step 4: Delete execution window pending orders (excluding restored ones)
                deleted_pending_count = 0

                logger.info(f"🔍 DEBUG: Analyzing execution window pending orders for deletion")
                logger.info(f"   - Total execution window pending orders: {len(execution_pending_orders)}")
                logger.info(f"   - Pending orders to skip (restored): {len(restored_pending_ids)}")

                # Show details of execution window pending orders
                for i, pending in enumerate(execution_pending_orders):
                    skip_deletion = pending.id in restored_pending_ids
                    logger.info(f"   - Execution[{i}]: {pending.frontend_id}, ID={pending.id}")
                    logger.info(f"     * Created: {pending.created_at}")
                    logger.info(f"     * quantity_pending: {pending.quantity_pending}, quantity_fulfilled: {pending.quantity_fulfilled}")
                    logger.info(f"     * Status: {pending._status}, Resolved: {pending.resolved_at}")
                    logger.info(f"     * Will delete: {not skip_deletion}")

                # First, delete plan creation pending orders (created during plan setup)
                plan_creation_deleted = 0
                for pending_id in plan_creation_pending_ids:
                    pending = db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.id == pending_id
                    ).first()
                    if pending:
                        logger.info(f"🗑️ Deleting plan creation pending order {pending.frontend_id} (ID: {pending.id})")
                        db.delete(pending)
                        plan_creation_deleted += 1
                    else:
                        logger.warning(f"Plan creation pending order {pending_id} not found in database")

                deleted_pending_count += plan_creation_deleted

                # Then, delete execution window pending orders (excluding restored ones)
                for pending in execution_pending_orders:
                    if pending.id not in restored_pending_ids and pending.id not in plan_creation_pending_ids:
                        logger.info(f"🗑️ Deleting execution window pending order {pending.frontend_id} (ID: {pending.id})")
                        db.delete(pending)
                        deleted_pending_count += 1
                    else:
                        skip_reason = "restored" if pending.id in restored_pending_ids else "plan creation"
                        logger.info(f"✅ Skipping deletion of pending order {pending.frontend_id} ({skip_reason})")

                rollback_stats["pending_orders_deleted"] = deleted_pending_count

                logger.info(f"🗑️ TOTAL PENDING ORDERS DELETED: {deleted_pending_count} (plan creation: {plan_creation_deleted}, execution: {deleted_pending_count - plan_creation_deleted})")

                logger.info(f"🔄 Restored {len(restored_pending_ids)} pending orders from snapshot")
                logger.info(f"🗑️ Deleted {deleted_pending_count} pending orders created during execution")
                logger.info(f"📊 Total pending orders found in execution window: {len(execution_pending_orders)}")
                logger.info(f"📊 Total pending orders in snapshot: {len(snapshot_data['affected_pending_orders'])}")
                logger.info(f"📊 Total pending orders modified during execution: {len(modified_pending_orders)}")

            # 4. Restore original states from snapshot
            # Restore orders
            for order_data in snapshot_data["affected_orders"]:
                order = db.query(models.OrderMaster).filter(
                    models.OrderMaster.id == UUID(order_data["id"])
                ).first()
                if order:
                    order.status = order_data["status"]
                    order.started_production_at = (
                        datetime.fromisoformat(order_data["started_production_at"])
                        if order_data["started_production_at"] else None
                    )
                    order.moved_to_warehouse_at = (
                        datetime.fromisoformat(order_data["moved_to_warehouse_at"])
                        if order_data["moved_to_warehouse_at"] else None
                    )
                    order.dispatched_at = (
                        datetime.fromisoformat(order_data["dispatched_at"])
                        if order_data["dispatched_at"] else None
                    )
                    rollback_stats["orders_restored"] += 1

            # Restore order items
            for item_data in snapshot_data["affected_order_items"]:
                item = db.query(models.OrderItem).filter(
                    models.OrderItem.id == UUID(item_data["id"])
                ).first()
                if item:
                    item.quantity_fulfilled = item_data["quantity_fulfilled"]
                    item.quantity_in_pending = item_data["quantity_in_pending"]
                    item.item_status = item_data["item_status"]
                    rollback_stats["order_items_restored"] += 1

            # Skip pending order restoration - using time-based deletion approach instead
            # All pending orders created during execution window are already deleted above

            # 5. Update plan status
            plan.status = "planned"
            plan.executed_at = None

            # 6. DELETE THE PLAN - Since rollback means the plan never existed
            logger.info(f"🗑️ Deleting rolled back plan {plan_id} ({plan.frontend_id})")
            plan_frontend_id = plan.frontend_id

            # Delete plan order links
            plan_order_links = db.query(models.PlanOrderLink).filter(
                models.PlanOrderLink.plan_id == plan_id
            ).all()
            for link in plan_order_links:
                db.delete(link)
            rollback_stats["links_deleted"] += len(plan_order_links)

            # Delete plan inventory links
            plan_inventory_links = db.query(models.PlanInventoryLink).filter(
                models.PlanInventoryLink.plan_id == plan_id
            ).all()
            for link in plan_inventory_links:
                db.delete(link)
            rollback_stats["links_deleted"] += len(plan_inventory_links)

            # Log the plan deletion for audit trail BEFORE deleting the plan
            try:
                deletion_log = plan_deletion_logs.create_deletion_log(
                    db=db,
                    plan_id=plan_id,
                    plan_frontend_id=plan_frontend_id,
                    plan_name=plan.name,
                    user_id=user_id,
                    deletion_reason="rollback",
                    rollback_stats=rollback_stats,
                    rollback_duration_seconds=(datetime.utcnow() - snapshot.created_at).total_seconds(),
                    success_status="success"
                )
                logger.info(f"📝 Created deletion log entry {deletion_log.id} for plan {plan_frontend_id}")
            except Exception as log_error:
                logger.error(f"⚠️ Failed to create deletion log: {log_error}")
                # Don't fail the rollback if logging fails

            # Finally delete the plan itself
            db.delete(plan)

            # 7. DELETE THE SNAPSHOT - Remove snapshot record to avoid foreign key issues
            logger.info(f"🗑️ Deleting snapshot {snapshot.id} for plan {plan_frontend_id}")
            db.delete(snapshot)

            db.commit()  # Commit all deletions together

            logger.info(f"Successfully rolled back plan {plan_id} and deleted it. Stats: {rollback_stats}")
            logger.info(f"🗑️ Plan {plan_frontend_id} and its snapshot have been completely removed from the system")

            return {
                "success": True,
                "message": f"Plan {plan_frontend_id} rolled back successfully and deleted",
                "rollback_stats": rollback_stats,
                "snapshot_deleted": True,
                "plan_deleted": True,
                "plan_deleted_at": datetime.utcnow().isoformat(),
                "note": "The plan and its snapshot have been completely removed from the system as if it never existed"
            }

        except Exception as e:
            db.rollback()
            logger.error(f"Rollback failed for plan {plan_id}: {e}")

            # Log failed rollback attempt for audit trail
            try:
                plan = db.query(models.PlanMaster).filter(models.PlanMaster.id == plan_id).first()
                if plan:
                    deletion_log = plan_deletion_logs.create_deletion_log(
                        db=db,
                        plan_id=plan_id,
                        plan_frontend_id=plan.frontend_id,
                        plan_name=plan.name,
                        user_id=user_id,
                        deletion_reason="rollback",
                        success_status="failed",
                        error_message=str(e)
                    )
                    logger.info(f"📝 Created failure deletion log entry {deletion_log.id} for plan {plan.frontend_id}")
            except Exception as log_error:
                logger.error(f"⚠️ Failed to create failure deletion log: {log_error}")

            raise

    def create_snapshot_from_predata(self, db: Session, *, plan_id: UUID, user_id: UUID, pre_execution_data: Dict[str, Any]) -> models.PlanSnapshot:
        """Create a snapshot using pre-captured state data.

        Used for hybrid plans where the plan_id is not known before execution.
        The caller captures order/pending-order states BEFORE calling create_hybrid_production,
        then passes that data here after getting the plan_id from the result.
        """
        try:
            logger.info(f"📸 Creating hybrid snapshot for plan {plan_id} from pre-execution data")

            expires_at = datetime.utcnow() + timedelta(minutes=10)
            snapshot = models.PlanSnapshot(
                plan_id=plan_id,
                snapshot_data=pre_execution_data,
                expires_at=expires_at,
                created_by_id=user_id
            )

            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)

            logger.info(f"✅ Created hybrid snapshot {snapshot.id} for plan {plan_id}, expires {snapshot.expires_at}")
            return snapshot

        except Exception as e:
            db.rollback()
            logger.error(f"❌ Failed to create hybrid snapshot for plan {plan_id}: {e}")
            raise

    def cleanup_expired_snapshots(self, db: Session) -> int:
        """Clean up expired snapshots (call this periodically)"""

        expired_snapshots = db.query(models.PlanSnapshot).filter(
            models.PlanSnapshot.expires_at <= datetime.utcnow()
        ).all()

        count = len(expired_snapshots)
        for snapshot in expired_snapshots:
            db.delete(snapshot)

        if count > 0:
            db.commit()
            logger.info(f"Cleaned up {count} expired snapshots")

        return count

# Create instance
snapshot = CRUDPlanSnapshot()