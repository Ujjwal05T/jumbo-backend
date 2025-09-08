from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, desc
from typing import List, Optional, Dict, Any
from uuid import UUID
from collections import defaultdict
import json

from .base import CRUDBase
from .. import models, schemas
from ..services.id_generator import FrontendIDGenerator


class CRUDPendingOrder(CRUDBase[models.PendingOrderItem, schemas.PendingOrderItemCreate, schemas.PendingOrderItemUpdate]):
    def get_pending_order_items(
        self, 
        db: Session, 
        *, 
        skip: int = 0, 
        limit: int = 100, 
        status: str = "pending"
    ) -> List[models.PendingOrderItem]:
        """Get pending order items with filtering - prevents conflicts by excluding already used items"""
        query = (
            db.query(models.PendingOrderItem)
            .options(joinedload(models.PendingOrderItem.original_order).joinedload(models.OrderMaster.client))
            .filter(models.PendingOrderItem._status == status)
        )
        
        # If requesting "pending" items, exclude those already used in active plans
        if status == "pending":
            query = query.filter(
                ~models.PendingOrderItem.id.in_(
                    db.query(models.PendingOrderItem.id)
                    .filter(models.PendingOrderItem._status == "included_in_plan")
                    .subquery()
                )
            )
        
        return (
            query.order_by(desc(models.PendingOrderItem.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )
    
    def get_pending_orders_by_specs(
        self, db: Session, paper_specs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get pending orders grouped by paper specifications - NEW FLOW with conflict prevention"""
        if not paper_specs:
            return []
        
        # Build filter conditions for multiple paper specs
        spec_conditions = []
        for spec in paper_specs:
            spec_condition = and_(
                models.PendingOrderItem.gsm == spec['gsm'],
                models.PendingOrderItem.bf == spec['bf'],
                models.PendingOrderItem.shade == spec['shade']
            )
            spec_conditions.append(spec_condition)
        
        # Combine with OR
        from sqlalchemy import or_
        paper_filter = or_(*spec_conditions) if len(spec_conditions) > 1 else spec_conditions[0]
        
        # CRITICAL: Filter out pending items already used in active plans
        # AND exclude algorithm limitation pending orders (since original orders were reduced)
        pending_items = (
            db.query(models.PendingOrderItem)
            .filter(
                and_(
                    models.PendingOrderItem._status == "pending",
                    paper_filter,
                    # Exclude items that are already included in active plans
                    ~models.PendingOrderItem.id.in_(
                        db.query(models.PendingOrderItem.id)
                        .filter(models.PendingOrderItem._status == "included_in_plan")
                        .subquery()
                    ),
                )
            )
            .all()
        )
        
        # Convert to optimizer format
        pending_requirements = []
        for item in pending_items:
            pending_requirements.append({
                'width': float(item.width_inches),
                'quantity': item.quantity_pending,
                'gsm': item.gsm,
                'bf': float(item.bf),
                'shade': item.shade,
                'pending_order_id': str(item.id),
                'original_order_id': str(item.original_order_id),
                'reason': item.reason
            })
        
        return pending_requirements
    
    def create_pending_order_item(
        self, db: Session, *, pending: schemas.PendingOrderItemCreate
    ) -> models.PendingOrderItem:
        """Create new pending order item"""
        frontend_id = FrontendIDGenerator.generate_frontend_id("pending_order_item", db)
        db_pending = models.PendingOrderItem(
            frontend_id=frontend_id,
            original_order_id=pending.original_order_id,
            width_inches=pending.width_inches,
            gsm=pending.gsm,
            bf=pending.bf,
            shade=pending.shade,
            quantity_pending=pending.quantity_pending,
            reason=pending.reason,
            created_by_id=pending.created_by_id
        )
        db.add(db_pending)
        db.commit()
        db.refresh(db_pending)
        return db_pending
    
    def create_pending_items_from_optimization(
        self, db: Session, pending_orders: List[Dict[str, Any]], user_id: UUID
    ) -> List[models.PendingOrderItem]:
        """Create pending order items from optimization output - NEW FLOW"""
        import uuid
        from ..services.pending_order_service import PendingOrderService
        
        # Use the pending order service with replace_existing=True for optimization results
        service = PendingOrderService(db=db, user_id=user_id)
        
        # Group pending orders by original_order_id since service method expects this
        grouped_pending = {}
        for pending in pending_orders:
            original_order_id = pending.get('original_order_id')
            if not original_order_id:
                raise ValueError(f"original_order_id is required for pending order: {pending}")
            
            if original_order_id not in grouped_pending:
                grouped_pending[original_order_id] = []
            grouped_pending[original_order_id].append(pending)
        
        # Create pending items for each order using the service
        all_created_items = []
        for original_order_id, order_pending_list in grouped_pending.items():
            created_items = service.create_pending_items(
                pending_orders=order_pending_list,
                original_order_id=uuid.UUID(original_order_id),
                reason="optimization_result",
                replace_existing=True  # CRITICAL FIX: Replace existing quantities from optimization
            )
            all_created_items.extend(created_items)
        
        return all_created_items
    
    def get_pending_items_summary(self, db: Session) -> Dict[str, Any]:
        """Get summary statistics for pending order items"""
        # Total pending items
        total_pending = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem._status == "pending"
        ).count()
        
        # Total pending quantity
        total_quantity = db.query(func.sum(models.PendingOrderItem.quantity_pending)).filter(
            models.PendingOrderItem._status == "pending"
        ).scalar() or 0
        
        # Group by paper specs
        spec_groups = db.query(
            models.PendingOrderItem.gsm,
            models.PendingOrderItem.bf,
            models.PendingOrderItem.shade,
            func.count(models.PendingOrderItem.id).label('count'),
            func.sum(models.PendingOrderItem.quantity_pending).label('total_quantity')
        ).filter(
            models.PendingOrderItem._status == "pending"
        ).group_by(
            models.PendingOrderItem.gsm,
            models.PendingOrderItem.bf,
            models.PendingOrderItem.shade
        ).all()
        
        return {
            "total_pending_items": total_pending,
            "total_pending_quantity": int(total_quantity),
            "unique_specifications": len(spec_groups),
            "specification_breakdown": [
                {
                    "gsm": group.gsm,
                    "bf": float(group.bf),
                    "shade": group.shade,
                    "item_count": group.count,
                    "total_quantity": int(group.total_quantity)
                }
                for group in spec_groups
            ]
        }
    
    def get_consolidation_opportunities(self, db: Session) -> Dict[str, Any]:
        """Get consolidation opportunities for pending items"""
        # Group pending items by paper specs
        pending_groups = defaultdict(list)
        
        pending_items = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem._status == "pending"
        ).all()
        
        for item in pending_items:
            spec_key = (item.gsm, float(item.bf), item.shade)
            pending_groups[spec_key].append({
                "id": str(item.id),
                "width": float(item.width_inches),
                "quantity": item.quantity_pending,
                "reason": item.reason,
                "created_at": item.created_at.isoformat()
            })
        
        # Find consolidation opportunities
        opportunities = []
        for spec_key, items in pending_groups.items():
            if len(items) > 1:  # Multiple items with same specs
                total_quantity = sum(item['quantity'] for item in items)
                opportunities.append({
                    "gsm": spec_key[0],
                    "bf": spec_key[1],
                    "shade": spec_key[2],
                    "item_count": len(items),
                    "total_quantity": total_quantity,
                    "items": items
                })
        
        return {
            "consolidation_opportunities": len(opportunities),
            "opportunities": opportunities
        }
    
    def debug_pending_items(self, db: Session) -> Dict[str, Any]:
        """Debug endpoint to check pending items data"""
        pending_items = db.query(models.PendingOrderItem).all()
        
        return {
            "total_items": len(pending_items),
            "status_breakdown": {
                status: len([item for item in pending_items if item.status == status])
                for status in ["pending", "included_in_plan", "resolved", "cancelled"]
            },
            "recent_items": [
                {
                    "id": str(item.id),
                    "width": float(item.width_inches),
                    "gsm": item.gsm,
                    "bf": float(item.bf),
                    "shade": item.shade,
                    "quantity": item.quantity_pending,
                    "status": item.status,
                    "created_at": item.created_at.isoformat()
                }
                for item in sorted(pending_items, key=lambda x: x.created_at, reverse=True)[:10]
            ]
        }


def start_production_from_pending_orders_impl(db: Session, *, request_data) -> Dict[str, Any]:
    """Start production from selected pending orders - same as main planning but for pending flow"""
    import logging
    from datetime import datetime
    from uuid import uuid4
    from ..services.id_generator import FrontendIDGenerator
    from ..services.barcode_generator import BarcodeGenerator
    
    logger = logging.getLogger(__name__)
    logger.info("🎯 PENDING TO PRODUCTION: Starting production from pending orders with cut_rolls format")
    
    # Extract data from request (same format as main planning)
    selected_cut_rolls = request_data.selected_cut_rolls
    all_available_cuts = request_data.all_available_cuts
    created_by_id = request_data.created_by_id  
    jumbo_roll_width = request_data.jumbo_roll_width
    
    logger.info(f"📊 REQUEST DATA: {len(selected_cut_rolls)} cut_rolls, created_by: {created_by_id}")
    
    
    # Extract all pending order IDs from cut_rolls (they have source_pending_id)
    # Convert Pydantic objects to dicts for easier access
    selected_cut_rolls_dict = [cut_roll.model_dump() if hasattr(cut_roll, 'model_dump') else dict(cut_roll) for cut_roll in selected_cut_rolls]
    
    # DEBUG: Log each cut roll to see what we're processing
    logger.info("🔍 DEBUGGING CUT ROLLS:")
    for i, cut_roll in enumerate(selected_cut_rolls_dict):
        logger.info(f"   Roll {i+1}: source_pending_id='{cut_roll.get('source_pending_id')}', source_type='{cut_roll.get('source_type')}', width={cut_roll.get('width_inches')}")
    
    all_pending_order_ids = [cut_roll.get("source_pending_id") for cut_roll in selected_cut_rolls_dict if cut_roll.get("source_pending_id")]
    
    logger.info(f"🔄 CUT ROLLS PROCESSED: {len(selected_cut_rolls_dict)} processed, {len(all_pending_order_ids)} with pending IDs")
    logger.info(f"🆔 PENDING ORDER IDs: {all_pending_order_ids}")
    
    # Additional debugging: Check if we have any pending order IDs at all
    if not all_pending_order_ids:
        logger.error("❌ CRITICAL: No pending order IDs found in cut_rolls! This means no quantity updates will happen.")
        logger.error("   This could mean:")
        logger.error("   1. Frontend is not sending source_pending_id field")
        logger.error("   2. All source_pending_id values are null/empty") 
        logger.error("   3. Cut rolls are not from pending orders")
    else:
        logger.info(f"✅ Found {len(all_pending_order_ids)} pending order IDs to process")
    
    # Track entities
    updated_orders = []
    updated_order_items = [] 
    created_inventory = []
    created_jumbo_rolls = []
    created_118_rolls = []
    created_wastage = []
    
    # Create plan record (same pattern as main production)
    plan_name = f"Pending Production Plan - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    
    # ✅ NEW: Create cut_pattern array with same structure as regular orders
    cut_pattern = []
    for index, cut_roll in enumerate(selected_cut_rolls_dict):
        # Get company name from pending order's original order
        company_name = 'Unknown Company'
        
        # Find pending order to get original order details
        if cut_roll.get("source_pending_id"):
            try:
                pending_order = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.id == UUID(cut_roll["source_pending_id"])
                ).first()
                
                if pending_order and pending_order.original_order and pending_order.original_order.client:
                    company_name = pending_order.original_order.client.company_name
                    logger.info(f"✅ Found company: {company_name} for pending order {pending_order.frontend_id}")
            except Exception as e:
                logger.warning(f"⚠️ Could not resolve company for pending order {cut_roll.get('source_pending_id')}: {e}")
        
        # Create cut_pattern entry with same structure as regular orders
        cut_pattern_entry = {
            "width": cut_roll.get("width_inches", 0),
            "gsm": cut_roll.get("gsm", 0),
            "bf": cut_roll.get("bf", 0.0),
            "shade": cut_roll.get("shade", "unknown"),
            "individual_roll_number": cut_roll.get("individual_roll_number", 1),
            "source": "cutting",  # Standard source for cut rolls
            "order_id": cut_roll.get("order_id", cut_roll.get("source_pending_id")),  # Use order_id or fallback to pending_id
            "selected": True,  # All pending production rolls are selected by user
            "source_type": "pending_order",  # Mark as coming from pending orders
            "source_pending_id": cut_roll.get("source_pending_id"),
            "company_name": company_name
        }
        
        cut_pattern.append(cut_pattern_entry)
        logger.info(f"📋 Cut Pattern Entry #{index+1}: {cut_roll.get('width_inches', 0)}\" - {company_name}")
    
    logger.info(f"✅ Created cut_pattern array with {len(cut_pattern)} entries (same structure as regular orders)")
    
    # ✅ CALCULATE ACTUAL WASTE PERCENTAGE from cut roll data
    total_waste_percentage = 0.0
    if cut_pattern:
        # Group cut rolls by (paper_spec, individual_roll_number) to calculate waste per 118" roll
        # This ensures different paper specs don't get mixed in waste calculations
        roll_groups = {}
        for cut_entry in cut_pattern:
            roll_num = cut_entry.get("individual_roll_number", 1)
            
            # Create paper specification key with validation
            gsm = cut_entry.get("gsm", 0) or 0
            bf = cut_entry.get("bf", 0.0) or 0.0  
            shade = cut_entry.get("shade", "Unknown") or "Unknown"
            paper_key = (gsm, bf, shade)
            
            # Create composite key: (paper_spec, roll_number)
            composite_key = (paper_key, roll_num)
            
            if composite_key not in roll_groups:
                roll_groups[composite_key] = []
            roll_groups[composite_key].append(cut_entry.get("width", 0))
        
        # Calculate waste for each 118" roll
        total_waste = 0.0
        total_rolls = len(roll_groups)
        
        for composite_key, widths in roll_groups.items():
            paper_key, roll_num = composite_key
            gsm, bf, shade = paper_key
            
            used_width = sum(widths)  # Total width used in this 118" roll
            waste_width = jumbo_roll_width - used_width  # Waste = Planning width - Used width
            
            # Ensure waste is never negative (clamp to 0 if used_width exceeds jumbo_roll_width)
            if waste_width < 0:
                logger.warning(f"⚠️  Roll #{roll_num} ({shade} {gsm}GSM): Used width {used_width}\" exceeds jumbo width {jumbo_roll_width}\" - setting waste to 0")
                waste_width = 0
            
            waste_percentage = (waste_width / jumbo_roll_width) * 100 if jumbo_roll_width > 0 else 0
            total_waste += waste_percentage
            logger.info(f"📊 Roll #{roll_num} ({shade} {gsm}GSM): Used {used_width}\", Waste {waste_width}\" ({waste_percentage:.1f}%)")
        
        # Average waste percentage across all rolls
        total_waste_percentage = total_waste / total_rolls if total_rolls > 0 else 0.0
        logger.info(f"📊 AVERAGE WASTE PERCENTAGE: {total_waste_percentage:.1f}% across {total_rolls} rolls")
    
    db_plan = models.PlanMaster(
        id=uuid4(),
        frontend_id=FrontendIDGenerator.generate_frontend_id("plan_master", db),
        name=plan_name,
        cut_pattern=json.dumps(cut_pattern),  # JSON string of cut_pattern array (same structure as regular orders)
        expected_waste_percentage=total_waste_percentage,  # ✅ FIXED: Calculate actual waste from cut roll data
        actual_waste_percentage=0.0,
        status="in_progress",  # Start directly in progress
        created_by_id=UUID(created_by_id),
        created_at=datetime.utcnow(),
        executed_at=datetime.utcnow()
    )
    
    db.add(db_plan)
    db.flush()  # Get the plan ID
    logger.info(f"✅ Created plan: {db_plan.frontend_id}")
    
    # No order updates needed for pending flow (no existing orders)
    
    # Update pending orders with proper quantity tracking (Task 6: Pending order status updates)
    # IMPROVEMENT: Now supports partial fulfillment - only marks as "resolved" when quantity_pending reaches 0
    # Allows remaining quantities to appear in future suggestion cycles
    unique_pending_ids = list(set(all_pending_order_ids))
    updated_pending_orders = []
    
    logger.info(f"📝 PENDING QUANTITY UPDATE: Processing {len(unique_pending_ids)} unique pending orders with partial fulfillment tracking")
    
    for pending_id in unique_pending_ids:
        try:
            logger.info(f"🔍 Processing pending_id: '{pending_id}' (type: {type(pending_id)})")
            
            # Validate pending_id format
            if not pending_id or not isinstance(pending_id, str):
                logger.warning(f"❌ Invalid pending_id format: {pending_id}")
                continue
                
            # Try to convert to UUID with better error handling
            try:
                pending_uuid = UUID(pending_id)
                logger.info(f"✅ Valid UUID: {pending_uuid}")
            except (ValueError, TypeError) as uuid_error:
                logger.error(f"❌ Invalid UUID format for '{pending_id}': {uuid_error}")
                continue
            
            # DEBUG: Check if pending order exists in database  
            pending_order_any_status = db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.id == pending_uuid
            ).first()
            
            if not pending_order_any_status:
                logger.error(f"❌ CRITICAL: Pending order {pending_uuid} NOT FOUND in database at all!")
                continue
            else:
                logger.info(f"✅ Found pending order {pending_uuid} with status: {pending_order_any_status._status}")
            
            pending_order = db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.id == pending_uuid,
                models.PendingOrderItem._status == "pending"
            ).first()
            
            if pending_order:
                logger.info(f"✅ Found pending order {pending_order.frontend_id}")
                logger.info(f"📊 Current quantities - Pending: {pending_order.quantity_pending}, Fulfilled: {pending_order.quantity_fulfilled}")
                
                # Count how many times this pending_id appears in selected cut_rolls (proper quantity tracking)
                fulfilled_count = sum(1 for cut_roll in selected_cut_rolls_dict 
                                    if str(cut_roll.get("source_pending_id", "")) == str(pending_uuid))
                logger.info(f"🔢 Fulfilling {fulfilled_count} rolls from pending order {pending_order.frontend_id}")
                
                # EDGE CASE HANDLING: Skip if no rolls to fulfill (defensive programming)
                if fulfilled_count <= 0:
                    logger.warning(f"⚠️ No rolls to fulfill for pending order {pending_order.frontend_id}")
                    continue
                
                # Update quantities with proper tracking - count each cut piece
                # Note: We don't cap fulfilled_count because the pending order represents a requirement
                # that can be fulfilled by multiple cut pieces
                pending_order.quantity_fulfilled += fulfilled_count
                
                # Only reduce quantity_pending if we're fulfilling the requirement
                # (Don't go below 0)
                quantity_to_reduce = min(fulfilled_count, pending_order.quantity_pending)
                pending_order.quantity_pending -= quantity_to_reduce
                
                logger.info(f"📊 Updated fulfillment: +{fulfilled_count} fulfilled, -{quantity_to_reduce} pending")
                
                # Update status based on remaining quantity
                if pending_order.quantity_pending <= 0:
                    # Fully satisfied - mark as resolved
                    pending_order._status = "resolved"
                    pending_order.resolved_at = datetime.utcnow()
                    logger.info(f"✅ FULLY RESOLVED: {pending_order.frontend_id} - {fulfilled_count} rolls fulfilled, 0 remaining")
                else:
                    # Partially satisfied - keep as pending for remaining quantity
                    pending_order._status = "pending" 
                    # Don't set resolved_at for partial fulfillment
                    logger.info(f"📋 PARTIALLY FULFILLED: {pending_order.frontend_id} - {fulfilled_count} rolls fulfilled, {pending_order.quantity_pending} remaining")
                
                # Always mark as updated for tracking
                updated_pending_orders.append(str(pending_order.id))
                logger.info(f"🔄 Updated quantities: Pending={pending_order.quantity_pending}, Fulfilled={pending_order.quantity_fulfilled}, Status={pending_order._status}")
            else:
                logger.warning(f"❌ Pending order not found: {pending_id}")
        except Exception as e:
            logger.error(f"❌ Error updating pending order {pending_id}: {e}")
    
    # ====== DETAILED LOGGING: Paper Specification Grouping ======
    logger.info("🔬 PAPER SPEC GROUPING ANALYSIS:")
    jumbo_roll_width = request_data.jumbo_roll_width or 118
    logger.info(f"📏 Jumbo roll width: {jumbo_roll_width}")
    
    # Group selected cut rolls by paper specification first, then by individual_roll_number (EXACT COPY)
    paper_spec_groups = {}  # {paper_spec_key: {roll_number: [cut_rolls]}}
    
    logger.info(f"📦 GROUPING START: Processing {len(selected_cut_rolls_dict)} cut rolls for paper spec grouping")
    logger.info("🔍 Analyzing each cut roll for grouping logic:")
    
    for i, cut_roll in enumerate(selected_cut_rolls_dict):
        logger.info(f"🔍 Processing Cut Roll #{i+1}:")
        logger.info(f"   Raw data: {cut_roll}")
        
        individual_roll_number = cut_roll.get("individual_roll_number")
        logger.info(f"   Individual roll number: {individual_roll_number}")
        
        if individual_roll_number:
            # Create paper specification key (gsm, bf, shade)
            paper_spec_key = (
                cut_roll.get("gsm"),
                cut_roll.get("bf"), 
                cut_roll.get("shade")
            )
            
            logger.info(f"   Paper spec key: {paper_spec_key}")
            logger.info(f"   Width: {cut_roll.get('width_inches')}")
            logger.info(f"   Source pending ID: {cut_roll.get('source_pending_id')}")
            
            # Initialize paper spec group if not exists
            if paper_spec_key not in paper_spec_groups:
                paper_spec_groups[paper_spec_key] = {}
                logger.info(f"   ✅ CREATED NEW PAPER SPEC GROUP: {paper_spec_key}")
            
            # Initialize roll number group within this paper spec
            if individual_roll_number not in paper_spec_groups[paper_spec_key]:
                paper_spec_groups[paper_spec_key][individual_roll_number] = []
                logger.info(f"   ✅ CREATED NEW ROLL GROUP: #{individual_roll_number} in {paper_spec_key}")
            else:
                logger.info(f"   📋 USING EXISTING ROLL GROUP: #{individual_roll_number} in {paper_spec_key}")
            
            # Add cut roll to the appropriate group
            paper_spec_groups[paper_spec_key][individual_roll_number].append(cut_roll)
            current_count = len(paper_spec_groups[paper_spec_key][individual_roll_number])
            logger.info(f"   ✅ ADDED to group: Now {current_count} rolls in #{individual_roll_number} for {paper_spec_key}")
            logger.info(f"   📋 Added roll data: Width={cut_roll.get('width_inches')}, Source={cut_roll.get('source_pending_id')}")
        else:
            logger.warning(f"📦 SKIPPED: Cut roll {i+1} has no individual_roll_number")
            
    logger.info(f"📦 PAPER SPEC GROUPING COMPLETE: Found {len(paper_spec_groups)} unique paper specifications")
    
    # ====== DETAILED LOGGING: Final Grouping Summary ======
    logger.info("🔬 FINAL GROUPING SUMMARY:")
    for spec_key, roll_groups in paper_spec_groups.items():
        gsm, bf, shade = spec_key
        logger.info(f"📋 Paper Spec: {gsm}gsm, {bf}bf, {shade}")
        total_rolls_in_spec = 0
        for roll_number, cut_rolls in roll_groups.items():
            roll_count = len(cut_rolls)
            total_rolls_in_spec += roll_count
            logger.info(f"   Roll #{roll_number}: {roll_count} cut rolls")
            for j, roll in enumerate(cut_rolls):
                logger.info(f"     Cut #{j+1}: {roll.get('width_inches')}\" (ID: {roll.get('source_pending_id', 'N/A')})")
        logger.info(f"   🔢 Total rolls for this spec: {total_rolls_in_spec}")
        logger.info("   ---")
    
    for spec_key, cut_rolls_for_spec in paper_spec_groups.items():
        gsm, bf, shade = spec_key
        
        # Find matching paper record
        paper_record = db.query(models.PaperMaster).filter(
            models.PaperMaster.gsm == gsm,
            models.PaperMaster.bf == bf,
            models.PaperMaster.shade == shade
        ).first()
        
        if not paper_record:
            logger.warning(f"❌ No paper record found for {gsm}gsm {bf}bf {shade}")
            continue
        
        logger.info(f"✅ Found paper record: {paper_record.frontend_id}")
        
        # Calculate how many jumbo rolls needed (3 cut rolls per jumbo, flexible 1-3)
        spec_cut_count = len(cut_rolls_for_spec)
        spec_jumbo_count = (spec_cut_count + 2) // 3  # Ceiling division for 1-3 rolls per jumbo
        
        logger.info(f"📊 SPEC {gsm}gsm {bf}bf {shade}: {spec_cut_count} cut rolls → {spec_jumbo_count} jumbo rolls needed")
        
        # Create jumbo rolls for this paper specification
        for jumbo_idx in range(spec_jumbo_count):
            virtual_jumbo_qr = f"VIRTUAL_JUMBO_{uuid4().hex[:8].upper()}"
            virtual_jumbo_barcode = f"VJB_{uuid4().hex[:8].upper()}"
            jumbo_roll = models.InventoryMaster(
                paper_id=paper_record.id,
                width_inches=jumbo_roll_width,
                weight_kg=0,
                roll_type="jumbo",
                status="consumed",
                qr_code=virtual_jumbo_qr,
                barcode_id=virtual_jumbo_barcode,
                frontend_id=FrontendIDGenerator.generate_frontend_id("inventory_master", db),
                created_by_id=UUID(created_by_id),
                created_at=datetime.utcnow(),
                location="Virtual Production"
            )
            
            db.add(jumbo_roll)
            db.flush()  # Get the ID
            created_jumbo_rolls.append(jumbo_roll)
            logger.info(f"🎯 Created jumbo roll: {jumbo_roll.frontend_id}")
            
            # Determine how many 118" rolls this jumbo should have (1-3, flexible)
            remaining_cuts = spec_cut_count - (jumbo_idx * 3)
            rolls_for_this_jumbo = min(3, remaining_cuts)
            
            # Create 118" rolls for this jumbo
            for roll_118_idx in range(rolls_for_this_jumbo):
                virtual_118_qr = f"VIRTUAL_118_{uuid4().hex[:8].upper()}"
                virtual_118_barcode = f"V118_{uuid4().hex[:8].upper()}"
                roll_118 = models.InventoryMaster(
                    paper_id=paper_record.id,
                    width_inches=jumbo_roll_width,
                    weight_kg=0,
                    roll_type="118",
                    status="consumed",
                    qr_code=virtual_118_qr,
                    barcode_id=virtual_118_barcode,
                    frontend_id=FrontendIDGenerator.generate_frontend_id("inventory_master", db),
                    created_by_id=UUID(created_by_id),
                    created_at=datetime.utcnow(),
                    location="Virtual Production",
                    parent_jumbo_id=jumbo_roll.id
                )
                
                db.add(roll_118)
                db.flush()  # Get the ID
                created_118_rolls.append(roll_118)
                logger.info(f"📏 Created 118\" roll: {roll_118.frontend_id}")
    
    # ====== DETAILED LOGGING: Cut Roll Inventory Creation ======
    logger.info("🔧 CUT ROLL INVENTORY CREATION:")
    logger.info(f"📦 Total cut rolls to process: {len(selected_cut_rolls_dict)}")
    logger.info("🔍 Processing each selected cut roll for inventory creation:")
    
    for i, cut_roll in enumerate(selected_cut_rolls_dict):
        try:
            logger.info(f"🔧 ===== PROCESSING CUT ROLL #{i+1}/{len(selected_cut_rolls_dict)} =====")
            logger.info(f"📦 Cut roll data: {cut_roll}")
            logger.info(f"📏 Dimensions: {cut_roll.get('width_inches')}\" x {cut_roll.get('weight_kg', 'N/A')}kg")
            logger.info(f"📋 Paper: GSM={cut_roll.get('gsm')}, BF={cut_roll.get('bf')}, Shade={cut_roll.get('shade')}")
            logger.info(f"🔗 Source: pending_id={cut_roll.get('source_pending_id')}, roll_number={cut_roll.get('individual_roll_number')}")
            
            # Find the paper record for this cut roll
            cut_roll_paper = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == cut_roll["gsm"],
                models.PaperMaster.bf == cut_roll["bf"], 
                models.PaperMaster.shade == cut_roll["shade"]
            ).first()
            
            if not cut_roll_paper:
                logger.error(f"❌ PAPER LOOKUP FAILED: No paper found for GSM={cut_roll['gsm']}, BF={cut_roll['bf']}, Shade={cut_roll['shade']}")
                logger.error(f"❌ SKIPPING cut roll #{i+1} due to missing paper record")
                continue
            else:
                logger.info(f"✅ PAPER FOUND: {cut_roll_paper.frontend_id} (ID: {cut_roll_paper.id})")
            
            # Find a suitable 118" roll to attach this cut to
            logger.info(f"🔍 Looking for suitable 118\" parent roll...")
            suitable_118_roll = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.paper_id == cut_roll_paper.id,
                models.InventoryMaster.roll_type == "118",
                models.InventoryMaster.status == "consumed"
            ).first()
            
            if suitable_118_roll:
                logger.info(f"✅ Found parent 118\" roll: {suitable_118_roll.frontend_id}")
            else:
                logger.warning(f"⚠️ No suitable 118\" parent roll found - will create cut roll without parent")
            
            # Create the cut roll inventory record with ORDER LINKING
            logger.info(f"🔧 Generating identifiers for inventory creation...")
            barcode_id = BarcodeGenerator.generate_cut_roll_barcode(db)
            frontend_id = FrontendIDGenerator.generate_frontend_id("inventory_master", db)
            logger.info(f"🔧 Generated IDs - Barcode: {barcode_id}, Frontend: {frontend_id}")
            
            # ✅ CRITICAL: Link cut roll to original order for client tracking
            logger.info(f"🔗 Attempting to link cut roll to original order...")
            order_id = cut_roll.get("order_id")
            logger.info(f"🔗 Order ID from cut_roll: {order_id}")
            if order_id:
                try:
                    order_uuid = UUID(order_id)
                    logger.info(f"✅ VALID ORDER LINK: {order_id}")
                except (ValueError, TypeError):
                    logger.warning(f"❌ INVALID ORDER ID FORMAT: {order_id}")
                    order_uuid = None
            else:
                logger.warning(f"❌ NO ORDER ID: Missing order_id in cut_roll data")
                order_uuid = None
            
            # Create inventory item with full logging
            logger.info(f"🏗️ CREATING INVENTORY RECORD:")
            logger.info(f"   Paper ID: {cut_roll_paper.id}")
            logger.info(f"   Width: {cut_roll['width_inches']}\"")
            logger.info(f"   QR Code: {cut_roll['qr_code']}")
            logger.info(f"   Barcode: {barcode_id}")
            logger.info(f"   Frontend ID: {frontend_id}")
            logger.info(f"   Parent 118 Roll: {suitable_118_roll.id if suitable_118_roll else 'None'}")
            logger.info(f"   Individual Roll #: {cut_roll.get('individual_roll_number', 1)}")
            logger.info(f"   Allocated to Order: {order_uuid}")
            
            inventory_item = models.InventoryMaster(
                paper_id=cut_roll_paper.id,
                width_inches=cut_roll["width_inches"],
                weight_kg=0,  # Will be updated via QR scan
                roll_type="cut",
                status="cutting",
                qr_code=cut_roll["qr_code"],
                barcode_id=barcode_id,
                frontend_id=frontend_id,
                created_by_id=UUID(created_by_id),
                created_at=datetime.utcnow(),
                location="Cutting Station",
                parent_118_roll_id=suitable_118_roll.id if suitable_118_roll else None,
                individual_roll_number=cut_roll.get("individual_roll_number", 1),
                source_type="pending_order",
                allocated_to_order_id=order_uuid  # ✅ LINK TO ORIGINAL ORDER FOR CLIENT INFO
            )
            
            logger.info(f"💾 SAVING TO DATABASE:")
            db.add(inventory_item)
            db.flush()  # Get the ID immediately
            created_inventory.append(inventory_item)
            logger.info(f"✅ SUCCESSFULLY CREATED: {inventory_item.frontend_id} (DB ID: {inventory_item.id})")
            logger.info(f"📋 FINAL INVENTORY: Width={inventory_item.width_inches}\", Paper={cut_roll_paper.frontend_id}, QR={inventory_item.qr_code}")
            logger.info(f"===== END CUT ROLL #{i+1} =====")
            logger.info("")  # Empty line for readability
            
        except Exception as e:
            logger.error(f"❌ Error creating cut roll inventory {i+1}: {e}")
            logger.error(f"❌ Cut roll data: {cut_roll}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
    
    # Link all created inventory items to the plan via PlanInventoryLink
    logger.info(f"🔗 PLAN LINKING: Creating PlanInventoryLink records")
    created_plan_links = []
    
    # ✅ FIX: Only link CUT ROLLS to the plan (frontend looks for roll_type="cut")
    # Jumbo and 118" rolls are for hierarchy tracking, but plan should show cut rolls only
    valid_inventory_items = [item for item in created_inventory if item and item.id is not None]
    logger.info(f"🔗 PLAN LINKING: Linking {len(valid_inventory_items)} CUT ROLLS to plan (jumbo/118\" rolls are for hierarchy only)")
    
    for inventory_item in valid_inventory_items:
        try:
            plan_link = models.PlanInventoryLink(
                id=uuid4(),
                frontend_id=FrontendIDGenerator.generate_frontend_id("plan_inventory_link", db),
                plan_id=db_plan.id,
                inventory_id=inventory_item.id,
                quantity_used=1.0  # Default quantity
            )
            
            db.add(plan_link)
            created_plan_links.append(plan_link)
            logger.info(f"🔗 Linked {inventory_item.frontend_id} to plan {db_plan.frontend_id}")
            
        except Exception as e:
            logger.error(f"❌ Error creating plan inventory link for {inventory_item.frontend_id}: {e}")
    
    logger.info(f"✅ PLAN LINKING COMPLETE: Created {len(created_plan_links)} plan-inventory links")
    
    # ✅ CREATE PLAN-ORDER LINKS for client tracking (same as main production)
    logger.info("🔗 PLAN-ORDER LINKING: Creating PlanOrderLink records for client tracking")
    created_plan_order_links = []
    
    # Get unique order IDs from cut rolls
    unique_order_ids = set()
    for cut_roll in selected_cut_rolls_dict:
        order_id = cut_roll.get("order_id")
        if order_id:
            try:
                unique_order_ids.add(UUID(order_id))
            except (ValueError, TypeError):
                logger.warning(f"❌ Invalid order_id in cut_roll: {order_id}")
    
    logger.info(f"🔗 Found {len(unique_order_ids)} unique orders to link to plan")
    
    # Create PlanOrderLink for each unique order
    for order_uuid in unique_order_ids:
        try:
            # Get order details
            order = db.query(models.OrderMaster).filter(models.OrderMaster.id == order_uuid).first()
            if not order:
                logger.warning(f"❌ Order not found: {order_uuid}")
                continue
                
            # Find an order item for this order (for the link)
            order_item = db.query(models.OrderItem).filter(models.OrderItem.order_id == order_uuid).first()
            if not order_item:
                logger.warning(f"❌ No order items found for order: {order_uuid}")
                continue
            
            # Create PlanOrderLink
            plan_order_link = models.PlanOrderLink(
                id=uuid4(),
                frontend_id=FrontendIDGenerator.generate_frontend_id("plan_order_link", db),
                plan_id=db_plan.id,
                order_id=order_uuid,
                order_item_id=order_item.id,
                quantity_allocated=1  # Default quantity for pending orders
            )
            
            db.add(plan_order_link)
            created_plan_order_links.append(plan_order_link)
            logger.info(f"🔗 Linked plan to order: {order.frontend_id} (Client: {order.client.company_name if order.client else 'Unknown'})")
            
        except Exception as e:
            logger.error(f"❌ Error creating plan-order link for {order_uuid}: {e}")
    
    logger.info(f"✅ PLAN-ORDER LINKING COMPLETE: Created {len(created_plan_order_links)} plan-order links")
    
    # WASTAGE PROCESSING: Handle any wastage (pending flow typically has minimal waste)
    logger.info("🗑️ WASTAGE PROCESSING: Processing potential wastage from pending production")
    # Note: Pending suggestions typically don't have wastage data, but we maintain the structure
    # for consistency with main production flow
    # If wastage data was provided in the request, it would be processed here
    logger.info("✅ WASTAGE COMPLETE: No wastage items to process for pending suggestions")
    
    # PHASE 2 PENDING ORDERS: Create pending orders from unused suggestions (if any)
    logger.info("📋 PHASE 2: Processing unused suggestions for new pending orders")
    created_pending_from_unused = []
    # Note: In pending flow, user only selects what they want, so typically no unused suggestions
    # All selected suggestions are converted to inventory, so no Phase 2 pending orders needed
    logger.info("✅ PHASE 2 COMPLETE: No unused suggestions to convert to pending orders")
    
    # Update plan status to completed since all processing is done
    logger.info(f"📊 PLAN STATUS UPDATE: Updating plan {db_plan.frontend_id} to completed")
    db_plan.status = "completed"
    db_plan.completed_at = datetime.utcnow()
    logger.info(f"✅ Plan {db_plan.frontend_id} marked as completed")
    
    # Commit all changes
    try:
        db.commit()
        logger.info("✅ DATABASE COMMIT: All changes committed successfully")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ DATABASE ROLLBACK: Commit failed: {e}")
        raise
    
    logger.info(f"✅ Production complete: {len(created_inventory)} inventory items, {len(updated_pending_orders)} pending orders updated")
    
    if len(created_inventory) != len(selected_cut_rolls):
        logger.warning(f"⚠️ MISMATCH DETECTED: {len(selected_cut_rolls)} selected vs {len(created_inventory)} created")
        logger.warning(f"⚠️ This indicates some rolls failed to process - check error logs above")
    else:
        logger.info(f"✅ PERFECT MATCH: All selected rolls were successfully processed")
    
    logger.info("🎯 ===== END PRODUCTION SUMMARY =====")
    logger.info("")

    # Return response matching StartProductionResponse format
    return {
        "plan_id": str(db_plan.id),
        "status": "completed", 
        "executed_at": db_plan.executed_at.isoformat() if db_plan.executed_at else datetime.utcnow().isoformat(),
        "summary": {
            "orders_updated": len(updated_orders),
            "order_items_updated": len(updated_order_items), 
            "pending_orders_resolved": len(updated_pending_orders),
            "inventory_created": len(created_inventory),
            "pending_orders_created_phase2": len(created_pending_from_unused),
            "jumbo_rolls_created": len(created_jumbo_rolls),
            "intermediate_118_rolls_created": len(created_118_rolls)
        },
        "details": {
            "updated_orders": updated_orders,  # Already List[str]
            "updated_order_items": updated_order_items,  # Already List[str] 
            "updated_pending_orders": updated_pending_orders,  # Already List[str]
            "created_inventory": [str(inv.id) for inv in created_inventory],  # List[str]
            "created_jumbo_rolls": [str(jr.id) for jr in created_jumbo_rolls],  # List[str]
            "created_118_rolls": [str(r118.id) for r118 in created_118_rolls],  # List[str]
            "created_wastage": [str(w.id) for w in created_wastage],  # List[str]
            "created_gupta_orders": []  # List[str] - empty for pending flow
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
        "message": f"Production started successfully from pending suggestions - Plan {db_plan.frontend_id} completed: Processed {len(updated_pending_orders)} pending orders (with partial fulfillment tracking), created {len(created_jumbo_rolls)} jumbo rolls, {len(created_118_rolls)} intermediate rolls, {len(created_inventory)} cut roll inventory items, {len(created_plan_links)} plan links"
    }


pending_order = CRUDPendingOrder(models.PendingOrderItem)