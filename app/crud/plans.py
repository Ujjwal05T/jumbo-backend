from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
import logging


from .base import CRUDBase
from .. import models, schemas
from ..services.barcode_generator import BarcodeGenerator

logger = logging.getLogger(__name__)


class CRUDPlan(CRUDBase[models.PlanMaster, schemas.PlanMasterCreate, schemas.PlanMasterUpdate]):
    def _validate_pending_order_id(self, db: Session, pending_id_str: str) -> UUID:
        """Validate that pending order ID exists before using it as foreign key"""
        if not pending_id_str:
            return None
            
        try:
            pending_uuid = UUID(pending_id_str)
            # Check if the pending order item actually exists
            pending_exists = db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.id == pending_uuid
            ).first()
            
            if pending_exists:
                return pending_uuid
            else:
                logger.warning(f"⚠️ PENDING VALIDATION: Pending order {pending_uuid} not found, setting to None")
                return None
                
        except (ValueError, TypeError) as e:
            logger.warning(f"⚠️ PENDING VALIDATION: Invalid pending order ID format '{pending_id_str}': {e}")
            return None

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
    
    def get_plan(self, db: Session, plan_id: UUID, include_relationships: bool = True) -> Optional[models.PlanMaster]:
        """Get plan by ID with optional relationships loading
        
        Args:
            db: Database session
            plan_id: UUID of the plan
            include_relationships: If True, loads all relationships (orders, inventory).
                                   If False, only loads the creator user (optimized for detail view).
        
        Returns:
            Plan with requested relationships or None if not found
        """
        query = db.query(models.PlanMaster)
        
        if include_relationships:
            # Full version: Load all relationships (used for production start, etc.)
            query = query.options(
                joinedload(models.PlanMaster.created_by),
                joinedload(models.PlanMaster.plan_orders).joinedload(models.PlanOrderLink.order),
                joinedload(models.PlanMaster.plan_inventory).joinedload(models.PlanInventoryLink.inventory)
            )
        else:
            # Optimized version: Only load creator user (used for plan details view)
            # This reduces data transfer and database load significantly
            query = query.options(
                joinedload(models.PlanMaster.created_by)
            )
        
        return query.filter(models.PlanMaster.id == plan_id).first()
    
    def create_plan(self, db: Session, *, plan: schemas.PlanMasterCreate) -> models.PlanMaster:
        """Create new cutting plan with order links and pending orders"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            # VALIDATION: Check if all orders have "created" status
            if plan.order_ids:
                non_created_orders = db.query(models.OrderMaster).filter(
                    models.OrderMaster.id.in_(plan.order_ids),
                    models.OrderMaster.status != "created"
                ).all()

                if non_created_orders:
                    order_details = [
                        f"{order.frontend_id or str(order.id)} (status: {order.status})"
                        for order in non_created_orders
                    ]
                    error_msg = (
                        f"Cannot create plan. Only orders with 'created' status can be planned. "
                        f"The following orders have different status: {', '.join(order_details)}."
                    )
                    logger.error(f"❌ PLAN VALIDATION: {error_msg}")
                    raise ValueError(error_msg)

                logger.info(f"✅ PLAN VALIDATION: All {len(plan.order_ids)} orders have 'created' status")

            # Create the plan record
            import json
            db_plan = models.PlanMaster(
                name=plan.name,
                cut_pattern=json.dumps(plan.cut_pattern) if isinstance(plan.cut_pattern, (list, dict)) else plan.cut_pattern,
                wastage_allocations=json.dumps(plan.wastage_allocations) if hasattr(plan, 'wastage_allocations') and plan.wastage_allocations else None,
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
            
            
            # Create pending orders from algorithm results if provided
            if hasattr(plan, 'pending_orders') and plan.pending_orders:
                logger.info(f"PENDING ORDERS DEBUG: Creating {len(plan.pending_orders)} pending orders for plan {plan.name}")
                from ..services.id_generator import FrontendIDGenerator

                for pending_data in plan.pending_orders:
                    # Find original order ID from the provided order_ids
                    original_order_id = pending_data.get('source_order_id') or pending_data.get('original_order_id') or pending_data.get('order_id') or (plan.order_ids[0] if plan.order_ids else None)

                    # VALIDATION: Ensure original_order_id is valid and in plan
                    if not original_order_id:
                        error_msg = f"❌ PENDING ORDER VALIDATION: No original_order_id found for pending order {pending_data}"
                        logger.error(error_msg)
                        raise ValueError(f"Invalid pending order data: {error_msg}")

                    # Verify the original_order_id is actually in this plan's order_ids
                    # Convert both to strings for comparison since plan.order_ids may contain UUID objects
                    plan_order_ids_str = [str(oid) for oid in plan.order_ids]
                    if str(original_order_id) not in plan_order_ids_str:
                        error_msg = f"❌ PENDING ORDER VALIDATION: original_order_id {original_order_id} not found in plan order_ids {plan_order_ids_str}"
                        logger.error(error_msg)
                        raise ValueError(f"Invalid pending order data: {error_msg}")

                    logger.info(f"✅ PENDING ORDER VALIDATION: Creating pending order for original_order_id {original_order_id}")

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
                        reason=pending_data.get('reason', 'algorithm_rejected'),
                        created_by_id=plan.created_by_id
                    )
                    db.add(pending_order)

                logger.info(f"PENDING ORDERS DEBUG: Successfully added {len(plan.pending_orders)} pending orders to database")

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
        allocated_wastage = []
        
        # NEW: STEP 1 - Convert pre-calculated wastage allocations to InventoryMaster entries
        
        # Check if plan has pre-calculated wastage allocations stored in separate field
        try:
            import json
            wastage_allocations = []

            # Get wastage allocations from dedicated field
            if db_plan.wastage_allocations:
                wastage_allocations = json.loads(db_plan.wastage_allocations) if isinstance(db_plan.wastage_allocations, str) else db_plan.wastage_allocations
                logger.info(f"✅ WASTAGE: Found {len(wastage_allocations)} pre-calculated wastage allocations in plan")
            else:
                logger.info("ℹ️ WASTAGE: No wastage allocations found in plan")

            if wastage_allocations:
                allocated_wastage = self._convert_wastage_allocations_to_cut_rolls(
                    db,
                    wastage_allocations=wastage_allocations,
                    plan_id=plan_id,
                    user_id=request_data.get("created_by_id")
                )
                
        except Exception as e:
            logger.error(f"❌ WASTAGE: Error during wastage allocation conversion: {e}")
            # Continue with normal production even if wastage conversion fails
        
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
        logger.info(f"Selected Cut Rolls: {selected_cut_rolls}")
        all_available_cuts = request_data.get("all_available_cuts", [])  # All cuts that were available for selection

        # NEW: Process added rolls early to create Gupta orders first
        added_rolls = request_data.get("added_rolls_data", [])
        gupta_order_mapping = {}
        created_gupta_orders = []  # Initialize as empty list

        if added_rolls:
            created_gupta_orders = self._process_added_rolls_early(
                db,
                request_data,
                selected_cut_rolls
            )
            # Get the single Gupta order ID for added rolls
            gupta_order_id = None
            if created_gupta_orders:
                gupta_order_id = created_gupta_orders[0].get("order", {}).get("id")

        # Initialize tracking lists
        created_inventory = []
        
        # NEW: Create virtual jumbo roll hierarchy based on optimization algorithm roll numbers
        jumbo_roll_width = request_data.get("jumbo_roll_width", 118)  # Get dynamic width from request
        
        # Group selected cut rolls by paper specification first, then by individual_roll_number
        # This ensures different paper types with same roll numbers are kept separate
        paper_spec_groups = {}  # {paper_spec_key: {roll_number: [cut_rolls]}}
        
        for i, cut_roll in enumerate(selected_cut_rolls):
            individual_roll_number = cut_roll.get("individual_roll_number")
            if individual_roll_number:
                # Create paper specification key (gsm, bf, shade)
                paper_spec_key = (
                    cut_roll.get("gsm"),
                    cut_roll.get("bf"),
                    cut_roll.get("shade")
                )

                # Initialize paper spec group if not exists
                if paper_spec_key not in paper_spec_groups:
                    paper_spec_groups[paper_spec_key] = {}

                # Initialize roll number group within this paper spec
                if individual_roll_number not in paper_spec_groups[paper_spec_key]:
                    paper_spec_groups[paper_spec_key][individual_roll_number] = []

                # Add cut roll to the appropriate group
                paper_spec_groups[paper_spec_key][individual_roll_number].append(cut_roll)
            else:
                logger.warning(f"📦 SKIPPED: Cut roll {i+1} has no individual_roll_number")
                
        
        # Validate paper specification separation
        roll_number_conflicts = {}
        for spec_key, roll_groups in paper_spec_groups.items():
            for roll_num in roll_groups.keys():
                if roll_num not in roll_number_conflicts:
                    roll_number_conflicts[roll_num] = []
                roll_number_conflicts[roll_num].append(spec_key)
        
       
        # Create jumbo rolls and link 118" rolls properly
        import uuid
        
        # Convert the nested structure to the format needed for jumbo creation
        # spec_to_118_rolls = {(gsm, bf, shade): [roll_numbers...]}
        spec_to_118_rolls = {}
        for spec_key, roll_groups in paper_spec_groups.items():
            spec_to_118_rolls[spec_key] = list(roll_groups.keys())
        
        # Create jumbo rolls for each paper specification separately
        jumbo_creation_summary = {}
        for spec_idx, ((gsm, bf, shade), roll_numbers) in enumerate(spec_to_118_rolls.items(), 1):
            jumbo_creation_summary[f"{gsm}gsm_{shade}"] = {"roll_count": len(roll_numbers), "jumbo_count": 0}
            
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
            logger.info(f"📦 SPEC JUMBOS: {len(roll_numbers)} rolls → {spec_jumbo_count} jumbos for {gsm}gsm {shade}")
            jumbo_creation_summary[f"{gsm}gsm_{shade}"]["jumbo_count"] = spec_jumbo_count
            
            # Create jumbo rolls for this paper specification
            for jumbo_idx in range(spec_jumbo_count):
                virtual_jumbo_qr = f"VIRTUAL_JUMBO_{uuid.uuid4().hex[:8].upper()}"
                virtual_jumbo_barcode = BarcodeGenerator.generate_jumbo_roll_barcode(db)
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
                
                logger.info(f"📦 CREATED JUMBO: {jumbo_roll.frontend_id} - {jumbo_roll_width}\" {gsm}gsm {shade} paper (#{jumbo_idx+1}/{spec_jumbo_count} for this spec)")
                
                # Assign 3 individual roll numbers to this jumbo
                start_idx = jumbo_idx * 3
                end_idx = min(start_idx + 3, len(roll_numbers))
                assigned_roll_numbers = roll_numbers[start_idx:end_idx]
                
                logger.info(f"📦 ASSIGNING ROLLS: Jumbo {jumbo_roll.frontend_id} gets roll numbers {assigned_roll_numbers}")
                
                # Create 118" rolls for the assigned individual roll numbers
                for seq, roll_num in enumerate(assigned_roll_numbers, 1):
                    virtual_118_qr = f"VIRTUAL_118_{uuid.uuid4().hex[:8].upper()}"
                    virtual_118_barcode = BarcodeGenerator.generate_118_roll_barcode(db)
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
                    
        
        # Final validation and summary logging
        
        # Group created jumbos by paper spec for validation
        jumbo_by_spec = {}
        for jumbo in created_jumbo_rolls:
            paper = db.query(models.PaperMaster).filter(models.PaperMaster.id == jumbo.paper_id).first()
            if paper:
                spec_key = (paper.gsm, paper.bf, paper.shade)
                if spec_key not in jumbo_by_spec:
                    jumbo_by_spec[spec_key] = []
                jumbo_by_spec[spec_key].append(jumbo)
        
            
        # Enhanced validation with detailed reporting
        
        # Validate that each paper spec got separate jumbos
        if len(jumbo_by_spec) != len(paper_spec_groups):
            logger.error(f"❌ VALIDATION FAILED: Expected {len(paper_spec_groups)} paper specs, but created jumbos for {len(jumbo_by_spec)} specs")
            logger.error(f"❌ This indicates paper type mixing or missing specifications")
        
        # Additional validation: Check for roll number conflicts within each paper spec
        for spec_key, jumbos in jumbo_by_spec.items():
            gsm, bf, shade = spec_key
            # Get all 118" rolls for this paper spec
            spec_118_rolls = [r for r in created_118_rolls if r.parent_jumbo_id in [j.id for j in jumbos]]
            roll_numbers_in_spec = [r.individual_roll_number for r in spec_118_rolls]

            # Check for duplicates within this spec (should not happen)
            if len(roll_numbers_in_spec) != len(set(roll_numbers_in_spec)):
                logger.error(f"❌ DUPLICATE ROLL NUMBERS DETECTED within {gsm}gsm {shade} specification!")
        
        # Create inventory records for SELECTED cut rolls with status "cutting"
        # Link cut rolls to their parent 118" rolls based on individual_roll_number
        for cut_roll in selected_cut_rolls:
            # Generate barcode for this cut roll
            import uuid
            barcode_id = BarcodeGenerator.generate_cut_roll_barcode(db)
            
            # Find parent 118" roll for this cut roll based on individual_roll_number
            individual_roll_number = cut_roll.get("individual_roll_number")
            
            # Find paper_id from cut roll specs (gsm, bf, shade) - ignore the paper_id from cut roll as it's unreliable
            paper_record = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == cut_roll.get("gsm"),
                models.PaperMaster.bf == cut_roll.get("bf"),
                models.PaperMaster.shade == cut_roll.get("shade")
            ).first()
            if paper_record:
                cut_roll_paper_id = paper_record.id
            else:
                cut_roll_paper_id = None
                logger.warning(f"❌ Could not find paper record for specs: {cut_roll.get('gsm')}gsm, {cut_roll.get('bf')}bf, {cut_roll.get('shade')}")
            
            parent_118_roll = None
            
            if individual_roll_number and cut_roll_paper_id:
                # Find the 118" roll with matching individual_roll_number AND same paper type
                # Use round-robin assignment to distribute cut rolls evenly across 118" rolls
                matching_118_rolls = [
                    roll for roll in created_118_rolls
                    if (roll.individual_roll_number == individual_roll_number and
                        roll.paper_id == cut_roll_paper_id)
                ]
                
                if matching_118_rolls:
                    # Count existing cut rolls for each 118" roll to find the least loaded one
                    roll_loads = {}
                    for roll_118 in matching_118_rolls:
                        # Count cut rolls already assigned to this 118" roll
                        existing_cuts = db.query(models.InventoryMaster).filter(
                            models.InventoryMaster.parent_118_roll_id == roll_118.id,
                            models.InventoryMaster.roll_type == "cut"
                        ).count()
                        roll_loads[roll_118.id] = existing_cuts
                    
                    # Select the 118" roll with the minimum load
                    min_load_roll_id = min(roll_loads.keys(), key=lambda k: roll_loads[k])
                    parent_118_roll = next(roll for roll in matching_118_rolls if roll.id == min_load_roll_id)
                else:
                    logger.warning(f"No matching 118\" rolls found for individual_roll_number={individual_roll_number} and paper_id={cut_roll_paper_id}")
            
            if not parent_118_roll:
                logger.warning(f"Could not find parent 118\" roll for cut roll with individual_roll_number={individual_roll_number} and paper_id={cut_roll_paper_id}")
            
            # Find the best matching order for this cut roll
            best_order = None
            cut_roll_width = cut_roll.get("width", cut_roll.get("width_inches", 0))  # Try both field names

            logger.info(f"🔍 CUT ROLL ALLOCATION START: Processing cut roll - width: {cut_roll_width}, paper_id: {cut_roll_paper_id}, source_type: {cut_roll.get('source_type')}, source_pending_id: {cut_roll.get('source_pending_id')}")

            # NEW: Check if this is an added roll and use Gupta order mapping
            # Identify added rolls by source_type or order_id pattern
            is_added_roll = (
                cut_roll.get("source_type") == "added_completion" or
                str(cut_roll.get("order_id", "")).startswith("GUPTA_")
            )

            if is_added_roll:
                # Use the created Gupta order ID directly
                if gupta_order_id:
                    best_order = db.query(models.OrderMaster).filter(
                        models.OrderMaster.id == gupta_order_id
                    ).first()

                    if not best_order:
                        logger.warning(f"🔧 ADDED ROLL: Gupta order with ID {gupta_order_id} not found")
                    else:
                        logger.info(f"🔧 ADDED ROLL: Found Gupta order {gupta_order_id}")
                else:
                    logger.warning(f"🔧 ADDED ROLL: No gupta_order_id available")

            logger.info(f"🔍 DEBUG: After Gupta check - best_order = {best_order}, is_added_roll = {is_added_roll}")

            # If not an added roll or no Gupta mapping found, use original logic
            if not best_order:
                # SIMPLIFIED: Use the cut roll's order_id directly (it's correct for all source types)
                cut_roll_order_id = cut_roll.get('order_id') or cut_roll.get('source_order_id') or cut_roll.get('original_order_id')
                logger.info(f"🔍 DIRECT ORDER ID: Using cut roll's order_id {cut_roll_order_id} for source_type: {cut_roll.get('source_type')}")

                if cut_roll_order_id:
                    # Look for the specific order this cut roll came from
                    for plan_order in db_plan.plan_orders:
                        # logger.info(f"🔍 CHECKING: Comparing cut roll order_id {cut_roll_order_id} with plan order_id {plan_order.order_id}")
                        if str(plan_order.order_id) == str(cut_roll_order_id):
                            best_order = plan_order.order
                            logger.info(f"🎯 EXACT MATCH: Cut roll allocated to original order {cut_roll_order_id}")
                            break

                # DYNAMIC INCLUSION: If order not in plan but valid, add it to plan
                if not best_order and cut_roll_order_id:
                    logger.info(f"🔍 DYNAMIC CHECK: Order {cut_roll_order_id} not in plan, checking if it's a valid order in database")
                    # Check if this is a valid order in the database
                    referenced_order = db.query(models.OrderMaster).filter(
                        models.OrderMaster.id == cut_roll_order_id
                    ).first()

                    if referenced_order:
                        logger.info(f"✅ DYNAMIC INCLUSION: Found valid order {cut_roll_order_id}, adding to plan")

                        # Get order items for this order to create proper links
                        order_items = db.query(models.OrderItem).filter(
                            models.OrderItem.order_id == referenced_order.id
                        ).all()

                        # Create plan-order links for each order item
                        for order_item in order_items:
                            plan_order_link = models.PlanOrderLink(
                                plan_id=db_plan.id,
                                order_id=referenced_order.id,
                                order_item_id=order_item.id,
                                quantity_allocated=1  # Default quantity
                            )
                            db.add(plan_order_link)

                        # Flush to ensure the links are created before continuing
                        db.flush()

                        # Now use this order
                        best_order = referenced_order
                        logger.info(f"🎯 DYNAMIC MATCH: Cut roll allocated to dynamically included order {cut_roll_order_id}")
                    else:
                        logger.error(f"❌ INVALID ORDER: Order {cut_roll_order_id} does not exist in database")

                # ERROR if still no match found
                if not best_order:
                    error_msg = f"❌ ALLOCATION FAILED: Cut roll cannot be allocated - order {cut_roll_order_id} not found in database (width: {cut_roll_width}, paper_id: {cut_roll_paper_id}, source_type: {cut_roll.get('source_type')}, source_pending_id: {cut_roll.get('source_pending_id')})"
                    logger.error(error_msg)
                    raise ValueError(f"Cut roll allocation failed: {error_msg}")
            
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
            
            
            # NEW: If source tracking is missing, try to reconstruct it from pending orders
            if not cut_roll.get('source_type') and cut_roll.get('gsm') and cut_roll.get('shade'):
                
                # Look for pending orders with matching specs 
                matching_pending = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.width_inches == cut_roll_width,
                    models.PendingOrderItem.gsm == cut_roll.get('gsm'),
                    models.PendingOrderItem.shade == cut_roll.get('shade'),
                    models.PendingOrderItem._status == "pending"
                ).first()
                
                if matching_pending:
                    # Add source tracking to the cut_roll dict
                    cut_roll['source_type'] = 'pending_order'
                    cut_roll['source_pending_id'] = str(matching_pending.id)
                else:
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
                source_pending_id=self._validate_pending_order_id(db, cut_roll.get("source_pending_id")),
                # NEW: Link to parent 118" roll for complete hierarchy
                parent_118_roll_id=parent_118_roll.id if parent_118_roll else None,
                individual_roll_number=cut_roll.get("individual_roll_number"),
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
        
        # NEW PENDING ORDER RESOLUTION LOGIC - COUNT-FIRST APPROACH
        # PHASE 1: Count how many cut rolls reference each pending order
        try:
            from collections import defaultdict

            pending_order_cut_roll_counts = defaultdict(int)

            logger.info("📊 PHASE 1: Counting cut rolls per pending order")

            # Count cut rolls grouped by source_pending_id
            for inventory_item in created_inventory:
                source_type = inventory_item.source_type
                source_pending_id = inventory_item.source_pending_id

                if source_type == 'pending_order' and source_pending_id:
                    # Normalize to string for consistent key handling
                    pending_id_str = str(source_pending_id)
                    pending_order_cut_roll_counts[pending_id_str] += 1

            logger.info(f"📊 Found {len(pending_order_cut_roll_counts)} unique pending orders referenced by cut rolls")
            for pending_id, count in pending_order_cut_roll_counts.items():
                logger.info(f"  → Pending order {pending_id[:8]}... has {count} cut rolls")

            # PHASE 2: Process each unique pending order ONCE
            resolved_pending_count = 0
            partially_resolved_count = 0

            logger.info("📊 PHASE 2: Processing pending order resolutions")

            for pending_id_str, cut_rolls_count in pending_order_cut_roll_counts.items():
                try:
                    # Convert to UUID
                    pending_uuid = UUID(pending_id_str)

                    # Find the pending order
                    pending_order = db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.id == pending_uuid,
                        models.PendingOrderItem._status == "pending"
                    ).first()

                    if not pending_order:
                        logger.warning(f"❌ Pending order {pending_id_str[:8]}... not found or not in 'pending' status")
                        continue

                    # Store old values for logging
                    old_fulfilled = getattr(pending_order, 'quantity_fulfilled', 0) or 0
                    old_pending = pending_order.quantity_pending

                    logger.info(f"📊 PROCESSING: {pending_order.frontend_id}")
                    logger.info(f"  → Current fulfilled: {old_fulfilled}")
                    logger.info(f"  → Current pending: {old_pending}")
                    logger.info(f"  → Cut rolls to resolve: {cut_rolls_count}")

                    # Calculate new quantities (don't exceed available quantity)
                    cut_rolls_to_resolve = min(cut_rolls_count, old_pending)
                    new_fulfilled = old_fulfilled + cut_rolls_to_resolve
                    new_pending = max(0, old_pending - cut_rolls_to_resolve)

                    # Update quantities
                    pending_order.quantity_fulfilled = new_fulfilled
                    pending_order.quantity_pending = new_pending

                    logger.info(f"  → New fulfilled: {new_fulfilled} (+{cut_rolls_to_resolve})")
                    logger.info(f"  → New pending: {new_pending}")

                    # CRITICAL: Only mark as "included_in_plan" if ALL quantities are fulfilled
                    if new_pending == 0:
                        # Fully resolved - change status
                        status_update_success = pending_order.mark_as_included_in_plan(db, resolved_by_production=True)

                        if status_update_success:
                            logger.info(f"✅ FULLY RESOLVED: {pending_order.frontend_id} marked as 'included_in_plan'")
                            resolved_pending_count += 1
                            updated_pending_orders.append(str(pending_order.id))
                        else:
                            logger.warning(f"❌ STATUS UPDATE FAILED: Could not mark {pending_order.frontend_id} as included_in_plan")
                    else:
                        # Partially resolved - keep status as "pending"
                        logger.info(f"⚠️ PARTIALLY RESOLVED: {pending_order.frontend_id} remains in 'pending' status ({new_pending} units still pending)")
                        partially_resolved_count += 1
                        updated_pending_orders.append(str(pending_order.id))

                    # Update original order item quantities
                    original_order_item = db.query(models.OrderItem).filter(
                        models.OrderItem.order_id == pending_order.original_order_id,
                        models.OrderItem.width_inches == pending_order.width_inches,
                        models.OrderItem.paper.has(
                            and_(
                                models.PaperMaster.gsm == pending_order.gsm,
                                models.PaperMaster.bf == pending_order.bf,
                                models.PaperMaster.shade == pending_order.shade
                            )
                        )
                    ).first()

                    if original_order_item:
                        logger.info(f"🔄 ORDER ITEM UPDATE: {original_order_item.frontend_id}")
                        logger.info(f"  → BEFORE - quantity_in_pending: {original_order_item.quantity_in_pending}")
                        logger.info(f"  → BEFORE - quantity_fulfilled: {original_order_item.quantity_fulfilled}")

                        old_in_pending = original_order_item.quantity_in_pending

                        # Decrement quantity_in_pending by the number of cut rolls resolved
                        if original_order_item.quantity_in_pending >= cut_rolls_to_resolve:
                            original_order_item.quantity_in_pending -= cut_rolls_to_resolve
                            logger.info(f"  → AFTER - quantity_in_pending: {original_order_item.quantity_in_pending} (-{cut_rolls_to_resolve})")
                        else:
                            logger.warning(f"⚠️ WARNING: quantity_in_pending ({original_order_item.quantity_in_pending}) < cut_rolls_to_resolve ({cut_rolls_to_resolve})")
                            original_order_item.quantity_in_pending = max(0, original_order_item.quantity_in_pending - cut_rolls_to_resolve)
                            logger.info(f"  → AFTER - quantity_in_pending: {original_order_item.quantity_in_pending}")

                        # NOTE: quantity_fulfilled will be incremented later during QR scanning
                        logger.info(f"  → quantity_fulfilled unchanged: {original_order_item.quantity_fulfilled} (will be updated during QR scanning)")

                        # Validation
                        if original_order_item.quantity_in_pending == old_in_pending - cut_rolls_to_resolve:
                            logger.info(f"✅ VALIDATION: Order item quantity_in_pending updated correctly")
                        else:
                            logger.error(f"❌ VALIDATION FAILED: Expected {old_in_pending - cut_rolls_to_resolve}, got {original_order_item.quantity_in_pending}")

                        logger.info(f"🔍 FINAL CHECK: Order item status")
                        logger.info(f"  → Total rolls ordered: {original_order_item.quantity_rolls}")
                        logger.info(f"  → Rolls fulfilled: {original_order_item.quantity_fulfilled}")
                        logger.info(f"  → Rolls in pending: {original_order_item.quantity_in_pending}")
                        logger.info(f"  → Remaining unfulfilled: {original_order_item.remaining_quantity}")
                    else:
                        logger.error(f"❌ CRITICAL: Could not find original order item for {pending_order.frontend_id}")
                        logger.error(f"   Search criteria: order_id={pending_order.original_order_id}, width={pending_order.width_inches}, gsm={pending_order.gsm}, bf={pending_order.bf}, shade={pending_order.shade}")

                    # Flush to database
                    db.flush()

                    # Verify database persistence
                    verification_pending = db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.id == pending_uuid
                    ).first()

                    if verification_pending:
                        logger.info(f"🔍 VERIFICATION: Database state for {verification_pending.frontend_id}")
                        logger.info(f"  → Status: {verification_pending.status}")
                        logger.info(f"  → quantity_pending: {verification_pending.quantity_pending}")
                        logger.info(f"  → quantity_fulfilled: {verification_pending.quantity_fulfilled}")

                except Exception as e:
                    logger.error(f"❌ ERROR: Exception processing pending order {pending_id_str[:8]}...: {e}")
                    import traceback
                    logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")

            logger.info(f"✅ RESOLUTION COMPLETE:")
            logger.info(f"  → Fully resolved (marked as 'included_in_plan'): {resolved_pending_count}")
            logger.info(f"  → Partially resolved (still 'pending'): {partially_resolved_count}")
            logger.info(f"  → Total pending orders updated: {len(updated_pending_orders)}")
            
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
                # PHASE 2 SOURCE SEPARATION: Only create pending orders from regular orders
                # Skip creating duplicates for unselected cut rolls that came from existing pending orders
                source_type = unselected_roll.get('source_type')
                source_pending_id = unselected_roll.get('source_pending_id')
                
                if source_type == 'pending_order' and source_pending_id:
                    logger.info(f"🔍 PHASE 2 SKIP: Unselected cut roll came from existing pending order {str(source_pending_id)[:8]}... - no duplication")
                    continue  # Skip creating new pending order for this unselected roll
                
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
                    logger.info(f"Created PHASE 2 pending order: 1 roll of {unselected_roll.get('width_inches')}\" {unselected_roll.get('shade')} paper (user deferred, from regular order)")
                    
                else:
                    logger.warning(f"Could not find original order for unselected cut roll: {unselected_roll}")
                    
            except Exception as e:
                logger.error(f"Error creating PHASE 2 pending order for unselected cut roll: {e}")
        
        db.flush()  # Ensure PHASE 2 pending orders are saved
        logger.info(f"✅ PHASE 2 COMPLETE: Created {len(created_pending_from_unselected)} pending orders from unselected cut rolls")
        
        # WASTAGE PROCESSING: Handle wastage data for 9-21 inch waste materials
        created_wastage = []
        wastage_data = request_data.get("wastage_data", [])
        logger.info(f"🗑️ WASTAGE PROCESSING: Processing {len(wastage_data)} wastage items")
        
        for i, wastage_item in enumerate(wastage_data):
            try:
                # Validate wastage width is in acceptable range (9-21 inches)
                width = float(wastage_item.get("width_inches", 0))
                if not (9 <= width <= 21):
                    logger.warning(f"⚠️ WASTAGE SKIP: Item {i+1} width {width}\" outside 9-21\" range")
                    continue
                
                # Generate wastage IDs using the new generators
                wastage_barcode_id = BarcodeGenerator.generate_wastage_barcode(db)
                
                # Find paper record for wastage
                import uuid
                received_paper_id = wastage_item.get("paper_id")
                logger.info(f"🔍 WASTAGE DEBUG: Received paper_id for item {i+1}: '{received_paper_id}' (type: {type(received_paper_id)})")
                
                paper_record = None
                paper_id = None
                
                # Try to use provided paper_id first
                if received_paper_id and received_paper_id.strip():
                    try:
                        paper_id = uuid.UUID(received_paper_id)
                        paper_record = db.query(models.PaperMaster).filter(models.PaperMaster.id == paper_id).first()
                        if paper_record:
                            logger.info(f"✅ WASTAGE DEBUG: Found paper by provided paper_id: {paper_id}")
                        else:
                            logger.warning(f"⚠️ WASTAGE DEBUG: Paper_id provided but record not found: {paper_id}")
                            paper_id = None
                    except (ValueError, TypeError) as e:
                        logger.warning(f"⚠️ WASTAGE DEBUG: Invalid paper_id format, will lookup by specs: '{received_paper_id}' - Error: {e}")
                
                # If no valid paper_id or paper not found, find it by GSM/BF/Shade specifications
                if not paper_record:
                    gsm = wastage_item.get('gsm')
                    bf = wastage_item.get('bf') 
                    shade = wastage_item.get('shade')
                    logger.info(f"🔍 WASTAGE DEBUG: Looking up paper by specs: GSM={gsm}, BF={bf}, Shade='{shade}'")
                    
                    paper_record = db.query(models.PaperMaster).filter(
                        models.PaperMaster.gsm == gsm,
                        models.PaperMaster.bf == bf,
                        models.PaperMaster.shade == shade
                    ).first()
                    
                    if paper_record:
                        paper_id = paper_record.id
                        logger.info(f"✅ WASTAGE DEBUG: Found paper by specs: {paper_id} (GSM={gsm}, BF={bf}, Shade='{shade}')")
                    else:
                        logger.error(f"❌ WASTAGE ERROR: No paper found for specs: GSM={gsm}, BF={bf}, Shade='{shade}'")
                        continue
                
                # Find source plan and jumbo roll if provided
                source_plan_id = None
                source_jumbo_roll_id = None
                
                try:
                    source_plan_id = uuid.UUID(wastage_item.get("source_plan_id"))
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ WASTAGE: Invalid source_plan_id for wastage item {i+1}")
                
                if wastage_item.get("source_jumbo_roll_id"):
                    try:
                        source_jumbo_roll_id = uuid.UUID(wastage_item.get("source_jumbo_roll_id"))
                    except (ValueError, TypeError):
                        logger.warning(f"⚠️ WASTAGE: Invalid source_jumbo_roll_id for wastage item {i+1}")
                
                # Create wastage inventory record
                wastage_inventory = models.WastageInventory(
                    width_inches=width,
                    paper_id=paper_id,
                    weight_kg=0.0,  # Will be set via QR scan later
                    source_plan_id=source_plan_id,
                    source_jumbo_roll_id=source_jumbo_roll_id,
                    individual_roll_number=wastage_item.get("individual_roll_number"),
                    status=models.WastageStatus.AVAILABLE.value,
                    location="WASTE_STORAGE",
                    notes=wastage_item.get("notes"),
                    created_by_id=uuid.UUID(request_data.get("created_by_id")) if request_data.get("created_by_id") else None,
                    barcode_id=wastage_barcode_id
                )
                
                db.add(wastage_inventory)
                db.flush()  # Get the ID and frontend_id
                created_wastage.append(wastage_inventory)
                
                logger.info(f"🗑️ WASTAGE CREATED: {wastage_inventory.frontend_id} - {width}\" {paper_record.shade} paper (Barcode: {wastage_barcode_id})")
                
            except Exception as e:
                logger.error(f"❌ WASTAGE ERROR: Failed to create wastage item {i+1}: {e}")
                continue
        
        logger.info(f"✅ WASTAGE COMPLETE: Created {len(created_wastage)} wastage inventory items")
        
        # NOTE: Added rolls processing moved to early stage before inventory creation
        # This ensures proper order ID tracking for inventory items

        db.commit()
        db.refresh(db_plan)

        # Build hierarchical production structure for simplified frontend consumption
        production_hierarchy = []
        jumbo_groups = {}

        print(f"DEBUG: Starting hierarchy build - created_jumbo_rolls: {len(created_jumbo_rolls)}, created_118_rolls: {len(created_118_rolls)}, created_inventory: {len(created_inventory)}")
        print(f"DEBUG: Sample jumbo roll IDs: {[jr.id for jr in created_jumbo_rolls[:3]]}")
        print(f"DEBUG: Sample 118\" roll parent_jumbo_ids: {[r118.parent_jumbo_id for r118 in created_118_rolls[:3]]}")

        # Group 118" rolls by parent jumbo
        for roll_118 in created_118_rolls:
            parent_jumbo_id = str(roll_118.parent_jumbo_id) if roll_118.parent_jumbo_id else None
            print(f"DEBUG: 118\" roll {roll_118.barcode_id} -> parent_jumbo_id: {parent_jumbo_id}")
            if parent_jumbo_id:
                if parent_jumbo_id not in jumbo_groups:
                    jumbo_groups[parent_jumbo_id] = {
                        "jumbo_roll": None,
                        "intermediate_rolls": [],
                        "cut_rolls": []
                    }
                jumbo_groups[parent_jumbo_id]["intermediate_rolls"].append({
                    "id": str(roll_118.id),
                    "barcode_id": roll_118.barcode_id,
                    "parent_jumbo_id": parent_jumbo_id,
                    "individual_roll_number": roll_118.individual_roll_number,
                    "width_inches": float(roll_118.width_inches),
                    "paper_spec": f"{roll_118.paper.gsm}gsm, {roll_118.paper.bf}bf, {roll_118.paper.shade}"
                })

        # Group cut rolls by their parent 118" rolls and then by jumbo
        print(f"DEBUG: Starting cut roll matching - {len(created_inventory)} cut rolls")
        for cut_roll in created_inventory:
            parent_118_barcode = None
            parent_jumbo_id = None

            print(f"DEBUG: Processing cut roll {cut_roll.barcode_id}, parent_118_roll_id: {getattr(cut_roll, 'parent_118_roll_id', 'None')}")

            # Use the proper UUID relationship: parent_118_roll_id
            if hasattr(cut_roll, 'parent_118_roll_id') and cut_roll.parent_118_roll_id:
                # Find the 118" roll by UUID and get its parent jumbo
                for roll_118 in created_118_rolls:
                    if str(roll_118.id) == str(cut_roll.parent_118_roll_id):
                        parent_118_barcode = roll_118.barcode_id
                        parent_jumbo_id = str(roll_118.parent_jumbo_id) if roll_118.parent_jumbo_id else None
                        print(f"DEBUG: Found parent 118\" roll {roll_118.barcode_id} for cut roll {cut_roll.barcode_id}")
                        break

            if parent_jumbo_id and parent_jumbo_id in jumbo_groups:
                print(f"DEBUG: Matched cut roll {cut_roll.barcode_id} to jumbo {parent_jumbo_id}")
                jumbo_groups[parent_jumbo_id]["cut_rolls"].append({
                    "id": str(cut_roll.id),
                    "barcode_id": cut_roll.barcode_id,
                    "width_inches": float(cut_roll.width_inches),
                    "parent_118_roll_barcode": parent_118_barcode,
                    "paper_spec": f"{cut_roll.paper.gsm}gsm, {cut_roll.paper.bf}bf, {cut_roll.paper.shade}",
                    "status": cut_roll.status
                })
            else:
                print(f"DEBUG: No match found for cut roll {cut_roll.barcode_id}, parent_jumbo_id: {parent_jumbo_id}")

        # Add jumbo roll details to each group
        for jumbo_roll in created_jumbo_rolls:
            jumbo_id = str(jumbo_roll.id)
            if jumbo_id in jumbo_groups:
                jumbo_groups[jumbo_id]["jumbo_roll"] = {
                    "id": jumbo_id,
                    "barcode_id": jumbo_roll.barcode_id,
                    "frontend_id": jumbo_roll.frontend_id,
                    "width_inches": float(jumbo_roll.width_inches),
                    "paper_spec": f"{jumbo_roll.paper.gsm}gsm, {jumbo_roll.paper.bf}bf, {jumbo_roll.paper.shade}",
                    "status": jumbo_roll.status,
                    "location": jumbo_roll.location
                }

        # Convert to final array format
        production_hierarchy = []
        for jumbo_id, group in jumbo_groups.items():
            if group["jumbo_roll"]:
                production_hierarchy.append({
                    "jumbo_roll": group["jumbo_roll"],
                    "intermediate_rolls": group["intermediate_rolls"],
                    "cut_rolls": group["cut_rolls"]
                })
                print(f"DEBUG: Final jumbo group {jumbo_id}: {len(group['cut_rolls'])} cut rolls")

        print(f"DEBUG: Final production_hierarchy built: {len(production_hierarchy)} jumbo groups")


        # Simplified wastage items
        wastage_items = [
            {
                "id": str(w.id),
                "barcode_id": w.barcode_id,
                "width_inches": float(w.width_inches),
                "paper_spec": f"{w.paper.gsm}gsm, {w.paper.bf}bf, {w.paper.shade}",
                "notes": w.notes,
                "status": w.status
            }
            for w in created_wastage
        ]

        print(f"DEBUG: Final production_hierarchy built: {len(production_hierarchy)} jumbo groups")
        print(f"DEBUG: Production hierarchy data preview: {production_hierarchy[:1] if production_hierarchy else 'EMPTY'}")
        print(f"DEBUG: About to return response with production_hierarchy length: {len(production_hierarchy)}")

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
                "intermediate_118_rolls_created": len(created_118_rolls),
                "wastage_items_created": len(created_wastage),
                "wastage_items_allocated": len(allocated_wastage),
                "gupta_orders_created": len(created_gupta_orders)
            },
            "details": {
                "updated_orders": updated_orders,
                "updated_order_items": updated_order_items,
                "updated_pending_orders": updated_pending_orders,  # Use the expected field name
                "created_inventory": [str(inv.id) for inv in created_inventory],
                "created_jumbo_rolls": [str(jr.id) for jr in created_jumbo_rolls],
                "created_118_rolls": [str(r118.id) for r118 in created_118_rolls],
                "created_wastage": [str(w.id) for w in created_wastage],
                "allocated_wastage": [str(w.id) for w in allocated_wastage],
                "created_gupta_orders": [order["order"]["frontend_id"] for order in created_gupta_orders]
            },
            "production_hierarchy": production_hierarchy,
            "wastage_items": wastage_items,
            "message": f"Production started successfully - Created {len(created_jumbo_rolls)} jumbo rolls with {len(created_inventory)} cut rolls and {len(created_wastage)} wastage items"
        }
    def _create_jumbo_id_mapping(self, created_jumbo_rolls, planResult):
        """
        Create mapping from original jumbo roll IDs to actual database jumbo barcodes.
        This maps planning algorithm IDs (like "JR-001") to actual barcodes (like "JR_00002").
        """
        jumbo_id_mapping = {}

        if not planResult or not created_jumbo_rolls or not hasattr(planResult, 'jumbo_roll_details'):
            return jumbo_id_mapping

        try:
            # Map original jumbo roll IDs to actual database jumbo rolls
            for jumbo in created_jumbo_rolls:
                # Find matching jumbo from plan result by paper spec
                paper_spec = f"{jumbo.paper.gsm}gsm, {jumbo.paper.bf}bf, {jumbo.paper.shade}"

                for plan_jumbo in planResult.jumbo_roll_details:
                    if (plan_jumbo and
                        plan_jumbo.paper_spec == paper_spec):

                        # Map both the jumbo_id and jumbo_frontend_id from planning to actual barcode
                        if hasattr(plan_jumbo, 'jumbo_id'):
                            jumbo_id_mapping[plan_jumbo.jumbo_id] = jumbo.barcode_id
                        if hasattr(plan_jumbo, 'jumbo_frontend_id'):
                            jumbo_id_mapping[plan_jumbo.jumbo_frontend_id] = jumbo.barcode_id

                        logger.info(f"🔄 JUMBO MAPPING: {plan_jumbo.jumbo_id} → {jumbo.barcode_id} ({paper_spec})")
                        break

        except Exception as e:
            logger.error(f"Error creating jumbo ID mapping: {e}")

        return jumbo_id_mapping

    def allocate_wastage_for_orders(
        self, 
        db: Session, 
        *, 
        wastage_allocations: List[Dict[str, Any]],
        user_id: UUID
    ) -> List[models.InventoryMaster]:
        """
        Allocate available wastage rolls to orders.
        This happens before creating new cuts.
        """
        from ..crud.inventory import CRUDInventory
        
        inventory_crud = CRUDInventory(models.InventoryMaster)
        allocated_wastage = []
        
        for allocation in wastage_allocations:
            # Allocate the wastage roll to the order
            wastage_roll = inventory_crud.allocate_wastage_to_order(
                db,
                wastage_id=allocation['wastage_id'],
                order_id=allocation['order_id']
            )
            
            if wastage_roll:
                allocated_wastage.append(wastage_roll)
                
                # Update order item fulfillment
                order_item = db.query(models.OrderItem).filter(
                    models.OrderItem.id == allocation['order_item_id']
                ).first()
                
                if order_item:
                    order_item.quantity_fulfilled += 1
                    logger.info(f"🔄 WASTAGE ALLOCATED: {wastage_roll.frontend_id} → Order {allocation['order_id']}")
        
        db.commit()
        return allocated_wastage
    
    def generate_wastage_from_plan(
        self, 
        db: Session, 
        *, 
        plan_id: UUID,
        cut_pattern: List[Dict[str, Any]],
        user_id: UUID
    ) -> List[models.InventoryMaster]:
        """
        Generate wastage inventory from plan execution.
        Creates InventoryMaster entries for 9-21 inch wastage.
        """
        from ..crud.inventory import CRUDInventory
        
        inventory_crud = CRUDInventory(models.InventoryMaster)
        wastage_items = []
        
        # Extract wastage from cut pattern
        for pattern_item in cut_pattern:
            if 'wastage' in pattern_item or 'trim' in pattern_item:
                # Calculate wastage widths from cutting pattern
                trim_left = pattern_item.get('trim_left', 0)
                trim_right = pattern_item.get('trim_right', 0)
                
                for trim_width in [trim_left, trim_right]:
                    if 9 <= trim_width <= 21:  # Only viable wastage
                        wastage_item = {
                            'width_inches': trim_width,
                            'paper_id': pattern_item.get('paper_id'),
                            'source_order_id': pattern_item.get('order_id')
                        }
                        wastage_items.append(wastage_item)
        
        # Create wastage inventory entries
        created_wastage = inventory_crud.create_wastage_rolls_from_plan(
            db,
            plan_id=plan_id,
            wastage_items=wastage_items,
            user_id=user_id
        )
        
        logger.info(f"🔄 WASTAGE GENERATED: Created {len(created_wastage)} wastage rolls from plan {plan_id}")
        return created_wastage
    
    def _check_wastage_allocations_from_wastage_table(
        self,
        db: Session,
        order_requirements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Check available wastage rolls from WastageInventory table that can fulfill order requirements.
        """
        wastage_allocations = []
        
        for order_req in order_requirements:
            paper_id = order_req.get('paper_id')
            width_inches = order_req.get('width_inches')
            
            logger.info(f"🔍 ORDER REQ: Looking for wastage matching Order {order_req.get('order_id')} - "
                       f"Width: {width_inches}\", Paper: {paper_id}")
            
            # Find available wastage rolls for this specification from WastageInventory table
            available_wastage = db.query(models.WastageInventory).filter(
                models.WastageInventory.paper_id == paper_id,
                models.WastageInventory.width_inches == width_inches,
                models.WastageInventory.status == models.WastageStatus.AVAILABLE.value
            ).all()
            
            logger.info(f"🔍 QUERY RESULT: Found {len(available_wastage)} available wastage rolls")
            
            for wastage_roll in available_wastage:
                logger.info(f"🔍 WASTAGE DEBUG: Found wastage roll {wastage_roll.frontend_id} - "
                           f"Width: {wastage_roll.width_inches}\", Paper: {wastage_roll.paper_id}, "
                           f"Weight: {wastage_roll.weight_kg}kg, Status: {wastage_roll.status}")
                
                allocation = {
                    'wastage_id': wastage_roll.id,
                    'wastage_frontend_id': wastage_roll.frontend_id,
                    'order_id': order_req.get('order_id'),
                    'order_item_id': order_req.get('order_item_id'),
                    'paper_id': paper_id,
                    'width_inches': width_inches,
                    'weight_kg': wastage_roll.weight_kg,
                    'source_plan_id': wastage_roll.source_plan_id
                }
                wastage_allocations.append(allocation)
                logger.info(f"✅ WASTAGE MATCH: Allocated {wastage_roll.frontend_id} to order {order_req.get('order_id')}")
                
                # Only one wastage roll per order requirement for now
                break
        
        logger.info(f"🔄 WASTAGE ALLOCATION: Found {len(wastage_allocations)} potential wastage matches")
        return wastage_allocations
    
    def allocate_wastage_from_wastage_table(
        self,
        db: Session,
        *,
        wastage_allocations: List[Dict[str, Any]],
        user_id: UUID
    ) -> List[models.WastageInventory]:
        """
        Allocate available wastage rolls from WastageInventory table to orders.
        """
        allocated_wastage = []
        
        for allocation in wastage_allocations:
            # Find and update the wastage roll status
            wastage_roll = db.query(models.WastageInventory).filter(
                models.WastageInventory.id == allocation['wastage_id']
            ).first()
            
            if wastage_roll and wastage_roll.status == models.WastageStatus.AVAILABLE.value:
                # Mark wastage as used
                wastage_roll.status = models.WastageStatus.USED.value
                allocated_wastage.append(wastage_roll)
                
                # Update order item fulfillment
                order_item = db.query(models.OrderItem).filter(
                    models.OrderItem.id == allocation['order_item_id']
                ).first()
                
                if order_item:
                    order_item.quantity_fulfilled += 1
                    logger.info(f"🔄 WASTAGE ALLOCATED: {wastage_roll.frontend_id} → Order {allocation['order_id']}")
        
        db.commit()
        return allocated_wastage
    
    def _convert_wastage_allocations_to_cut_rolls(
        self,
        db: Session,
        wastage_allocations: List[Dict[str, Any]],
        plan_id: UUID,
        user_id: UUID
    ) -> List[models.InventoryMaster]:
        """
        Convert pre-calculated wastage allocations to InventoryMaster entries with is_wastage_roll=1.
        This creates the cut roll entries for wastage that was allocated during planning.
        """
        logger = logging.getLogger(__name__)
        created_cut_rolls = []
        
        for allocation in wastage_allocations:
            try:
                # Handle UUID conversion for wastage_id
                wastage_id = allocation['wastage_id']
                if isinstance(wastage_id, str):
                    from uuid import UUID
                    wastage_id = UUID(wastage_id)

                # Handle UUID conversion for order_id
                order_id = allocation['order_id']
                if isinstance(order_id, str):
                    from uuid import UUID
                    order_id = UUID(order_id)

                # Handle UUID conversion for order_item_id
                order_item_id = allocation['order_item_id']
                if isinstance(order_item_id, str):
                    from uuid import UUID
                    order_item_id = UUID(order_item_id)
                
                # Get the original wastage roll from WastageInventory
                wastage_roll = db.query(models.WastageInventory).filter(
                    models.WastageInventory.id == wastage_id
                ).first()
                
                if not wastage_roll:
                    logger.warning(f"❌ WASTAGE CONVERSION: Wastage roll {wastage_id} not found")
                    continue
                
                if wastage_roll.status != models.WastageStatus.AVAILABLE.value:
                    logger.warning(f"❌ WASTAGE CONVERSION: Wastage roll {wastage_roll.frontend_id} not available (status: {wastage_roll.status})")
                    continue
                
                # Create InventoryMaster entry for this wastage roll
                cut_roll = models.InventoryMaster(
                    paper_id=wastage_roll.paper_id,
                    width_inches=wastage_roll.width_inches,
                    weight_kg=wastage_roll.weight_kg,
                    roll_type="cut",
                    status="available",
                    allocated_to_order_id=order_id,
                    is_wastage_roll=True,  # Mark as wastage roll
                    wastage_source_order_id=order_id,  # Link to order that will use this wastage
                    wastage_source_plan_id=plan_id,  # Link to current plan
                    qr_code=f"WCR_{wastage_roll.frontend_id}_{plan_id}",
                    barcode_id=self._generate_scr_barcode(db),
                    location="PRODUCTION",
                    created_by_id=user_id
                )
                logger.info(f" WASTAGE : Creating cut roll {cut_roll}")
                
                db.add(cut_roll)
                db.flush()  # Get the cut roll ID
                
                # Mark original wastage as used
                wastage_roll.status = models.WastageStatus.USED.value
                
                # Create plan-inventory link
                plan_inventory_link = models.PlanInventoryLink(
                    plan_id=plan_id,
                    inventory_id=cut_roll.id,
                    quantity_used=1.0
                )
                db.add(plan_inventory_link)
                
                # Update order item fulfillment
                order_item = db.query(models.OrderItem).filter(
                    models.OrderItem.id == order_item_id
                ).first()
                
                if order_item:
                    # Update quantity_fulfilled (remaining_quantity is calculated automatically)
                    wastage_weight = float(wastage_roll.weight_kg) if wastage_roll.weight_kg else 0
                    order_item.quantity_fulfilled += 1
                    # Note: remaining_quantity is a calculated property (quantity_rolls - quantity_fulfilled)
                    
                    logger.info(f"✅ WASTAGE CONVERTED: {wastage_roll.frontend_id} → {cut_roll.frontend_id} "
                               f"({wastage_weight}kg) for order {order_id}")
                
                created_cut_rolls.append(cut_roll)
                
            except Exception as e:
                logger.error(f"❌ WASTAGE CONVERSION ERROR: {e} for allocation {allocation}")
                continue
        
        db.commit()
        logger.info(f"🔄 WASTAGE CONVERSION COMPLETE: Created {len(created_cut_rolls)} cut rolls from wastage")
        return created_cut_rolls

    def _generate_scr_barcode(self, db: Session) -> str:
        """Generate SCR barcode for scrap cut rolls from wastage"""
        return BarcodeGenerator.generate_scrap_cut_roll_barcode(db)

    def _process_added_rolls_early(
        self,
        db: Session,
        request_data: Dict[str, Any],
        selected_cut_rolls: List[Dict]
    ) -> List[Dict]:
        """
        Process added rolls EARLY to create single Gupta order with multiple order items.
        """
        import uuid
        from collections import defaultdict
        from ..services.id_generator import FrontendIDGenerator

        # Extract added rolls from selected_cut_rolls
        added_rolls = [roll for roll in selected_cut_rolls if roll.get('source_type') == 'added_completion']

        if not added_rolls:
            return []

        logger.info(f"➕ EARLY ADDED ROLLS: Processing {len(added_rolls)} added rolls")

        # Find or create Gupta Publishing House client
        gupta_client = db.query(models.ClientMaster).filter(
            models.ClientMaster.company_name == "Gupta Publishing House"
        ).first()

        if not gupta_client:
            gupta_client = models.ClientMaster(
                id=uuid.uuid4(),
                frontend_id="CL-GUPTA-001",
                company_name="Gupta Publishing House",
                email="orders@guptapublishing.com",
                contact_person="Gupta Orders",
                phone="1234567890",
                created_by_id=uuid.UUID(request_data.get("created_by_id")) if request_data.get("created_by_id") else uuid.uuid4(),
                status="active"
            )
            db.add(gupta_client)
            db.flush()

        # Create single Gupta order
        new_order_id = str(uuid.uuid4())
        new_frontend_id = FrontendIDGenerator.generate_frontend_id("order_master", db)

        new_order = models.OrderMaster(
            id=uuid.UUID(new_order_id),
            frontend_id=new_frontend_id,
            client_id=gupta_client.id,
            status="in_process",
            priority="normal",
            payment_type="bill",
            created_by_id=uuid.UUID(request_data.get("created_by_id")) if request_data.get("created_by_id") else None
        )
        db.add(new_order)
        db.flush()

        logger.info(f"✅ EARLY ADDED ROLLS: Created order {new_order.frontend_id}")

        # Group rolls by (gsm, bf, shade, width) for order items
        item_groups = defaultdict(int)
        for roll in added_rolls:
            gsm = roll.get('gsm')
            bf = roll.get('bf')
            shade = roll.get('shade')
            width = roll.get('width_inches')
            key = (gsm, bf, shade, width)
            item_groups[key] += 1

        # Create order items for each unique paper spec + width combination
        order_items_created = []
        for (gsm, bf, shade, width), quantity in item_groups.items():
            # Find paper record
            paper_record = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == gsm,
                models.PaperMaster.bf == bf,
                models.PaperMaster.shade == shade
            ).first()

            if not paper_record:
                logger.error(f"❌ No paper found for GSM={gsm}, BF={bf}, Shade={shade}")
                continue

            order_item_frontend_id = FrontendIDGenerator.generate_frontend_id("order_item", db)

            order_item = models.OrderItem(
                id=uuid.uuid4(),
                frontend_id=order_item_frontend_id,
                order_id=new_order.id,
                paper_id=paper_record.id,
                width_inches=width,
                quantity_rolls=quantity,
                quantity_kg=quantity * 100.0,  # Estimate weight
                quantity_fulfilled=0,
                rate=50.0,
                amount=quantity * 50.0,
                item_status="pending"
            )
            db.add(order_item)
            order_items_created.append(order_item)

        db.flush()
        logger.info(f"✅ EARLY ADDED ROLLS: Created {len(order_items_created)} order items")

        # Return single order result
        return [{
            "order": {
                "id": str(new_order.id),
                "frontend_id": new_order.frontend_id,
                "client_name": gupta_client.company_name
            }
        }]

    def create_manual_plan_with_inventory(
        self,
        db: Session,
        *,
        manual_plan_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a manual plan with inventory hierarchy.

        This creates:
        - PlanMaster record with type="manual"
        - InventoryMaster hierarchy: Jumbo → 118" Rolls → Cut Rolls
        - PlanInventoryLink entries
        - Uses proper ID generators and barcode generators
        """
        import uuid
        import json
        from ..services.id_generator import FrontendIDGenerator

        logger.info("🔧 MANUAL PLAN: Starting manual plan creation")

        # Extract data
        wastage = manual_plan_data.get("wastage", 1)
        planning_width = manual_plan_data.get("planning_width", 123)
        created_by_id = manual_plan_data.get("created_by_id")
        paper_specs = manual_plan_data.get("paper_specs", [])

        # Create PlanMaster record with temporary cut_pattern
        plan_name = f"Manual Plan - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
        db_plan = models.PlanMaster(
            name=plan_name,
            cut_pattern=json.dumps([]),  # Temporary, will be updated
            expected_waste_percentage=0.0,
            status="in_progress",  # Manual plans are immediately in progress
            created_by_id=uuid.UUID(created_by_id) if isinstance(created_by_id, str) else created_by_id
        )
        db.add(db_plan)
        db.flush()

        logger.info(f"✅ MANUAL PLAN: Created plan {db_plan.frontend_id}")

        # Track created inventory and cut pattern data
        created_jumbo_rolls = []
        created_118_rolls = []
        created_cut_rolls = []
        cut_rolls_generated = []  # For cut_pattern
        jumbo_roll_details = []  # For cut_pattern
        total_wastage_inches = 0  # Track total wastage

        # Process each paper specification
        for paper_spec in paper_specs:
            gsm = paper_spec.get("gsm")
            bf = paper_spec.get("bf")
            shade = paper_spec.get("shade")

            # Find paper record
            paper_record = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == gsm,
                models.PaperMaster.bf == bf,
                models.PaperMaster.shade == shade
            ).first()

            if not paper_record:
                logger.warning(f"❌ MANUAL PLAN: Paper not found - GSM={gsm}, BF={bf}, Shade={shade}")
                continue

            # Process each jumbo roll
            for jumbo_data in paper_spec.get("jumbo_rolls", []):
                jumbo_number = jumbo_data.get("jumbo_number")

                # Create Jumbo Roll in InventoryMaster
                jumbo_qr = f"MANUAL_JUMBO_{uuid.uuid4().hex[:8].upper()}"
                jumbo_barcode = BarcodeGenerator.generate_jumbo_roll_barcode(db)

                jumbo_roll = models.InventoryMaster(
                    paper_id=paper_record.id,
                    width_inches=planning_width,
                    weight_kg=0,
                    roll_type="jumbo",
                    status="consumed",
                    qr_code=jumbo_qr,
                    barcode_id=jumbo_barcode,
                    location="MANUAL",
                    created_by_id=uuid.UUID(created_by_id) if isinstance(created_by_id, str) else created_by_id
                )
                db.add(jumbo_roll)
                db.flush()
                created_jumbo_rolls.append(jumbo_roll)

                logger.info(f"📦 MANUAL PLAN: Created Jumbo {jumbo_roll.frontend_id} - {gsm}gsm {shade}")

                # Track jumbo details for cut_pattern
                jumbo_detail = {
                    "jumbo_id": str(jumbo_roll.id),
                    "jumbo_barcode": jumbo_barcode,
                    "paper_spec": f"{gsm}gsm, {bf}bf, {shade}",
                    "width_inches": planning_width,
                    "sets": [],
                    "total_wastage": 0
                }

                # Process each roll set (118" rolls)
                for roll_set_data in jumbo_data.get("roll_sets", []):
                    set_number = roll_set_data.get("set_number")

                    # Create 118" Roll in InventoryMaster
                    roll_118_qr = f"MANUAL_118_{uuid.uuid4().hex[:8].upper()}"
                    roll_118_barcode = BarcodeGenerator.generate_118_roll_barcode(db)

                    roll_118 = models.InventoryMaster(
                        paper_id=paper_record.id,
                        width_inches=planning_width,
                        weight_kg=0,
                        roll_type="118",
                        status="consumed",
                        qr_code=roll_118_qr,
                        barcode_id=roll_118_barcode,
                        location="MANUAL",
                        parent_jumbo_id=jumbo_roll.id,
                        roll_sequence=set_number,
                        created_by_id=uuid.UUID(created_by_id) if isinstance(created_by_id, str) else created_by_id
                    )
                    db.add(roll_118)
                    db.flush()
                    created_118_rolls.append(roll_118)

                    logger.info(f"  📦 MANUAL PLAN: Created 118\" Roll {roll_118.frontend_id} (Set #{set_number})")

                    # Track set data for cut_pattern
                    set_detail = {
                        "set_number": set_number,
                        "roll_118_id": str(roll_118.id),
                        "roll_118_barcode": roll_118_barcode,
                        "cuts": [],
                        "total_width_used": 0,
                        "wastage_inches": 0
                    }

                    # Process each cut roll
                    for cut_roll_data in roll_set_data.get("cut_rolls", []):
                        width_inches = cut_roll_data.get("width_inches")
                        quantity = cut_roll_data.get("quantity", 1)
                        client_name = cut_roll_data.get("client_name")
                        order_source = cut_roll_data.get("order_source", "Manual")

                        # Find or create client
                        manual_client_id = None
                        if client_name:
                            client = db.query(models.ClientMaster).filter(
                                models.ClientMaster.company_name == client_name
                            ).first()

                            if not client:
                                # Create new client
                                client_frontend_id = FrontendIDGenerator.generate_frontend_id("client_master", db)
                                client = models.ClientMaster(
                                    id=uuid.uuid4(),
                                    frontend_id=client_frontend_id,
                                    company_name=client_name,
                                    email=f"{client_name.lower().replace(' ', '_')}@manual.com",
                                    contact_person="Manual Entry",
                                    phone="0000000000",
                                    status="active",
                                    created_by_id=uuid.UUID(created_by_id) if isinstance(created_by_id, str) else created_by_id
                                )
                                db.add(client)
                                db.flush()
                                logger.info(f"  ✅ MANUAL PLAN: Created client {client.frontend_id} - {client_name}")

                            manual_client_id = client.id

                        # Track width used in this set
                        set_detail["total_width_used"] += width_inches * quantity

                        # Create cut rolls based on quantity
                        for q in range(quantity):
                            cut_roll_qr = f"MANUAL_CUT_{uuid.uuid4().hex[:8].upper()}"
                            cut_roll_barcode = BarcodeGenerator.generate_cut_roll_barcode(db)

                            cut_roll = models.InventoryMaster(
                                paper_id=paper_record.id,
                                width_inches=width_inches,
                                weight_kg=0,
                                roll_type="cut",
                                status="cutting",
                                qr_code=cut_roll_qr,
                                barcode_id=cut_roll_barcode,
                                location="PRODUCTION",
                                parent_118_roll_id=roll_118.id,
                                allocated_to_order_id=None,  # Manual plans don't have orders
                                manual_client_id=manual_client_id,  # Store client directly
                                created_by_id=uuid.UUID(created_by_id) if isinstance(created_by_id, str) else created_by_id
                            )
                            db.add(cut_roll)
                            db.flush()
                            created_cut_rolls.append(cut_roll)

                            # Create plan-inventory link
                            plan_inventory_link = models.PlanInventoryLink(
                                plan_id=db_plan.id,
                                inventory_id=cut_roll.id,
                                quantity_used=1.0
                            )
                            db.add(plan_inventory_link)

                            logger.info(f"    📦 MANUAL PLAN: Created Cut Roll {cut_roll.frontend_id} - {width_inches}\" for {client_name}")

                            # Add to cut_rolls_generated for cut_pattern
                            cut_rolls_generated.append({
                                "cut_roll_id": str(cut_roll.id),
                                "barcode": cut_roll_barcode,
                                "width_inches": width_inches,
                                "client_name": client_name,
                                "order_source": order_source,
                                "paper_spec": f"{gsm}gsm, {bf}bf, {shade}",
                                "parent_jumbo_barcode": jumbo_barcode,
                                "parent_118_barcode": roll_118_barcode,
                                "status": "cutting"
                            })

                        # Add cut detail to set
                        set_detail["cuts"].append({
                            "width_inches": width_inches,
                            "quantity": quantity,
                            "client_name": client_name,
                            "order_source": order_source
                        })

                    # Calculate wastage for this set
                    set_detail["wastage_inches"] = planning_width - set_detail["total_width_used"]
                    jumbo_detail["total_wastage"] += set_detail["wastage_inches"]
                    total_wastage_inches += set_detail["wastage_inches"]

                    # Add set to jumbo
                    jumbo_detail["sets"].append(set_detail)

                # Add jumbo to jumbo_roll_details
                jumbo_roll_details.append(jumbo_detail)

        # Calculate summary metrics
        total_cut_rolls = len(created_cut_rolls)
        total_width_used = sum(detail["total_width_used"] for detail in jumbo_roll_details for detail in detail["sets"])
        overall_waste_percentage = (total_wastage_inches / (total_width_used + total_wastage_inches) * 100) if (total_width_used + total_wastage_inches) > 0 else 0

        # Update plan with complete cut_pattern matching regular planning structure
        db_plan.cut_pattern = json.dumps(cut_rolls_generated)
        db_plan.expected_waste_percentage = round(overall_waste_percentage, 2)

        # Commit all changes
        db.commit()
        db.refresh(db_plan)

        # Build response hierarchy
        production_hierarchy = []

        for jumbo in created_jumbo_rolls:
            # Find 118" rolls for this jumbo
            rolls_118_for_jumbo = [r for r in created_118_rolls if r.parent_jumbo_id == jumbo.id]

            intermediate_rolls = []
            all_cuts_for_jumbo = []

            for roll_118 in rolls_118_for_jumbo:
                # Find cut rolls for this 118" roll
                cuts_for_118 = [c for c in created_cut_rolls if c.parent_118_roll_id == roll_118.id]

                intermediate_rolls.append({
                    "id": str(roll_118.id),
                    "frontend_id": roll_118.frontend_id,
                    "barcode_id": roll_118.barcode_id,
                    "width_inches": float(roll_118.width_inches),
                    "roll_sequence": roll_118.roll_sequence,
                    "paper_spec": f"{roll_118.paper.gsm}gsm, {roll_118.paper.bf}bf, {roll_118.paper.shade}"
                })

                for cut in cuts_for_118:
                    client_name = "Unknown"
                    if cut.manual_client_id:
                        client = db.query(models.ClientMaster).filter(
                            models.ClientMaster.id == cut.manual_client_id
                        ).first()
                        if client:
                            client_name = client.company_name

                    all_cuts_for_jumbo.append({
                        "id": str(cut.id),
                        "frontend_id": cut.frontend_id,
                        "barcode_id": cut.barcode_id,
                        "width_inches": float(cut.width_inches),
                        "client_name": client_name,
                        "parent_118_barcode": roll_118.barcode_id,
                        "paper_spec": f"{cut.paper.gsm}gsm, {cut.paper.bf}bf, {cut.paper.shade}",
                        "status": cut.status
                    })

            production_hierarchy.append({
                "jumbo_roll": {
                    "id": str(jumbo.id),
                    "frontend_id": jumbo.frontend_id,
                    "barcode_id": jumbo.barcode_id,
                    "width_inches": float(jumbo.width_inches),
                    "paper_spec": f"{jumbo.paper.gsm}gsm, {jumbo.paper.bf}bf, {jumbo.paper.shade}",
                    "status": jumbo.status,
                    "location": jumbo.location
                },
                "intermediate_rolls": intermediate_rolls,
                "cut_rolls": all_cuts_for_jumbo
            })

        logger.info(f"✅ MANUAL PLAN: Complete - {len(created_jumbo_rolls)} jumbos, {len(created_118_rolls)} 118\" rolls, {len(created_cut_rolls)} cut rolls")

        return {
            "plan_id": str(db_plan.id),
            "plan_frontend_id": db_plan.frontend_id,
            "status": db_plan.status,
            "summary": {
                "jumbo_rolls_created": len(created_jumbo_rolls),
                "intermediate_118_rolls_created": len(created_118_rolls),
                "cut_rolls_created": len(created_cut_rolls),
                "wastage": wastage,
                "planning_width": planning_width
            },
            "production_hierarchy": production_hierarchy,
            "message": f"Manual plan created successfully - {len(created_jumbo_rolls)} jumbo rolls with {len(created_cut_rolls)} cut rolls"
        }

# ============================================================================
# HYBRID PLANNING - Combines auto-generated and manual planning
# ============================================================================

def create_hybrid_production(db: Session, hybrid_data: dict):
    """
    Create production from hybrid planning (algorithm + manual rolls).

    Combines algorithm-generated and manual rolls with set-level selection.
    """
    import uuid
    from datetime import datetime
    from .. import models

    logger.info("🏭 HYBRID PRODUCTION: Starting")

    try:
        wastage = hybrid_data.get('wastage')
        planning_width = hybrid_data.get('planning_width')
        created_by_id = uuid.UUID(hybrid_data.get('created_by_id'))
        order_ids = [uuid.UUID(oid) for oid in hybrid_data.get('order_ids', [])]
        paper_specs = hybrid_data.get('paper_specs', [])
        orphaned_rolls = hybrid_data.get('orphaned_rolls', [])
        pending_orders_data = hybrid_data.get('pending_orders', [])

        # Count selected cuts
        total_cuts = sum(
            len(roll_set['cuts'])
            for spec in paper_specs
            for jumbo in spec['jumbos']
            for roll_set in jumbo['sets']
            if roll_set.get('is_selected', True)
        )

        logger.info(f"   - Width: {planning_width}\", Cuts: {total_cuts}, Orphans: {len(orphaned_rolls)}")

        # Calculate expected waste percentage efficiently
        # Get all selected sets across all specs and jumbos
        selected_sets = [
            roll_set
            for spec in paper_specs
            for jumbo in spec['jumbos']
            for roll_set in jumbo['sets']
            if roll_set.get('is_selected', True)
        ]

        # Calculate total width used across all selected sets
        total_width_used = sum(
            cut['width_inches'] * cut.get('quantity', 1)
            for roll_set in selected_sets
            for cut in roll_set.get('cuts', [])
        )

        # Total available width = planning_width * number of selected sets
        total_available_width = len(selected_sets) * planning_width

        # Calculate waste percentage: (total waste / total available width) * 100
        # Ensure it's non-negative (0 if over-capacity)
        expected_waste_percentage = (
            max(0, ((total_available_width - total_width_used) / total_available_width) * 100)
            if total_available_width > 0 else 0
        )

        logger.info(f"📊 WASTE CALCULATION: Used {total_width_used}\" / {total_available_width}\" = {expected_waste_percentage:.2f}% waste")

        # Create plan
        plan_name = f"Hybrid Plan - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
        plan = models.PlanMaster(
            name=plan_name,
            cut_pattern=[],
            wastage_allocations=hybrid_data.get('wastage_allocations', []),
            expected_waste_percentage=expected_waste_percentage,
            created_by_id=created_by_id,
            status="in_progress"
        )
        db.add(plan)
        db.flush()

        # Counters
        jumbos_created = 0
        cut_rolls_created = 0
        orders_updated = set()
        production_hierarchy = []
        roll_counter = 0
        created_cut_rolls = []  # Track cut roll inventory items for pending resolution

        # Process paper specs
        for spec in paper_specs:
            gsm, bf, shade = spec['gsm'], spec['bf'], spec['shade']

            # Get paper master record
            paper = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == gsm,
                models.PaperMaster.bf == bf,
                models.PaperMaster.shade == shade
            ).first()

            if not paper:
                raise ValueError(f"Paper not found: GSM={gsm}, BF={bf}, Shade={shade}")

            for jumbo in spec['jumbos']:
                # Skip if no selected sets
                selected_sets = [s for s in jumbo['sets'] if s.get('is_selected', True)]
                if not selected_sets:
                    continue

                # Create jumbo (124")
                jumbo_barcode = BarcodeGenerator.generate_jumbo_roll_barcode(db)
                jumbo_roll = models.InventoryMaster(
                    width_inches=124,
                    paper_id=paper.id,
                    weight_kg=0,  # Will be updated during production
                    roll_type="jumbo",
                    status="cutting",
                    barcode_id=jumbo_barcode,
                    qr_code=jumbo_barcode,  # Use same as barcode_id
                    created_by_id=created_by_id
                )
                db.add(jumbo_roll)
                db.flush()

                # Link jumbo to plan
                db.add(models.PlanInventoryLink(
                    plan_id=plan.id,
                    inventory_id=jumbo_roll.id,
                    quantity_used=1.0
                ))

                jumbos_created += 1

                jumbo_details = {
                    'jumbo_roll': {
                        'barcode_id': jumbo_roll.barcode_id,
                        'gsm': gsm,
                        'bf': bf,
                        'shade': shade,
                        'paper_id': str(paper.id),
                        'paper_spec': f"{gsm}gsm, {bf}bf, {shade}"
                    },
                    'cut_rolls': []
                }

                # Create intermediate rolls only for sets that exist in payload
                for roll_set in jumbo['sets']:
                    set_num = roll_set['set_number']

                    # Skip unselected sets
                    if not roll_set.get('is_selected', True):
                        continue

                    # Only generate barcode and create 118" roll if set has cuts
                    set_barcode = BarcodeGenerator.generate_118_roll_barcode(db)
                    inter = models.InventoryMaster(
                        width_inches=planning_width,
                        paper_id=paper.id,
                        weight_kg=0,
                        roll_type="118",
                        status="cutting",
                        barcode_id=set_barcode,
                        qr_code=set_barcode,  # Use same as barcode_id
                        parent_jumbo_id=jumbo_roll.id,
                        roll_sequence=set_num,
                        created_by_id=created_by_id
                    )
                    db.add(inter)
                    db.flush()

                    # Link 118" roll to plan
                    db.add(models.PlanInventoryLink(
                        plan_id=plan.id,
                        inventory_id=inter.id,
                        quantity_used=1.0
                    ))

                    # Create cut rolls
                    for cut in roll_set['cuts']:
                        cut_barcode = BarcodeGenerator.generate_cut_roll_barcode(db)

                        # Determine status: "available" for wastage, "cutting" otherwise
                        is_wastage = cut.get('is_wastage', False)
                        cut_status = "available" if is_wastage else "cutting"

                        # Determine allocated_to_order_id and manual_client_id
                        allocated_order_id = None
                        manual_client_id = None

                        if cut['source'] == 'manual':
                            # Manual rolls: find or create client
                            client_name = cut.get('client_name') or cut.get('clientName')
                            if client_name:
                                client = db.query(models.ClientMaster).filter(
                                    models.ClientMaster.company_name == client_name
                                ).first()
                                if client:
                                    manual_client_id = client.id
                        else:
                            # Algorithm rolls: allocate to order
                            if cut.get('order_id'):
                                try:
                                    allocated_order_id = uuid.UUID(cut['order_id'])
                                except:
                                    pass

                        # Validate source_pending_id
                        source_pending_id_val = None
                        if cut.get('source_pending_id'):
                            try:
                                pending_uuid = uuid.UUID(cut['source_pending_id'])
                                # Check if the pending order item actually exists
                                pending_exists = db.query(models.PendingOrderItem).filter(
                                    models.PendingOrderItem.id == pending_uuid
                                ).first()
                                if pending_exists:
                                    source_pending_id_val = pending_uuid
                                else:
                                    logger.warning(f"⚠️ PENDING VALIDATION: Pending order {pending_uuid} not found, setting to None")
                            except (ValueError, AttributeError):
                                logger.warning(f"⚠️ PENDING VALIDATION: Invalid UUID format for pending_id: {cut.get('source_pending_id')}")

                        cut_roll = models.InventoryMaster(
                            width_inches=cut['width_inches'],
                            paper_id=paper.id,
                            weight_kg=0,
                            roll_type="cut",
                            status=cut_status,
                            barcode_id=cut_barcode,
                            qr_code=cut_barcode,  # Use same as barcode_id
                            parent_118_roll_id=inter.id,
                            parent_jumbo_id=jumbo_roll.id,
                            created_by_id=created_by_id,
                            allocated_to_order_id=allocated_order_id,
                            manual_client_id=manual_client_id,
                            source_type=cut.get('source_type') or ('manual' if cut['source'] == 'manual' else 'regular_order'),
                            source_pending_id=source_pending_id_val,
                            is_wastage_roll=is_wastage
                        )
                        db.add(cut_roll)
                        db.flush()

                        created_cut_rolls.append(cut_roll)

                        # Link cut roll to plan
                        db.add(models.PlanInventoryLink(
                            plan_id=plan.id,
                            inventory_id=cut_roll.id,
                            quantity_used=cut.get('quantity', 1)
                        ))

                        cut_rolls_created += 1
                        roll_counter += 1

                        jumbo_details['cut_rolls'].append({
                            'barcode_id': cut_roll.barcode_id,
                            'width_inches': cut['width_inches'],
                            'client_name': cut.get('client_name') or cut.get('clientName', 'N/A'),
                            'status': cut_roll.status,
                            'gsm': gsm,
                            'bf': bf,
                            'shade': shade,
                            'paper_id': str(paper.id),
                            'source_type': cut_roll.source_type
                        })

                        # Link to order if from algorithm
                        if cut['source'] == 'algorithm' and cut.get('order_id'):
                            try:
                                oid = uuid.UUID(cut['order_id'])
                                orders_updated.add(str(oid))

                                items = db.query(models.OrderItem).filter(
                                    models.OrderItem.order_id == oid,
                                    models.OrderItem.width_inches == cut['width_inches']
                                ).all()

                                if items:
                                    order_item = items[0]

                                    # Only increment quantity_fulfilled for wastage/stock allocated rolls
                                    if is_wastage:
                                        order_item.quantity_fulfilled = (order_item.quantity_fulfilled or 0) + 1
                                        order_item.item_status = 'in_warehouse'
                                    # For newly generated rolls, just update status to in_process
                                    else:
                                        if order_item.item_status == 'created':
                                            order_item.item_status = 'in_process'

                                    # Create plan-order link with order_item_id
                                    existing_link = db.query(models.PlanOrderLink).filter(
                                        models.PlanOrderLink.plan_id == plan.id,
                                        models.PlanOrderLink.order_id == oid,
                                        models.PlanOrderLink.order_item_id == order_item.id
                                    ).first()

                                    if not existing_link:
                                        db.add(models.PlanOrderLink(
                                            plan_id=plan.id,
                                            order_id=oid,
                                            order_item_id=order_item.id,
                                            quantity_allocated=1  # Always 1 since we split by quantity
                                        ))

                                    order = db.query(models.OrderMaster).get(oid)
                                    if order:
                                        order.status = 'in_process'
                            except Exception as e:
                                logger.warning(f"Failed to link order {cut.get('order_id')}: {e}")
                                pass

                    # NEW WASTAGE INVENTORY: Calculate trim off-cut for this set
                    # Exclude is_wastage cuts (stock rolls) from width sum — they are pre-existing material
                    set_width_used = sum(
                        float(cut['width_inches']) * int(cut.get('quantity', 1))
                        for cut in roll_set['cuts']
                        if not cut.get('is_wastage', False)
                    )
                    trim = float(planning_width) - set_width_used
                    if 9 <= trim <= 21:
                        try:
                            wastage_barcode = BarcodeGenerator.generate_wastage_barcode(db)
                            db.add(models.WastageInventory(
                                width_inches=trim,
                                paper_id=paper.id,
                                weight_kg=0.0,
                                source_plan_id=plan.id,
                                source_jumbo_roll_id=jumbo_roll.id,
                                status=models.WastageStatus.AVAILABLE.value,
                                location="WASTE_STORAGE",
                                barcode_id=wastage_barcode,
                                created_by_id=created_by_id
                            ))
                            logger.info(f"🗑️ HYBRID WASTAGE NEW: {trim}\" trim from set {set_num} → WastageInventory")
                        except Exception as e:
                            logger.warning(f"❌ HYBRID WASTAGE NEW: Failed creating trim wastage for set {set_num}: {e}")

                production_hierarchy.append(jumbo_details)

        # PHASE 1: Resolve consumed pending order items
        # For each cut roll that came from an existing PendingOrderItem (source_pending_id set),
        # decrement its quantity_pending / increment quantity_fulfilled, update status and
        # decrement the originating OrderItem.quantity_in_pending.
        try:
            from collections import defaultdict
            from sqlalchemy import and_

            pending_order_cut_roll_counts = defaultdict(int)

            logger.info("📊 HYBRID PHASE 1: Counting cut rolls per pending order")

            for cut_roll_item in created_cut_rolls:
                if cut_roll_item.source_type == 'pending_order' and cut_roll_item.source_pending_id:
                    pending_order_cut_roll_counts[str(cut_roll_item.source_pending_id)] += 1

            logger.info(f"📊 HYBRID PHASE 1: Found {len(pending_order_cut_roll_counts)} unique pending orders consumed")

            for pending_id_str, cut_rolls_count in pending_order_cut_roll_counts.items():
                try:
                    pending_uuid = uuid.UUID(pending_id_str)

                    pending_order = db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.id == pending_uuid,
                        models.PendingOrderItem._status == "pending"
                    ).first()

                    if not pending_order:
                        logger.warning(f"❌ HYBRID PHASE 1: Pending order {pending_id_str[:8]}... not found or not 'pending'")
                        continue

                    old_fulfilled = getattr(pending_order, 'quantity_fulfilled', 0) or 0
                    old_pending = pending_order.quantity_pending

                    cut_rolls_to_resolve = min(cut_rolls_count, old_pending)
                    new_fulfilled = old_fulfilled + cut_rolls_to_resolve
                    new_pending = max(0, old_pending - cut_rolls_to_resolve)

                    pending_order.quantity_fulfilled = new_fulfilled
                    pending_order.quantity_pending = new_pending

                    logger.info(f"📊 HYBRID PHASE 1: {pending_order.frontend_id} → fulfilled {old_fulfilled}→{new_fulfilled}, pending {old_pending}→{new_pending}")

                    if new_pending == 0:
                        status_ok = pending_order.mark_as_included_in_plan(db, resolved_by_production=True)
                        if status_ok:
                            logger.info(f"✅ HYBRID PHASE 1: {pending_order.frontend_id} marked as 'included_in_plan'")
                        else:
                            logger.warning(f"❌ HYBRID PHASE 1: Could not mark {pending_order.frontend_id} as included_in_plan")
                    else:
                        logger.info(f"⚠️ HYBRID PHASE 1: {pending_order.frontend_id} partially resolved, {new_pending} still pending")

                    # Decrement quantity_in_pending on the originating OrderItem
                    original_order_item = db.query(models.OrderItem).filter(
                        models.OrderItem.order_id == pending_order.original_order_id,
                        models.OrderItem.width_inches == pending_order.width_inches,
                        models.OrderItem.paper.has(
                            and_(
                                models.PaperMaster.gsm == pending_order.gsm,
                                models.PaperMaster.bf == pending_order.bf,
                                models.PaperMaster.shade == pending_order.shade
                            )
                        )
                    ).first()

                    if original_order_item:
                        original_order_item.quantity_in_pending = max(
                            0,
                            (original_order_item.quantity_in_pending or 0) - cut_rolls_to_resolve
                        )
                        logger.info(f"🔄 HYBRID PHASE 1: OrderItem {original_order_item.frontend_id} quantity_in_pending → {original_order_item.quantity_in_pending}")
                    else:
                        logger.error(f"❌ HYBRID PHASE 1: Could not find original OrderItem for pending {pending_order.frontend_id}")

                    db.flush()

                except Exception as e:
                    logger.error(f"❌ HYBRID PHASE 1: Error processing pending order {pending_id_str[:8]}...: {e}")

        except Exception as e:
            logger.warning(f"HYBRID PHASE 1: Pending order resolution failed (non-fatal): {e}")

        # Create pending from orphans (only for those with order_id)
        pending_created = 0
        for orphan in orphaned_rolls:
            # Only create pending items for orphaned rolls that came from orders
            if orphan.get('order_id'):
                try:
                    db.add(models.PendingOrderItem(
                        original_order_id=uuid.UUID(orphan['order_id']),
                        width_inches=orphan['width_inches'],
                        quantity_pending=orphan.get('quantity', 1),
                        gsm=orphan['gsm'],
                        bf=orphan['bf'],
                        shade=orphan['shade'],
                        reason='Orphaned from hybrid plan'
                    ))
                    pending_created += 1
                except Exception as e:
                    logger.warning(f"Failed to create pending item for orphaned roll: {e}")
            else:
                # Orphaned manual rolls (no order_id) are just discarded
                logger.info(f"Discarding orphaned manual roll: {orphan['width_inches']}\" (no order_id)")

        # BLOCK 2: Create pending order items for deferred/unfulfilled rolls
        try:
            from ..services.id_generator import FrontendIDGenerator

            # Case (a): Deselected sets — algorithm cuts whose sets the user did not select
            for spec in paper_specs:
                gsm, bf, shade = spec['gsm'], spec['bf'], spec['shade']
                for jumbo in spec['jumbos']:
                    for roll_set in jumbo['sets']:
                        if roll_set.get('is_selected', True):
                            continue  # Only process deselected sets
                        for cut in roll_set.get('cuts', []):
                            if cut.get('source') != 'algorithm':
                                continue
                            if not cut.get('order_id'):
                                continue
                            if cut.get('source_type') == 'pending_order':
                                # Already an existing pending item — don't duplicate
                                continue
                            try:
                                oid = uuid.UUID(cut['order_id'])
                                frontend_id = FrontendIDGenerator.generate_frontend_id("pending_order_item", db)
                                db.add(models.PendingOrderItem(
                                    frontend_id=frontend_id,
                                    original_order_id=oid,
                                    width_inches=float(cut['width_inches']),
                                    quantity_pending=int(cut.get('quantity', 1)),
                                    gsm=gsm,
                                    bf=float(bf),
                                    shade=shade,
                                    status='pending',
                                    reason='user_deferred_production',
                                    created_by_id=created_by_id
                                ))
                                pending_created += 1
                                logger.info(f"📋 HYBRID BLOCK2a: Deselected set → pending {cut['width_inches']}\" order {str(oid)[:8]}...")
                            except Exception as e:
                                logger.warning(f"❌ HYBRID BLOCK2a: Failed for deselected cut: {e}")

            # Case (b): Algorithm-unfulfilled rolls — orders the algorithm could not fit at all
            for pending_item in pending_orders_data:
                source_order_id = pending_item.get('source_order_id')
                if not source_order_id:
                    logger.warning(f"⚠️ HYBRID BLOCK2b: No source_order_id in pending item, skipping")
                    continue
                try:
                    oid = uuid.UUID(str(source_order_id))
                    frontend_id = FrontendIDGenerator.generate_frontend_id("pending_order_item", db)
                    db.add(models.PendingOrderItem(
                        frontend_id=frontend_id,
                        original_order_id=oid,
                        width_inches=float(pending_item.get('width', 0)),
                        quantity_pending=int(pending_item.get('quantity', 1)),
                        gsm=pending_item.get('gsm'),
                        bf=float(pending_item.get('bf', 0)),
                        shade=pending_item.get('shade', ''),
                        status='pending',
                        reason='insufficient_cutting_efficiency',
                        created_by_id=created_by_id
                    ))
                    pending_created += 1
                    logger.info(f"📋 HYBRID BLOCK2b: Algo-unfulfilled → pending {pending_item.get('width')}\" order {str(oid)[:8]}...")
                except Exception as e:
                    logger.warning(f"❌ HYBRID BLOCK2b: Failed for algo pending item: {e}")

        except Exception as e:
            logger.warning(f"HYBRID BLOCK2: Pending creation failed (non-fatal): {e}")

        # WASTAGE ALLOCATIONS: Mark existing WastageInventory rolls as USED and update OrderItem
        try:
            for allocation in hybrid_data.get('wastage_allocations', []):
                wastage_id_raw = allocation.get('wastage_id')
                if not wastage_id_raw:
                    continue
                try:
                    wastage_uuid = uuid.UUID(str(wastage_id_raw))
                    wastage_roll = db.query(models.WastageInventory).filter(
                        models.WastageInventory.id == wastage_uuid,
                        models.WastageInventory.status == models.WastageStatus.AVAILABLE.value
                    ).first()
                    if not wastage_roll:
                        logger.warning(f"⚠️ HYBRID WASTAGE ALLOC: Roll {wastage_uuid} not found or already used")
                        continue

                    wastage_roll.status = models.WastageStatus.USED.value
                    logger.info(f"✅ HYBRID WASTAGE ALLOC: Marked {wastage_roll.frontend_id} as USED")

                    # Resolve order_id and order_item_id
                    order_id_raw = allocation.get('order_id')
                    order_item_id_raw = allocation.get('order_item_id')
                    alloc_order_id = uuid.UUID(str(order_id_raw)) if order_id_raw else None
                    alloc_order_item_id = uuid.UUID(str(order_item_id_raw)) if order_item_id_raw else None

                    # Create InventoryMaster cut roll linked to the order
                    scr_barcode = BarcodeGenerator.generate_scrap_cut_roll_barcode(db)
                    wastage_cut_roll = models.InventoryMaster(
                        paper_id=wastage_roll.paper_id,
                        width_inches=wastage_roll.width_inches,
                        weight_kg=wastage_roll.weight_kg,
                        roll_type="cut",
                        status="available",
                        allocated_to_order_id=alloc_order_id,
                        is_wastage_roll=True,
                        wastage_source_order_id=alloc_order_id,
                        wastage_source_plan_id=plan.id,
                        barcode_id=scr_barcode,
                        qr_code=scr_barcode,
                        location="PRODUCTION",
                        created_by_id=created_by_id
                    )
                    db.add(wastage_cut_roll)
                    db.flush()

                    # Link cut roll to plan
                    db.add(models.PlanInventoryLink(
                        plan_id=plan.id,
                        inventory_id=wastage_cut_roll.id,
                        quantity_used=1.0
                    ))

                    # Increment OrderItem.quantity_fulfilled
                    if alloc_order_item_id:
                        order_item = db.query(models.OrderItem).filter(
                            models.OrderItem.id == alloc_order_item_id
                        ).first()
                        if order_item:
                            order_item.quantity_fulfilled = (order_item.quantity_fulfilled or 0) + 1
                            order_item.item_status = 'in_warehouse'
                            logger.info(f"🔄 HYBRID WASTAGE ALLOC: OrderItem {order_item.frontend_id} quantity_fulfilled → {order_item.quantity_fulfilled}")
                        else:
                            logger.warning(f"⚠️ HYBRID WASTAGE ALLOC: OrderItem {alloc_order_item_id} not found")
                    else:
                        logger.warning(f"⚠️ HYBRID WASTAGE ALLOC: No order_item_id in allocation for {wastage_roll.frontend_id}")

                    db.flush()
                except Exception as e:
                    logger.warning(f"❌ HYBRID WASTAGE ALLOC: Failed for wastage_id {wastage_id_raw}: {e}")
        except Exception as e:
            logger.warning(f"HYBRID WASTAGE ALLOC: Failed (non-fatal): {e}")

        db.commit()

        logger.info(f"✅ Created: J={jumbos_created}, CR={cut_rolls_created}, Orders={len(orders_updated)}, Pending={pending_created}")

        return {
            'plan_id': str(plan.id),
            'plan_frontend_id': plan.frontend_id,
            'production_hierarchy': production_hierarchy,
            'summary': {
                'jumbos_created': jumbos_created,
                'cut_rolls_created': cut_rolls_created,
                'orders_updated': len(orders_updated),
                'pending_items_created': pending_created
            }
        }
    except Exception as e:
        logger.error(f"❌ HYBRID: {e}")
        db.rollback()
        raise


plan = CRUDPlan(models.PlanMaster)
