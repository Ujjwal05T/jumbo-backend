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
        import logging
        logger = logging.getLogger(__name__)
        
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
        
        # Process selected and unselected cut rolls - get data first
        selected_cut_rolls = request_data.get("selected_cut_rolls", [])
        all_available_cuts = request_data.get("all_available_cuts", [])  # All cuts that were available for selection
        
        # Update status of pending orders that are actually resolved by selected cut rolls
        # Only mark pending orders as "included_in_plan" if they were actually 
        # consumed by optimization to create cut rolls that are now being selected for production
        from ..services.workflow_manager import WorkflowManager
        try:
            # Create a temporary workflow instance to access the pending order update logic
            temp_workflow = WorkflowManager(db=db, user_id=request_data.get("created_by_id"))
            
            # For each selected cut roll, find corresponding pending orders that should be marked as resolved
            # This logic should match the cut roll specifications with pending order specifications
            resolved_pending_count = 0
            logger.info(f"🔍 PENDING RESOLUTION: Processing {len(selected_cut_rolls)} selected cut rolls for pending order resolution")
            for cut_roll in selected_cut_rolls:
                # Convert to Decimal to match database types exactly
                from decimal import Decimal
                width = Decimal(str(cut_roll.get("width_inches", 0)))
                gsm = int(cut_roll.get("gsm", 0))
                bf = Decimal(str(cut_roll.get("bf", 0)))
                shade = str(cut_roll.get("shade", "")).strip()
                order_id = cut_roll.get("order_id")
                
                logger.info(f"🔍 PENDING MATCH: Looking for pending orders matching cut roll: {width}\" {gsm}gsm {bf}bf {shade} (order: {order_id})")
                
                # Find matching pending orders that are resolved by this cut roll selection
                # Search by specifications even if order_id is None
                from uuid import UUID
                try:
                    # Build base query with specifications - use tolerance for float comparisons
                    logger.info(f"🔍 QUERY DEBUG: Searching for width={width} (type: {type(width)}), gsm={gsm} (type: {type(gsm)}), bf={bf} (type: {type(bf)}), shade='{shade}' (type: {type(shade)})")
                    
                    # Use exact Decimal comparison since we converted to Decimal
                    base_query = db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.width_inches == width,
                        models.PendingOrderItem.gsm == gsm,
                        models.PendingOrderItem.bf == bf,
                        models.PendingOrderItem.shade == shade,
                        models.PendingOrderItem._status == "pending"
                    )
                    
                    # PRIORITIZE SPECIFICATION MATCHING: Try specifications first, then order_id as secondary filter
                    matching_pending = base_query.all()
                    
                    # If we found matches by specs but want to prefer same order_id, filter further
                    if order_id and len(matching_pending) > 1:
                        try:
                            order_id_uuid = UUID(order_id) if isinstance(order_id, str) else order_id
                            order_specific_matches = [p for p in matching_pending if p.original_order_id == order_id_uuid]
                            if order_specific_matches:
                                matching_pending = order_specific_matches
                                logger.info(f"🔍 ORDER PRIORITY: Filtered to {len(matching_pending)} matches with same order_id")
                        except (ValueError, TypeError) as e:
                            logger.info(f"🔍 ORDER ID ISSUE: Using spec-only matching due to order_id error: {e}")
                            # Continue with spec-only matches
                    
                    # With Decimal conversion, exact matching should work now
                    
                    logger.info(f"🔍 PENDING FOUND: {len(matching_pending)} matching pending orders found")
                    
                    # CRITICAL DEBUG: If no matches, this is the root issue!
                    if len(matching_pending) == 0:
                        logger.error(f"🔍 ROOT ISSUE: No pending orders match cut roll {width}\" {gsm}gsm {bf}bf {shade}")
                        logger.error(f"🔍 CHECKING: Are there ANY pending orders in database?")
                        total_pending = db.query(models.PendingOrderItem).filter(
                            models.PendingOrderItem._status == "pending"
                        ).count()
                        logger.error(f"🔍 TOTAL PENDING ORDERS: {total_pending}")
                        
                        if total_pending > 0:
                            logger.error(f"🔍 DATA TYPE ISSUE: Cut roll types - width:{type(width)}, gsm:{type(gsm)}, bf:{type(bf)}")
                            sample_pending = db.query(models.PendingOrderItem).filter(
                                models.PendingOrderItem._status == "pending"
                            ).first()
                            if sample_pending:
                                logger.error(f"🔍 DB TYPES: width:{type(sample_pending.width_inches)}, gsm:{type(sample_pending.gsm)}, bf:{type(sample_pending.bf)}")
                                logger.error(f"🔍 DB VALUES: width:{sample_pending.width_inches}, gsm:{sample_pending.gsm}, bf:{sample_pending.bf}, shade:'{sample_pending.shade}'")
                    else:
                        logger.info(f"🔍 SUCCESS: Found matches, proceeding with status update")
                    
                    # Debug: If no matches found, let's see what pending orders actually exist
                    if len(matching_pending) == 0:
                        # Check if there are any pending orders with the same specs but different order_id
                        debug_pending = db.query(models.PendingOrderItem).filter(
                            models.PendingOrderItem._status == "pending"
                        ).all()
                        logger.info(f"🔍 DEBUG: Found {len(debug_pending)} total pending orders in database")
                        for debug_item in debug_pending:
                            logger.info(f"  - DB Pending {debug_item.frontend_id}: order_id={debug_item.original_order_id}, width={debug_item.width_inches} (type: {type(debug_item.width_inches)}), gsm={debug_item.gsm} (type: {type(debug_item.gsm)}), bf={debug_item.bf} (type: {type(debug_item.bf)}), shade='{debug_item.shade}' (type: {type(debug_item.shade)})")
                        
                        # Check with relaxed comparison
                        relaxed_pending = db.query(models.PendingOrderItem).filter(
                            models.PendingOrderItem._status == "pending"
                        ).all()
                        for pending_item in relaxed_pending:
                            width_match = float(pending_item.width_inches) == float(width) if width and pending_item.width_inches else False
                            gsm_match = int(pending_item.gsm) == int(gsm) if gsm and pending_item.gsm else False
                            bf_match = float(pending_item.bf) == float(bf) if bf and pending_item.bf else False
                            shade_match = str(pending_item.shade).strip().lower() == str(shade).strip().lower() if shade and pending_item.shade else False
                            if width_match and gsm_match and bf_match and shade_match:
                                logger.info(f"🔍 RELAXED MATCH FOUND: {pending_item.frontend_id} matches with relaxed comparison")
                        
                        # Also check if there are ANY pending orders for this order_id if we have one
                        if order_id:
                            order_pending = db.query(models.PendingOrderItem).filter(
                                models.PendingOrderItem.original_order_id == order_id_uuid,
                                models.PendingOrderItem._status == "pending"
                            ).all()
                            logger.info(f"🔍 DEBUG: Found {len(order_pending)} pending orders for order_id {order_id_uuid}")
                            for order_item in order_pending:
                                logger.info(f"  - Pending {order_item.frontend_id}: width={order_item.width_inches}, gsm={order_item.gsm}, bf={order_item.bf}, shade={order_item.shade}")
                    
                    for pending_item in matching_pending:
                        # Only update one pending item per cut roll selected
                        if pending_item.quantity_pending > 0:
                            logger.info(f"🔍 PENDING RESOLVE: Marking pending order {pending_item.frontend_id} as included_in_plan")
                            logger.info(f"🔍 BEFORE UPDATE: status={pending_item.status}, quantity_pending={pending_item.quantity_pending}, quantity_fulfilled={getattr(pending_item, 'quantity_fulfilled', 'NOT_SET')}")
                            
                            # Use the safe method that includes validation
                            try:
                                if pending_item.mark_as_included_in_plan(db, resolved_by_production=True):
                                    # Update quantity fields
                                    old_fulfilled = getattr(pending_item, 'quantity_fulfilled', 0) or 0
                                    old_pending = pending_item.quantity_pending
                                    
                                    pending_item.quantity_fulfilled = old_fulfilled + 1
                                    pending_item.quantity_pending = max(0, old_pending - 1)
                                    
                                    # Force flush to database to ensure changes are persisted
                                    db.flush()
                                    
                                    resolved_pending_count += 1
                                    updated_pending_orders.append(str(pending_item.id))
                                    
                                    logger.info(f"✅ PENDING SUCCESS: Resolved pending order {pending_item.frontend_id}")
                                    logger.info(f"🔍 AFTER UPDATE: status={pending_item.status}, quantity_pending={pending_item.quantity_pending}, quantity_fulfilled={pending_item.quantity_fulfilled}")
                                    break  # Only resolve one item per cut roll
                                else:
                                    logger.warning(f"❌ PENDING FAILED: Could not mark pending order {pending_item.frontend_id} as included_in_plan")
                            except Exception as e:
                                logger.error(f"❌ PENDING ERROR: Exception during update of {pending_item.frontend_id}: {e}")
                                import traceback
                                logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
                            
                except Exception as e:
                    logger.error(f"Error in pending order resolution for cut roll {width}\" {gsm}gsm {bf}bf {shade}: {e}")
                    continue
                        
            logger.info(f"Resolved {resolved_pending_count} pending order items based on selected cut rolls")
            
        except Exception as e:
            logger.warning(f"Error updating resolved pending orders during production start: {e}")
            # Don't fail the entire production start if pending order updates fail
        
        # Initialize tracking lists
        created_inventory = []
        created_pending_items = []
        
        # Create inventory records for SELECTED cut rolls with status "cutting"
        for cut_roll in selected_cut_rolls:
            # Generate barcode for this cut roll
            from ..services.barcode_generator import BarcodeGenerator
            import uuid
            barcode_id = BarcodeGenerator.generate_cut_roll_barcode(db)
            
            # Find the best matching order for this cut roll
            best_order = None
            cut_roll_width = cut_roll.get("width_inches", 0)
            cut_roll_paper_id = cut_roll.get("paper_id")
            
            # Look through all orders associated with this plan
            for plan_order in db_plan.plan_orders:
                order = plan_order.order
                if order:
                    # Check if this order has items matching the cut roll specs
                    for order_item in order.order_items:
                        if (str(order_item.paper_id) == str(cut_roll_paper_id) and 
                            abs(float(order_item.width_inches) - float(cut_roll_width)) < 0.01):
                            best_order = order
                            break
                if best_order:
                    break
            
            # Create inventory record for selected rolls
            # Generate NEW QR code for production (don't reuse planning QR codes)
            production_qr_code = f"PROD_{barcode_id}_{uuid.uuid4().hex[:8].upper()}"
            
            inventory_item = models.InventoryMaster(
                paper_id=cut_roll.get("paper_id"),
                width_inches=cut_roll.get("width_inches", 0),
                weight_kg=0,  # Will be updated via QR scan
                roll_type="cut",
                status="cutting",
                qr_code=production_qr_code,  # Use NEW production QR code
                barcode_id=barcode_id,
                allocated_to_order_id=best_order.id if best_order else None,
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
        
        # Move UNSELECTED cut rolls to pending orders
        if all_available_cuts:
            # Debug: Log the selected and available cut rolls data structure
            from ..services.id_generator import FrontendIDGenerator
            
            logger.info(f"🔍 ROLL COMPARISON DEBUG: Number of selected cut rolls: {len(selected_cut_rolls)}")
            logger.info(f"🔍 ROLL COMPARISON DEBUG: Number of available cuts: {len(all_available_cuts)}")
            
            # Debug: Log sample data structure
            if selected_cut_rolls:
                logger.info(f"🔍 SAMPLE SELECTED CUT ROLL: {selected_cut_rolls[0]}")
            if all_available_cuts:
                logger.info(f"🔍 SAMPLE AVAILABLE CUT: {all_available_cuts[0]}")
            
            # Create multiple sets for different comparison methods
            selected_barcodes = {cut.get("barcode_id") for cut in selected_cut_rolls if cut.get("barcode_id")}
            selected_qr_codes = {cut.get("qr_code") for cut in selected_cut_rolls if cut.get("qr_code")}
            
            # Also create composite identifiers as fallback
            selected_cut_identifiers = set()
            for cut in selected_cut_rolls:
                # Create a unique identifier from available fields
                identifier = (
                    cut.get("width_inches", cut.get("width", 0)),
                    cut.get("gsm", 0),
                    cut.get("bf", 0),
                    cut.get("shade", ""),
                    cut.get("individual_roll_number", 0),
                    cut.get("paper_id", "")
                )
                selected_cut_identifiers.add(identifier)
                logger.info(f"🔍 SELECTED IDENTIFIER: {identifier}")
            
            logger.info(f"🔍 SELECTED BARCODES: {selected_barcodes}")
            logger.info(f"🔍 SELECTED QR CODES: {selected_qr_codes}")
            logger.info(f"🔍 TOTAL SELECTED IDENTIFIERS: {len(selected_cut_identifiers)}")
            
            for available_cut in all_available_cuts:
                # Try multiple comparison methods
                available_barcode = available_cut.get("barcode_id")
                available_qr = available_cut.get("qr_code")
                
                # Create the same identifier for available cut
                available_identifier = (
                    available_cut.get("width_inches", available_cut.get("width", 0)),
                    available_cut.get("gsm", 0),
                    available_cut.get("bf", 0),
                    available_cut.get("shade", ""),
                    available_cut.get("individual_roll_number", 0),
                    available_cut.get("paper_id", "")
                )
                
                # Check if selected using any method
                is_selected_by_barcode = available_barcode and available_barcode in selected_barcodes
                is_selected_by_qr = available_qr and available_qr in selected_qr_codes
                is_selected_by_identifier = available_identifier in selected_cut_identifiers
                
                is_selected = is_selected_by_barcode or is_selected_by_qr or is_selected_by_identifier
                
                logger.info(f"🔍 AVAILABLE CUT: barcode='{available_barcode}', qr='{available_qr}', identifier={available_identifier}")
                logger.info(f"🔍 SELECTION CHECK: by_barcode={is_selected_by_barcode}, by_qr={is_selected_by_qr}, by_identifier={is_selected_by_identifier} -> SELECTED: {is_selected}")
                
                # If this cut was not selected, move it to pending orders
                if not is_selected:
                    # Debug: Check if order_id is available
                    order_id = available_cut.get("order_id")
                    logger.info(f"🔍 PENDING DEBUG: Creating pending item for unselected cut: {available_cut}")
                    logger.info(f"🔍 PENDING DEBUG: order_id = {order_id}")
                    
                    if not order_id:
                        logger.warning(f"⚠️ PENDING WARNING: No order_id found for unselected cut roll. Available keys: {list(available_cut.keys())}")
                        # Use the first order from plan_orders as fallback
                        if db_plan.plan_orders:
                            order_id = db_plan.plan_orders[0].order_id
                            logger.info(f"🔧 PENDING FALLBACK: Using first plan order_id as fallback: {order_id}")
                        else:
                            logger.error(f"❌ PENDING ERROR: No plan orders available for fallback")
                            continue  # Skip this item if no fallback available
                    
                    # Create pending order item for unselected cut
                    frontend_id = FrontendIDGenerator.generate_frontend_id("pending_order_item", db)
                    
                    pending_item = models.PendingOrderItem(
                        frontend_id=frontend_id,
                        original_order_id=order_id,
                        width_inches=available_cut.get("width_inches", 0),
                        quantity_pending=1,  # Each cut roll is quantity 1
                        gsm=available_cut.get("gsm"),
                        bf=available_cut.get("bf"),
                        shade=available_cut.get("shade"),
                        reason="unselected_for_production",
                        status="pending",
                        created_by_id=request_data.get("created_by_id")
                    )
                    db.add(pending_item)
                    db.flush()
                    
                    created_pending_items.append(pending_item)
                    updated_pending_orders.append(str(pending_item.id))
        
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
                "inventory_created": len(created_inventory),
                "pending_items_created": len(created_pending_items)
            },
            "details": {
                "updated_orders": updated_orders,
                "updated_order_items": updated_order_items,
                "updated_pending_orders": updated_pending_orders,
                "created_inventory": [str(inv.id) for inv in created_inventory],
                "created_pending_items": [str(pending.id) for pending in created_pending_items]
            },
            "created_inventory_details": [
                {
                    "id": str(inv.id),
                    "barcode_id": inv.barcode_id,
                    "qr_code": inv.qr_code,
                    "width_inches": float(inv.width_inches),
                    "paper_id": str(inv.paper_id),
                    "status": inv.status,
                    "created_at": inv.created_at.isoformat() if inv.created_at else None
                } for inv in created_inventory
            ],
            "message": f"Production started successfully - Updated {len(updated_orders)} orders, {len(updated_order_items)} order items, {len(updated_pending_orders)} pending orders, and created {len(created_pending_items)} pending items from unselected rolls"
        }


plan = CRUDPlan(models.PlanMaster)