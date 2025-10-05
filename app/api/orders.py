from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Any
from uuid import UUID
import logging
import json
from datetime import datetime

from .base import get_db, validate_status_transition
from .. import crud_operations, schemas, models
from .order_edit_logs import create_order_edit_log

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# ORDER MASTER ENDPOINTS
# ============================================================================

@router.post("/orders", response_model=schemas.OrderMaster, tags=["Order Master"])
async def create_order(request: Request, db: Session = Depends(get_db)):
    """Create a new order with multiple order items"""
    try:
        # Parse request data
        request_data = await request.json()
        logger.info(f"Creating order with data: {request_data}")
        
        return crud_operations.create_order_with_items(db=db, order_data=request_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders", response_model=List[schemas.OrderMaster], tags=["Order Master"])
def get_orders(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    client_id: str = None,
    db: Session = Depends(get_db)
):
    """Get all orders with pagination and filters"""
    try:
        return crud_operations.get_orders(db=db, skip=skip, limit=limit, status=status, client_id=client_id)
    except Exception as e:
        logger.error(f"Error getting orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/with-summary", tags=["Order Master"])
def get_orders_with_summary(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    client_id: str = None,
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db)
):
    """Get orders with summary data (ordered, pending, cut, dispatched) for client orders page"""
    try:
        from sqlalchemy.orm import joinedload
        from sqlalchemy import and_, case, func
        from datetime import datetime
        import uuid

        # Base query with joins
        query = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.order_items).joinedload(models.OrderItem.paper)
        )

        # Apply filters
        if client_id and client_id.strip() and client_id != "all":
            query = query.filter(models.OrderMaster.client_id == uuid.UUID(client_id))

        if status and status != "all":
            query = query.filter(models.OrderMaster.status == status)

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                query = query.filter(models.OrderMaster.created_at >= start_dt)
            except ValueError:
                pass

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                query = query.filter(models.OrderMaster.created_at <= end_dt)
            except ValueError:
                pass

        # Execute query
        orders = query.order_by(models.OrderMaster.created_at.desc()).offset(skip).limit(limit).all()

        # Transform to include summary data
        orders_with_summary = []

        for order in orders:
            # Calculate summary statistics from order items
            total_ordered = sum(item.quantity_rolls for item in order.order_items)
            total_fulfilled = sum(item.quantity_fulfilled for item in order.order_items)

            # Calculate pending items (exactly same as View Details - only 'pending' status)
            all_pending_items = db.query(models.PendingOrderItem).filter(
                models.PendingOrderItem.original_order_id == order.id,
                models.PendingOrderItem._status == 'pending'
            ).all()
            total_pending = sum(item.quantity_pending for item in all_pending_items)

            # Calculate cut items (from InventoryMaster allocated to this order - same logic as View Details)
            allocated_inventory = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.allocated_to_order_id == order.id
            ).all()
            total_cut = len(allocated_inventory)

            # Calculate dispatched items (quantity fulfilled from order items - same logic as View Details)
            total_dispatched = total_fulfilled

            # Calculate total value
            total_value = sum(item.amount for item in order.order_items)

            # Check if overdue
            is_overdue = False
            if order.delivery_date and order.status != 'completed':
                # Handle both datetime and date objects
                current_date = datetime.utcnow().date()
                delivery_date = order.delivery_date.date() if hasattr(order.delivery_date, 'date') else order.delivery_date
                is_overdue = delivery_date < current_date

            orders_with_summary.append({
                "order_id": str(order.id),
                "frontend_id": order.frontend_id,
                "client_name": order.client.company_name if order.client else "Unknown Client",
                "status": order.status,
                "priority": order.priority,
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "created_at": order.created_at.isoformat(),
                "total_items": len(order.order_items),
                "total_value": float(total_value),
                "payment_type": order.payment_type,
                "is_overdue": is_overdue,

                # Summary fields requested
                "total_quantity_ordered": total_ordered,
                "total_quantity_pending": total_pending,
                "total_quantity_cut": total_cut,
                "total_quantity_dispatched": total_dispatched,
                "total_quantity_fulfilled": total_fulfilled,
                "fulfillment_percentage": (total_fulfilled / total_ordered * 100) if total_ordered > 0 else 0
            })

        return orders_with_summary

    except Exception as e:
        logger.error(f"Error getting orders with summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/{order_id}", response_model=schemas.OrderMaster, tags=["Order Master"])
def get_order(order_id: UUID, db: Session = Depends(get_db)):
    """Get order by ID with related data"""
    order = crud_operations.get_order(db=db, order_id=order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.put("/orders/{order_id}", response_model=schemas.OrderMaster, tags=["Order Master"])
async def update_order(
    order_id: UUID,
    order_update: schemas.OrderMasterUpdate,
    request: Request,
    db: Session = Depends(get_db)
):
    """Update order information (only if status is 'created')"""
    try:
        # Parse request body to get user info
        request_body = await request.json()
        edited_by_id = request_body.get("edited_by_id")  # Get user ID from request

        # Extract only the order update fields (remove edited_by_id)
        order_data = {k: v for k, v in request_body.items() if k != "edited_by_id"}
        order_update = schemas.OrderMasterUpdate(**order_data)

        # Get the order first to check status
        order = crud_operations.get_order(db=db, order_id=order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Only allow updates of orders in 'created' status
        if order.status != "created":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot update order with status '{order.status}'. Only orders with status 'created' can be updated."
            )

        # Perform the update
        updated_order = crud_operations.update_order(db=db, order_id=order_id, order_update=order_update)
        if not updated_order:
            raise HTTPException(status_code=500, detail="Failed to update order")

        # Note: Individual field change logging removed - only tracking order items changes

        return updated_order
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/orders/{order_id}/with-items", response_model=schemas.OrderMaster, tags=["Order Master"])
async def update_order_with_items(
    order_id: UUID,
    request: Request,
    db: Session = Depends(get_db)
):
    """Update order with items (only if status is 'created') - replaces all order items"""
    try:
        # Parse and log raw request data first
        raw_data = await request.json()
        logger.info(f"Raw request data for order {order_id}: {raw_data}")

        # Extract user ID for logging
        edited_by_id = raw_data.get("edited_by_id")

        # Remove edited_by_id from the data before parsing with Pydantic
        order_data = {k: v for k, v in raw_data.items() if k != "edited_by_id"}

        # Try to parse with Pydantic schema
        try:
            order_update = schemas.OrderMasterUpdateWithItems(**order_data)
            logger.info(f"Successfully parsed order update: {order_update}")
        except Exception as parse_error:
            logger.error(f"Pydantic validation error: {parse_error}")
            raise HTTPException(status_code=422, detail=f"Validation error: {str(parse_error)}")

        # Get the order first to check status
        order = crud_operations.get_order(db=db, order_id=order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Only allow updates of orders in 'created' status
        if order.status != "created":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot update order with status '{order.status}'. Only orders with status 'created' can be updated."
            )

        # Track old order items for logging
        old_items = [
            {
                "paper_id": str(item.paper_id),
                "width_inches": float(item.width_inches),
                "quantity_rolls": item.quantity_rolls,
                "rate": float(item.rate)
            }
            for item in order.order_items
        ]

        # Perform the update with items
        updated_order = crud_operations.update_order_with_items(db=db, order_id=order_id, order_update=order_update)
        if not updated_order:
            raise HTTPException(status_code=500, detail="Failed to update order")

        # Track new order items for logging
        new_items = [
            {
                "paper_id": str(item.paper_id),
                "width_inches": float(item.width_inches),
                "quantity_rolls": item.quantity_rolls,
                "rate": float(item.rate)
            }
            for item in updated_order.order_items
        ]

        # Log the order items update using separate database session
        try:
            from sqlalchemy.orm import sessionmaker
            from ..database import engine

            # Create separate session for logging
            LogSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            log_db = LogSession()

            try:
                # Use the actual user ID if provided, otherwise fall back to system user
                user_id_for_logging = edited_by_id

                if not user_id_for_logging:
                    # Fall back to system user if no user ID provided
                    system_user = log_db.query(models.UserMaster).filter(
                        models.UserMaster.username == "system"
                    ).first()

                    if not system_user:
                        logger.warning("No system user found, creating one for logging")
                        system_user = models.UserMaster(
                            name="System User",
                            username="system",
                            password_hash="system",
                            role="system",
                            contact="system@localhost",
                            department="System",
                            status="active"
                        )
                        log_db.add(system_user)
                        log_db.commit()
                        log_db.refresh(system_user)

                    user_id_for_logging = str(system_user.id)

                logger.info(f"Logging order items update for order {order_id} by user {user_id_for_logging}")

                # Log order items update only
                create_order_edit_log(
                    db=log_db,
                    order_id=str(order_id),
                    edited_by_id=user_id_for_logging,
                    action="update_order_items",
                    field_name="order_items",
                    old_value=old_items,
                    new_value=new_items,
                    description=f"Updated order items: {len(old_items)} -> {len(new_items)} items",
                    request=request
                )
                logger.info("Successfully logged order items update")

            finally:
                log_db.close()

        except Exception as log_error:
            # Log the error but don't fail the main operation
            logger.error(f"Failed to log order items update: {log_error}", exc_info=True)

        return updated_order
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating order with items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/orders/{order_id}", tags=["Order Master"])
def delete_order(order_id: UUID, db: Session = Depends(get_db)):
    """Delete order (only if status is 'created')"""
    try:
        # Get the order first to check status
        order = crud_operations.get_order(db=db, order_id=order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Only allow deletion of orders in 'created' status
        if order.status != "created":
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot delete order with status '{order.status}'. Only orders with status 'created' can be deleted."
            )
        
        # Delete the order using CRUD operations
        success = crud_operations.delete_order(db=db, order_id=order_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete order")
        
        return {"message": "Order deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ORDER ITEMS ENDPOINTS
# ============================================================================

@router.post("/order-items/{item_id}/fulfill", tags=["Order Items"])
def fulfill_order_item(
    item_id: UUID,
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Fulfill specific order item quantity"""
    try:
        quantity = request_data.get("quantity", 1)
        return crud_operations.fulfill_order_item(db=db, item_id=item_id, quantity=quantity)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fulfilling order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/order-items/bulk-fulfill", tags=["Order Items"])
def bulk_fulfill_order_items(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Bulk fulfill multiple order items"""
    try:
        fulfillment_requests = request_data.get("fulfillment_requests", [])
        return crud_operations.bulk_fulfill_order_items(db=db, fulfillment_requests=fulfillment_requests)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk fulfilling order items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/orders/{order_id}/items", response_model=schemas.OrderItem, tags=["Order Items"])
def create_order_item(
    order_id: UUID,
    item: schemas.OrderItemCreate,
    db: Session = Depends(get_db)
):
    """Create a new order item for existing order"""
    try:
        return crud_operations.create_order_item(db=db, order_id=order_id, item=item)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/{order_id}/items", response_model=List[schemas.OrderItem], tags=["Order Items"])
def get_order_items(order_id: UUID, db: Session = Depends(get_db)):
    """Get all items for a specific order"""
    try:
        return crud_operations.get_order_items(db=db, order_id=order_id)
    except Exception as e:
        logger.error(f"Error getting order items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/order-items/{item_id}", response_model=schemas.OrderItem, tags=["Order Items"])
def get_order_item(item_id: UUID, db: Session = Depends(get_db)):
    """Get specific order item by ID"""
    item = crud_operations.get_order_item(db=db, item_id=item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Order item not found")
    return item

@router.put("/order-items/{item_id}", response_model=schemas.OrderItem, tags=["Order Items"])
def update_order_item(
    item_id: UUID,
    item_update: schemas.OrderItemUpdate, 
    db: Session = Depends(get_db)
):
    """Update order item"""
    try:
        item = crud_operations.update_order_item(db=db, item_id=item_id, item_update=item_update)
        if not item:
            raise HTTPException(status_code=404, detail="Order item not found")
        return item
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/order-items/{item_id}", tags=["Order Items"])
def delete_order_item(item_id: UUID, db: Session = Depends(get_db)):
    """Delete order item"""
    try:
        success = crud_operations.delete_order_item(db=db, item_id=item_id)
        if not success:
            raise HTTPException(status_code=404, detail="Order item not found")
        return {"message": "Order item deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# DISPATCH ENDPOINTS - STEP 5: Complete OrderItems
# ============================================================================

@router.post("/dispatch/create-dispatch", tags=["Dispatch"])
def create_dispatch_record(
    dispatch_data: schemas.DispatchFormData,
    db: Session = Depends(get_db)
):
    """Create dispatch record with form data and mark items as dispatched - supports regular inventory and wastage items"""
    try:
        # Validate client exists
        client = crud_operations.get_client(db, dispatch_data.client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        # Validate at least one item type is provided
        if not dispatch_data.inventory_ids and not dispatch_data.wastage_ids:
            raise HTTPException(status_code=400, detail="At least one inventory_id or wastage_id must be provided")

        # Get regular inventory items to be dispatched
        inventory_items = []
        total_weight = 0.0

        for inventory_id in dispatch_data.inventory_ids:
            item = crud_operations.get_inventory_item(db, inventory_id)
            if not item:
                logger.warning(f"Inventory item {inventory_id} not found, skipping")
                continue
            if item.status != "available":
                logger.warning(f"Inventory item {inventory_id} not available (status: {item.status}), skipping")
                continue

            inventory_items.append(item)
            total_weight += float(item.weight_kg)

        # Get wastage items to be dispatched
        wastage_items = []
        for wastage_id in dispatch_data.wastage_ids:
            wastage_item = db.query(models.WastageInventory).filter(
                models.WastageInventory.id == wastage_id
            ).first()

            if not wastage_item:
                logger.warning(f"Wastage item {wastage_id} not found, skipping")
                continue
            if wastage_item.status != "available":
                logger.warning(f"Wastage item {wastage_id} not available (status: {wastage_item.status}), skipping")
                continue

            wastage_items.append(wastage_item)
            total_weight += float(wastage_item.weight_kg) if wastage_item.weight_kg else 0.0

        # Validate we have at least some items
        total_items_count = len(inventory_items) + len(wastage_items)
        if total_items_count == 0:
            raise HTTPException(status_code=400, detail="No available items found for dispatch")
        
        # Create dispatch record
        dispatch_record = models.DispatchRecord(
            vehicle_number=dispatch_data.vehicle_number,
            driver_name=dispatch_data.driver_name,
            driver_mobile=dispatch_data.driver_mobile,
            payment_type=dispatch_data.payment_type,
            dispatch_date=dispatch_data.dispatch_date,
            dispatch_number=dispatch_data.dispatch_number,
            reference_number=dispatch_data.reference_number,
            client_id=dispatch_data.client_id,
            primary_order_id=dispatch_data.primary_order_id,
            order_date=dispatch_data.order_date,
            total_items=total_items_count,
            total_weight_kg=total_weight,
            created_by_id=dispatch_data.created_by_id
        )

        db.add(dispatch_record)
        db.flush()  # Get ID

        # Create dispatch items and update inventory status
        completed_items = []
        updated_orders = []

        # Process regular inventory items
        for item in inventory_items:
            # Create dispatch item record
            dispatch_item = models.DispatchItem(
                dispatch_record_id=dispatch_record.id,
                inventory_id=item.id,
                qr_code=item.qr_code,
                barcode_id=item.barcode_id,
                width_inches=float(item.width_inches),
                weight_kg=float(item.weight_kg),
                paper_spec=f"{item.paper.gsm}gsm, {item.paper.bf}bf, {item.paper.shade}" if item.paper else "Unknown"
            )
            db.add(dispatch_item)

            # Mark inventory as used
            item.status = "used"
            item.location = "dispatched"
            completed_items.append(str(item.id))

            # Update matching order items
            if item.paper:
                matching_order_items = db.query(models.OrderItem).join(models.OrderMaster).filter(
                    models.OrderItem.paper_id == item.paper_id,
                    models.OrderItem.width_inches == float(item.width_inches),
                    models.OrderMaster.status == "in_process",
                    models.OrderItem.item_status == "in_warehouse"
                ).limit(1).all()

                for order_item in matching_order_items:
                    # Only mark as completed if status is "in_warehouse" (fully fulfilled)
                    if order_item.item_status == "in_warehouse":
                        order_item.item_status = "completed"
                        order_item.dispatched_at = func.now()

                    # Check if order is complete
                    order = crud_operations.get_order(db, order_item.order_id)
                    if order:
                        all_items_completed = all(
                            oi.item_status == "completed" for oi in order.order_items
                        )
                        if all_items_completed and order.status != "completed":
                            order.status = "completed"
                            if str(order.id) not in updated_orders:
                                updated_orders.append(str(order.id))

        # Process wastage items
        for wastage_item in wastage_items:
            # Create dispatch item with wastage reel_no as barcode_id
            dispatch_item = models.DispatchItem(
                dispatch_record_id=dispatch_record.id,
                inventory_id=None,  # No link to regular inventory
                qr_code=wastage_item.barcode_id or wastage_item.frontend_id or "",
                barcode_id=wastage_item.reel_no,  # Use reel_no as barcode_id
                width_inches=float(wastage_item.width_inches) if wastage_item.width_inches else 0.0,
                weight_kg=float(wastage_item.weight_kg) if wastage_item.weight_kg else 0.0,
                paper_spec=f"{wastage_item.paper.gsm}gsm, {wastage_item.paper.bf}bf, {wastage_item.paper.shade}" if wastage_item.paper else "Unknown"
            )
            db.add(dispatch_item)

            # Mark wastage as used
            wastage_item.status = "used"
            completed_items.append(f"wastage_{str(wastage_item.id)}")

        db.commit()
        db.refresh(dispatch_record)

        return {
            "message": f"Dispatch record created successfully with {total_items_count} items ({len(inventory_items)} regular, {len(wastage_items)} wastage)",
            "dispatch_id": str(dispatch_record.id),
            "dispatch_number": dispatch_record.dispatch_number,
            "client_name": client.company_name,
            "vehicle_number": dispatch_record.vehicle_number,
            "driver_name": dispatch_record.driver_name,
            "total_items": total_items_count,
            "total_weight_kg": total_weight,
            "completed_orders": updated_orders,
            "summary": {
                "dispatched_items": total_items_count,
                "regular_items": len(inventory_items),
                "wastage_items": len(wastage_items),
                "orders_completed": len(updated_orders),
                "total_weight": total_weight
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating dispatch record: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dispatch/clients", tags=["Dispatch"])
def get_clients_for_dispatch(db: Session = Depends(get_db)):
    """Get active clients for dispatch form dropdown"""
    try:
        clients = crud_operations.get_clients(db, skip=0, limit=1000, status="active")
        return {
            "clients": [
                {
                    "id": str(client.id),
                    "company_name": client.company_name,
                    "contact_person": client.contact_person,
                    "phone": client.phone,
                    "address": client.address
                }
                for client in clients
            ]
        }
    except Exception as e:
        logger.error(f"Error getting clients: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dispatch/warehouse-items", tags=["Dispatch"])
def get_warehouse_items(
    skip: int = 0,
    limit: int = 100,
    client_id: str = None,
    order_id: str = None,
    db: Session = Depends(get_db)
):
    """Get cut rolls (inventory items) that are ready for dispatch - weight added and status 'available'"""
    try:
        from sqlalchemy.orm import joinedload
        import uuid
        
        # Base query for inventory items (cut rolls) with status "available" and weight > 0.1
        # Include order and client data in the SELECT to avoid N+1 queries
        query = db.query(
            models.InventoryMaster,
            models.OrderMaster.frontend_id.label('order_frontend_id'),
            models.ClientMaster.company_name.label('client_company_name')
        ).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.created_by)
        ).outerjoin(
            models.OrderMaster,
            models.InventoryMaster.allocated_to_order_id == models.OrderMaster.id
        ).outerjoin(
            models.ClientMaster,
            models.OrderMaster.client_id == models.ClientMaster.id
        ).filter(
            models.InventoryMaster.roll_type == "cut",
            models.InventoryMaster.status == "available",
            models.InventoryMaster.weight_kg > 0.1  # Real weight has been added
        )
        
        # Filter by client_id or order_id if provided
        if client_id and client_id.strip() and client_id != "none":
            query = query.filter(models.ClientMaster.id == uuid.UUID(client_id))
        elif order_id and order_id.strip() and order_id != "none":
            query = query.filter(models.OrderMaster.id == uuid.UUID(order_id))

        # Execute query and get results (now returns tuples)
        query_results = query.order_by(models.InventoryMaster.created_at.desc()).offset(skip).limit(limit).all()
        
        items_data = []
        for result in query_results:
            # Unpack the tuple: (InventoryMaster, order_frontend_id, client_company_name)
            item, order_frontend_id, client_company_name = result

            # Use the joined data directly
            client_name = client_company_name if client_company_name else "N/A"
            order_id = order_frontend_id if order_frontend_id else (str(item.allocated_to_order_id)[:8] + "..." if item.allocated_to_order_id else "N/A")

            items_data.append({
                "inventory_id": str(item.id),
                "qr_code": item.qr_code,
                "barcode_id": item.barcode_id,
                "paper_spec": f"{item.paper.gsm}gsm, {item.paper.bf}bf, {item.paper.shade}" if item.paper else "N/A",
                "width_inches": float(item.width_inches),
                "weight_kg": float(item.weight_kg),
                "location": item.location or "production_floor",
                "status": item.status,
                "production_date": item.production_date.isoformat(),
                "created_by": item.created_by.name if item.created_by else "Unknown",
                "created_at": item.created_at.isoformat(),
                "client_name": client_name,
                "order_id": order_id,
                "allocated_to_order_id": str(item.allocated_to_order_id) if item.allocated_to_order_id else None,
                "is_wastage_roll": getattr(item, 'is_wastage_roll', False)
            })
        
        # Update filter criteria description
        filter_criteria = "roll_type=cut, status=available, weight_kg > 0.1"
        if client_id and client_id.strip() and client_id != "none":
            filter_criteria += f", client_id={client_id}"
        if order_id and order_id.strip() and order_id != "none":
            filter_criteria += f", order_id={order_id}"
        
        return {
            "warehouse_items": items_data,
            "total_items": len(items_data),
            "dispatch_info": {
                "description": "Cut rolls with real weight added, ready for dispatch",
                "filter_criteria": filter_criteria,
                "filtered_by_client": bool(client_id and client_id.strip() and client_id != "none"),
                "filtered_by_order": bool(order_id and order_id.strip() and order_id != "none")
            },
            "pagination": {
                "skip": skip,
                "limit": limit,
                "has_more": len(items_data) == limit
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting warehouse items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PARTIAL JUMBO COMPLETION - GUPTA PUBLISHING HOUSE ORDER CREATION
# ============================================================================

@router.post("/orders/create-gupta-completion-order", tags=["Partial Jumbo Completion"])
async def create_gupta_completion_order(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Create order for Gupta Publishing House to complete partial jumbos.
    User specifies cut rolls needed to complete partial jumbo.
    """
    try:
        # Parse request data
        request_data = await request.json()
        required_rolls = request_data.get("required_rolls", [])
        created_by_id = request_data.get("created_by_id")
        notes = request_data.get("notes", "Partial jumbo completion order")
        
        if not required_rolls:
            raise HTTPException(status_code=400, detail="required_rolls cannot be empty")
        
        if not created_by_id:
            raise HTTPException(status_code=400, detail="created_by_id is required")
        
        # Find Gupta Publishing House client (hardcoded)
        gupta_client = db.query(models.ClientMaster).filter(
            models.ClientMaster.company_name.ilike("%Gupta Publishing%")
        ).first()
        
        if not gupta_client:
            raise HTTPException(
                status_code=404, 
                detail="Gupta Publishing House client not found in client master"
            )
        
        logger.info(f"Creating Gupta completion order with {len(required_rolls)} rolls")
        
        # Create new order for Gupta Publishing House
        new_order = models.OrderMaster(
            client_id=gupta_client.id,
            status="created",
            priority="normal", 
            payment_type="bill",
            delivery_date=None,
            created_by_id=created_by_id,
            created_at=datetime.utcnow()
        )
        
        db.add(new_order)
        db.flush()  # Get the order ID
        
        # Create order items for each required roll
        order_items = []
        total_amount = 0
        
        for roll_spec in required_rolls:
            # Extract roll specifications
            width_inches = float(roll_spec.get("width_inches", 0))
            paper_id = roll_spec.get("paper_id")
            rate = float(roll_spec.get("rate", 0))
            
            if width_inches <= 0:
                raise HTTPException(status_code=400, detail="width_inches must be greater than 0")
            
            if not paper_id:
                raise HTTPException(status_code=400, detail="paper_id is required for each roll")
            
            # Calculate quantities (standard: 1 inch = 13kg)
            quantity_kg = width_inches * 13
            amount = quantity_kg * rate
            total_amount += amount
            
            # Create order item
            order_item = models.OrderItem(
                order_id=new_order.id,
                paper_id=paper_id,
                width_inches=width_inches,
                quantity_rolls=1,
                quantity_kg=quantity_kg,
                rate=rate,
                amount=amount,
                quantity_fulfilled=0,
                quantity_in_pending=0,
                item_status="created",
                created_at=datetime.utcnow()
            )
            
            db.add(order_item)
            order_items.append(order_item)
        
        # Commit the transaction
        db.commit()
        db.refresh(new_order)
        
        # Prepare response
        response_data = {
            "order": {
                "id": str(new_order.id),
                "frontend_id": new_order.frontend_id,
                "client_id": str(new_order.client_id),
                "client_name": gupta_client.company_name,
                "status": new_order.status,
                "priority": new_order.priority,
                "payment_type": new_order.payment_type,
                "created_at": new_order.created_at.isoformat(),
                "total_items": len(order_items),
                "total_amount": total_amount
            },
            "order_items": [
                {
                    "id": str(item.id),
                    "paper_id": str(item.paper_id),
                    "width_inches": float(item.width_inches),
                    "quantity_rolls": item.quantity_rolls,
                    "quantity_kg": float(item.quantity_kg),
                    "rate": float(item.rate),
                    "amount": float(item.amount)
                }
                for item in order_items
            ],
            "message": f"Successfully created Gupta completion order {new_order.frontend_id} with {len(order_items)} items"
        }
        
        logger.info(f"Created Gupta completion order: {new_order.frontend_id}")
        return response_data
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating Gupta completion order: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create completion order: {str(e)}")

