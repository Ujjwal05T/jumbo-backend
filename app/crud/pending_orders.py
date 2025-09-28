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
        # FIX: Load original order and client relationships for client name mapping
        pending_items = (
            db.query(models.PendingOrderItem)
            .options(
                joinedload(models.PendingOrderItem.original_order)
                .joinedload(models.OrderMaster.client)
            )
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
            # FIX: Add client information from loaded relationships
            client_name = 'Unknown'
            client_id = None
            
            if item.original_order and item.original_order.client:
                client_name = item.original_order.client.company_name
                client_id = str(item.original_order.client.id)
            
            pending_requirements.append({
                'width': float(item.width_inches),
                'quantity': item.quantity_pending,
                'gsm': item.gsm,
                'bf': float(item.bf),
                'shade': item.shade,
                'pending_order_id': str(item.id),
                'original_order_id': str(item.original_order_id),
                'reason': item.reason,
                'client_name': client_name,  # FIX: Now includes client name
                'client_id': client_id        # FIX: Now includes client ID
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

    def get_pending_order_item_with_details(self, db: Session, *, item_id: UUID) -> models.PendingOrderItem:
        """Get pending order item with all related details"""
        item = db.query(models.PendingOrderItem).options(
            joinedload(models.PendingOrderItem.original_order).joinedload(models.OrderMaster.client),
            joinedload(models.PendingOrderItem.created_by),
            joinedload(models.PendingOrderItem.production_order)
        ).filter(models.PendingOrderItem.id == item_id).first()

        if not item:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Pending order item not found")

        return item

    def get_available_orders_for_pending_allocation(self, db: Session, *, item_id: UUID) -> Dict[str, Any]:
        """Get list of orders that can receive pending order allocation"""
        # Get the pending order item first
        pending_item = self.get_pending_order_item_with_details(db=db, item_id=item_id)

        # Find orders that have items with matching paper specifications
        matching_orders = db.query(models.OrderMaster).join(models.OrderItem).join(models.PaperMaster).filter(
            models.PaperMaster.gsm == pending_item.gsm,
            models.PaperMaster.bf == pending_item.bf,
            models.PaperMaster.shade == pending_item.shade,
            models.OrderMaster.status.in_(["created", "in_process"]),  # Only active orders
            models.OrderItem.width_inches == pending_item.width_inches  # Matching width
        ).options(joinedload(models.OrderMaster.client)).distinct().all()

        # Also get all other active orders (for user choice)
        all_active_orders = db.query(models.OrderMaster).filter(
            models.OrderMaster.status.in_(["created", "in_process"])
        ).options(joinedload(models.OrderMaster.client)).all()

        # Convert to response format
        def order_to_dict(order, has_matching=False, matching_count=0):
            return {
                "id": str(order.id),
                "frontend_id": order.frontend_id,
                "client_id": str(order.client_id),
                "client_name": order.client.company_name if order.client else "Unknown",
                "status": order.status,
                "priority": order.priority,
                "payment_type": order.payment_type,
                "delivery_date": order.delivery_date,
                "created_at": order.created_at,
                "has_matching_paper": has_matching,
                "matching_items_count": matching_count
            }

        # Calculate matching items count for matching orders
        matching_orders_data = []
        for order in matching_orders:
            matching_count = db.query(models.OrderItem).join(models.PaperMaster).filter(
                models.OrderItem.order_id == order.id,
                models.PaperMaster.gsm == pending_item.gsm,
                models.PaperMaster.bf == pending_item.bf,
                models.PaperMaster.shade == pending_item.shade,
                models.OrderItem.width_inches == pending_item.width_inches
            ).count()
            matching_orders_data.append(order_to_dict(order, True, matching_count))

        # Get other orders (excluding already matched ones)
        matching_order_ids = {order.id for order in matching_orders}
        other_orders_data = [
            order_to_dict(order, False, 0)
            for order in all_active_orders
            if order.id not in matching_order_ids
        ]

        return {
            "pending_item": {
                "id": str(pending_item.id),
                "frontend_id": pending_item.frontend_id,
                "width_inches": float(pending_item.width_inches),
                "gsm": pending_item.gsm,
                "bf": float(pending_item.bf),
                "shade": pending_item.shade,
                "quantity_pending": pending_item.quantity_pending,
                "status": pending_item.status,
                "original_order_client": pending_item.original_order.client.company_name if pending_item.original_order and pending_item.original_order.client else "Unknown"
            },
            "matching_orders": matching_orders_data,
            "other_orders": other_orders_data,
            "total_available": len(matching_orders_data) + len(other_orders_data)
        }

    def allocate_pending_order_to_order(
        self,
        db: Session,
        *,
        item_id: UUID,
        target_order_id: UUID,
        quantity_to_transfer: int,
        created_by_id: UUID
    ) -> Dict[str, Any]:
        """Allocate pending order item to a specific order (quantity-wise transfer)"""
        from datetime import datetime
        from ..services.id_generator import FrontendIDGenerator

        # Get pending order item
        pending_item = self.get_pending_order_item_with_details(db=db, item_id=item_id)

        # Validate quantity
        if quantity_to_transfer > pending_item.quantity_pending:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transfer {quantity_to_transfer} items. Only {pending_item.quantity_pending} available."
            )

        # Get target order
        target_order = db.query(models.OrderMaster).filter(models.OrderMaster.id == target_order_id).first()
        if not target_order:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Target order not found")

        # Check if target order has matching order item
        matching_order_item = db.query(models.OrderItem).join(models.PaperMaster).filter(
            models.OrderItem.order_id == target_order_id,
            models.PaperMaster.gsm == pending_item.gsm,
            models.PaperMaster.bf == pending_item.bf,
            models.PaperMaster.shade == pending_item.shade,
            models.OrderItem.width_inches == pending_item.width_inches
        ).first()

        created_order_item = None
        updated_order_item = None

        if matching_order_item:
            # Update existing order item
            matching_order_item.quantity_rolls += quantity_to_transfer
            matching_order_item.quantity_kg = models.OrderItem.calculate_quantity_kg(
                float(matching_order_item.width_inches),
                matching_order_item.quantity_rolls
            )
            matching_order_item.amount = float(matching_order_item.quantity_kg) * float(matching_order_item.rate)
            matching_order_item.updated_at = datetime.utcnow()
            updated_order_item = matching_order_item
        else:
            # Create new order item in target order
            # Find paper master
            paper_master = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == pending_item.gsm,
                models.PaperMaster.bf == pending_item.bf,
                models.PaperMaster.shade == pending_item.shade
            ).first()

            if not paper_master:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Paper specification not found in paper master")

            # Calculate values for new order item
            quantity_kg = models.OrderItem.calculate_quantity_kg(float(pending_item.width_inches), quantity_to_transfer)
            default_rate = 100.0  # Default rate - should be configurable
            amount = quantity_kg * default_rate

            new_order_item = models.OrderItem(
                frontend_id=FrontendIDGenerator.generate_frontend_id("order_item", db),
                order_id=target_order_id,
                paper_id=paper_master.id,
                width_inches=pending_item.width_inches,
                quantity_rolls=quantity_to_transfer,
                quantity_kg=quantity_kg,
                rate=default_rate,
                amount=amount,
                quantity_fulfilled=0,
                quantity_in_pending=0,
                item_status="created",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )

            db.add(new_order_item)
            db.flush()
            created_order_item = new_order_item

        # Update pending order item
        pending_item.quantity_pending -= quantity_to_transfer
        pending_item.quantity_fulfilled = (pending_item.quantity_fulfilled or 0) + quantity_to_transfer

        if pending_item.quantity_pending <= 0:
            pending_item._status = "resolved"
            pending_item.resolved_at = datetime.utcnow()

        db.commit()

        return {
            "message": f"Successfully transferred {quantity_to_transfer} items from pending order to {target_order.frontend_id}",
            "pending_order_item": pending_item,
            "created_order_item": created_order_item,
            "updated_order_item": updated_order_item,
            "allocation_details": {
                "quantity_transferred": quantity_to_transfer,
                "remaining_pending": pending_item.quantity_pending,
                "target_order_frontend_id": target_order.frontend_id,
                "target_client": target_order.client.company_name if target_order.client else "Unknown"
            }
        }

    def transfer_pending_order_between_orders(
        self,
        db: Session,
        *,
        item_id: UUID,
        source_order_id: UUID,
        target_order_id: UUID,
        quantity_to_transfer: int,
        created_by_id: UUID
    ) -> Dict[str, Any]:
        """Transfer pending order item from one order to another (quantity-wise)"""
        # Note: This is more complex as it involves creating a new pending order for the target
        # For simplicity, we'll implement this as: reduce from source, allocate to target

        # Get pending order item
        pending_item = self.get_pending_order_item_with_details(db=db, item_id=item_id)

        # Verify the pending item is associated with the source order
        if str(pending_item.original_order_id) != str(source_order_id):
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Pending order item is not associated with the specified source order"
            )

        # Use the allocate function to move to target order
        result = self.allocate_pending_order_to_order(
            db=db,
            item_id=item_id,
            target_order_id=target_order_id,
            quantity_to_transfer=quantity_to_transfer,
            created_by_id=created_by_id
        )

        # Update message for transfer context
        result["message"] = f"Successfully transferred {quantity_to_transfer} items from {pending_item.original_order.frontend_id if pending_item.original_order else 'unknown'} to {result['allocation_details']['target_order_frontend_id']}"

        return result

    def cancel_pending_order_item(
        self,
        db: Session,
        *,
        item_id: UUID,
        cancelled_by_id: UUID
    ) -> Dict[str, Any]:
        """
        Cancel/delete a pending order item by setting quantity_pending to 0 and status to resolved.
        This removes it from pending lists and algorithms without physical deletion.
        """
        from datetime import datetime
        from fastapi import HTTPException

        # Get pending order item
        pending_item = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.id == item_id
        ).first()

        if not pending_item:
            raise HTTPException(status_code=404, detail="Pending order item not found")

        # Validate current status - only allow cancellation of pending items
        if pending_item._status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel pending order item with status '{pending_item._status}'. Only 'pending' items can be cancelled."
            )

        # Store original values for response
        original_quantity = pending_item.quantity_pending
        original_status = pending_item._status

        # Cancel the pending order item
        pending_item.quantity_pending = 0
        pending_item._status = "resolved"
        pending_item.resolved_at = datetime.utcnow()

        try:
            db.commit()

            return {
                "message": f"Successfully cancelled pending order item {pending_item.frontend_id}",
                "cancelled_item": {
                    "id": str(pending_item.id),
                    "frontend_id": pending_item.frontend_id,
                    "width_inches": float(pending_item.width_inches),
                    "gsm": pending_item.gsm,
                    "bf": float(pending_item.bf),
                    "shade": pending_item.shade,
                    "original_quantity_pending": original_quantity,
                    "original_status": original_status,
                    "new_quantity_pending": pending_item.quantity_pending,
                    "new_status": pending_item._status,
                    "resolved_at": pending_item.resolved_at.isoformat() if pending_item.resolved_at else None
                },
                "cancelled_by_id": str(cancelled_by_id),
                "cancelled_at": pending_item.resolved_at.isoformat() if pending_item.resolved_at else None
            }
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to cancel pending order item: {str(e)}")


# UNUSED FUNCTION - Replaced by inline manual cut processing in start_production_from_pending_orders_impl
# This function was replaced to avoid database transaction conflicts and improve error handling


def start_production_from_pending_orders_impl(db: Session, *, request_data) -> Dict[str, Any]:
    """Start production from selected pending orders - same as main planning but for pending flow"""
    import logging
    from datetime import datetime, timedelta
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
    
    # Log manual cuts specifically
    manual_cuts_count = sum(1 for cut in selected_cut_rolls_dict if cut.get('is_manual_cut', False) or cut.get('source_type') == 'manual_cut')
    if manual_cuts_count > 0:
        logger.info(f"🔧 MANUAL CUTS DETECTED: {manual_cuts_count} manual cuts in {len(selected_cut_rolls_dict)} total cuts")
    
    # Separate manual cuts from regular pending order cuts
    regular_cut_rolls = [cut_roll for cut_roll in selected_cut_rolls_dict if cut_roll.get("source_pending_id")]
    manual_cut_rolls = [cut_roll for cut_roll in selected_cut_rolls_dict if cut_roll.get("is_manual_cut", False) or cut_roll.get("source_type") == "manual_cut"]
    
    logger.info(f"🔄 SEPARATED CUTS: {len(regular_cut_rolls)} regular, {len(manual_cut_rolls)} manual")
    
    # Log manual cut details for debugging
    for i, cut_roll in enumerate(selected_cut_rolls_dict):
        if cut_roll.get("is_manual_cut", False) or cut_roll.get("source_type") == "manual_cut":
            client_id = cut_roll.get("manual_cut_client_id")
            client_name = cut_roll.get("manual_cut_client_name")
            width = cut_roll.get("width_inches")
            logger.info(f" {cut_roll}")
    
    # Additional check for manual cuts based on QR code pattern
    additional_manual_cuts = [cut_roll for cut_roll in selected_cut_rolls_dict 
                             if cut_roll.get("qr_code", "").startswith("MANUAL_CUT_") and cut_roll not in manual_cut_rolls]
    
    if additional_manual_cuts:
        logger.info(f"🔍 Found {len(additional_manual_cuts)} additional manual cuts by QR code pattern")
        manual_cut_rolls.extend(additional_manual_cuts)
        
    logger.info(f"🔄 FINAL SEPARATION: {len(regular_cut_rolls)} regular, {len(manual_cut_rolls)} manual")
    
    # Manual cuts will be processed later in the function inline (around line 748+)
    # This avoids database transaction conflicts and provides better error handling
    
    all_pending_order_ids = [cut_roll.get("source_pending_id") for cut_roll in regular_cut_rolls]
    
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
    
    # Use original cut rolls - manual cuts will get order info during inline processing later
    updated_cut_rolls_dict = selected_cut_rolls_dict
    
    # ✅ NEW: Create cut_pattern array with same structure as regular orders
    cut_pattern = []
    for index, cut_roll in enumerate(updated_cut_rolls_dict):
        # Get company name - handle both pending orders and manual cuts
        company_name = 'Unknown Company'

        # Check if this is a manual cut first
        if cut_roll.get("is_manual_cut") or cut_roll.get("source_type") == "manual_cut":
            # Manual cut - get client name directly from frontend data
            company_name = cut_roll.get("manual_cut_client_name", "Unknown Manual Client")
            logger.info(f"✅ Manual cut company: {company_name} for manual cut {cut_roll.get('qr_code', 'unknown')}")
        elif cut_roll.get("source_pending_id"):
            # Regular pending order - resolve from pending order's original order
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
            "source_type": cut_roll.get("source_type", "pending_order"),  # Use actual source_type from frontend
            "source_pending_id": cut_roll.get("source_pending_id"),
            "company_name": company_name,
            # Add manual cut specific fields if present
            "is_manual_cut": cut_roll.get("is_manual_cut", False),
            "manual_cut_client_id": cut_roll.get("manual_cut_client_id"),
            "manual_cut_client_name": cut_roll.get("manual_cut_client_name"),
            "description": cut_roll.get("description")
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
    
    # Update pending orders - Process each cut_roll individually (each represents 1 piece)
    updated_pending_orders = []
    
    logger.info(f"📝 PENDING QUANTITY UPDATE: Processing {len(regular_cut_rolls)} regular cut_rolls individually")
    
    # Initialize tracking variables
    successful_reductions = 0
    skipped_reductions = 0
    
    # Initialize pending order tracking variables
    unique_pending_ids = list(set(cut_roll.get("source_pending_id") for cut_roll in regular_cut_rolls if cut_roll.get("source_pending_id")))
    before_state = {}
    expected_reductions = {}
    total_before = 0
    expected_total_reduction = 0
    after_state = {}
    total_after = 0
    actual_total_reduction = 0
    
    # Process regular cut rolls for pending quantity updates
    if len(regular_cut_rolls) == 0:
        logger.info("📋 No regular cuts found - processing manual cuts only")
    else:
        if unique_pending_ids:
            logger.info(f"📊 Processing {len(unique_pending_ids)} unique pending orders")
            for pending_id in unique_pending_ids:
                try:
                    pending_uuid = UUID(pending_id)
                    pending_order = db.query(models.PendingOrderItem).filter(
                        models.PendingOrderItem.id == pending_uuid
                    ).first()
                    if pending_order:
                        before_state[pending_id] = {
                            'frontend_id': pending_order.frontend_id,
                            'pending': pending_order.quantity_pending,
                            'fulfilled': pending_order.quantity_fulfilled or 0
                        }
                        total_before += pending_order.quantity_pending
                except Exception as e:
                    logger.error(f"Error reading pending order {pending_id[:8]}: {e}")
        
        # Calculate expected reductions per pending order
        for cut_roll in regular_cut_rolls:
            pending_id = cut_roll.get("source_pending_id")
            if pending_id:
                expected_reductions[pending_id] = expected_reductions.get(pending_id, 0) + 1
        
        # Calculate total expected reduction
        expected_total_reduction = sum(expected_reductions.values())
        
        # Process each regular cut_roll individually
        for i, cut_roll in enumerate(regular_cut_rolls):
            source_pending_id = cut_roll.get("source_pending_id")
        
            if not source_pending_id or source_pending_id in ["None", "null"]:
                continue
            
            try:
                pending_uuid = UUID(source_pending_id)
                
                # Get pending order
                pending_order = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.id == pending_uuid,
                    models.PendingOrderItem._status == "pending"
                ).first()
                
                if pending_order and pending_order.quantity_pending > 0:
                    old_pending = pending_order.quantity_pending
                    old_fulfilled = pending_order.quantity_fulfilled or 0
                    
                    # Reduce by 1 for each cut_roll
                    pending_order.quantity_fulfilled = old_fulfilled + 1
                    pending_order.quantity_pending = max(0, old_pending - 1)
                    
                    # Update status if fully resolved
                    if pending_order.quantity_pending <= 0 and pending_order._status != "resolved":
                        pending_order._status = "resolved"
                        pending_order.resolved_at = datetime.utcnow()
                        logger.info(f"✅ RESOLVED: {pending_order.frontend_id} (was {old_pending}, now fulfilled)")
                    elif old_pending != pending_order.quantity_pending:
                        logger.info(f"📉 REDUCED: {pending_order.frontend_id} {old_pending}→{pending_order.quantity_pending} pending")
                    
                    # Add to updated list only once per unique pending order
                    pending_id_str = str(pending_order.id)
                    if pending_id_str not in updated_pending_orders:
                        updated_pending_orders.append(pending_id_str)
                    
                    successful_reductions += 1
                else:
                    skipped_reductions += 1
                    
            except Exception as e:
                logger.error(f"❌ Error processing cut roll with pending_id {source_pending_id}: {e}")
                skipped_reductions += 1
                continue
    
    # Close the else block for regular cut processing
    
    # ====== MANUAL CUTS PROCESSING: Create Orders for Manual Cuts ======
    created_manual_orders = []
    created_manual_order_items = []
    client_orders = {}  # Initialize outside so it's accessible during inventory creation
    
    if manual_cut_rolls:
        logger.info(f"🔧 PROCESSING {len(manual_cut_rolls)} MANUAL CUTS")
        
        # Group manual cuts by (client_id + paper_specs + width)
        manual_cut_groups = {}
        for cut_roll in manual_cut_rolls:
            logger.info(f"🔍 DEBUG: cut_roll type = {type(cut_roll)}, value = {cut_roll}")
            client_id = cut_roll.get("manual_cut_client_id")
            client_name = cut_roll.get("manual_cut_client_name")
            
            if not client_id:
                logger.error(f"❌ MANUAL CUT VALIDATION FAILED: Missing client_id for cut {cut_roll.get('qr_code', 'unknown')}")
                logger.error(f"   Manual cut data: width={cut_roll.get('width_inches')}, description='{cut_roll.get('description', 'N/A')}'")
                logger.error(f"   This indicates the frontend sent invalid manual cut data - check client selection in UI")
                continue
            if not client_name:
                logger.error(f"❌ MANUAL CUT VALIDATION FAILED: Missing client_name for cut {cut_roll.get('qr_code', 'unknown')}")
                logger.error(f"   Client ID was: {client_id}, but client_name is missing")
                logger.error(f"   This suggests client lookup failed in frontend - check client data loading")
                continue
                
            gsm = cut_roll.get("gsm", 0)
            bf = cut_roll.get("bf", 0.0)
            shade = cut_roll.get("shade", "")
            width = cut_roll.get("width_inches", 0.0)
            
            # Create grouping key
            group_key = f"{client_id}|{gsm}|{bf}|{shade}|{width}"
            
            if group_key not in manual_cut_groups:
                manual_cut_groups[group_key] = {
                    'client_id': client_id,
                    'client_name': client_name,
                    'gsm': gsm,
                    'bf': bf,
                    'shade': shade,
                    'width': width,
                    'cuts': []
                }
            manual_cut_groups[group_key]['cuts'].append(cut_roll)
        
        logger.info(f"📊 Grouped into {len(manual_cut_groups)} order groups by client+specs+width")
        
        # Create orders for each client (using the client_orders dict defined above)
        logger.info(f"🔨 MANUAL CUT ORDER CREATION: Processing {len(manual_cut_groups)} groups")
        
        for group_key, group_data in manual_cut_groups.items():
            client_id = group_data['client_id']
            logger.info(f"🔧 PROCESSING GROUP: {group_key}")
            logger.info(f"   → Client ID: {client_id}")
            logger.info(f"   → Client Name: {group_data['client_name']}")
            logger.info(f"   → Paper Specs: {group_data['gsm']}GSM {group_data['bf']}BF {group_data['shade']}")
            logger.info(f"   → Width: {group_data['width']}\"")
            logger.info(f"   → Number of cuts: {len(group_data['cuts'])}")
            
            # Create or get OrderMaster for this client
            if client_id not in client_orders:
                logger.info(f"📋 CREATING NEW ORDER for client {client_id}")
                try:
                    # Get client info
                    logger.info(f"🔍 LOOKING UP CLIENT: {client_id}")
                    client = db.query(models.ClientMaster).filter(models.ClientMaster.id == UUID(client_id)).first()
                    if not client:
                        logger.error(f"❌ CLIENT NOT FOUND: {client_id} - skipping manual cuts for {group_data['client_name']}")
                        logger.error(f"   Available clients in DB: {[str(c.id) for c in db.query(models.ClientMaster).limit(5).all()]}")
                        continue
                    
                    logger.info(f"✅ FOUND CLIENT: {client.company_name} (ID: {client.id})")
                    
                    # Create OrderMaster
                    frontend_id = FrontendIDGenerator.generate_frontend_id("order_master", db)
                    logger.info(f"🏗️ CREATING ORDER MASTER:")
                    logger.info(f"   → Frontend ID: {frontend_id}")
                    logger.info(f"   → Client ID: {client_id}")
                    logger.info(f"   → Created by: {created_by_id}")
                    
                    order_master = models.OrderMaster(
                        frontend_id=frontend_id,
                        client_id=UUID(client_id),
                        status="in_process",
                        created_by_id=UUID(created_by_id),
                        created_at=datetime.utcnow(),
                        delivery_date=datetime.utcnow() + timedelta(days=7)  # Default 7 days
                    )
                    
                    logger.info(f"📝 ADDING ORDER TO DATABASE...")
                    db.add(order_master)
                    db.flush()  # Get the ID
                    logger.info(f"✅ ORDER CREATED: ID={order_master.id}, Frontend={order_master.frontend_id}")
                    
                    client_orders[client_id] = order_master
                    created_manual_orders.append({
                        "order": order_master,
                        "items": []  # Will be populated with order items
                    })
                    
                    logger.info(f"✅ CREATED ORDER: {order_master.frontend_id} for {client.company_name}")
                    
                except Exception as e:
                    logger.error(f"❌ ORDER CREATION FAILED for client {client_id}: {e}")
                    logger.error(f"   Exception type: {type(e)}")
                    import traceback
                    logger.error(f"   Stack trace: {traceback.format_exc()}")
                    continue
            else:
                logger.info(f"🔄 REUSING EXISTING ORDER for client {client_id}: {client_orders[client_id].frontend_id}")
            
            # Create OrderItem for this group
            logger.info(f"📦 CREATING ORDER ITEM for group {group_key}")
            try:
                order_master = client_orders[client_id]
                quantity = len(group_data['cuts'])  # Number of manual cuts for this spec+width
                
                # Find or create paper master for this specification
                logger.info(f"🔍 LOOKING FOR PAPER MASTER: {group_data['gsm']}GSM {group_data['bf']}BF {group_data['shade']}")
                paper_master = db.query(models.PaperMaster).filter(
                    models.PaperMaster.gsm == group_data['gsm'],
                    models.PaperMaster.bf == group_data['bf'],
                    models.PaperMaster.shade == group_data['shade']
                ).first()
                
                if not paper_master:
                    logger.info(f"📄 CREATING NEW PAPER MASTER")
                    # Create new paper master for this specification
                    paper_master = models.PaperMaster(
                        name=f"{group_data['gsm']}GSM {group_data['bf']}BF {group_data['shade']}",
                        gsm=group_data['gsm'],
                        bf=group_data['bf'],
                        shade=group_data['shade'],
                        frontend_id=FrontendIDGenerator.generate_frontend_id("paper_master", db),
                        created_by_id=UUID(created_by_id),
                        created_at=datetime.utcnow()
                    )
                    db.add(paper_master)
                    db.flush()  # Get the paper_master.id
                    logger.info(f"✅ PAPER MASTER CREATED: ID={paper_master.id}, Frontend={paper_master.frontend_id}")
                else:
                    logger.info(f"✅ FOUND EXISTING PAPER MASTER: ID={paper_master.id}, Frontend={paper_master.frontend_id}")
                
                # Estimate weight and set default rate
                estimated_weight_kg = quantity * 50.0  # Rough estimate
                default_rate = 100.0  # Default rate per kg
                total_amount = estimated_weight_kg * default_rate
                
                logger.info(f"💰 ORDER ITEM CALCULATIONS:")
                logger.info(f"   → Quantity: {quantity} rolls")
                logger.info(f"   → Estimated weight: {estimated_weight_kg} kg")
                logger.info(f"   → Rate: {default_rate} per kg")
                logger.info(f"   → Total amount: {total_amount}")
                
                item_frontend_id = FrontendIDGenerator.generate_frontend_id("order_item", db)
                logger.info(f"🏗️ CREATING ORDER ITEM:")
                logger.info(f"   → Frontend ID: {item_frontend_id}")
                logger.info(f"   → Order ID: {order_master.id}")
                logger.info(f"   → Paper ID: {paper_master.id}")
                logger.info(f"   → Width: {group_data['width']}\"")
                
                order_item = models.OrderItem(
                    frontend_id=item_frontend_id,
                    order_id=order_master.id,
                    paper_id=paper_master.id,
                    width_inches=group_data['width'],
                    quantity_rolls=quantity,
                    quantity_kg=estimated_weight_kg,
                    rate=default_rate,
                    amount=total_amount,
                    quantity_fulfilled=0,
                    quantity_in_pending=0,  # Manual cuts don't go to pending
                    item_status="in_process",
                    created_at=datetime.utcnow()
                )
                
                logger.info(f"📝 ADDING ORDER ITEM TO DATABASE...")
                db.add(order_item)
                db.flush()
                logger.info(f"✅ ORDER ITEM CREATED: ID={order_item.id}, Frontend={order_item.frontend_id}")
                
                created_manual_order_items.append(str(order_item.id))
                
                # Add order item to the correct manual order's items list
                for manual_order in created_manual_orders:
                    if manual_order["order"].id == order_master.id:
                        manual_order["items"].append(order_item)
                        break
                        
                logger.info(f"✅ CREATED ORDER ITEM: {order_item.frontend_id} - {quantity}x {group_data['width']}\" {group_data['shade']} {group_data['gsm']}GSM")
                
            except Exception as e:
                logger.error(f"❌ Error creating order item for group {group_key}: {e}")
                logger.error(f"   Exception type: {type(e)}")
                import traceback
                logger.error(f"   Stack trace: {traceback.format_exc()}")
                continue
        
        if created_manual_orders:
            logger.info(f"🎉 MANUAL CUTS SUCCESS: Created {len(created_manual_orders)} orders, {len(created_manual_order_items)} order items")
            for i, manual_order in enumerate(created_manual_orders):
                order = manual_order["order"]
                items = manual_order["items"]
                logger.info(f"   → Order {i+1}: {order.frontend_id} with {len(items)} items")
        else:
            logger.error(f"❌ MANUAL CUTS FAILED: No orders created from {len(manual_cut_rolls)} manual cuts")
            logger.error(f"   Manual cut groups: {len(manual_cut_groups)}")
            logger.error(f"   Client orders dict: {len(client_orders)}")
    
    # Group cut rolls by paper specification
    jumbo_roll_width = request_data.jumbo_roll_width or 118
    paper_spec_groups = {}
    all_cut_rolls_for_plan = regular_cut_rolls + manual_cut_rolls
    
    for i, cut_roll in enumerate(all_cut_rolls_for_plan):
        individual_roll_number = cut_roll.get("individual_roll_number")
        
        if individual_roll_number:
            paper_spec_key = (
                cut_roll.get("gsm"),
                cut_roll.get("bf"), 
                cut_roll.get("shade")
            )
            
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
            
    # Create inventory hierarchy
    
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
    
    # Create cut roll inventory
    logger.info(f"🔧 Creating {len(selected_cut_rolls_dict)} cut roll inventory items...")
    
    for i, cut_roll in enumerate(selected_cut_rolls_dict):
        try:
            
            # Find the paper record for this cut roll
            cut_roll_paper = db.query(models.PaperMaster).filter(
                models.PaperMaster.gsm == cut_roll["gsm"],
                models.PaperMaster.bf == cut_roll["bf"], 
                models.PaperMaster.shade == cut_roll["shade"]
            ).first()
            
            if not cut_roll_paper:
                logger.error(f"❌ No paper found for GSM={cut_roll['gsm']}, BF={cut_roll['bf']}, Shade={cut_roll['shade']} - skipping")
                continue
            
            # Find a suitable 118" roll to attach this cut to
            suitable_118_roll = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.paper_id == cut_roll_paper.id,
                models.InventoryMaster.roll_type == "118",
                models.InventoryMaster.status == "consumed"
            ).first()
            
            # Create the cut roll inventory record
            barcode_id = BarcodeGenerator.generate_cut_roll_barcode(db)
            frontend_id = FrontendIDGenerator.generate_frontend_id("inventory_master", db)
            
            # Link cut roll to order
            if cut_roll.get("is_manual_cut", False):
                # Manual cut - link to created manual order
                client_id = cut_roll.get("manual_cut_client_id")
                order_uuid = client_orders[client_id].id if client_id and client_id in client_orders else None
            else:
                # Regular cut - link to original order
                order_id = cut_roll.get("order_id")
                if order_id:
                    try:
                        order_uuid = UUID(order_id)
                        logger.info(f"✅ REGULAR CUT ORDER LINK: {order_id}")
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
            
            db.add(inventory_item)
            db.flush()
            created_inventory.append(inventory_item)
            
        except Exception as e:
            logger.error(f"❌ Error creating cut roll inventory {i+1}: {e}")
            logger.error(f"❌ Cut roll data: {cut_roll}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
    
    # Link inventory items to plan
    created_plan_links = []
    valid_inventory_items = [item for item in created_inventory if item and item.id is not None]
    
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
    
    # WASTAGE PROCESSING FOR PENDING ORDERS
    # Create wastage from pending order source types
    pending_order_wastage_data = []
    logger.info(f"🗑️ PENDING ORDER WASTAGE: Processing wastage from pending orders")
    
    # Extract wastage information from selected_cut_rolls with pending_order source
    for cut_roll in selected_cut_rolls_dict:
        if cut_roll.get('source_type') == 'pending_order' and cut_roll.get('source_pending_id'):
            # Extract wastage width from the cut roll data
            # This could come from different fields depending on how data is structured
            wastage_width = cut_roll.get('wastage_width') or cut_roll.get('leftover_width')
            
            # Create wastage for any valid width
            if wastage_width:
                pending_wastage_item = {
                    "width_inches": float(wastage_width),
                    "paper_id": cut_roll.get('paper_id'),
                    "gsm": cut_roll.get('gsm'),
                    "bf": cut_roll.get('bf'),
                    "shade": cut_roll.get('shade'),
                    "source_plan_id": str(db_plan.id),
                    "source_jumbo_roll_id": cut_roll.get('jumbo_roll_id'),
                    "individual_roll_number": cut_roll.get('individual_roll_number'),
                    "notes": f"Wastage from pending order {cut_roll.get('source_pending_id')[:8]}",
                    "source_pending_id": cut_roll.get('source_pending_id')
                }
                pending_order_wastage_data.append(pending_wastage_item)
                logger.info(f"🗑️ PENDING ORDER WASTAGE: Found {wastage_width}\" potential wastage from pending order {cut_roll.get('source_pending_id')[:8]}")
    
    # Process pending order wastage
    raw_wastage_data = request_data.wastage_data if hasattr(request_data, 'wastage_data') else []
    
    # Convert Pydantic objects to dicts for easier access (same as we do with cut_rolls)
    wastage_data = [item.model_dump() if hasattr(item, 'model_dump') else dict(item) for item in raw_wastage_data]
    logger.info(f"🗑️ WASTAGE: Converted {len(wastage_data)} wastage items to dictionaries")
    
    # Process pending order wastage and add to the regular wastage data
    if pending_order_wastage_data:
        # Extend the main wastage data with pending order wastage
        wastage_data.extend(pending_order_wastage_data)
        logger.info(f"🗑️ PENDING ORDER WASTAGE: Added {len(pending_order_wastage_data)} wastage items from pending orders to processing queue")
    
    # If there's wastage data without a source_plan_id, set it to the current plan
    for item in wastage_data:
        if not item.get('source_plan_id'):
            item['source_plan_id'] = str(db_plan.id)
            
    logger.info(f"🗑️ WASTAGE PROCESSING: Total of {len(wastage_data)} wastage items (including {len(pending_order_wastage_data)} from pending orders)")
    
    # Process wastage data to create wastage inventory items
    if wastage_data:
        logger.info(f"🗑️ Creating {len(wastage_data)} wastage inventory items...")
        
        for i, wastage_item in enumerate(wastage_data):
            try:
                # Validate wastage width is positive
                width = float(wastage_item.get("width_inches", 0))
                if width <= 0:
                    logger.warning(f"⚠️ WASTAGE SKIP: Item {i+1} width {width}\" is not positive")
                    continue
                
                # Generate wastage IDs
                wastage_barcode_id = BarcodeGenerator.generate_wastage_barcode(db)
                
                # Find paper record for wastage
                paper_id = None
                received_paper_id = wastage_item.get("paper_id")
                
                # Try to use provided paper_id first
                if received_paper_id and received_paper_id.strip():
                    try:
                        paper_id = UUID(received_paper_id)
                        paper_record = db.query(models.PaperMaster).filter(models.PaperMaster.id == paper_id).first()
                        if not paper_record:
                            paper_id = None
                    except (ValueError, TypeError):
                        paper_id = None
                
                # If no valid paper_id, find it by GSM/BF/Shade specifications
                if not paper_id:
                    gsm = wastage_item.get('gsm')
                    bf = wastage_item.get('bf') 
                    shade = wastage_item.get('shade')
                    
                    paper_record = db.query(models.PaperMaster).filter(
                        models.PaperMaster.gsm == gsm,
                        models.PaperMaster.bf == bf,
                        models.PaperMaster.shade == shade
                    ).first()
                    
                    if paper_record:
                        paper_id = paper_record.id
                    else:
                        logger.error(f"❌ WASTAGE ERROR: No paper found for specs: GSM={gsm}, BF={bf}, Shade='{shade}'")
                        continue
                
                # Find source plan and jumbo roll if provided
                source_plan_id = None
                source_jumbo_roll_id = None
                
                try:
                    source_plan_id = UUID(wastage_item.get("source_plan_id"))
                except (ValueError, TypeError):
                    source_plan_id = db_plan.id
                
                if wastage_item.get("source_jumbo_roll_id"):
                    try:
                        source_jumbo_roll_id = UUID(wastage_item.get("source_jumbo_roll_id"))
                    except (ValueError, TypeError):
                        pass
                
                # Create wastage inventory record
                wastage_inventory = models.WastageInventory(
                    width_inches=width,
                    paper_id=paper_id,
                    weight_kg=0.0,  # Will be set via QR scan later
                    source_plan_id=source_plan_id,
                    source_jumbo_roll_id=source_jumbo_roll_id,
                    individual_roll_number=wastage_item.get("individual_roll_number"),
                    status="available",  # Using string value since we don't have enum import
                    location="WASTE_STORAGE",
                    notes=wastage_item.get("notes"),
                    created_by_id=UUID(created_by_id) if created_by_id else None,
                    barcode_id=wastage_barcode_id,
                    frontend_id=FrontendIDGenerator.generate_frontend_id("wastage_inventory", db)
                )
                
                db.add(wastage_inventory)
                db.flush()  # Get the ID and frontend_id
                created_wastage.append(wastage_inventory)
                
                logger.info(f"🗑️ WASTAGE CREATED: {wastage_inventory.frontend_id} - {width}\" paper (Barcode: {wastage_barcode_id})")
                
            except Exception as e:
                logger.error(f"❌ WASTAGE ERROR: Failed to create wastage item {i+1}: {e}")
                continue
        
        logger.info(f"✅ WASTAGE COMPLETE: Created {len(created_wastage)} wastage inventory items")
    else:
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
    
    # Summary of reductions
    logger.info(f"📊 REDUCTION SUMMARY: {successful_reductions} successful, {skipped_reductions} skipped, {len(regular_cut_rolls)} total cut_rolls")
    
    # Commit all changes
    logger.info(f"📝 ABOUT TO COMMIT: {len(updated_pending_orders)} pending orders updated")
    
    # VERIFICATION: Check actual database state before commit
    logger.info("🔍 PRE-COMMIT VERIFICATION: Checking pending orders in session...")
    for pending_id_str in set(updated_pending_orders):  # Remove duplicates
        try:
            pending_uuid = UUID(pending_id_str)
            pending_order = db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.id == pending_uuid
            ).first()
            if pending_order:
                logger.info(f"   → {pending_order.frontend_id}: pending={pending_order.quantity_pending}, fulfilled={pending_order.quantity_fulfilled}, status={pending_order._status}")
        except Exception as e:
            logger.error(f"   → Error checking {pending_id_str[:8]}: {e}")
    
    try:
        db.commit()
        logger.info("✅ DATABASE COMMIT: All changes committed successfully")
        
        # COMPREHENSIVE POST-COMMIT VERIFICATION: Check actual final state  
        logger.info("🔍 POST-PRODUCTION DATABASE STATE:")
        
        for pending_id in unique_pending_ids:
            try:
                pending_uuid = UUID(pending_id)
                pending_order = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.id == pending_uuid
                ).first()
                if pending_order and pending_id in before_state:
                    before = before_state[pending_id]
                    actual_reduction = before['pending'] - pending_order.quantity_pending
                    expected_reduction = expected_reductions.get(pending_id, 0)
                    
                    after_state[pending_id] = {
                        'frontend_id': pending_order.frontend_id,
                        'width': pending_order.width_inches,
                        'pending': pending_order.quantity_pending,
                        'fulfilled': pending_order.quantity_fulfilled or 0,
                        'status': pending_order._status
                    }
                    
                    total_after += pending_order.quantity_pending
                    actual_total_reduction += actual_reduction
                    
                    if actual_reduction == expected_reduction:
                        logger.info(f"   ✅ {pending_order.frontend_id}: {before['pending']} → {pending_order.quantity_pending} (-{actual_reduction}) CORRECT")
                    else:
                        logger.error(f"   ❌ {pending_order.frontend_id}: {before['pending']} → {pending_order.quantity_pending} (-{actual_reduction}) EXPECTED -{expected_reduction}")
                        
            except Exception as e:
                logger.error(f"   → Error checking {pending_id[:8]}: {e}")
        
        logger.info(f"📊 FINAL VERIFICATION:")
        logger.info(f"   → Total before: {total_before}")
        logger.info(f"   → Total after: {total_after}")
        logger.info(f"   → Expected reduction: -{expected_total_reduction}")
        logger.info(f"   → Actual reduction: -{actual_total_reduction}")
        logger.info(f"   → Cut_rolls sent: {len(regular_cut_rolls)}")
        logger.info(f"   → Successful reductions: {successful_reductions}")
        logger.info(f"   → Skipped reductions: {skipped_reductions}")
        
        if actual_total_reduction == expected_total_reduction:
            logger.info("✅ PERFECT MATCH: Database reduction matches expectations")
        else:
            logger.error(f"❌ MISMATCH: Expected -{expected_total_reduction}, got -{actual_total_reduction}, difference: {expected_total_reduction - actual_total_reduction}")
        
        # Additional verification logs
        logger.info("🔍 POST-COMMIT VERIFICATION: Re-querying database...")
        for pending_id_str in set(updated_pending_orders):  # Remove duplicates
            try:
                pending_uuid = UUID(pending_id_str)
                pending_order = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.id == pending_uuid
                ).first()
                if pending_order:
                    logger.info(f"   → {pending_order.frontend_id}: pending={pending_order.quantity_pending}, fulfilled={pending_order.quantity_fulfilled}, status={pending_order._status}")
            except Exception as e:
                logger.error(f"   → Error re-checking {pending_id_str[:8]}: {e}")
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
            "intermediate_118_rolls_created": len(created_118_rolls),
            "manual_orders_created": len(created_manual_orders),
            "manual_order_items_created": sum(len(order["items"]) for order in created_manual_orders)
        },
        "details": {
            "updated_orders": updated_orders,  # Already List[str]
            "updated_order_items": updated_order_items,  # Already List[str] 
            "updated_pending_orders": updated_pending_orders,  # Already List[str]
            "created_inventory": [str(inv.id) for inv in created_inventory],  # List[str]
            "created_jumbo_rolls": [str(jr.id) for jr in created_jumbo_rolls],  # List[str]
            "created_118_rolls": [str(r118.id) for r118 in created_118_rolls],  # List[str]
            "created_wastage": [str(w.id) for w in created_wastage],  # List[str]
            "created_gupta_orders": [],  # List[str] - empty for pending flow
            "created_manual_orders": [order["order"].frontend_id for order in created_manual_orders],  # List[str]
            "created_manual_order_items": [f"{order['order'].frontend_id}: {len(order['items'])} items" for order in created_manual_orders]  # List[str]
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