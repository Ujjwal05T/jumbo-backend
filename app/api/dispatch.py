from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, and_, or_
from typing import List, Optional
import logging
from datetime import datetime, date
import uuid

from .base import get_db
from .. import models, schemas
from ..crud_operations import get_client

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# DISPATCH HISTORY ENDPOINTS
# ============================================================================

@router.get("/dispatch/history", tags=["Dispatch History"])
def get_dispatch_history(
    skip: int = 0,
    limit: int = 50,
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get dispatch history with filtering and pagination"""
    try:
        # Base query with relationships
        query = db.query(models.DispatchRecord).options(
            joinedload(models.DispatchRecord.client),
            joinedload(models.DispatchRecord.primary_order),
            joinedload(models.DispatchRecord.created_by),
            joinedload(models.DispatchRecord.dispatch_items)
        )
        
        # Apply filters
        if client_id and client_id.strip() and client_id != "all":
            try:
                client_uuid = uuid.UUID(client_id)
                query = query.filter(models.DispatchRecord.client_id == client_uuid)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid client ID format")
        
        if status and status.strip() and status != "all":
            query = query.filter(models.DispatchRecord.status == status)
        
        # Date range filters
        if from_date and from_date.strip():
            try:
                from_dt = datetime.strptime(from_date, "%Y-%m-%d")
                query = query.filter(models.DispatchRecord.dispatch_date >= from_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid from_date format. Use YYYY-MM-DD")
        
        if to_date and to_date.strip():
            try:
                to_dt = datetime.strptime(to_date, "%Y-%m-%d")
                # Include the entire day
                to_dt = to_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(models.DispatchRecord.dispatch_date <= to_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid to_date format. Use YYYY-MM-DD")
        
        # Search filter (search in dispatch number, reference number, driver name, vehicle number)
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    models.DispatchRecord.dispatch_number.like(search_term),
                    models.DispatchRecord.reference_number.like(search_term),
                    models.DispatchRecord.driver_name.like(search_term),
                    models.DispatchRecord.vehicle_number.like(search_term)
                )
            )
        
        # Get total count before pagination
        total_count = query.count()
        
        # Apply pagination and ordering
        dispatches = query.order_by(desc(models.DispatchRecord.dispatch_date)).offset(skip).limit(limit).all()
        
        # Format response
        dispatch_list = []
        for dispatch in dispatches:
            dispatch_list.append({
                "id": str(dispatch.id),
                "frontend_id": dispatch.frontend_id,
                "dispatch_number": dispatch.dispatch_number,
                "reference_number": dispatch.reference_number,
                "dispatch_date": dispatch.dispatch_date.isoformat() if dispatch.dispatch_date else None,
                "order_frontend_id": dispatch.order_frontend_id,  # Return order frontend ID
                "client": {
                    "id": str(dispatch.client.id),
                    "company_name": dispatch.client.company_name,
                    "contact_person": dispatch.client.contact_person
                } if dispatch.client else None,
                "primary_order": {
                    "id": str(dispatch.primary_order.id),
                    "order_number": dispatch.primary_order.frontend_id
                } if dispatch.primary_order else None,
                "vehicle_number": dispatch.vehicle_number,
                "driver_name": dispatch.driver_name,
                "driver_mobile": dispatch.driver_mobile,
                "payment_type": dispatch.payment_type,
                "status": dispatch.status,
                "total_items": dispatch.total_items,
                "total_weight_kg": float(dispatch.total_weight_kg) if dispatch.total_weight_kg else 0.0,
                "created_by": {
                    "id": str(dispatch.created_by.id),
                    "name": dispatch.created_by.name
                } if dispatch.created_by else None,
                "created_at": dispatch.created_at.isoformat() if dispatch.created_at else None,
                "delivered_at": dispatch.delivered_at.isoformat() if dispatch.delivered_at else None,
                "items_count": len(dispatch.dispatch_items) if dispatch.dispatch_items else 0
            })
        
        return {
            "dispatches": dispatch_list,
            "total_count": total_count,
            "current_page": (skip // limit) + 1 if limit > 0 else 1,
            "total_pages": (total_count + limit - 1) // limit if limit > 0 else 1,
            "has_next": skip + limit < total_count,
            "has_previous": skip > 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching dispatch history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dispatch/{dispatch_id}/details", tags=["Dispatch History"])
def get_dispatch_details(
    dispatch_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed information for a specific dispatch record"""
    try:
        dispatch_uuid = uuid.UUID(dispatch_id)
        
        # Query with all relationships
        dispatch = db.query(models.DispatchRecord).options(
            joinedload(models.DispatchRecord.client),
            joinedload(models.DispatchRecord.primary_order),
            joinedload(models.DispatchRecord.created_by),
            joinedload(models.DispatchRecord.dispatch_items).joinedload(models.DispatchItem.inventory)
        ).filter(models.DispatchRecord.id == dispatch_uuid).first()
        
        if not dispatch:
            raise HTTPException(status_code=404, detail="Dispatch record not found")
        
        # Format dispatch items
        items = []
        for item in dispatch.dispatch_items:
            inventory = item.inventory if hasattr(item, 'inventory') else None

            # Check if item is from wastage inventory and fetch reel_no
            reel_no = None
            is_wastage_item = False

            # Check if barcode starts with SCR or qr_code starts with WCR_
            if (item.barcode_id and item.barcode_id.startswith('SCR')) or \
               (item.qr_code and item.qr_code.startswith('WCR_')):
                is_wastage_item = True
                try:
                    # Parse QR code: WCR_{wastage_frontend_id}_{plan_id}
                    qr_to_parse = item.qr_code if item.qr_code else ""

                    if qr_to_parse.startswith('WCR_'):
                        parts = qr_to_parse.split('_')
                        if len(parts) >= 2:
                            wastage_frontend_id = parts[1]

                            # Query WastageInventory by frontend_id
                            wastage_item = db.query(models.WastageInventory).filter(
                                models.WastageInventory.frontend_id == wastage_frontend_id
                            ).first()

                            if wastage_item:
                                reel_no = wastage_item.reel_no
                                logger.debug(f"Found reel_no '{reel_no}' for wastage item QR: {item.qr_code}")
                            else:
                                logger.warning(f"WastageInventory not found for frontend_id: {wastage_frontend_id}")
                except Exception as e:
                    logger.error(f"Error parsing QR code or fetching wastage reel_no: {e}")

            items.append({
                "id": str(item.id),
                "frontend_id": item.frontend_id,
                "qr_code": item.qr_code,
                "barcode_id": is_wastage_item and reel_no or item.barcode_id,
                "width_inches": float(item.width_inches),
                "weight_kg": float(item.weight_kg),
                "paper_spec": item.paper_spec,
                "status": item.status,
                "dispatched_at": item.dispatched_at.isoformat() if item.dispatched_at else None,
                "reel_no": reel_no,
                "is_wastage_item": is_wastage_item,
                "order_frontend_id": item.order_frontend_id,  # Return order frontend ID
                "inventory": {
                    "id": str(inventory.id),
                    "location": inventory.location,
                    "roll_type": inventory.roll_type
                } if inventory else None
            })
        
        return {
            "id": str(dispatch.id),
            "frontend_id": dispatch.frontend_id,
            "dispatch_number": dispatch.dispatch_number,
            "reference_number": dispatch.reference_number,
            "dispatch_date": dispatch.dispatch_date.isoformat() if dispatch.dispatch_date else None,
            "order_date": dispatch.order_date.isoformat() if dispatch.order_date else None,
            "order_frontend_id": dispatch.order_frontend_id,  # Return order frontend ID
            "client": {
                "id": str(dispatch.client.id),
                "company_name": dispatch.client.company_name or "",
                "contact_person": dispatch.client.contact_person or "",
                "mobile": dispatch.client.phone or "",  # ClientMaster uses 'phone' field
                "email": dispatch.client.email or "",
                "address": dispatch.client.address or ""
            } if dispatch.client else {
                "id": "",
                "company_name": "Unknown Client",
                "contact_person": "",
                "mobile": "",
                "email": "",
                "address": ""
            },
            "primary_order": {
                "id": str(dispatch.primary_order.id),
                "order_number": dispatch.primary_order.frontend_id,
                "status": dispatch.primary_order.status,
                "payment_type": dispatch.primary_order.payment_type
            } if dispatch.primary_order else None,
            "vehicle_number": dispatch.vehicle_number,
            "driver_name": dispatch.driver_name,
            "driver_mobile": dispatch.driver_mobile,
            "payment_type": dispatch.payment_type,
            "status": dispatch.status,
            "total_items": dispatch.total_items,
            "total_weight_kg": float(dispatch.total_weight_kg) if dispatch.total_weight_kg else 0.0,
            "created_by": {
                "id": str(dispatch.created_by.id),
                "name": dispatch.created_by.name,
                "username": dispatch.created_by.username
            } if dispatch.created_by else None,
            "created_at": dispatch.created_at.isoformat() if dispatch.created_at else None,
            "delivered_at": dispatch.delivered_at.isoformat() if dispatch.delivered_at else None,
            "items": items
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dispatch ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching dispatch details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dispatch/stats", tags=["Dispatch History"])
def get_dispatch_stats(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get dispatch statistics for dashboard"""
    try:
        # Base query
        query = db.query(models.DispatchRecord)
        
        # Apply date filters
        if from_date and from_date.strip():
            try:
                from_dt = datetime.strptime(from_date, "%Y-%m-%d")
                query = query.filter(models.DispatchRecord.dispatch_date >= from_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid from_date format. Use YYYY-MM-DD")
        
        if to_date and to_date.strip():
            try:
                to_dt = datetime.strptime(to_date, "%Y-%m-%d")
                to_dt = to_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(models.DispatchRecord.dispatch_date <= to_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid to_date format. Use YYYY-MM-DD")
        
        # Get all dispatches
        dispatches = query.all()
        
        # Calculate statistics
        total_dispatches = len(dispatches)
        total_items = sum(d.total_items for d in dispatches)
        total_weight = sum(float(d.total_weight_kg) if d.total_weight_kg else 0 for d in dispatches)
        
        # Status breakdown
        status_counts = {}
        for dispatch in dispatches:
            status = dispatch.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Payment type breakdown
        payment_counts = {}
        for dispatch in dispatches:
            payment_type = dispatch.payment_type
            payment_counts[payment_type] = payment_counts.get(payment_type, 0) + 1
        
        # Recent dispatches (last 5)
        recent_dispatches = sorted(dispatches, key=lambda x: x.dispatch_date or datetime.min, reverse=True)[:5]
        recent_list = []
        for dispatch in recent_dispatches:
            recent_list.append({
                "id": str(dispatch.id),
                "dispatch_number": dispatch.dispatch_number,
                "client_name": dispatch.client.company_name if dispatch.client else "Unknown",
                "total_items": dispatch.total_items,
                "dispatch_date": dispatch.dispatch_date.isoformat() if dispatch.dispatch_date else None
            })
        
        return {
            "summary": {
                "total_dispatches": total_dispatches,
                "total_items_dispatched": total_items,
                "total_weight_kg": round(total_weight, 2)
            },
            "status_breakdown": status_counts,
            "payment_type_breakdown": payment_counts,
            "recent_dispatches": recent_list,
            "date_range": {
                "from_date": from_date,
                "to_date": to_date
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching dispatch stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/dispatch/{dispatch_id}/status", tags=["Dispatch History"])
def update_dispatch_status(
    dispatch_id: str,
    status_data: dict,
    db: Session = Depends(get_db)
):
    """Update dispatch status (e.g., mark as delivered)"""
    try:
        dispatch_uuid = uuid.UUID(dispatch_id)
        new_status = status_data.get("status")
        
        if not new_status:
            raise HTTPException(status_code=400, detail="Status is required")
        
        if new_status not in ["dispatched", "delivered", "returned"]:
            raise HTTPException(status_code=400, detail="Invalid status. Must be one of: dispatched, delivered, returned")
        
        dispatch = db.query(models.DispatchRecord).filter(models.DispatchRecord.id == dispatch_uuid).first()
        if not dispatch:
            raise HTTPException(status_code=404, detail="Dispatch record not found")
        
        dispatch.status = new_status
        
        # Set delivered_at timestamp if status is delivered
        if new_status == "delivered" and not dispatch.delivered_at:
            dispatch.delivered_at = datetime.utcnow()
        
        db.commit()
        db.refresh(dispatch)
        
        return {
            "message": f"Dispatch status updated to {new_status}",
            "dispatch_id": str(dispatch.id),
            "new_status": dispatch.status,
            "delivered_at": dispatch.delivered_at.isoformat() if dispatch.delivered_at else None
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dispatch ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating dispatch status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/dispatch/{dispatch_id}", tags=["Dispatch History"])
def update_dispatch_record(
    dispatch_id: str,
    update_data: schemas.DispatchUpdateData,
    db: Session = Depends(get_db)
):
    """
    Update dispatch record - allows editing vehicle details and adding/removing items

    IMPORTANT: This endpoint performs complex database operations:
    - Removes items: Reverts inventory status back to 'available'
    - Adds items: Marks inventory as 'used' and updates order status
    - Recalculates totals automatically

    Restrictions:
    - Cannot edit dispatches with status 'delivered' or 'returned'
    - Cannot change client_id (too complex, create new dispatch instead)
    """
    try:
        logger.info("=" * 80)
        logger.info(f"DISPATCH UPDATE REQUEST for {dispatch_id}")
        logger.info(f"Update data: {update_data}")
        logger.info("=" * 80)

        dispatch_uuid = uuid.UUID(dispatch_id)

        # ===== 1. FETCH AND VALIDATE EXISTING DISPATCH =====
        dispatch = db.query(models.DispatchRecord).options(
            joinedload(models.DispatchRecord.dispatch_items)
        ).filter(models.DispatchRecord.id == dispatch_uuid).first()

        if not dispatch:
            raise HTTPException(status_code=404, detail="Dispatch record not found")

        logger.info(f"Found dispatch: {dispatch.dispatch_number}, current items: {len(dispatch.dispatch_items)}")

        # Check if dispatch can be edited
        if dispatch.status in ["delivered", "returned"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot edit dispatch with status '{dispatch.status}'. Only 'dispatched' status can be edited."
            )

        if dispatch.delivered_at:
            raise HTTPException(
                status_code=400,
                detail="Cannot edit dispatch that has been marked as delivered"
            )

        # ===== 2. UPDATE BASIC DISPATCH DETAILS =====
        if update_data.vehicle_number is not None:
            dispatch.vehicle_number = update_data.vehicle_number
        if update_data.driver_name is not None:
            dispatch.driver_name = update_data.driver_name
        if update_data.driver_mobile is not None:
            dispatch.driver_mobile = update_data.driver_mobile
        if update_data.locket_no is not None:
            dispatch.locket_no = update_data.locket_no
        if update_data.payment_type is not None:
            dispatch.payment_type = update_data.payment_type
        if update_data.reference_number is not None:
            dispatch.reference_number = update_data.reference_number

        # Dispatch date validation (±7 days from original)
        if update_data.dispatch_date is not None:
            from datetime import timedelta
            original_date = dispatch.dispatch_date
            date_diff = abs((update_data.dispatch_date - original_date).days)
            if date_diff > 7:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dispatch date can only be changed within ±7 days of original date. Difference: {date_diff} days"
                )
            dispatch.dispatch_date = update_data.dispatch_date

        # ===== 3. HANDLE ITEMS CHANGES (ADD/REMOVE) =====
        items_changed = False

        if (update_data.inventory_ids is not None or
            update_data.wastage_ids is not None or
            update_data.manual_cut_roll_ids is not None):

            items_changed = True

            # Get current items
            current_inventory_ids = set()
            current_wastage_ids = set()
            current_manual_ids = set()

            logger.info("=== BUILDING CURRENT ITEM SETS ===")
            for item in dispatch.dispatch_items:
                if item.inventory_id:
                    # Regular inventory item
                    current_inventory_ids.add(item.inventory_id)
                    logger.info(f"  Current regular: {item.barcode_id} → {item.inventory_id}")
                else:
                    # Identify by barcode pattern
                    if item.barcode_id and item.barcode_id.startswith('WSB'):
                        # Wastage item
                        wastage = db.query(models.WastageInventory).filter(
                            or_(
                                models.WastageInventory.barcode_id == item.barcode_id,
                                models.WastageInventory.reel_no == item.barcode_id
                            )
                        ).first()
                        if wastage:
                            current_wastage_ids.add(wastage.id)
                            logger.info(f"  Current wastage: {item.barcode_id} → {wastage.id}")
                        else:
                            logger.warning(f"  ⚠️ Could not find wastage for barcode: {item.barcode_id}")
                    elif item.barcode_id and item.barcode_id.startswith('CR_'):
                        # Manual cut roll (can be CR_05, CR_06, CR_07, CR_08, etc.)
                        manual = db.query(models.ManualCutRoll).filter(
                            models.ManualCutRoll.barcode_id == item.barcode_id
                        ).first()
                        if manual:
                            current_manual_ids.add(manual.id)
                            logger.info(f"  Current manual: {item.barcode_id} → {manual.id}")
                        else:
                            logger.warning(f"  ⚠️ Could not find manual for barcode: {item.barcode_id}")

            logger.info(f"Current sets - Regular: {len(current_inventory_ids)}, Wastage: {len(current_wastage_ids)}, Manual: {len(current_manual_ids)}")
            logger.info(f"Current inventory IDs: {current_inventory_ids}")
            logger.info(f"Current wastage IDs: {current_wastage_ids}")
            logger.info(f"Current manual IDs: {current_manual_ids}")

            # Get new items (if provided, otherwise keep current)
            new_inventory_ids = set(update_data.inventory_ids) if update_data.inventory_ids is not None else current_inventory_ids
            new_wastage_ids = set(update_data.wastage_ids) if update_data.wastage_ids is not None else current_wastage_ids
            new_manual_ids = set(update_data.manual_cut_roll_ids) if update_data.manual_cut_roll_ids is not None else current_manual_ids

            logger.info(f"New sets - Regular: {len(new_inventory_ids)}, Wastage: {len(new_wastage_ids)}, Manual: {len(new_manual_ids)}")
            logger.info(f"New inventory IDs: {new_inventory_ids}")
            logger.info(f"New wastage IDs: {new_wastage_ids}")
            logger.info(f"New manual IDs: {new_manual_ids}")

            # Calculate differences
            removed_inventory_ids = current_inventory_ids - new_inventory_ids
            added_inventory_ids = new_inventory_ids - current_inventory_ids

            removed_wastage_ids = current_wastage_ids - new_wastage_ids
            added_wastage_ids = new_wastage_ids - current_wastage_ids

            removed_manual_ids = current_manual_ids - new_manual_ids
            added_manual_ids = new_manual_ids - current_manual_ids

            logger.info("=== CALCULATED DIFFERENCES ===")
            logger.info(f"Dispatch {dispatch.dispatch_number} - Items to REMOVE: {len(removed_inventory_ids)} regular, {len(removed_wastage_ids)} wastage, {len(removed_manual_ids)} manual")
            logger.info(f"  Removed regular IDs: {removed_inventory_ids}")
            logger.info(f"  Removed wastage IDs: {removed_wastage_ids}")
            logger.info(f"  Removed manual IDs: {removed_manual_ids}")
            logger.info(f"Dispatch {dispatch.dispatch_number} - Items to ADD: {len(added_inventory_ids)} regular, {len(added_wastage_ids)} wastage, {len(added_manual_ids)} manual")
            logger.info(f"  Added regular IDs: {added_inventory_ids}")
            logger.info(f"  Added wastage IDs: {added_wastage_ids}")
            logger.info(f"  Added manual IDs: {added_manual_ids}")

            # ===== 4. REMOVE ITEMS (Revert inventory status) =====
            logger.info("=== STARTING ITEM REMOVAL ===")

            # Remove regular inventory items
            for inv_id in removed_inventory_ids:
                logger.info(f"Processing removal of regular item: {inv_id}")
                # Find and delete dispatch item
                dispatch_item = db.query(models.DispatchItem).filter(
                    models.DispatchItem.dispatch_record_id == dispatch.id,
                    models.DispatchItem.inventory_id == inv_id
                ).first()

                if dispatch_item:
                    logger.info(f"  Found dispatch item: {dispatch_item.barcode_id}, deleting...")
                    db.delete(dispatch_item)
                else:
                    logger.warning(f"  ⚠️ Dispatch item not found for inventory {inv_id}")

                # Revert inventory status
                inventory = db.query(models.InventoryMaster).filter(
                    models.InventoryMaster.id == inv_id
                ).first()

                if inventory:
                    logger.info(f"  Reverting {inventory.barcode_id}: {inventory.status} → available")
                    inventory.status = "available"
                    inventory.location = "warehouse"
                    logger.info(f"  ✓ Reverted inventory {inventory.barcode_id} to available")

                    # Revert order item status (fuzzy match - best effort)
                    # Note: This may revert the wrong order item if multiple matches exist
                    if inventory.paper:
                        matching_order_items = db.query(models.OrderItem).join(models.OrderMaster).filter(
                            models.OrderItem.paper_id == inventory.paper_id,
                            models.OrderItem.width_inches == float(inventory.width_inches),
                            models.OrderItem.item_status == "completed"
                        ).limit(1).all()

                        for order_item in matching_order_items:
                            order_item.item_status = "in_warehouse"
                            order_item.dispatched_at = None
                            logger.info(f"  ✓ Reverted order item {order_item.frontend_id} to in_warehouse")

                            # Check if order needs to be reverted from completed
                            order = db.query(models.OrderMaster).filter(
                                models.OrderMaster.id == order_item.order_id
                            ).first()

                            if order and order.status == "completed":
                                # Check if any items are not completed
                                has_incomplete = db.query(models.OrderItem).filter(
                                    models.OrderItem.order_id == order.id,
                                    models.OrderItem.item_status != "completed"
                                ).count() > 0

                                if has_incomplete:
                                    order.status = "in_process"
                                    logger.info(f"  ✓ Reverted order {order.frontend_id} to in_process")
                else:
                    logger.warning(f"  ⚠️ Inventory {inv_id} not found in database")

            # Remove wastage items
            for wastage_id in removed_wastage_ids:
                # Find dispatch item by wastage identification
                wastage = db.query(models.WastageInventory).filter(
                    models.WastageInventory.id == wastage_id
                ).first()

                if wastage:
                    dispatch_item = db.query(models.DispatchItem).filter(
                        models.DispatchItem.dispatch_record_id == dispatch.id,
                        models.DispatchItem.inventory_id == None,
                        or_(
                            models.DispatchItem.barcode_id == wastage.barcode_id,
                            models.DispatchItem.barcode_id == wastage.reel_no
                        )
                    ).first()

                    if dispatch_item:
                        db.delete(dispatch_item)

                    # Revert wastage status
                    wastage.status = "available"
                    logger.info(f"Reverted wastage {wastage.barcode_id or wastage.reel_no} to available")

            # Remove manual cut rolls
            for manual_id in removed_manual_ids:
                manual_roll = db.query(models.ManualCutRoll).filter(
                    models.ManualCutRoll.id == manual_id
                ).first()

                if manual_roll:
                    dispatch_item = db.query(models.DispatchItem).filter(
                        models.DispatchItem.dispatch_record_id == dispatch.id,
                        models.DispatchItem.inventory_id == None,
                        models.DispatchItem.barcode_id == manual_roll.barcode_id
                    ).first()

                    if dispatch_item:
                        db.delete(dispatch_item)

                    # Revert manual roll status
                    manual_roll.status = "available"
                    manual_roll.location = "warehouse"
                    logger.info(f"Reverted manual roll {manual_roll.barcode_id} to available")

            # Flush deletions to database before adding new items
            if removed_inventory_ids or removed_wastage_ids or removed_manual_ids:
                logger.info("Flushing item removals to database...")
                db.flush()

            # ===== 5. ADD NEW ITEMS =====

            # Import ID generator
            from ..services.id_generator import FrontendIDGenerator
            from sqlalchemy import func

            # Add regular inventory items
            for inv_id in added_inventory_ids:
                inventory = db.query(models.InventoryMaster).filter(
                    models.InventoryMaster.id == inv_id
                ).first()

                if not inventory:
                    logger.warning(f"Inventory {inv_id} not found, skipping")
                    continue

                if inventory.status != "available":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Inventory item {inventory.barcode_id} is not available (status: {inventory.status})"
                    )

                # Get order frontend ID if inventory is allocated to an order
                item_order_frontend_id = None
                if inventory.allocated_to_order_id:
                    order = db.query(models.OrderMaster).filter(
                        models.OrderMaster.id == inventory.allocated_to_order_id
                    ).first()
                    if order:
                        item_order_frontend_id = order.frontend_id

                # Create dispatch item
                dispatch_item = models.DispatchItem(
                    dispatch_record_id=dispatch.id,
                    inventory_id=inventory.id,
                    qr_code=inventory.qr_code or inventory.barcode_id,
                    barcode_id=inventory.barcode_id,
                    width_inches=float(inventory.width_inches),
                    weight_kg=float(inventory.weight_kg),
                    paper_spec=f"{inventory.paper.gsm}gsm, {inventory.paper.bf}bf, {inventory.paper.shade}" if inventory.paper else "Unknown",
                    order_frontend_id=item_order_frontend_id  # Store order frontend ID
                )
                db.add(dispatch_item)
                db.flush()  # Get ID

                # Generate frontend ID
                dispatch_item.frontend_id = FrontendIDGenerator.generate_frontend_id("dispatch_item", db)

                # Mark inventory as used
                inventory.status = "used"
                inventory.location = "dispatched"
                logger.info(f"Marked inventory {inventory.barcode_id} as used")

                # Update matching order items
                if inventory.paper:
                    matching_order_items = db.query(models.OrderItem).join(models.OrderMaster).filter(
                        models.OrderItem.paper_id == inventory.paper_id,
                        models.OrderItem.width_inches == float(inventory.width_inches),
                        models.OrderMaster.status == "in_process",
                        models.OrderItem.item_status == "in_warehouse"
                    ).limit(1).all()

                    for order_item in matching_order_items:
                        order_item.item_status = "completed"
                        order_item.dispatched_at = func.now()
                        logger.info(f"Marked order item {order_item.frontend_id} as completed")

                        # Check if order is complete
                        order = db.query(models.OrderMaster).filter(
                            models.OrderMaster.id == order_item.order_id
                        ).first()

                        if order:
                            all_items_completed = all(
                                oi.item_status == "completed" for oi in order.order_items
                            )
                            if all_items_completed and order.status != "completed":
                                order.status = "completed"
                                logger.info(f"Marked order {order.frontend_id} as completed")

            # Add wastage items
            for wastage_id in added_wastage_ids:
                wastage = db.query(models.WastageInventory).filter(
                    models.WastageInventory.id == wastage_id
                ).first()

                if not wastage:
                    logger.warning(f"Wastage item {wastage_id} not found, skipping")
                    continue

                if wastage.status != "available":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Wastage item {wastage.barcode_id or wastage.reel_no} is not available (status: {wastage.status})"
                    )

                # Create dispatch item
                dispatch_item = models.DispatchItem(
                    dispatch_record_id=dispatch.id,
                    inventory_id=None,
                    qr_code=wastage.barcode_id or wastage.frontend_id or "",
                    barcode_id=wastage.reel_no or wastage.barcode_id,
                    width_inches=float(wastage.width_inches) if wastage.width_inches else 0.0,
                    weight_kg=float(wastage.weight_kg) if wastage.weight_kg else 0.0,
                    paper_spec=f"{wastage.paper.gsm}gsm, {wastage.paper.bf}bf, {wastage.paper.shade}" if wastage.paper else "Unknown"
                )
                db.add(dispatch_item)
                db.flush()

                # Generate frontend ID
                dispatch_item.frontend_id = FrontendIDGenerator.generate_frontend_id("dispatch_item", db)

                # Mark wastage as used
                wastage.status = "used"
                logger.info(f"Marked wastage {wastage.barcode_id or wastage.reel_no} as used")

            # Add manual cut rolls
            for manual_id in added_manual_ids:
                manual_roll = db.query(models.ManualCutRoll).filter(
                    models.ManualCutRoll.id == manual_id
                ).first()

                if not manual_roll:
                    logger.warning(f"Manual cut roll {manual_id} not found, skipping")
                    continue

                if manual_roll.status != "available":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Manual cut roll {manual_roll.barcode_id} is not available (status: {manual_roll.status})"
                    )

                # Create dispatch item
                dispatch_item = models.DispatchItem(
                    dispatch_record_id=dispatch.id,
                    inventory_id=None,
                    qr_code=manual_roll.barcode_id or manual_roll.frontend_id or "",
                    barcode_id=manual_roll.barcode_id,
                    width_inches=float(manual_roll.width_inches),
                    weight_kg=float(manual_roll.weight_kg),
                    paper_spec=f"{manual_roll.paper.gsm}gsm, {manual_roll.paper.bf}bf, {manual_roll.paper.shade}" if manual_roll.paper else "Unknown"
                )
                db.add(dispatch_item)
                db.flush()

                # Generate frontend ID
                dispatch_item.frontend_id = FrontendIDGenerator.generate_frontend_id("dispatch_item", db)

                # Mark manual roll as used
                manual_roll.status = "used"
                manual_roll.location = "dispatched"
                logger.info(f"Marked manual roll {manual_roll.barcode_id} as used")

        # ===== 6. RECALCULATE TOTALS =====
        if items_changed:
            # Refresh dispatch items
            db.refresh(dispatch)

            total_items = len(dispatch.dispatch_items)
            total_weight = sum(float(item.weight_kg) for item in dispatch.dispatch_items)

            dispatch.total_items = total_items
            dispatch.total_weight_kg = total_weight

            logger.info(f"Updated dispatch totals - Items: {total_items}, Weight: {total_weight}kg")

        # ===== 7. COMMIT TRANSACTION =====
        db.commit()
        db.refresh(dispatch)

        return {
            "message": "Dispatch record updated successfully",
            "dispatch_id": str(dispatch.id),
            "dispatch_number": dispatch.dispatch_number,
            "total_items": dispatch.total_items,
            "total_weight_kg": float(dispatch.total_weight_kg) if dispatch.total_weight_kg else 0.0,
            "updated_fields": {
                "vehicle_details": update_data.vehicle_number is not None or update_data.driver_name is not None or update_data.driver_mobile is not None,
                "items_changed": items_changed
            }
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dispatch ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating dispatch record: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PDF GENERATION ENDPOINTS
# ============================================================================

@router.get("/dispatch/wastage-inventory-items", tags=["Dispatch History"])
def get_wastage_inventory_items(
    status: str = "available",
    db: Session = Depends(get_db)
):
    """Get wastage inventory items available for dispatch"""
    try:
        from sqlalchemy.orm import joinedload

        # Query wastage inventory items with status "available"
        query = db.query(models.WastageInventory).options(
            joinedload(models.WastageInventory.paper),
            joinedload(models.WastageInventory.created_by),
            joinedload(models.WastageInventory.source_plan),
            joinedload(models.WastageInventory.source_jumbo_roll)
        ).filter(
            models.WastageInventory.status == status
        )

        wastage_items = query.order_by(desc(models.WastageInventory.created_at)).all()

        # Format response
        wastage_list = []
        for item in wastage_items:
            wastage_list.append({
                "id": str(item.id),
                "frontend_id": item.frontend_id,
                "barcode_id": item.barcode_id,
                "reel_no": item.reel_no,
                "width_inches": float(item.width_inches) if item.width_inches else 0.0,
                "weight_kg": float(item.weight_kg) if item.weight_kg else 0.0,
                "paper_spec": f"{item.paper.gsm}gsm, {item.paper.bf}bf, {item.paper.shade}" if item.paper else "Unknown",
                "paper": {
                    "id": str(item.paper.id),
                    "name": item.paper.name,
                    "gsm": item.paper.gsm,
                    "bf": float(item.paper.bf),
                    "shade": item.paper.shade
                } if item.paper else None,
                "status": item.status,
                "location": item.location,
                "source_plan_id": str(item.source_plan_id) if item.source_plan_id else None,
                "source_plan": item.source_plan.frontend_id if item.source_plan else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "created_by": item.created_by.name if item.created_by else "Unknown",
                "notes": item.notes
            })

        return {
            "wastage_items": wastage_list,
            "total_count": len(wastage_list)
        }

    except Exception as e:
        logger.error(f"Error fetching wastage inventory items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dispatch/manual-cut-rolls", tags=["Dispatch History"])
def get_manual_cut_rolls_for_dispatch(
    status: str = "available",
    client_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get manual cut rolls available for dispatch"""
    try:
        from sqlalchemy.orm import joinedload

        # Query manual cut rolls with status "available"
        query = db.query(models.ManualCutRoll).options(
            joinedload(models.ManualCutRoll.paper),
            joinedload(models.ManualCutRoll.client),
            joinedload(models.ManualCutRoll.created_by)
        ).filter(
            models.ManualCutRoll.status == status
        )

        # Filter by client if provided
        if client_id and client_id.strip() and client_id != "none":
            query = query.filter(models.ManualCutRoll.client_id == uuid.UUID(client_id))

        manual_rolls = query.order_by(desc(models.ManualCutRoll.created_at)).all()

        # Format response
        manual_roll_list = []
        for roll in manual_rolls:
            manual_roll_list.append({
                "id": str(roll.id),
                "frontend_id": roll.frontend_id,
                "barcode_id": roll.barcode_id,
                "reel_number": roll.reel_number,
                "width_inches": float(roll.width_inches),
                "weight_kg": float(roll.weight_kg),
                "paper_spec": f"{roll.paper.gsm}gsm, {roll.paper.bf}bf, {roll.paper.shade}" if roll.paper else "Unknown",
                "paper": {
                    "id": str(roll.paper.id),
                    "name": roll.paper.name,
                    "gsm": roll.paper.gsm,
                    "bf": float(roll.paper.bf),
                    "shade": roll.paper.shade
                } if roll.paper else None,
                "client_name": roll.client.company_name if roll.client else "Unknown",
                "client_id": str(roll.client_id),
                "status": roll.status,
                "location": roll.location,
                "created_at": roll.created_at.isoformat() if roll.created_at else None,
                "created_by": roll.created_by.name if roll.created_by else "Unknown",
                "is_manual": True
            })

        return {
            "manual_cut_rolls": manual_roll_list,
            "total_count": len(manual_roll_list)
        }

    except Exception as e:
        logger.error(f"Error fetching manual cut rolls for dispatch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dispatch/{dispatch_id}/pdf", tags=["Dispatch PDF"])
def generate_dispatch_pdf(
    dispatch_id: str,
    db: Session = Depends(get_db)
):
    """Generate PDF for dispatch record with visual roll representation"""
    try:
        dispatch_uuid = uuid.UUID(dispatch_id)
        
        # Get dispatch with all relationships
        dispatch = db.query(models.DispatchRecord).options(
            joinedload(models.DispatchRecord.client),
            joinedload(models.DispatchRecord.primary_order),
            joinedload(models.DispatchRecord.created_by),
            joinedload(models.DispatchRecord.dispatch_items)
        ).filter(models.DispatchRecord.id == dispatch_uuid).first()
        
        if not dispatch:
            raise HTTPException(status_code=404, detail="Dispatch record not found")
        
        # Generate PDF content
        pdf_content = generate_dispatch_pdf_content(dispatch)
        
        # Return PDF as response
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=dispatch_{dispatch.dispatch_number}_{dispatch.dispatch_date.strftime('%Y%m%d') if dispatch.dispatch_date else 'unknown'}.pdf"
            }
        )
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dispatch ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating dispatch PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def generate_dispatch_pdf_content(dispatch: models.DispatchRecord) -> bytes:
    """Generate PDF content for dispatch record with visual cutting patterns"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.graphics.shapes import Drawing, Rect, String
        from reportlab.graphics import renderPDF
        import io
        
        # Create PDF buffer
        buffer = io.BytesIO()
        
        # Create document
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        
        # Build content
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        header_style = ParagraphStyle(
            'HeaderStyle',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=12,
            alignment=TA_LEFT
        )
        
        # Title
        story.append(Paragraph("DISPATCH RECORD", title_style))
        story.append(Spacer(1, 20))
        
        # Dispatch Information
        dispatch_info = [
            ["Dispatch Number:", dispatch.dispatch_number or "N/A"],
            ["Reference Number:", dispatch.reference_number or "N/A"],
            ["Dispatch Date:", dispatch.dispatch_date.strftime("%d-%m-%Y") if dispatch.dispatch_date else "N/A"],
            ["Status:", dispatch.status or "N/A"],
        ]
        
        dispatch_table = Table(dispatch_info, colWidths=[2*inch, 3*inch])
        dispatch_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(dispatch_table)
        story.append(Spacer(1, 20))
        
        # Client Information
        if dispatch.client:
            story.append(Paragraph("CLIENT INFORMATION", header_style))
            client_info = [
                ["Company Name:", getattr(dispatch.client, 'company_name', None) or "N/A"],
                ["Contact Person:", getattr(dispatch.client, 'contact_person', None) or "N/A"],
                ["Mobile:", getattr(dispatch.client, 'phone', None) or "N/A"],
                ["Email:", getattr(dispatch.client, 'email', None) or "N/A"],
                ["Address:", getattr(dispatch.client, 'address', None) or "N/A"],
            ]
            
            client_table = Table(client_info, colWidths=[2*inch, 3*inch])
            client_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.grey),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('BACKGROUND', (1, 0), (1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(client_table)
            story.append(Spacer(1, 20))
        
        # Vehicle and Driver Information
        story.append(Paragraph("TRANSPORT DETAILS", header_style))
        transport_info = [
            ["Vehicle Number:", dispatch.vehicle_number or "N/A"],
            ["Driver Name:", dispatch.driver_name or "N/A"],  
            ["Driver Mobile:", dispatch.driver_mobile or "N/A"],
            ["Payment Type:", dispatch.payment_type or "N/A"],
        ]
        
        transport_table = Table(transport_info, colWidths=[2*inch, 3*inch])
        transport_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(transport_table)
        story.append(Spacer(1, 20))
        
        # Dispatch Items with Visual Representation
        if dispatch.dispatch_items:
            story.append(Paragraph("DISPATCHED ITEMS WITH VISUAL CUTTING PATTERN", header_style))
            
            # Add color legend
            story.append(Paragraph("Color Legend:", ParagraphStyle('Legend', parent=styles['Normal'], fontSize=10, spaceAfter=6)))
            legend_data = [
                ["Color", "Meaning"],
                ["Green", "Narrow Rolls (≤20\")"],
                ["Blue", "Standard Rolls (20-35\")"],
                ["Orange", "Wide Rolls (>35\")"],
                ["Red", "Unused Space/Waste"]
            ]
            
            legend_table = Table(legend_data, colWidths=[1*inch, 2*inch])
            legend_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            
            story.append(legend_table)
            story.append(Spacer(1, 15))
            
            # Group items by paper specification for better visualization
            items_by_spec = {}
            for item in dispatch.dispatch_items:
                spec_key = item.paper_spec or "Unknown Specification"
                if spec_key not in items_by_spec:
                    items_by_spec[spec_key] = []
                items_by_spec[spec_key].append(item)
            
            for spec_key, items in items_by_spec.items():
                # Specification header
                story.append(Paragraph(f"<b>{spec_key}</b>", header_style))
                story.append(Spacer(1, 5))
                
                # Visual representation of dispatched items
                story.append(Paragraph("<b>Dispatched Items Visualization:</b>", 
                    ParagraphStyle('SubHeader', parent=styles['Normal'], fontSize=10, spaceAfter=6)))
                
                # Calculate dimensions for visualization
                total_width_inches = 118  # Standard jumbo roll width
                visual_width = 500  # Width of visual in points
                visual_height = 40   # Height of visual in points
                
                # Sort items by width for better grouping
                sorted_items = sorted(items, key=lambda x: float(x.width_inches) if x.width_inches else 0)
                
                # Group items by similar widths (group items within 0.5" of each other)
                width_groups = []
                current_group = []
                last_width = None
                
                for item in sorted_items:
                    item_width = float(item.width_inches) if item.width_inches else 0
                    if last_width is None or abs(item_width - last_width) <= 0.5:
                        current_group.append(item)
                        last_width = item_width
                    else:
                        if current_group:
                            width_groups.append(current_group)
                        current_group = [item]
                        last_width = item_width
                
                if current_group:
                    width_groups.append(current_group)
                
                # Simulate packing items into 118" rolls (best-fit)
                rolls_representation = []
                remaining_items = sorted_items.copy()
                
                while remaining_items:
                    current_roll = []
                    current_roll_width = 0
                    items_to_remove = []
                    
                    # Try to fit items into current roll
                    for item in remaining_items:
                        item_width = float(item.width_inches) if item.width_inches else 0
                        if current_roll_width + item_width <= total_width_inches:
                            current_roll.append(item)
                            current_roll_width += item_width
                            items_to_remove.append(item)
                    
                    # Remove items that were packed
                    for item in items_to_remove:
                        remaining_items.remove(item)
                    
                    if current_roll:
                        rolls_representation.append({
                            'items': current_roll,
                            'total_width': current_roll_width,
                            'waste': total_width_inches - current_roll_width
                        })
                    else:
                        # Safety break to prevent infinite loop
                        break
                
                for roll_idx, roll_data in enumerate(rolls_representation):
                    # Roll header
                    story.append(Paragraph(f"<i>Simulated Roll #{roll_idx + 1}</i>", 
                        ParagraphStyle('RollHeader', parent=styles['Normal'], fontSize=9, leftIndent=20, spaceAfter=3)))
                    
                    # Create drawing for this roll
                    drawing = Drawing(visual_width, visual_height)
                    current_x = 0
                    
                    # Color palette based on item properties
                    def get_color_for_item(item):
                        item_width = float(item.width_inches) if item.width_inches else 0
                        if item_width <= 20:
                            return colors.Color(0.2, 0.8, 0.4)  # Green for narrow
                        elif item_width <= 35:
                            return colors.Color(0.2, 0.6, 0.8)  # Blue for standard
                        else:
                            return colors.Color(0.8, 0.6, 0.2)  # Orange for wide
                    
                    # Draw each dispatched item
                    for item in roll_data['items']:
                        item_width = float(item.width_inches) if item.width_inches else 0
                        width_ratio = item_width / total_width_inches
                        section_width = visual_width * width_ratio
                        
                        # Select color based on width
                        color = get_color_for_item(item)
                        
                        # Draw rectangle
                        rect = Rect(current_x, 5, section_width, visual_height - 10)
                        rect.fillColor = color
                        rect.strokeColor = colors.white
                        rect.strokeWidth = 1
                        drawing.add(rect)
                        
                        # Add width label and barcode
                        if section_width > 25:  # Only add text if section is wide enough
                            text = String(current_x + section_width/2, visual_height/2 + 2, f'{item_width:.1f}"')
                            text.textAnchor = 'middle'
                            text.fontSize = 7
                            text.fillColor = colors.white
                            drawing.add(text)
                            
                            # Add barcode ID if available
                            if item.barcode_id and section_width > 35:
                                barcode_text = String(current_x + section_width/2, visual_height/2 - 4, f'{item.barcode_id}')
                                barcode_text.textAnchor = 'middle'
                                barcode_text.fontSize = 6
                                barcode_text.fillColor = colors.white
                                drawing.add(barcode_text)
                        
                        current_x += section_width
                    
                    # Draw waste section
                    waste_width = roll_data['waste']
                    if waste_width > 0:
                        waste_ratio = waste_width / total_width_inches
                        waste_section_width = visual_width * waste_ratio
                        
                        waste_rect = Rect(current_x, 5, waste_section_width, visual_height - 10)
                        waste_rect.fillColor = colors.Color(0.9, 0.3, 0.3)  # Red for waste
                        waste_rect.strokeColor = colors.white
                        waste_rect.strokeWidth = 1
                        drawing.add(waste_rect)
                        
                        # Add waste label
                        if waste_section_width > 20:
                            waste_text = String(current_x + waste_section_width/2, visual_height/2, f'{waste_width:.1f}"')
                            waste_text.textAnchor = 'middle'
                            waste_text.fontSize = 7
                            waste_text.fillColor = colors.white
                            drawing.add(waste_text)
                    
                    # Add total width indicator
                    total_text = String(visual_width/2, -5, f'{total_width_inches}" Total Roll Width')
                    total_text.textAnchor = 'middle'
                    total_text.fontSize = 8
                    total_text.fillColor = colors.Color(0.4, 0.4, 0.4)
                    drawing.add(total_text)
                    
                    story.append(drawing)
                    story.append(Spacer(1, 10))
                    
                    # Statistics for this simulated roll
                    efficiency = (roll_data['total_width'] / total_width_inches) * 100
                    total_weight = sum(float(item.weight_kg) if item.weight_kg else 0 for item in roll_data['items'])
                    
                    stats_data = [
                        ["Statistic", "Value"],
                        ["Used Width", f"{roll_data['total_width']:.1f} inches"],
                        ["Waste", f"{waste_width:.1f} inches"], 
                        ["Efficiency", f"{efficiency:.1f}%"],
                        ["Items Count", str(len(roll_data['items']))],
                        ["Total Weight", f"{total_weight:.1f} kg"]
                    ]
                    
                    stats_table = Table(stats_data, colWidths=[1.5*inch, 1.5*inch])
                    stats_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, 0), 9),
                        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                        ('FONTSIZE', (0, 1), (-1, -1), 8),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black),
                        ('LEFTPADDING', (0, 0), (-1, -1), 20),
                    ]))
                    
                    story.append(stats_table)
                    story.append(Spacer(1, 15))
            
            # Detailed items table
            story.append(Paragraph("DETAILED ITEMS LIST", header_style))
            items_data = [
                ["S.No", "Barcode", "QR Code", "Width (inches)", "Weight (kg)", "Paper Spec", "Status"]
            ]
            
            # Items data
            for i, item in enumerate(dispatch.dispatch_items, 1):
                items_data.append([
                    str(i),
                    item.barcode_id or "N/A",
                    item.qr_code or "N/A", 
                    f"{float(item.width_inches):.1f}" if item.width_inches else "N/A",
                    f"{float(item.weight_kg):.2f}" if item.weight_kg else "N/A",
                    item.paper_spec or "N/A",
                    item.status or "N/A"
                ])
            
            items_table = Table(items_data, colWidths=[0.5*inch, 1*inch, 1.5*inch, 1*inch, 0.8*inch, 1.5*inch, 0.8*inch])
            items_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(items_table)
            story.append(Spacer(1, 20))
        
        # Summary
        story.append(Paragraph("SUMMARY", header_style))
        summary_info = [
            ["Total Items:", str(dispatch.total_items)],
            ["Total Weight:", f"{float(dispatch.total_weight_kg):.2f} kg" if dispatch.total_weight_kg else "0.00 kg"],
            ["Created By:", dispatch.created_by.name if dispatch.created_by else "N/A"],
            ["Created At:", dispatch.created_at.strftime("%d-%m-%Y %H:%M") if dispatch.created_at else "N/A"],
        ]
        
        summary_table = Table(summary_info, colWidths=[2*inch, 3*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(summary_table)
        
        # Build PDF
        doc.build(story)
        
        # Get PDF content
        pdf_content = buffer.getvalue()
        buffer.close()
        
        return pdf_content
        
    except Exception as e:
        logger.error(f"Error generating PDF content: {e}")
        raise Exception(f"Failed to generate PDF: {str(e)}")