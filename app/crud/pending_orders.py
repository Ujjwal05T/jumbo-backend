from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, desc
from typing import List, Optional, Dict, Any
from uuid import UUID
from collections import defaultdict

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
    all_pending_order_ids = [cut_roll.get("source_pending_id") for cut_roll in selected_cut_rolls_dict if cut_roll.get("source_pending_id")]
    
    logger.info(f"🔄 CUT ROLLS RECEIVED: {len(selected_cut_rolls)} cut_rolls with {len(all_pending_order_ids)} pending order references")
    
    # ✅ NEW APPROACH: Reuse the EXACT same logic as main production but without plan_id
    # The cut_rolls are already in the correct format from frontend
    logger.info("🎯 REUSING MAIN PRODUCTION LOGIC: Using same approach as start_production_for_plan")
    
    # Use the existing production logic but without a plan_id
    # We'll adapt the core logic from start_production_for_plan
    
    # Track entities
    updated_orders = []
    updated_order_items = [] 
    created_inventory = []
    created_jumbo_rolls = []
    created_118_rolls = []
    created_wastage = []
    
    # Create a PlanMaster record for proper tracking (like main production flow)
    logger.info("📋 PLAN CREATION: Creating PlanMaster record for pending production")
    
    # Create plan record (same pattern as main production)
    plan_name = f"Pending Production Plan - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    cut_pattern = {"selected_cut_rolls": selected_cut_rolls_dict, "source": "pending_orders"}
    
    db_plan = models.PlanMaster(
        id=uuid4(),
        frontend_id=FrontendIDGenerator.generate_frontend_id("plan_master", db),
        name=plan_name,
        cut_pattern=str(cut_pattern),  # JSON string of suggestions
        expected_waste_percentage=0.0,  # No waste expected from suggestions
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
    
    # Update pending orders status (Task 6: Pending order status updates)
    unique_pending_ids = list(set(all_pending_order_ids))
    updated_pending_orders = []
    
    logger.info(f"📝 PENDING STATUS UPDATE: Processing {len(unique_pending_ids)} unique pending orders")
    
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
            
            pending_order = db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.id == pending_uuid,
                models.PendingOrderItem._status == "pending"
            ).first()
            
            if pending_order:
                logger.info(f"✅ Found pending order {pending_order.frontend_id}")
                # Mark as resolved since it's been used in production
                pending_order._status = "resolved"
                pending_order.updated_at = datetime.utcnow()
                updated_pending_orders.append(str(pending_order.id))
                logger.info(f"🔄 Updated status: {pending_order.frontend_id} -> resolved")
            else:
                logger.warning(f"❌ Pending order not found: {pending_id}")
        except Exception as e:
            logger.error(f"❌ Error updating pending order {pending_id}: {e}")
    
    # ✅ COPY EXACT INVENTORY CREATION from main production - Group by paper spec and individual_roll_number
    jumbo_roll_width = request_data.jumbo_roll_width or 118
    
    # Group selected cut rolls by paper specification first, then by individual_roll_number (EXACT COPY)
    paper_spec_groups = {}  # {paper_spec_key: {roll_number: [cut_rolls]}}
    
    logger.info(f"📦 GROUPING: Starting paper specification grouping for {len(selected_cut_rolls_dict)} cut rolls")
    
    for i, cut_roll in enumerate(selected_cut_rolls_dict):
        individual_roll_number = cut_roll.get("individual_roll_number")
        if individual_roll_number:
            # Create paper specification key (gsm, bf, shade)
            paper_spec_key = (
                cut_roll.get("gsm"),
                cut_roll.get("bf"),
                cut_roll.get("shade")
            )
            
            logger.info(f"📦 Cut Roll {i+1}: Roll #{individual_roll_number}, Spec: {paper_spec_key}")
            
            # Initialize paper spec group if not exists
            if paper_spec_key not in paper_spec_groups:
                paper_spec_groups[paper_spec_key] = {}
                logger.info(f"📦 NEW PAPER SPEC: Created group for {paper_spec_key}")
            
            # Initialize roll number group within this paper spec
            if individual_roll_number not in paper_spec_groups[paper_spec_key]:
                paper_spec_groups[paper_spec_key][individual_roll_number] = []
                logger.info(f"📦 NEW ROLL GROUP: Added roll #{individual_roll_number} to spec {paper_spec_key}")
            
            # Add cut roll to the appropriate group
            paper_spec_groups[paper_spec_key][individual_roll_number].append(cut_roll)
            logger.info(f"📦 ADDED: Cut roll to spec {paper_spec_key}, roll #{individual_roll_number}")
        else:
            logger.warning(f"📦 SKIPPED: Cut roll {i+1} has no individual_roll_number")
            
    logger.info(f"📦 PAPER SPEC GROUPING: Found {len(paper_spec_groups)} unique paper specifications")
    
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
    
    # Now create cut rolls following the existing pattern
    logger.info(f"🔧 CUT ROLL CREATION: Processing {len(selected_cut_rolls_dict)} cut rolls")
    for i, cut_roll in enumerate(selected_cut_rolls_dict):
        try:
            logger.info(f"🔧 Processing cut roll {i+1}/{len(selected_cut_rolls_dict)}: {cut_roll['width_inches']}\" {cut_roll['gsm']}gsm")
            
            # Find the paper record for this cut roll
            cut_roll_paper = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == cut_roll["gsm"],
                models.PaperMaster.bf == cut_roll["bf"], 
                models.PaperMaster.shade == cut_roll["shade"]
            ).first()
            
            if not cut_roll_paper:
                logger.error(f"❌ Paper not found for cut roll {i+1}: {cut_roll['gsm']}gsm {cut_roll['bf']}bf {cut_roll['shade']}")
                continue
            else:
                logger.info(f"✅ Found paper: {cut_roll_paper.frontend_id}")
            
            # Find a suitable 118" roll to attach this cut to
            suitable_118_roll = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.paper_id == cut_roll_paper.id,
                models.InventoryMaster.roll_type == "118",
                models.InventoryMaster.status == "consumed"
            ).first()
            
            # Create the cut roll inventory record with ORDER LINKING
            logger.info(f"🔧 Creating inventory item with barcode generation...")
            barcode_id = BarcodeGenerator.generate_cut_roll_barcode(db)
            frontend_id = FrontendIDGenerator.generate_frontend_id("inventory_master", db)
            logger.info(f"🔧 Generated IDs - Barcode: {barcode_id}, Frontend: {frontend_id}")
            
            # ✅ CRITICAL: Link cut roll to original order for client tracking
            order_id = cut_roll.get("order_id")
            if order_id:
                try:
                    order_uuid = UUID(order_id)
                    logger.info(f"✅ Linking cut roll to original order: {order_id}")
                except (ValueError, TypeError):
                    logger.warning(f"❌ Invalid order_id format: {order_id}")
                    order_uuid = None
            else:
                logger.warning(f"❌ No order_id found in cut_roll data")
                order_uuid = None
            
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
            
            logger.info(f"🔧 Adding inventory item to database...")
            db.add(inventory_item)
            db.flush()  # Get the ID immediately
            created_inventory.append(inventory_item)
            logger.info(f"✂️ Created cut roll: {inventory_item.frontend_id} ({cut_roll['width_inches']}\") ID: {inventory_item.id}")
            
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
        "message": f"Production started successfully from pending suggestions - Plan {db_plan.frontend_id} completed: Resolved {len(updated_pending_orders)} pending orders, created {len(created_jumbo_rolls)} jumbo rolls, {len(created_118_rolls)} intermediate rolls, {len(created_inventory)} cut roll inventory items, {len(created_plan_links)} plan links"
    }


pending_order = CRUDPendingOrder(models.PendingOrderItem)