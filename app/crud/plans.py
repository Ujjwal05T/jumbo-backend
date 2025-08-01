from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from .base import CRUDBase
from .. import models, schemas


class CRUDPlan(CRUDBase[models.PlanMaster, schemas.PlanMasterCreate, schemas.PlanMasterUpdate]):
    def get_plans(
        self, db: Session, *, skip: int = 0, limit: int = 100, status: str = None
    ) -> List[models.PlanMaster]:
        """Get plans with filtering by status"""
        query = db.query(models.PlanMaster).options(
            joinedload(models.PlanMaster.created_by),
            joinedload(models.PlanMaster.plan_orders),
            joinedload(models.PlanMaster.plan_inventory)
        )
        
        if status:
            query = query.filter(models.PlanMaster.status == status)
            
        return query.order_by(models.PlanMaster.created_at.desc()).offset(skip).limit(limit).all()
    
    def get_plan(self, db: Session, plan_id: UUID) -> Optional[models.PlanMaster]:
        """Get plan by ID with all relationships"""
        return (
            db.query(models.PlanMaster)
            .options(
                joinedload(models.PlanMaster.created_by),
                joinedload(models.PlanMaster.plan_orders).joinedload(models.PlanOrderLink.order),
                joinedload(models.PlanMaster.plan_inventory).joinedload(models.PlanInventoryLink.inventory)
            )
            .filter(models.PlanMaster.id == plan_id)
            .first()
        )
    
    def create_plan(self, db: Session, *, plan: schemas.PlanMasterCreate) -> models.PlanMaster:
        """Create new cutting plan"""
        db_plan = models.PlanMaster(
            name=plan.name,
            cut_pattern=plan.cut_pattern,
            expected_waste_percentage=plan.expected_waste_percentage,
            created_by_id=plan.created_by_id
        )
        db.add(db_plan)
        db.commit()
        db.refresh(db_plan)
        return db_plan
    
    def update_plan(
        self, db: Session, *, plan_id: UUID, plan_update: schemas.PlanMasterUpdate
    ) -> Optional[models.PlanMaster]:
        """Update plan"""
        db_plan = self.get_plan(db, plan_id)
        if db_plan:
            update_data = plan_update.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(db_plan, field, value)
            db.commit()
            db.refresh(db_plan)
        return db_plan
    
    def update_plan_status(
        self, db: Session, *, plan_id: UUID, new_status: str
    ) -> Optional[models.PlanMaster]:
        """Update plan status"""
        db_plan = self.get_plan(db, plan_id)
        if db_plan:
            db_plan.status = new_status
            if new_status == "in_progress":
                db_plan.executed_at = datetime.utcnow()
            elif new_status == "completed":
                db_plan.completed_at = datetime.utcnow()
            db.commit()
            db.refresh(db_plan)
        return db_plan
    
    def execute_plan(self, db: Session, *, plan_id: UUID) -> Optional[models.PlanMaster]:
        """Execute plan - change status to in_progress"""
        return self.update_plan_status(db, plan_id=plan_id, new_status="in_progress")
    
    def complete_plan(self, db: Session, *, plan_id: UUID) -> Optional[models.PlanMaster]:
        """Complete plan - change status to completed"""
        return self.update_plan_status(db, plan_id=plan_id, new_status="completed")
    
    def start_production_for_plan(
        self, db: Session, *, plan_id: UUID, request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Start production for a plan - NEW FLOW with comprehensive status updates"""
        db_plan = self.get_plan(db, plan_id)
        if not db_plan:
            raise ValueError("Plan not found")
        
        # Update plan status
        db_plan.status = "in_progress"
        db_plan.executed_at = datetime.utcnow()
        
        # Track updated entities
        updated_orders = []
        updated_order_items = []
        updated_pending_orders = []
        
        # Update related order statuses to "in_process"
        for plan_order in db_plan.plan_orders:
            order = plan_order.order
            if order and order.status == "created":
                order.status = "in_process"
                order.started_production_at = datetime.utcnow()
                updated_orders.append(str(order.id))
                
                # Update order items status
                for item in order.order_items:
                    if item.item_status == "created":
                        item.item_status = "in_process"
                        item.started_production_at = datetime.utcnow()
                        updated_order_items.append(str(item.id))
        
        # TODO: Implement proper pending order resolution tracking
        # Only mark pending orders as "included_in_plan" if they were actually 
        # consumed by optimization to create cut rolls, not just because their
        # parent order is in the plan. Items still pending due to high waste
        # should remain with status "pending".
        
        # Create inventory records for cut rolls with status "cutting"
        selected_cut_rolls = request_data.get("selected_cut_rolls", [])
        created_inventory = []
        
        for cut_roll in selected_cut_rolls:
            # Create inventory record
            inventory_item = models.InventoryMaster(
                paper_id=cut_roll.get("paper_id"),
                width_inches=cut_roll.get("width_inches", 0),
                weight_kg=0,  # Will be updated via QR scan
                roll_type="cut",
                status="cutting",
                qr_code=cut_roll.get("qr_code"),
                created_by_id=request_data.get("created_by_id")
            )
            db.add(inventory_item)
            db.flush()  # Get inventory_item.id
            
            # Create plan-inventory link to associate this inventory item with the plan
            plan_inventory_link = models.PlanInventoryLink(
                plan_id=plan_id,
                inventory_id=inventory_item.id,
                quantity_used=1.0  # One roll used
            )
            db.add(plan_inventory_link)
            
            created_inventory.append(inventory_item)
        
        db.commit()
        db.refresh(db_plan)
        
        return {
            "plan_id": str(db_plan.id),
            "status": db_plan.status,
            "executed_at": db_plan.executed_at.isoformat() if db_plan.executed_at else None,
            "summary": {
                "orders_updated": len(updated_orders),
                "order_items_updated": len(updated_order_items),
                "pending_orders_updated": len(updated_pending_orders),
                "inventory_created": len(created_inventory)
            },
            "details": {
                "updated_orders": updated_orders,
                "updated_order_items": updated_order_items,
                "updated_pending_orders": updated_pending_orders,
                "created_inventory": [str(inv.id) for inv in created_inventory]
            },
            "message": f"Production started successfully - Updated {len(updated_orders)} orders, {len(updated_order_items)} order items, and {len(updated_pending_orders)} pending orders"
        }


plan = CRUDPlan(models.PlanMaster)