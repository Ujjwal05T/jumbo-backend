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
        """Create new cutting plan with order links and pending orders"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Create the plan record
            import json
            db_plan = models.PlanMaster(
                name=plan.name,
                cut_pattern=json.dumps(plan.cut_pattern) if isinstance(plan.cut_pattern, list) else plan.cut_pattern,
                expected_waste_percentage=plan.expected_waste_percentage,
                created_by_id=plan.created_by_id
            )
            db.add(db_plan)
            db.flush()  # Get the plan ID
            
            # Create plan-order links (need to link to specific order items)
            for order_id in plan.order_ids:
                # Get order items for this order
                order_items = db.query(models.OrderItem).filter(
                    models.OrderItem.order_id == order_id
                ).all()
                
                # Create links for each order item
                for order_item in order_items:
                    plan_order_link = models.PlanOrderLink(
                        plan_id=db_plan.id,
                        order_id=order_id,
                        order_item_id=order_item.id,
                        quantity_allocated=1  # Default quantity
                    )
                    db.add(plan_order_link)
            
            logger.info(f"Created plan {db_plan.id} with {len(plan.order_ids)} order links")
            
            # Create pending orders from algorithm results if provided
            if hasattr(plan, 'pending_orders') and plan.pending_orders:
                from ..services.id_generator import FrontendIDGenerator
                
                for pending_data in plan.pending_orders:
                    # Find original order ID from the provided order_ids
                    original_order_id = plan.order_ids[0] if plan.order_ids else None
                    
                    # Generate frontend ID
                    frontend_id = FrontendIDGenerator.generate_frontend_id("pending_order_item", db)
                    
                    pending_order = models.PendingOrderItem(
                        frontend_id=frontend_id,
                        original_order_id=original_order_id,
                        width_inches=float(pending_data.get('width', 0)),
                        quantity_pending=int(pending_data.get('quantity', 1)),
                        gsm=pending_data.get('gsm', 0),
                        bf=float(pending_data.get('bf', 0)),
                        shade=pending_data.get('shade', ''),
                        status="pending",
                        included_in_plan_generation=False,  # Algorithm rejected these
                        reason=pending_data.get('reason', 'algorithm_rejected'),
                        created_by_id=plan.created_by_id
                    )
                    db.add(pending_order)
                
                logger.info(f"Created {len(plan.pending_orders)} pending orders from algorithm")
            
            db.commit()
            db.refresh(db_plan)
            return db_plan
            
        except Exception as e:
            logger.error(f"Error creating plan: {e}")
            db.rollback()
            raise
    
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
        created_jumbo_rolls = []
        created_118_rolls = []
        
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
        
        # Initialize tracking lists
        created_inventory = []
        
        # NEW: Create virtual jumbo roll hierarchy based on optimization algorithm roll numbers
        jumbo_roll_width = request_data.get("jumbo_roll_width", 118)  # Get dynamic width from request
        
        # Group selected cut rolls by individual_roll_number (from optimization algorithm)
        roll_number_groups = {}
        paper_specs = {}  # Track paper specs for each roll number
        
        for cut_roll in selected_cut_rolls:
            individual_roll_number = cut_roll.get("individual_roll_number")
            if individual_roll_number:
                if individual_roll_number not in roll_number_groups:
                    roll_number_groups[individual_roll_number] = []
                    paper_specs[individual_roll_number] = {
                        'gsm': cut_roll.get("gsm"),
                        'bf': cut_roll.get("bf"),
                        'shade': cut_roll.get("shade"),
                        'paper_id': cut_roll.get("paper_id")
                    }
                roll_number_groups[individual_roll_number].append(cut_roll)
        
        # Calculate jumbo rolls needed: 3 individual rolls = 1 jumbo
        total_118_rolls = len(roll_number_groups)
        jumbo_count = (total_118_rolls + 2) // 3  # Ceiling division
        
        logger.info(f"📦 JUMBO CREATION: {total_118_rolls} individual 118\" rolls = {jumbo_count} jumbo rolls needed")
        
        # Create jumbo rolls and link 118" rolls properly
        import uuid
        
        # Group 118" rolls by paper specification for jumbo creation
        spec_to_118_rolls = {}
        for roll_num, spec in paper_specs.items():
            spec_key = (spec['gsm'], spec['bf'], spec['shade'])
            if spec_key not in spec_to_118_rolls:
                spec_to_118_rolls[spec_key] = []
            spec_to_118_rolls[spec_key].append(roll_num)
        
        # Create jumbo rolls for each paper specification
        for (gsm, bf, shade), roll_numbers in spec_to_118_rolls.items():
            # Find paper record
            paper_record = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == gsm,
                models.PaperMaster.bf == bf,
                models.PaperMaster.shade == shade
            ).first()
            
            if not paper_record:
                logger.warning(f"Could not find paper record for GSM={gsm}, BF={bf}, Shade={shade}")
                continue
            
            # Calculate jumbo rolls needed for this paper spec
            spec_jumbo_count = (len(roll_numbers) + 2) // 3
            
            # Create jumbo rolls for this paper specification
            for jumbo_idx in range(spec_jumbo_count):
                virtual_jumbo_qr = f"VIRTUAL_JUMBO_{uuid.uuid4().hex[:8].upper()}"
                virtual_jumbo_barcode = f"VJB_{uuid.uuid4().hex[:8].upper()}"
                jumbo_roll = models.InventoryMaster(
                    paper_id=paper_record.id,
                    width_inches=jumbo_roll_width,
                    weight_kg=0,
                    roll_type="jumbo",
                    status="consumed",
                    qr_code=virtual_jumbo_qr,
                    barcode_id=virtual_jumbo_barcode,
                    location="VIRTUAL",
                    created_by_id=request_data.get("created_by_id")
                )
                db.add(jumbo_roll)
                db.flush()
                created_jumbo_rolls.append(jumbo_roll)
                
                logger.info(f"📦 CREATED JUMBO: {jumbo_roll.frontend_id} - {jumbo_roll_width}\" {shade} paper")
                
                # Assign 3 individual roll numbers to this jumbo
                start_idx = jumbo_idx * 3
                end_idx = min(start_idx + 3, len(roll_numbers))
                assigned_roll_numbers = roll_numbers[start_idx:end_idx]
                
                # Create 118" rolls for the assigned individual roll numbers
                for seq, roll_num in enumerate(assigned_roll_numbers, 1):
                    virtual_118_qr = f"VIRTUAL_118_{uuid.uuid4().hex[:8].upper()}"
                    virtual_118_barcode = f"V118_{uuid.uuid4().hex[:8].upper()}"
                    roll_118 = models.InventoryMaster(
                        paper_id=paper_record.id,
                        width_inches=jumbo_roll_width,
                        weight_kg=0,
                        roll_type="118",
                        status="consumed",
                        qr_code=virtual_118_qr,
                        barcode_id=virtual_118_barcode,
                        location="VIRTUAL",
                        parent_jumbo_id=jumbo_roll.id,
                        roll_sequence=seq,
                        individual_roll_number=roll_num,  # Store the algorithm's roll number
                        created_by_id=request_data.get("created_by_id")
                    )
                    db.add(roll_118)
                    db.flush()
                    created_118_rolls.append(roll_118)
                    
                    logger.info(f"🧻 CREATED 118\" ROLL: {roll_118.frontend_id} - Roll #{roll_num}, Sequence {seq} of Jumbo {jumbo_roll.frontend_id}")
        
        logger.info(f"✅ HIERARCHY CREATED: {len(created_jumbo_rolls)} jumbo rolls, {len(created_118_rolls)} intermediate rolls")
        
        # Create inventory records for SELECTED cut rolls with status "cutting"
        # Link cut rolls to their parent 118" rolls based on individual_roll_number
        for cut_roll in selected_cut_rolls:
            # Generate barcode for this cut roll
            from ..services.barcode_generator import BarcodeGenerator
            import uuid
            barcode_id = BarcodeGenerator.generate_cut_roll_barcode(db)
            
            # Find parent 118" roll for this cut roll based on individual_roll_number
            individual_roll_number = cut_roll.get("individual_roll_number")
            parent_118_roll = None
            
            if individual_roll_number:
                # Find the 118" roll with matching individual_roll_number
                for roll_118 in created_118_rolls:
                    if roll_118.individual_roll_number == individual_roll_number:
                        parent_118_roll = roll_118
                        logger.info(f"🔗 LINKING: Cut roll -> 118\" Roll {parent_118_roll.frontend_id} (Roll #{individual_roll_number})")
                        break
            
            if not parent_118_roll:
                logger.warning(f"Could not find parent 118\" roll for cut roll with individual_roll_number={individual_roll_number}")
            
            # Find the best matching order for this cut roll
            best_order = None
            cut_roll_width = cut_roll.get("width", cut_roll.get("width_inches", 0))  # Try both field names
            cut_roll_paper_id = cut_roll.get("paper_id")  # This might be None from optimizer
            
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
            
            # Handle paper_id - optimizer might not set this, so find it from the order
            if not cut_roll_paper_id and best_order:
                # Find paper_id from the best matching order item
                for order_item in best_order.order_items:
                    if abs(float(order_item.width_inches) - float(cut_roll_width)) < 0.01:
                        cut_roll_paper_id = order_item.paper_id
                        break
            
            logger.info(f"🔍 INVENTORY DEBUG: cut_roll data = {cut_roll}")
            logger.info(f"🔍 INVENTORY DEBUG: source_type = {cut_roll.get('source_type')}")
            logger.info(f"🔍 INVENTORY DEBUG: source_pending_id = {cut_roll.get('source_pending_id')}")
            
            # NEW: If source tracking is missing, try to reconstruct it from pending orders
            if not cut_roll.get('source_type') and cut_roll.get('gsm') and cut_roll.get('shade'):
                logger.info(f"🔍 RECONSTRUCTING: Trying to find source tracking from pending orders for {cut_roll_width}\" GSM={cut_roll.get('gsm')} Shade={cut_roll.get('shade')}")
                
                # Look for pending orders with matching specs 
                matching_pending = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.width_inches == cut_roll_width,
                    models.PendingOrderItem.gsm == cut_roll.get('gsm'),
                    models.PendingOrderItem.shade == cut_roll.get('shade'),
                    models.PendingOrderItem._status == "pending"  # FIXED: Use _status column, not status property
                    # REMOVED: included_in_plan_generation filter - these ARE from plan generation
                ).first()
                
                if matching_pending:
                    logger.info(f"🔍 RECONSTRUCTED: Found matching pending order {matching_pending.frontend_id} for cut roll")
                    # Add source tracking to the cut_roll dict
                    cut_roll['source_type'] = 'pending_order'
                    cut_roll['source_pending_id'] = str(matching_pending.id)
                    logger.info(f"🔍 RECONSTRUCTED: Added source_type='pending_order', source_pending_id='{matching_pending.id}'")
                else:
                    logger.info(f"🔍 RECONSTRUCTED: No matching pending order found, assuming regular order")
                    cut_roll['source_type'] = 'regular_order'
            
            inventory_item = models.InventoryMaster(
                paper_id=cut_roll_paper_id,
                width_inches=cut_roll_width,
                weight_kg=0,  # Will be updated via QR scan
                roll_type="cut",
                status="cutting",
                qr_code=production_qr_code,  # Use NEW production QR code
                barcode_id=barcode_id,
                allocated_to_order_id=best_order.id if best_order else None,
                # NEW: Save source tracking information from cut roll
                source_type=cut_roll.get("source_type"),
                source_pending_id=UUID(cut_roll.get("source_pending_id")) if cut_roll.get("source_pending_id") else None,
                # NEW: Link to parent 118" roll for complete hierarchy
                parent_118_roll_id=parent_118_roll.id if parent_118_roll else None,
                individual_roll_number=cut_roll.get("individual_roll_number"),
                created_by_id=request_data.get("created_by_id")
            )
            db.add(inventory_item)
            db.flush()  # Get inventory_item.id
            
            # CRITICAL DEBUG: Log what was actually saved to database
            logger.info(f"🔍 INVENTORY CREATED: id={inventory_item.id}, width={inventory_item.width_inches}, source_type={inventory_item.source_type}, source_pending_id={inventory_item.source_pending_id}, parent_118_roll_id={inventory_item.parent_118_roll_id}")
            
            # Create plan-inventory link to associate this inventory item with the plan
            plan_inventory_link = models.PlanInventoryLink(
                plan_id=plan_id,
                inventory_id=inventory_item.id,
                quantity_used=1.0  # One roll used
            )
            db.add(plan_inventory_link)
            
            created_inventory.append(inventory_item)
        
        # NEW CORRECT PENDING ORDER RESOLUTION LOGIC  
        # Now process the created inventory items to resolve pending orders
        try:
            resolved_pending_count = 0
            logger.info(f"🔍 NEW PENDING RESOLUTION: Processing {len(created_inventory)} inventory items with source tracking")
            
            # Process each created inventory item to find its source pending order (if any)
            for i, inventory_item in enumerate(created_inventory):
                logger.info(f"🔍 INVENTORY ITEM {i+1}: Processing {inventory_item.width_inches}\" {inventory_item.barcode_id}")
                
                # Check if this inventory item came from a pending order (read from database)
                source_type = inventory_item.source_type
                source_pending_id = inventory_item.source_pending_id
                
                logger.info(f"🔍 INVENTORY ITEM {i+1}: source_type={source_type}, source_pending_id={source_pending_id}")
                
                if source_type == 'pending_order' and source_pending_id:
                    # This cut roll was generated from a pending order - resolve it
                    try:
                        # Convert string UUID to UUID object if needed
                        if isinstance(source_pending_id, str):
                            pending_uuid = UUID(source_pending_id)
                        else:
                            pending_uuid = source_pending_id
                        
                        # ENHANCED DEBUGGING: Check what pending orders exist
                        all_pending_with_id = db.query(models.PendingOrderItem).filter(
                            models.PendingOrderItem.id == pending_uuid
                        ).all()
                        
                        logger.info(f"🔍 DATABASE DEBUG: Found {len(all_pending_with_id)} pending orders with ID {pending_uuid}")
                        for po in all_pending_with_id:
                            logger.info(f"  📋 Pending order: id={po.id}, status={po.status}, included_in_plan={po.included_in_plan_generation}, width={po.width_inches}")
                        
                        # Find the pending order with exact criteria
                        pending_order = db.query(models.PendingOrderItem).filter(
                            models.PendingOrderItem.id == pending_uuid,
                            models.PendingOrderItem._status == "pending"  # FIXED: Use _status column, not status property
                            # REMOVED: included_in_plan_generation filter - these ARE the pending orders from plan generation
                        ).first()
                        
                        if pending_order and pending_order.quantity_pending > 0:
                            logger.info(f"✅ RESOLVING: Cut roll {i+1} came from pending {pending_order.frontend_id} - marking as included_in_plan")
                            
                            # Use the safe method that includes validation
                            if pending_order.mark_as_included_in_plan(db, resolved_by_production=True):
                                # Update quantity fields
                                old_fulfilled = getattr(pending_order, 'quantity_fulfilled', 0) or 0
                                old_pending = pending_order.quantity_pending
                                
                                pending_order.quantity_fulfilled = old_fulfilled + 1
                                pending_order.quantity_pending = max(0, old_pending - 1)
                                
                                # NEW: Decrement quantity_in_pending from original order item
                                original_order_item = db.query(models.OrderItem).filter(
                                    models.OrderItem.order_id == pending_order.original_order_id,
                                    models.OrderItem.width_inches == pending_order.width_inches,
                                    models.OrderItem.paper.has(
                                        models.PaperMaster.gsm == pending_order.gsm,
                                        models.PaperMaster.bf == pending_order.bf,
                                        models.PaperMaster.shade == pending_order.shade
                                    )
                                ).first()
                                
                                if original_order_item:
                                    # Decrement quantity_in_pending and increment quantity_fulfilled
                                    if original_order_item.quantity_in_pending > 0:
                                        original_order_item.quantity_in_pending -= 1
                                    original_order_item.quantity_fulfilled += 1
                                    logger.info(f"✅ UPDATED ORDER ITEM: {original_order_item.frontend_id} - quantity_in_pending: {original_order_item.quantity_in_pending}, quantity_fulfilled: {original_order_item.quantity_fulfilled}")
                                else:
                                    logger.warning(f"Could not find original order item to update for resolved pending order {pending_order.frontend_id}")
                                
                                # Force flush to database to ensure changes are persisted
                                db.flush()
                                
                                resolved_pending_count += 1
                                updated_pending_orders.append(str(pending_order.id))
                                
                                logger.info(f"✅ SUCCESS: Resolved pending {pending_order.frontend_id} - qty_pending: {old_pending} -> {pending_order.quantity_pending}")
                            else:
                                logger.warning(f"❌ FAILED: Could not mark pending {pending_order.frontend_id} as included_in_plan")
                        elif pending_order and pending_order.included_in_plan_generation == False:
                            logger.info(f"⏸️ SKIPPED: Pending order {pending_order.frontend_id} was not included in plan generation (high waste) - keeping as pending")
                        elif not pending_order:
                            logger.warning(f"⚠️ NOT FOUND: Could not find pending order with ID {source_pending_id}")
                        else:
                            logger.info(f"ℹ️ NO QUANTITY: Pending order {pending_order.frontend_id} has no remaining quantity to resolve")
                            
                    except Exception as e:
                        logger.error(f"❌ ERROR: Exception resolving pending order for cut roll {i+1}: {e}")
                        import traceback
                        logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
                        
                elif source_type == 'regular_order':
                    logger.info(f"ℹ️ REGULAR ORDER: Cut roll {i+1} came from regular order - no pending order to resolve")
                else:
                    logger.info(f"ℹ️ NO SOURCE: Cut roll {i+1} has no source tracking - likely from regular order")
            
            logger.info(f"✅ RESOLUTION COMPLETE: Resolved {resolved_pending_count} pending orders based on source tracking of selected cut rolls")
            
        except Exception as e:
            logger.warning(f"Error updating resolved pending orders during production start: {e}")
            # Don't fail the entire production start if pending order updates fail
        
        # PHASE 2: Create pending orders for unselected cut rolls (per documentation)
        # These are user business decisions to defer production
        logger.info("Creating PHASE 2 pending orders for unselected cut rolls (user deferred production)")
        
        created_pending_from_unselected = []
        unselected_cut_rolls = []
        
        # Find unselected cut rolls by comparing available vs selected
        # Since cut rolls don't have unique IDs, use a combination of identifying fields
        def make_roll_key(roll):
            return (
                roll.get('width_inches', roll.get('width', 0)),
                roll.get('gsm', 0), 
                roll.get('bf', 0),
                roll.get('shade', ''),
                roll.get('individual_roll_number', 1),
                roll.get('order_id', '')
            )
        
        selected_roll_keys = {make_roll_key(roll) for roll in selected_cut_rolls}
        
        logger.info(f"🔍 PHASE 2 DEBUG: {len(selected_cut_rolls)} selected cut rolls, {len(all_available_cuts)} available cuts")
        logger.info(f"🔍 PHASE 2 DEBUG: Selected keys count: {len(selected_roll_keys)}")
        
        for available_roll in all_available_cuts:
            available_key = make_roll_key(available_roll)
            if available_key not in selected_roll_keys:
                unselected_cut_rolls.append(available_roll)
                logger.info(f"🔍 PHASE 2 DEBUG: Unselected roll found: {available_key}")
            else:
                logger.info(f"🔍 PHASE 2 DEBUG: Roll WAS selected: {available_key}")
        
        logger.info(f"🔍 PHASE 2: Found {len(unselected_cut_rolls)} unselected cut rolls for pending order creation")
        
        # Create pending orders for each unselected cut roll
        for unselected_roll in unselected_cut_rolls:
            try:
                # Find the original order this cut roll was meant for
                original_order_id = unselected_roll.get('order_id')
                
                if original_order_id:
                    # Convert to UUID if needed
                    if isinstance(original_order_id, str):
                        original_order_id = UUID(original_order_id)
                    
                    # Generate frontend ID for the pending order
                    from ..services.id_generator import FrontendIDGenerator
                    frontend_id = FrontendIDGenerator.generate_frontend_id("pending_order_item", db)
                    
                    # Create PHASE 2 pending order (user deferred production)
                    # Note: PendingOrderItem stores paper specs directly (gsm, bf, shade) instead of paper_id
                    pending_order = models.PendingOrderItem(
                        frontend_id=frontend_id,
                        original_order_id=original_order_id,
                        width_inches=float(unselected_roll.get('width_inches', 0)),
                        quantity_pending=1,  # One roll per unselected cut roll
                        gsm=unselected_roll.get('gsm', 0),
                        bf=float(unselected_roll.get('bf', 0)),
                        shade=unselected_roll.get('shade', ''),
                        status="pending",
                        included_in_plan_generation=True,  # PHASE 2: User business decision
                        reason="user_deferred_production",
                        created_by_id=request_data.get("created_by_id")
                    )
                    
                    db.add(pending_order)
                    created_pending_from_unselected.append(pending_order)
                    logger.info(f"Created PHASE 2 pending order: 1 roll of {unselected_roll.get('width_inches')}\" {unselected_roll.get('shade')} paper (user deferred)")
                    
                else:
                    logger.warning(f"Could not find original order for unselected cut roll: {unselected_roll}")
                    
            except Exception as e:
                logger.error(f"Error creating PHASE 2 pending order for unselected cut roll: {e}")
        
        db.flush()  # Ensure PHASE 2 pending orders are saved
        logger.info(f"✅ PHASE 2 COMPLETE: Created {len(created_pending_from_unselected)} pending orders from unselected cut rolls")
        
        db.commit()
        db.refresh(db_plan)
        
        return {
            "plan_id": str(db_plan.id),
            "status": db_plan.status,
            "executed_at": db_plan.executed_at.isoformat() if db_plan.executed_at else None,
            "summary": {
                "orders_updated": len(updated_orders),
                "order_items_updated": len(updated_order_items),
                "pending_orders_resolved": len(updated_pending_orders),
                "inventory_created": len(created_inventory),
                "pending_orders_created_phase2": len(created_pending_from_unselected),
                "jumbo_rolls_created": len(created_jumbo_rolls),
                "intermediate_118_rolls_created": len(created_118_rolls)
            },
            "details": {
                "updated_orders": updated_orders,
                "updated_order_items": updated_order_items,
                "updated_pending_orders": updated_pending_orders,  # Use the expected field name
                "created_inventory": [str(inv.id) for inv in created_inventory],
                "created_jumbo_rolls": [str(jr.id) for jr in created_jumbo_rolls],
                "created_118_rolls": [str(r118.id) for r118 in created_118_rolls]
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
            "message": f"Production started successfully - Updated {len(updated_orders)} orders, {len(updated_order_items)} order items, resolved {len(updated_pending_orders)} pending orders, created {len(created_jumbo_rolls)} jumbo rolls, {len(created_118_rolls)} intermediate rolls, {len(created_inventory)} cut roll inventory items, and created {len(created_pending_from_unselected)} PHASE 2 pending orders from unselected cuts"
        }


plan = CRUDPlan(models.PlanMaster)