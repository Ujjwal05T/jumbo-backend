from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from uuid import UUID
import logging
import json

from .base import get_db, validate_status_transition
from .. import crud_operations, schemas, models

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

@router.get("/orders/{order_id}", response_model=schemas.OrderMaster, tags=["Order Master"])
def get_order(order_id: UUID, db: Session = Depends(get_db)):
    """Get order by ID with related data"""
    order = crud_operations.get_order(db=db, order_id=order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.put("/orders/{order_id}", response_model=schemas.OrderMaster, tags=["Order Master"])
def update_order(
    order_id: UUID,
    order_update: schemas.OrderMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update order information (only if status is 'created')"""
    try:
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
        
        # Try to parse with Pydantic schema
        try:
            order_update = schemas.OrderMasterUpdateWithItems(**raw_data)
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
        
        # Perform the update with items
        updated_order = crud_operations.update_order_with_items(db=db, order_id=order_id, order_update=order_update)
        if not updated_order:
            raise HTTPException(status_code=500, detail="Failed to update order")
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
    """Create dispatch record with form data and mark items as dispatched"""
    try:
        # Validate client exists
        client = crud_operations.get_client(db, dispatch_data.client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        # Get inventory items to be dispatched
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
        
        if not inventory_items:
            raise HTTPException(status_code=400, detail="No available inventory items found")
        
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
            total_items=len(inventory_items),
            total_weight_kg=total_weight,
            created_by_id=dispatch_data.created_by_id
        )
        
        db.add(dispatch_record)
        db.flush()  # Get ID
        
        # Create dispatch items and update inventory status
        completed_items = []
        updated_orders = []
        
        for item in inventory_items:
            # Create dispatch item record
            dispatch_item = models.DispatchItem(
                dispatch_record_id=dispatch_record.id,
                inventory_id=item.id,
                qr_code=item.qr_code,
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
                    models.OrderItem.width_inches == int(item.width_inches),
                    models.OrderMaster.status == "in_process",
                    models.OrderItem.item_status == "in_warehouse"
                ).limit(1).all()
                
                for order_item in matching_order_items:
                    order_item.item_status = "completed"
                    order_item.dispatched_at = db.func.now()
                    
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
        
        db.commit()
        db.refresh(dispatch_record)
        
        return {
            "message": f"Dispatch record created successfully with {len(completed_items)} items",
            "dispatch_id": str(dispatch_record.id),
            "dispatch_number": dispatch_record.dispatch_number,
            "client_name": client.company_name,
            "vehicle_number": dispatch_record.vehicle_number,
            "driver_name": dispatch_record.driver_name,
            "total_items": len(completed_items),
            "total_weight_kg": total_weight,
            "completed_orders": updated_orders,
            "summary": {
                "dispatched_items": len(completed_items),
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
    db: Session = Depends(get_db)
):
    """Get cut rolls (inventory items) that are ready for dispatch - weight added and status 'available'"""
    try:
        from sqlalchemy.orm import joinedload
        
        # Get inventory items (cut rolls) with status "available" and weight > 0.1 (real weight added)
        warehouse_items = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.created_by)
        ).filter(
            models.InventoryMaster.roll_type == "cut",
            models.InventoryMaster.status == "available",
            models.InventoryMaster.weight_kg > 0.1  # Real weight has been added
        ).order_by(models.InventoryMaster.created_at.desc()).offset(skip).limit(limit).all()
        
        items_data = []
        for item in warehouse_items:
            items_data.append({
                "inventory_id": str(item.id),
                "qr_code": item.qr_code,
                "paper_spec": f"{item.paper.gsm}gsm, {item.paper.bf}bf, {item.paper.shade}" if item.paper else "N/A",
                "width_inches": float(item.width_inches),
                "weight_kg": float(item.weight_kg),
                "location": item.location or "production_floor",
                "status": item.status,
                "production_date": item.production_date.isoformat(),
                "created_by": item.created_by.name if item.created_by else "Unknown",
                "created_at": item.created_at.isoformat()
            })
        
        return {
            "warehouse_items": items_data,
            "total_items": len(items_data),
            "dispatch_info": {
                "description": "Cut rolls with real weight added, ready for dispatch",
                "filter_criteria": "roll_type=cut, status=available, weight_kg > 0.1"
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

