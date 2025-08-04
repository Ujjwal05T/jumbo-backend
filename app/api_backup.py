from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional
import logging
import uuid
import json
from uuid import UUID
from datetime import datetime

from . import crud, schemas, models, database

# ============================================================================
# STATUS VALIDATION UTILITIES
# ============================================================================

def validate_status_transition(current_status: str, new_status: str, entity_type: str) -> bool:
    """
    Validate if a status transition is allowed for a given entity type.
    
    Args:
        current_status: Current status of the entity
        new_status: Desired new status
        entity_type: Type of entity (order, order_item, inventory, pending_order)
    
    Returns:
        bool: True if transition is valid, False otherwise
    """
    valid_transitions = {
        "order": {
            models.OrderStatus.CREATED: [models.OrderStatus.IN_PROCESS, models.OrderStatus.CANCELLED],
            models.OrderStatus.IN_PROCESS: [models.OrderStatus.COMPLETED, models.OrderStatus.CANCELLED],
            models.OrderStatus.COMPLETED: [],  # Terminal state
            models.OrderStatus.CANCELLED: []   # Terminal state
        },
        "order_item": {
            models.OrderItemStatus.CREATED: [models.OrderItemStatus.IN_PROCESS],
            models.OrderItemStatus.IN_PROCESS: [models.OrderItemStatus.IN_WAREHOUSE],
            models.OrderItemStatus.IN_WAREHOUSE: [models.OrderItemStatus.COMPLETED],
            models.OrderItemStatus.COMPLETED: []  # Terminal state
        },
        "inventory": {
            models.InventoryStatus.CUTTING: [models.InventoryStatus.AVAILABLE, models.InventoryStatus.DAMAGED],
            models.InventoryStatus.AVAILABLE: [models.InventoryStatus.ALLOCATED, models.InventoryStatus.USED, models.InventoryStatus.DAMAGED],
            models.InventoryStatus.ALLOCATED: [models.InventoryStatus.USED, models.InventoryStatus.AVAILABLE, models.InventoryStatus.DAMAGED],
            models.InventoryStatus.USED: [],  # Terminal state
            models.InventoryStatus.DAMAGED: []  # Terminal state
        },
        "pending_order": {
            models.PendingOrderStatus.PENDING: [models.PendingOrderStatus.INCLUDED_IN_PLAN, models.PendingOrderStatus.CANCELLED],
            models.PendingOrderStatus.INCLUDED_IN_PLAN: [models.PendingOrderStatus.RESOLVED],
            models.PendingOrderStatus.RESOLVED: [],  # Terminal state
            models.PendingOrderStatus.CANCELLED: []  # Terminal state
        }
    }
    
    if entity_type not in valid_transitions:
        logger.error(f"Unknown entity type: {entity_type}")
        return False
    
    if current_status not in valid_transitions[entity_type]:
        logger.error(f"Unknown current status for {entity_type}: {current_status}")
        return False
    
    return new_status in valid_transitions[entity_type][current_status]

def get_status_summary(db: Session) -> Dict[str, Any]:
    """
    Get a comprehensive summary of all entity statuses in the system.
    Useful for monitoring and debugging status flows.
    """
    try:
        # Order status summary
        order_status_counts = {}
        for status in models.OrderStatus:
            count = db.query(models.OrderMaster).filter(models.OrderMaster.status == status).count()
            order_status_counts[status.value] = count
        
        # Order item status summary
        item_status_counts = {}
        for status in models.OrderItemStatus:
            count = db.query(models.OrderItem).filter(models.OrderItem.item_status == status).count()
            item_status_counts[status.value] = count
        
        # Inventory status summary
        inventory_status_counts = {}
        for status in models.InventoryStatus:
            count = db.query(models.InventoryMaster).filter(models.InventoryMaster.status == status).count()
            inventory_status_counts[status.value] = count
        
        # Pending order status summary
        pending_status_counts = {}
        for status in models.PendingOrderStatus:
            count = db.query(models.PendingOrderItem).filter(models.PendingOrderItem.status == status).count()
            pending_status_counts[status.value] = count
        
        return {
            "orders": order_status_counts,
            "order_items": item_status_counts,
            "inventory": inventory_status_counts,
            "pending_orders": pending_status_counts,
            "generated_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error generating status summary: {e}")
        return {"error": str(e)}

def auto_update_order_statuses(db: Session) -> Dict[str, Any]:
    """
    Automatically update order statuses based on their item statuses.
    This ensures data consistency and handles edge cases where orders
    might not have been updated properly during the workflow.
    """
    try:
        updated_orders = []
        
        # Find orders that should be marked as completed
        orders_to_check = db.query(models.OrderMaster).filter(
            models.OrderMaster.status == models.OrderStatus.IN_PROCESS
        ).all()
        
        for order in orders_to_check:
            # Check if all items are completed
            all_items_completed = all(
                item.item_status == models.OrderItemStatus.COMPLETED
                for item in order.order_items
            )
            
            # Check if all quantities are fulfilled
            all_quantities_fulfilled = all(
                item.quantity_fulfilled >= item.quantity_rolls
                for item in order.order_items
            )
            
            if all_items_completed and all_quantities_fulfilled:
                order.status = models.OrderStatus.COMPLETED
                if not order.dispatched_at:
                    order.dispatched_at = datetime.utcnow()
                order.updated_at = datetime.utcnow()
                updated_orders.append(str(order.id))
                logger.info(f"Auto-updated order {order.id} to COMPLETED status")
        
        if updated_orders:
            db.commit()
        
        return {
            "updated_orders": updated_orders,
            "count": len(updated_orders),
            "updated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error in auto status update: {e}")
        return {"error": str(e)}

# Set up logging
logger = logging.getLogger(__name__)

# Create main router
router = APIRouter()

# Dependency
def get_db():
    if database.SessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection not available. Please check server logs."
        )
    
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================================================
# CLIENT MASTER ENDPOINTS
# ============================================================================

@router.post("/clients", response_model=schemas.ClientMaster, tags=["Client Master"])
def create_client(client: schemas.ClientMasterCreate, db: Session = Depends(get_db)):
    """Create a new client in Client Master"""
    try:
        return crud.create_client(db=db, client=client)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating client: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/clients", response_model=List[schemas.ClientMaster], tags=["Client Master"])
def get_clients(
    skip: int = 0,
    limit: int = 100,
    status: str = "active",
    db: Session = Depends(get_db)
):
    """Get all clients with pagination and status filter"""
    try:
        return crud.get_clients(db=db, skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting clients: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/clients/{client_id}", response_model=schemas.ClientMaster, tags=["Client Master"])
def get_client(client_id: UUID, db: Session = Depends(get_db)):
    """Get client by ID"""
    client = crud.get_client(db=db, client_id=client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client

@router.put("/clients/{client_id}", response_model=schemas.ClientMaster, tags=["Client Master"])
def update_client(
    client_id: UUID,
    client_update: schemas.ClientMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update client information"""
    try:
        client = crud.update_client(db=db, client_id=client_id, client_update=client_update)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        return client
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating client: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/clients/{client_id}", tags=["Client Master"])
def delete_client(client_id: UUID, db: Session = Depends(get_db)):
    """Delete (deactivate) client"""
    try:
        success = crud.delete_client(db=db, client_id=client_id)
        if not success:
            raise HTTPException(status_code=404, detail="Client not found")
        return {"message": "Client deactivated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting client: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# ============================================================================
# USER MASTER ENDPOINTS
# ============================================================================

@router.get("/users", response_model=List[schemas.UserMaster], tags=["User Master"])
def get_users(
    skip: int = 0,
    limit: int = 100,
    role: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all users with pagination and role filter"""
    try:
        return crud.get_users(db=db, skip=skip, limit=limit, role=role)
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}", response_model=schemas.UserMaster, tags=["User Master"])
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    """Get user by ID"""
    user = crud.get_user(db=db, user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/users/{user_id}", response_model=schemas.UserMaster, tags=["User Master"])
def update_user(
    user_id: UUID,
    user_update: schemas.UserMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update user information"""
    try:
        user = crud.update_user(db=db, user_id=user_id, user_update=user_update)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PAPER MASTER ENDPOINTS
# ============================================================================

@router.post("/papers", response_model=schemas.PaperMaster, tags=["Paper Master"])
def create_paper(paper: schemas.PaperMasterCreate, db: Session = Depends(get_db)):
    """Create a new paper specification in Paper Master"""
    try:
        logger.info(f"Creating paper with data: {paper.model_dump()}")
        
        # Validate required fields
        if not paper.name or not paper.name.strip():
            raise HTTPException(status_code=400, detail="Paper name is required and cannot be empty")
        
        if paper.gsm <= 0:
            raise HTTPException(status_code=400, detail="GSM must be greater than 0")
        
        if paper.bf <= 0:
            raise HTTPException(status_code=400, detail="BF must be greater than 0")
        
        if not paper.shade or not paper.shade.strip():
            raise HTTPException(status_code=400, detail="Shade is required and cannot be empty")
        
        # Validate enum values
        valid_types = ["standard", "premium", "recycled", "specialty"]
        if paper.type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid paper type. Must be one of: {valid_types}")
        
        return crud.create_paper(db=db, paper=paper)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating paper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/papers", response_model=List[schemas.PaperMaster], tags=["Paper Master"])
def get_papers(
    skip: int = 0,
    limit: int = 100,
    status: str = "active",
    db: Session = Depends(get_db)
):
    """Get all paper specifications with pagination and status filter"""
    try:
        return crud.get_papers(db=db, skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting papers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/papers/{paper_id}", response_model=schemas.PaperMaster, tags=["Paper Master"])
def get_paper(paper_id: UUID, db: Session = Depends(get_db)):
    """Get paper specification by ID"""
    paper = crud.get_paper(db=db, paper_id=paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper specification not found")
    return paper

@router.get("/papers/search", response_model=Optional[schemas.PaperMaster], tags=["Paper Master"])
def search_paper_by_specs(
    gsm: int,
    bf: float,
    shade: str,
    type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Search paper by specifications (GSM, BF, Shade, Type)"""
    try:
        paper = crud.get_paper_by_specs(db=db, gsm=gsm, bf=bf, shade=shade, type=type)
        return paper
    except Exception as e:
        logger.error(f"Error searching paper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/papers/{paper_id}", response_model=schemas.PaperMaster, tags=["Paper Master"])
def update_paper(
    paper_id: UUID,
    paper_update: schemas.PaperMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update paper specification"""
    try:
        logger.info(f"Updating paper {paper_id} with data: {paper_update.model_dump(exclude_unset=True)}")
        
        # Validate fields if provided
        if paper_update.name is not None and (not paper_update.name or not paper_update.name.strip()):
            raise HTTPException(status_code=400, detail="Paper name cannot be empty")
        
        if paper_update.gsm is not None and paper_update.gsm <= 0:
            raise HTTPException(status_code=400, detail="GSM must be greater than 0")
        
        if paper_update.bf is not None and paper_update.bf <= 0:
            raise HTTPException(status_code=400, detail="BF must be greater than 0")
        
        if paper_update.shade is not None and (not paper_update.shade or not paper_update.shade.strip()):
            raise HTTPException(status_code=400, detail="Shade cannot be empty")
        
        if paper_update.thickness is not None and paper_update.thickness <= 0:
            raise HTTPException(status_code=400, detail="Thickness must be greater than 0")
        
        # Validate enum values if provided
        if paper_update.type is not None:
            valid_types = ["standard", "premium", "recycled", "specialty"]
            if paper_update.type not in valid_types:
                raise HTTPException(status_code=400, detail=f"Invalid paper type. Must be one of: {valid_types}")
        
        if paper_update.status is not None:
            valid_statuses = ["active", "inactive", "suspended"]
            if paper_update.status not in valid_statuses:
                raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
        
        paper = crud.update_paper(db=db, paper_id=paper_id, paper_update=paper_update)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper specification not found")
        return paper
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating paper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/papers/{paper_id}", tags=["Paper Master"])
def delete_paper(paper_id: UUID, db: Session = Depends(get_db)):
    """Delete (deactivate) paper specification"""
    try:
        success = crud.delete_paper(db=db, paper_id=paper_id)
        if not success:
            raise HTTPException(status_code=404, detail="Paper specification not found")
        return {"message": "Paper specification deactivated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting paper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/papers/debug/validation", tags=["Paper Master"])
def debug_paper_validation(db: Session = Depends(get_db)):
    """Debug endpoint to check paper validation and duplicates"""
    try:
        # Get all active papers
        papers = db.query(models.PaperMaster).filter(
            models.PaperMaster.status == "active"
        ).all()
        
        # Check for duplicate specifications
        spec_groups = {}
        name_duplicates = {}
        
        for paper in papers:
            # Group by specifications
            spec_key = f"{paper.gsm}-{paper.bf}-{paper.shade}-{paper.type}"
            if spec_key not in spec_groups:
                spec_groups[spec_key] = []
            spec_groups[spec_key].append({
                "id": str(paper.id),
                "name": paper.name,
                "gsm": paper.gsm,
                "bf": paper.bf,
                "shade": paper.shade,
                "type": paper.type
            })
            
            # Group by name
            if paper.name not in name_duplicates:
                name_duplicates[paper.name] = []
            name_duplicates[paper.name].append({
                "id": str(paper.id),
                "gsm": paper.gsm,
                "bf": paper.bf,
                "shade": paper.shade,
                "type": paper.type
            })
        
        # Find duplicates
        duplicate_specs = {k: v for k, v in spec_groups.items() if len(v) > 1}
        duplicate_names = {k: v for k, v in name_duplicates.items() if len(v) > 1}
        
        return {
            "total_active_papers": len(papers),
            "duplicate_specifications": duplicate_specs,
            "duplicate_names": duplicate_names,
            "validation_rules": {
                "name": "Required, max 255 chars, must be unique",
                "gsm": "Required, must be > 0",
                "bf": "Required, must be > 0",
                "shade": "Required, max 50 chars",
                "type": "Must be one of: standard, premium, recycled, specialty",
                "thickness": "Optional, must be > 0 if provided"
            }
        }
    except Exception as e:
        logger.error(f"Debug endpoint error: {e}")
        return {"error": str(e)}

# ============================================================================
# ORDER MASTER ENDPOINTS
# ============================================================================

@router.post("/orders", response_model=schemas.OrderMaster, tags=["Order Master"])
async def create_order(request: Request, db: Session = Depends(get_db)):
    """Create a new order with multiple order items"""
    try:
        # First, let's see the raw request body
        body = await request.body()
        logger.info(f"Raw request body: {body.decode()}")
        
        # Parse the JSON
        data = json.loads(body.decode())
        logger.info(f"Parsed JSON data: {data}")
        
        # Try to validate with Pydantic
        try:
            order = schemas.OrderMasterCreate(**data)
            logger.info(f"Successfully validated order: {order.model_dump()}")
        except Exception as validation_error:
            logger.error(f"Pydantic validation failed: {validation_error}")
            raise HTTPException(status_code=422, detail=f"Validation error: {str(validation_error)}")
        
        if not order.order_items or len(order.order_items) == 0:
            raise HTTPException(status_code=400, detail="At least one order item is required")
        
        result = crud.create_order(db=db, order=order)
        logger.info(f"Order created successfully: {result.id}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders", response_model=List[schemas.OrderMaster], tags=["Order Master"])
def get_orders(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    client_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """Get all orders with pagination and filters"""
    try:
        return crud.get_orders(db=db, skip=skip, limit=limit, status=status, client_id=client_id)
    except Exception as e:
        logger.error(f"Error getting orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/{order_id}", response_model=schemas.OrderMaster, tags=["Order Master"])
def get_order(order_id: UUID, db: Session = Depends(get_db)):
    """Get order by ID with related data"""
    order = crud.get_order(db=db, order_id=order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.put("/orders/{order_id}", response_model=schemas.OrderMaster, tags=["Order Master"])
def update_order(
    order_id: UUID,
    order_update: schemas.OrderMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update order information"""
    try:
        order = crud.update_order(db=db, order_id=order_id, order_update=order_update)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    except Exception as e:
        logger.error(f"Error updating order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/order-items/{item_id}/fulfill", tags=["Order Items"])
def fulfill_order_item(
    item_id: UUID,
    request_data: Dict[str, int],
    db: Session = Depends(get_db)
):
    """Fulfill a specific order item by updating quantity_fulfilled"""
    try:
        # Get the order item
        order_item = crud.get_order_item(db=db, order_item_id=item_id)
        if not order_item:
            raise HTTPException(status_code=404, detail="Order item not found")
        
        # Extract quantity to fulfill
        quantity_to_fulfill = request_data.get('quantity_fulfilled', 0)
        if quantity_to_fulfill < 0:
            raise HTTPException(status_code=400, detail="Quantity fulfilled cannot be negative")
        
        if quantity_to_fulfill > order_item.quantity_rolls:
            raise HTTPException(status_code=400, detail="Cannot fulfill more than ordered quantity")
        
        # Update the order item
        update_data = schemas.OrderItemUpdate(quantity_fulfilled=quantity_to_fulfill)
        updated_item = crud.update_order_item(db=db, order_item_id=item_id, order_item_update=update_data)
        if not updated_item:
            raise HTTPException(status_code=500, detail="Failed to update order item")
        
        # Update order status if needed
        order = crud.get_order(db=db, order_id=order_item.order_id)
        if order and order.is_fully_fulfilled:
            order.status = "completed"
            db.commit()
            db.refresh(order)
        elif order and order.total_quantity_fulfilled > 0:
            order.status = "in_process"
            db.commit()
            db.refresh(order)
        
        return {"message": "Order item fulfilled successfully", "order_item": updated_item}
        
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
        fulfillment_requests = request_data.get('fulfillment_requests', [])
        
        if not fulfillment_requests:
            raise HTTPException(status_code=400, detail="fulfillment_requests is required")
        
        results = []
        updated_orders = set()
        
        for request in fulfillment_requests:
            item_id = request.get('item_id')
            quantity_fulfilled = request.get('quantity_fulfilled', 0)
            
            if not item_id:
                continue
                
            # Update order item
            order_item = crud.get_order_item(db=db, order_item_id=item_id)
            if order_item:
                update_data = schemas.OrderItemUpdate(quantity_fulfilled=quantity_fulfilled)
                updated_item = crud.update_order_item(db=db, order_item_id=item_id, order_item_update=update_data)
                if updated_item:
                    results.append({"item_id": item_id, "status": "fulfilled", "quantity": quantity_fulfilled})
                    updated_orders.add(updated_item.order_id)
        
        # Update order statuses
        for order_id in updated_orders:
            order = crud.get_order(db=db, order_id=order_id)
            if order:
                if order.is_fully_fulfilled:
                    order.status = "completed"
                elif order.total_quantity_fulfilled > 0:
                    order.status = "in_process"
                db.commit()
        
        result = {"fulfilled_items": results, "updated_orders": len(updated_orders)}
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk fulfilling orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================================
# ORDER ITEM ENDPOINTS
# ============================================================================

@router.post("/orders/{order_id}/items", response_model=schemas.OrderItem, tags=["Order Items"])
def create_order_item(
    order_id: UUID,
    order_item: schemas.OrderItemCreate,
    db: Session = Depends(get_db)
):
    """Create a new order item for an existing order"""
    try:
        # Verify order exists
        order = crud.get_order(db=db, order_id=order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        return crud.create_order_item(db=db, order_id=order_id, order_item=order_item)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/{order_id}/items", response_model=List[schemas.OrderItem], tags=["Order Items"])
def get_order_items(order_id: UUID, db: Session = Depends(get_db)):
    """Get all items for a specific order"""
    try:
        order = crud.get_order(db=db, order_id=order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        return order.order_items
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting order items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/order-items/{item_id}", response_model=schemas.OrderItem, tags=["Order Items"])
def get_order_item(item_id: UUID, db: Session = Depends(get_db)):
    """Get specific order item by ID"""
    item = crud.get_order_item(db=db, order_item_id=item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Order item not found")
    return item

@router.put("/order-items/{item_id}", response_model=schemas.OrderItem, tags=["Order Items"])
def update_order_item(
    item_id: UUID,
    order_item_update: schemas.OrderItemUpdate,
    db: Session = Depends(get_db)
):
    """Update order item"""
    try:
        item = crud.update_order_item(db=db, order_item_id=item_id, order_item_update=order_item_update)
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
        success = crud.delete_order_item(db=db, order_item_id=item_id)
        if not success:
            raise HTTPException(status_code=404, detail="Order item not found")
        return {"message": "Order item deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PENDING ORDER ITEM ENDPOINTS  
# ============================================================================

@router.post("/pending-order-items", response_model=schemas.PendingOrderItem, tags=["Pending Order Items"])
def create_pending_order_item(pending: schemas.PendingOrderItemCreate, db: Session = Depends(get_db)):
    """Create a new pending order item"""
    try:
        from .services.pending_order_service import PendingOrderService
        service = PendingOrderService(db, pending.created_by_id)
        
        # Convert to service format
        pending_items = [{
            'width': pending.width_inches,
            'quantity': pending.quantity_pending,
            'gsm': pending.gsm,
            'bf': pending.bf,
            'shade': pending.shade
        }]
        
        created_items = service.create_pending_items(
            pending_orders=pending_items,
            original_order_id=pending.original_order_id,
            reason=pending.reason
        )
        
        return created_items[0] if created_items else None
    except Exception as e:
        logger.error(f"Error creating pending order item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-order-items", response_model=List[schemas.PendingOrderItem], tags=["Pending Order Items"])
def get_pending_order_items(
    skip: int = 0,
    limit: int = 100,
    status: str = "pending",
    db: Session = Depends(get_db)
):
    """Get all pending order items with pagination"""
    try:
        from .services.pending_order_service import PendingOrderService
        service = PendingOrderService(db)
        
        # Get pending items from database (SQL Server requires ORDER BY with OFFSET)
        query = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == status
        ).order_by(models.PendingOrderItem.created_at.desc()).offset(skip).limit(limit)
        
        return query.all()
    except Exception as e:
        logger.error(f"Error getting pending order items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-order-items/summary", tags=["Pending Order Items"])
def get_pending_items_summary(db: Session = Depends(get_db)):
    """Get summary statistics for pending order items"""
    try:
        from .services.pending_order_service import PendingOrderService
        service = PendingOrderService(db)
        return service.get_pending_summary()
    except Exception as e:
        logger.error(f"Error getting pending items summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-order-items/debug", tags=["Pending Order Items"])
def debug_pending_items(db: Session = Depends(get_db)):
    """Debug endpoint to check pending items data"""
    try:
        # Check if table exists and has data
        total_items = db.query(models.PendingOrderItem).count()
        pending_items = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == "pending"
        ).limit(5).all()
        
        all_statuses = db.query(models.PendingOrderItem.status).distinct().all()
        
        return {
            "total_pending_items_in_db": total_items,
            "pending_status_count": len(pending_items),
            "all_statuses_in_db": [status[0] for status in all_statuses],
            "sample_items": [
                {
                    "id": str(item.id),
                    "width_inches": item.width_inches,
                    "gsm": item.gsm,
                    "shade": item.shade,
                    "quantity_pending": item.quantity_pending,
                    "status": item.status,
                    "reason": item.reason,
                    "created_at": item.created_at.isoformat() if item.created_at else None
                } for item in pending_items
            ]
        }
    except Exception as e:
        logger.error(f"Debug endpoint error: {e}")
        return {
            "error": str(e),
            "table_exists": False,
            "total_pending_items_in_db": 0
        }

@router.get("/pending-order-items/consolidation", tags=["Pending Order Items"])
def get_consolidation_opportunities(db: Session = Depends(get_db)):
    """Get consolidation opportunities for pending items"""
    try:
        from .services.pending_order_service import PendingOrderService
        service = PendingOrderService(db)
        return service.get_consolidation_opportunities()
    except Exception as e:
        logger.error(f"Error getting consolidation opportunities: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# OLD FLOW REMOVED: Legacy pending-orders endpoint
# Use /pending-order-items instead

# ============================================================================
# INVENTORY MASTER ENDPOINTS
# ============================================================================

@router.post("/inventory", response_model=schemas.InventoryMaster, tags=["Inventory Master"])
def create_inventory_item(inventory: schemas.InventoryMasterCreate, db: Session = Depends(get_db)):
    """Create a new inventory item"""
    try:
        return crud.create_inventory_item(db=db, inventory=inventory)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating inventory item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory", response_model=List[schemas.InventoryMaster], tags=["Inventory Master"])
def get_inventory_items(
    skip: int = 0,
    limit: int = 100,
    roll_type: Optional[str] = None,
    status: str = "available",
    db: Session = Depends(get_db)
):
    """Get all inventory items with pagination and filters"""
    try:
        return crud.get_inventory_items(db=db, skip=skip, limit=limit, roll_type=roll_type, status=status)
    except Exception as e:
        logger.error(f"Error getting inventory items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory/{inventory_id}", response_model=schemas.InventoryMaster, tags=["Inventory Master"])
def get_inventory_item(inventory_id: UUID, db: Session = Depends(get_db)):
    """Get inventory item by ID"""
    item = crud.get_inventory_item(db=db, inventory_id=inventory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item

@router.put("/inventory/{inventory_id}", response_model=schemas.InventoryMaster, tags=["Inventory Master"])
def update_inventory_item(
    inventory_id: UUID,
    inventory_update: schemas.InventoryMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update inventory item"""
    try:
        item = crud.update_inventory_item(db=db, inventory_id=inventory_id, inventory_update=inventory_update)
        if not item:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        return item
    except Exception as e:
        logger.error(f"Error updating inventory item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory/jumbo-rolls", response_model=List[schemas.InventoryMaster], tags=["Inventory Master"])
def get_jumbo_rolls(
    skip: int = 0,
    limit: int = 100,
    status: str = "available",
    db: Session = Depends(get_db)
):
    """Get jumbo rolls from inventory"""
    try:
        return crud.get_inventory_items(db=db, skip=skip, limit=limit, roll_type="jumbo", status=status)
    except Exception as e:
        logger.error(f"Error getting jumbo rolls: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory/cut-rolls", response_model=List[schemas.InventoryMaster], tags=["Inventory Master"])
def get_cut_rolls(
    skip: int = 0,
    limit: int = 100,
    status: str = "available",
    db: Session = Depends(get_db)
):
    """Get cut rolls from inventory"""
    try:
        return crud.get_inventory_items(db=db, skip=skip, limit=limit, roll_type="cut", status=status)
    except Exception as e:
        logger.error(f"Error getting cut rolls: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/inventory/available/{paper_id}", response_model=List[schemas.InventoryMaster], tags=["Inventory Master"])
def get_available_inventory(
    paper_id: UUID,
    width_inches: Optional[float] = None,
    roll_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get available inventory for cutting optimization"""
    try:
        return crud.get_available_inventory(db=db, paper_id=paper_id, width_inches=width_inches, roll_type=roll_type)
    except Exception as e:
        logger.error(f"Error getting available inventory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PLAN MASTER ENDPOINTS
# ============================================================================

@router.post("/plans", response_model=schemas.PlanMaster, tags=["Plan Master"])
def create_plan(plan: schemas.PlanMasterCreate, db: Session = Depends(get_db)):
    """Create a new cutting plan"""
    try:
        return crud.create_plan(db=db, plan=plan)
    except Exception as e:
        logger.error(f"Error creating plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/plans", response_model=List[schemas.PlanMaster], tags=["Plan Master"])
def get_plans(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all cutting plans with pagination"""
    try:
        return crud.get_plans(db=db, skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting plans: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/plans/{plan_id}", response_model=schemas.PlanMaster, tags=["Plan Master"])
def get_plan(plan_id: UUID, db: Session = Depends(get_db)):
    """Get cutting plan by ID"""
    plan = crud.get_plan(db=db, plan_id=plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Cutting plan not found")
    return plan

@router.put("/plans/{plan_id}", response_model=schemas.PlanMaster, tags=["Plan Master"])
def update_plan(
    plan_id: UUID,
    plan_update: schemas.PlanMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update cutting plan status"""
    try:
        plan = crud.update_plan(db=db, plan_id=plan_id, plan_update=plan_update)
        if not plan:
            raise HTTPException(status_code=404, detail="Cutting plan not found")
        return plan
    except Exception as e:
        logger.error(f"Error updating plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# ============================================================================
# CUTTING OPTIMIZER ROUTES
# ============================================================================

@router.post("/optimizer/create-plan", response_model=schemas.OptimizerOutput, tags=["Cutting Optimizer"])
def create_cutting_plan(
    request: schemas.CreatePlanRequest,
    db: Session = Depends(get_db)
):
    """NEW FLOW: Create a cutting plan using 3-input/4-output optimization
    
    Fetches order details, pending orders, and available inventory,
    runs the NEW FLOW optimization algorithm, and returns 4 outputs.
    """
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        from . import crud
        import uuid
        
        # Convert string IDs to UUIDs
        uuid_order_ids = []
        for order_id in request.order_ids:
            try:
                uuid_order_ids.append(uuid.UUID(order_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {order_id}")
        
        # NEW FLOW: Get order requirements with paper specs
        order_requirements = crud.get_orders_with_paper_specs(db, uuid_order_ids)
        
        if not order_requirements:
            raise HTTPException(status_code=404, detail="No valid orders found with provided IDs")
        
        # NEW FLOW: Get paper specifications from orders
        paper_specs = []
        for req in order_requirements:
            spec = {'gsm': req['gsm'], 'bf': req['bf'], 'shade': req['shade']}
            if spec not in paper_specs:
                paper_specs.append(spec)
        
        # NEW FLOW: Fetch pending orders for same specifications
        pending_orders_db = crud.get_pending_orders_by_paper_specs(db, paper_specs)
        pending_requirements = []
        for pending in pending_orders_db:
            if pending.paper:
                pending_requirements.append({
                    'width': float(pending.width_inches),
                    'quantity': pending.quantity_pending,
                    'gsm': pending.paper.gsm,
                    'bf': float(pending.paper.bf),
                    'shade': pending.paper.shade,
                    'pending_id': str(pending.id)
                })
        
        # NEW FLOW: Fetch available inventory (20-25" waste rolls)
        available_inventory_db = crud.get_available_inventory_by_paper_specs(db, paper_specs)
        available_inventory = []
        for inv_item in available_inventory_db:
            if inv_item.paper:
                available_inventory.append({
                    'id': str(inv_item.id),
                    'width': float(inv_item.width_inches),
                    'gsm': inv_item.paper.gsm,
                    'bf': float(inv_item.paper.bf),
                    'shade': inv_item.paper.shade,
                    'weight': float(inv_item.weight_kg) if inv_item.weight_kg else 0
                })
        
        logger.info(f"NEW FLOW Optimization: {len(order_requirements)} orders, {len(pending_requirements)} pending, {len(available_inventory)} inventory")
        
        # NEW FLOW: Run 3-input optimization
        optimizer = CuttingOptimizer()
        optimization_result = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=pending_requirements,
            available_inventory=available_inventory,
            interactive=False
        )
        
        return optimization_result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating cutting plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# WORKFLOW MANAGEMENT ROUTES
# ============================================================================

@router.post("/workflow/generate-plan", response_model=schemas.WorkflowResult, tags=["Workflow Management"])
def generate_cutting_plan_from_workflow(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """NEW FLOW: Generate a cutting plan using workflow manager with 4-output processing"""
    try:
        from .services.workflow_manager import WorkflowManager
        import uuid
        
        # Extract data from request body
        order_ids = request_data.get('order_ids', [])
        created_by_id = request_data.get('created_by_id')
        
        if not order_ids:
            raise HTTPException(status_code=400, detail="order_ids is required")
        if not created_by_id:
            raise HTTPException(status_code=400, detail="created_by_id is required")
        
        # Convert string IDs to UUIDs
        uuid_order_ids = []
        for order_id in order_ids:
            try:
                uuid_order_ids.append(uuid.UUID(order_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {order_id}")
        
        try:
            created_by_uuid = uuid.UUID(created_by_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format for created_by_id: {created_by_id}")
        
        # Initialize workflow manager
        workflow_manager = WorkflowManager(db=db, user_id=created_by_uuid)
        
        # NEW FLOW: Process orders directly (skip inventory check)
        result = workflow_manager.process_multiple_orders(uuid_order_ids)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating cutting plan from workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/workflow/process-orders", tags=["Workflow Management"])
def process_multiple_orders(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Process multiple orders together for optimal cutting plans"""
    try:
        from .services.workflow_manager import WorkflowManager
        import uuid
        
        # Extract data from request body
        order_ids = request_data.get('order_ids', [])
        user_id = request_data.get('user_id')
        
        if not order_ids:
            raise HTTPException(status_code=400, detail="order_ids is required")
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        
        # Convert string IDs to UUIDs
        uuid_order_ids = []
        for order_id in order_ids:
            try:
                uuid_order_ids.append(uuid.UUID(order_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {order_id}")
        
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format for user_id: {user_id}")
        
        # Initialize workflow manager
        workflow_manager = WorkflowManager(db=db, user_id=user_uuid)
        
        # Process orders
        result = workflow_manager.process_multiple_orders(uuid_order_ids)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing multiple orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/workflow/status", tags=["Workflow Management"])
def get_workflow_status(db: Session = Depends(get_db)):
    """Get overall workflow status and metrics"""
    try:
        from .services.workflow_manager import WorkflowManager
        
        # Initialize workflow manager
        workflow_manager = WorkflowManager(db=db)
        
        # Get workflow status
        status = workflow_manager.get_workflow_status()
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting workflow status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/workflow/orders-with-relationships", tags=["Workflow Management"])
def get_orders_with_relationships(
    order_ids: List[str],
    db: Session = Depends(get_db)
):
    """Get orders with all related data (User, Client, Paper) via foreign keys"""
    try:
        from .services.workflow_manager import WorkflowManager
        import uuid
        
        # Convert string IDs to UUIDs
        uuid_order_ids = []
        for order_id in order_ids:
            try:
                uuid_order_ids.append(uuid.UUID(order_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {order_id}")
        
        # Initialize workflow manager
        workflow_manager = WorkflowManager(db=db)
        
        # Get orders with relationships
        orders = workflow_manager.get_orders_with_relationships(uuid_order_ids)
        
        # Convert to response format
        result = []
        for order in orders:
            order_data = {
                "id": str(order.id),
                "width": order.width,
                "quantity": order.quantity,
                "quantity_fulfilled": order.quantity_fulfilled or 0,
                "min_length": order.min_length,
                "status": order.status,
                "created_at": order.created_at,
                "client": {
                    "id": str(order.client.id),
                    "name": order.client.name,
                    "contact": order.client.contact
                } if order.client else None,
                "paper": {
                    "id": str(order.paper.id),
                    "gsm": order.paper.gsm,
                    "bf": order.paper.bf,
                    "shade": order.paper.shade,
                    "type": order.paper.type
                } if order.paper else None,
                "created_by": {
                    "id": str(order.created_by.id),
                    "name": order.created_by.name,
                    "username": order.created_by.username,
                    "role": order.created_by.role
                } if order.created_by else None
            }
            result.append(order_data)
        
        return {
            "orders": result,
            "total_count": len(result)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting orders with relationships: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# PLAN STATUS UPDATE ROUTES
# ============================================================================

@router.put("/plans/{plan_id}/status", response_model=schemas.PlanMaster, tags=["Plan Management"])
def update_plan_status(
    plan_id: str,
    status: str,
    actual_waste_percentage: Optional[float] = None,
    db: Session = Depends(get_db)
):
    """Update plan status and actual waste percentage"""
    try:
        import uuid
        
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {plan_id}")
        
        # Validate status
        valid_statuses = [status.value for status in schemas.PlanStatus]
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
        
        # Create update data
        update_data = schemas.PlanMasterUpdate(
            status=status,
            actual_waste_percentage=actual_waste_percentage
        )
        
        # Update plan
        plan = crud.update_plan(db, plan_uuid, update_data)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        return plan
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating plan status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/{plan_id}/execute", response_model=schemas.PlanMaster, tags=["Plan Management"])
def execute_cutting_plan(
    plan_id: str,
    db: Session = Depends(get_db)
):
    """Execute a cutting plan by updating status to in_progress"""
    try:
        import uuid
        
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {plan_id}")
        
        # Update plan status to in_progress
        update_data = schemas.PlanMasterUpdate(status="in_progress")
        plan = crud.update_plan(db, plan_uuid, update_data)
        
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        return plan
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing cutting plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/{plan_id}/complete", response_model=schemas.PlanMaster, tags=["Plan Management"])
def complete_cutting_plan(
    plan_id: str,
    actual_waste_percentage: Optional[float] = None,
    db: Session = Depends(get_db)
):
    """Complete a cutting plan by updating status to completed"""
    try:
        import uuid
        
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {plan_id}")
        
        # Update plan status to completed
        update_data = schemas.PlanMasterUpdate(
            status="completed",
            actual_waste_percentage=actual_waste_percentage
        )
        plan = crud.update_plan(db, plan_uuid, update_data)
        
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        return plan
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing cutting plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/{plan_id}/start-production", tags=["Plan Management"])
def start_production(
    plan_id: str,
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    NEW FLOW: Start production for a plan
    1. Update order/order item statuses to 'in_process'
    2. Create inventory records for selected cut rolls
    3. Update pending order statuses to 'included_in_plan'
    4. Add production tracking timestamps
    """
    try:
        import uuid
        from datetime import datetime
        
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {plan_id}")
        
        # Get the plan
        plan = crud.get_plan(db, plan_uuid)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Extract selected cut rolls from request
        selected_cut_rolls = request_data.get('selected_cut_rolls', [])
        user_id = request_data.get('user_id')
        
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")
        
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format for user_id: {user_id}")
        
        # Get all orders linked to this plan
        plan_order_links = db.query(models.PlanOrderLink).filter(
            models.PlanOrderLink.plan_id == plan_uuid
        ).all()
        
        order_ids = [link.order_id for link in plan_order_links]
        updated_orders = []
        updated_order_items = []
        created_inventory = []
        updated_pending_orders = []
        
        current_time = datetime.utcnow()
        
        # 1. Update order statuses: created → in_process (with validation)
        for order_id in order_ids:
            order = crud.get_order(db, order_id)
            if not order:
                logger.warning(f"Order {order_id} not found during production start")
                continue
                
            # Validate status transition - only CREATED orders can start production
            if order.status == models.OrderStatus.CREATED:
                order.status = models.OrderStatus.IN_PROCESS
                order.started_production_at = current_time
                order.updated_at = current_time
                updated_orders.append(str(order_id))
                logger.info(f"Order {order_id} status updated: CREATED → IN_PROCESS")
                
                # 2. Update order item statuses: created → in_process (with validation)
                for order_item in order.order_items:
                    if order_item.item_status == models.OrderItemStatus.CREATED:
                        order_item.item_status = models.OrderItemStatus.IN_PROCESS
                        order_item.started_production_at = current_time
                        order_item.updated_at = current_time
                        updated_order_items.append(str(order_item.id))
                        logger.info(f"Order item {order_item.id} status updated: CREATED → IN_PROCESS")
                    else:
                        logger.warning(f"Order item {order_item.id} not in CREATED status, current: {order_item.item_status}")
            elif order.status == models.OrderStatus.IN_PROCESS:
                logger.warning(f"Order {order_id} is already IN_PROCESS - production may have already started")
            else:
                logger.error(f"Order {order_id} cannot start production from status: {order.status}. Expected: CREATED")
                # Don't raise an error, just skip this order and continue with others
        
        # 3. Create inventory records for selected cut rolls with status 'cutting'
        for cut_roll in selected_cut_rolls:
            # Find or create paper master for this cut roll
            paper = crud.get_paper_by_specs(
                db,
                gsm=cut_roll['gsm'],
                bf=cut_roll['bf'],
                shade=cut_roll['shade']
            )
            
            if not paper:
                # Create paper master if it doesn't exist
                paper_data = type('PaperCreate', (), {
                    'name': f"{cut_roll['shade']} {cut_roll['gsm']}GSM BF{cut_roll['bf']}",
                    'gsm': cut_roll['gsm'],
                    'bf': cut_roll['bf'],
                    'shade': cut_roll['shade'],
                    'type': 'standard',
                    'created_by_id': user_uuid
                })()
                paper = crud.create_paper(db, paper_data)
            
            # Create inventory record with status 'cutting'
            inventory_item = models.InventoryMaster(
                paper_id=paper.id,
                width_inches=float(cut_roll['width']),
                weight_kg=0.0,  # Will be updated when QR weight is added
                roll_type=models.RollType.CUT,
                status=models.InventoryStatus.CUTTING,
                qr_code=f"QR_{plan_uuid}_{len(created_inventory)+1}",  # Generate unique QR code
                production_date=current_time,
                created_by_id=user_uuid
            )
            db.add(inventory_item)
            created_inventory.append({
                "id": str(inventory_item.id),
                "width": float(cut_roll['width']),
                "qr_code": inventory_item.qr_code,
                "status": "cutting"
            })
        
        # 4. Update pending order statuses: pending → included_in_plan
        # Get pending orders that might be included in this plan
        if selected_cut_rolls:
            # Get unique paper specs from selected cut rolls
            paper_specs = []
            for roll in selected_cut_rolls:
                spec = (roll['gsm'], roll['shade'], roll['bf'])
                if spec not in paper_specs:
                    paper_specs.append(spec)
            
            # Find pending orders with matching specs
            for gsm, shade, bf in paper_specs:
                pending_items = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.gsm == gsm,
                    models.PendingOrderItem.shade == shade,
                    models.PendingOrderItem.bf == bf,
                    models.PendingOrderItem.status == models.PendingOrderStatus.PENDING
                ).all()
                
                for pending_item in pending_items:
                    # Check if this pending item's width matches any selected cut roll
                    matching_roll = next(
                        (roll for roll in selected_cut_rolls 
                         if abs(float(roll['width']) - float(pending_item.width_inches)) < 0.1 and
                            roll['gsm'] == pending_item.gsm and
                            roll['shade'] == pending_item.shade and
                            abs(float(roll['bf']) - float(pending_item.bf)) < 0.1),
                        None
                    )
                    
                    if matching_roll:
                        pending_item.status = models.PendingOrderStatus.INCLUDED_IN_PLAN
                        updated_pending_orders.append(str(pending_item.id))
        
        # 5. Update plan status to in_progress
        plan.status = models.PlanStatus.IN_PROGRESS
        plan.executed_at = current_time
        
        db.commit()
        
        return {
            "message": "Production started successfully",
            "plan_id": plan_id,
            "plan_status": "in_progress",
            "started_at": current_time.isoformat(),
            "summary": {
                "orders_updated": len(updated_orders),
                "order_items_updated": len(updated_order_items),
                "inventory_created": len(created_inventory),
                "pending_orders_updated": len(updated_pending_orders)
            },
            "details": {
                "updated_orders": updated_orders,
                "updated_order_items": updated_order_items,
                "created_inventory": created_inventory,
                "updated_pending_orders": updated_pending_orders
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error starting production: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# INVENTORY LINKING ROUTES
# ============================================================================

@router.post("/plans/{plan_id}/link-inventory", tags=["Plan Management"])
def link_inventory_to_plan(
    plan_id: str,
    inventory_links: List[Dict[str, Any]],
    db: Session = Depends(get_db)
):
    """Link inventory items to a cutting plan"""
    try:
        import uuid
        
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {plan_id}")
        
        # Verify plan exists
        plan = crud.get_plan(db, plan_uuid)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Create inventory links
        created_links = []
        for link_data in inventory_links:
            try:
                inventory_id = uuid.UUID(link_data.get("inventory_id"))
                quantity_used = float(link_data.get("quantity_used", 0))
                
                # Verify inventory item exists
                inventory_item = crud.get_inventory_item(db, inventory_id)
                if not inventory_item:
                    raise HTTPException(status_code=404, detail=f"Inventory item {inventory_id} not found")
                
                # Create plan inventory link
                inventory_link = models.PlanInventoryLink(
                    plan_id=plan_uuid,
                    inventory_id=inventory_id,
                    quantity_used=quantity_used
                )
                db.add(inventory_link)
                created_links.append({
                    "inventory_id": str(inventory_id),
                    "quantity_used": quantity_used,
                    "inventory_item": {
                        "id": str(inventory_item.id),
                        "roll_type": inventory_item.roll_type,
                        "width": inventory_item.width,
                        "length": inventory_item.length,
                        "weight": inventory_item.weight
                    }
                })
                
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=f"Invalid data in inventory link: {ve}")
        
        db.commit()
        
        return {
            "message": f"Successfully linked {len(created_links)} inventory items to plan",
            "plan_id": plan_id,
            "inventory_links": created_links
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error linking inventory to plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/plans/{plan_id}/inventory", tags=["Plan Management"])
def get_plan_inventory_links(
    plan_id: str,
    db: Session = Depends(get_db)
):
    """Get all inventory items linked to a cutting plan"""
    try:
        import uuid
        
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {plan_id}")
        
        # Get plan with inventory links
        plan = db.query(models.PlanMaster).filter(
            models.PlanMaster.id == plan_uuid
        ).first()
        
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get inventory links with related inventory data
        inventory_links = db.query(models.PlanInventoryLink).join(
            models.InventoryMaster
        ).filter(
            models.PlanInventoryLink.plan_id == plan_uuid
        ).all()
        
        result = []
        for link in inventory_links:
            result.append({
                "link_id": str(link.id),
                "quantity_used": float(link.quantity_used),
                "inventory_item": {
                    "id": str(link.inventory.id),
                    "roll_type": link.inventory.roll_type,
                    "width": link.inventory.width,
                    "length": link.inventory.length,
                    "weight": link.inventory.weight,
                    "status": link.inventory.status,
                    "paper": {
                        "gsm": link.inventory.paper.gsm,
                        "bf": link.inventory.paper.bf,
                        "shade": link.inventory.paper.shade
                    } if link.inventory.paper else None
                }
            })
        
        return {
            "plan_id": plan_id,
            "inventory_links": result,
            "total_links": len(result)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plan inventory links: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/plans/{plan_id}/inventory/{link_id}", tags=["Plan Management"])
def remove_inventory_link(
    plan_id: str,
    link_id: str,
    db: Session = Depends(get_db)
):
    """Remove an inventory link from a cutting plan"""
    try:
        import uuid
        
        try:
            plan_uuid = uuid.UUID(plan_id)
            link_uuid = uuid.UUID(link_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid UUID format")
        
        # Find and delete the link
        inventory_link = db.query(models.PlanInventoryLink).filter(
            models.PlanInventoryLink.id == link_uuid,
            models.PlanInventoryLink.plan_id == plan_uuid
        ).first()
        
        if not inventory_link:
            raise HTTPException(status_code=404, detail="Inventory link not found")
        
        db.delete(inventory_link)
        db.commit()
        
        return {
            "message": "Inventory link removed successfully",
            "plan_id": plan_id,
            "link_id": link_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing inventory link: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/inventory/{inventory_id}/status", response_model=schemas.InventoryMaster, tags=["Inventory Management"])
def update_inventory_status(
    inventory_id: str,
    status: str,
    db: Session = Depends(get_db)
):
    """Update inventory item status"""
    try:
        import uuid
        
        try:
            inventory_uuid = uuid.UUID(inventory_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {inventory_id}")
        
        # Validate status
        valid_statuses = [status.value for status in schemas.InventoryStatus]
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
        
        # Update inventory status
        update_data = schemas.InventoryMasterUpdate(status=status)
        inventory_item = crud.update_inventory_item(db, inventory_uuid, update_data)
        
        if not inventory_item:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        
        return inventory_item
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating inventory status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@router.post("/auth/register", response_model=schemas.UserMaster, tags=["Authentication"])
def register_user(
    user_data: schemas.UserMasterCreate,
    db: Session = Depends(get_db)
):
    """Register a new user in UserMaster"""
    try:
        from .auth import register_user
        
        # Register user with hashed password
        user = register_user(db, user_data)
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/login", tags=["Authentication"])
def login_user(
    credentials: schemas.UserMasterLogin,
    db: Session = Depends(get_db)
):
    """Authenticate user and return user information"""
    try:
        from .auth import authenticate_user
        
        # Authenticate user
        user = authenticate_user(db, credentials.username, credentials.password)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        return {
            "message": "Login successful",
            "user": {
                "id": str(user.id),
                "name": user.name,
                "username": user.username,
                "role": user.role,
                "department": user.department,
                "status": user.status
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
# ============================================================================
# CUTTING OPTIMIZER ENDPOINTS (Migrated from old cutting_optimizer.py)
# ============================================================================

@router.post("/optimizer/from-specs", tags=["Cutting Optimizer"])
def generate_cutting_plan_from_specs(
    rolls: List[Dict[str, Any]],
    jumbo_roll_width: int = 118,
    consider_standard_sizes: bool = True,
    db: Session = Depends(get_db)
):
    """
    Generate an optimized cutting plan from custom roll specifications.
    
    This endpoint allows generating a cutting plan without requiring orders to exist in the system.
    It's useful for planning and what-if scenarios.
    """
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        
        # Validate input
        if not rolls:
            raise HTTPException(status_code=400, detail="No roll specifications provided")
        
        # Convert request to optimizer format
        order_requirements = []
        for i, roll in enumerate(rolls):
            try:
                order_requirements.append({
                    'width': float(roll.get('width', 0)),
                    'quantity': int(roll.get('quantity', 1)),
                    'gsm': int(roll.get('gsm', 90)),
                    'bf': float(roll.get('bf', 18.0)),
                    'shade': roll.get('shade', 'white'),
                    'min_length': roll.get('min_length', 1000),
                    'order_id': f"spec_{i}"
                })
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid roll specification at index {i}: {e}"
                )
        
        # Initialize optimizer with custom width
        optimizer = CuttingOptimizer(jumbo_roll_width=jumbo_roll_width)
        
        # Generate the optimized plan
        plan = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            interactive=False
        )
        
        # Convert to response format
        return {
            'patterns': [
                {
                    'rolls': jumbo['rolls'],
                    'waste_percentage': jumbo['waste_percentage'],
                    'waste_inches': jumbo['trim_left'],
                    'jumbo_number': jumbo['jumbo_number'],
                    'paper_spec': jumbo['paper_spec']
                }
                for jumbo in plan['jumbo_rolls_used']
            ],
            'total_rolls_needed': plan['summary']['total_jumbos_used'],
            'total_waste_percentage': plan['summary']['overall_waste_percentage'],
            'total_waste_inches': plan['summary']['total_trim_inches'],
            'jumbo_roll_width_used': jumbo_roll_width,
            'unfulfilled_orders': [
                {
                    'width': order['width'],
                    'quantity': order['quantity'],
                    'gsm': order['gsm'],
                    'bf': order['bf'],
                    'shade': order['shade']
                }
                for order in plan['pending_orders']
            ],
            'specification_groups_processed': plan['summary']['specification_groups_processed'],
            'all_orders_fulfilled': plan['summary']['all_orders_fulfilled']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating cutting plan from specs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/optimizer/validate-plan", tags=["Cutting Optimizer"])
def validate_cutting_plan(
    plan_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Validate a cutting plan against business rules and constraints.
    
    This endpoint checks if a cutting plan is valid and provides feedback
    on any issues or potential improvements.
    """
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        
        # Initialize validation result
        validation_result = {
            "valid": True,
            "issues": [],
            "recommendations": [],
            "summary": {
                "total_patterns": 0,
                "total_requirements": 0,
                "validation_passed": True,
                "average_waste_percentage": 0,
                "total_jumbo_rolls": 0
            }
        }
        
        # Extract patterns and requirements
        patterns = plan_data.get('patterns', [])
        requirements = plan_data.get('requirements', [])
        jumbo_roll_width = plan_data.get('jumbo_roll_width', 118)
        
        # Basic validation checks
        if not patterns:
            validation_result["valid"] = False
            validation_result["issues"].append("No cutting patterns found in plan")
            return validation_result
        
        # Validate each pattern
        total_waste = 0
        total_patterns = len(patterns)
        
        for i, pattern in enumerate(patterns):
            pattern_issues = []
            
            # Check if pattern has rolls
            rolls = pattern.get('rolls', [])
            if not rolls:
                pattern_issues.append(f"Pattern {i+1}: No rolls specified")
                continue
            
            # Calculate pattern width and validate
            pattern_width = sum(roll.get('width', 0) for roll in rolls)
            waste_inches = pattern.get('waste_inches', jumbo_roll_width - pattern_width)
            waste_percentage = (waste_inches / jumbo_roll_width) * 100 if jumbo_roll_width > 0 else 0
            
            total_waste += waste_percentage
            
            # Validate pattern constraints
            if pattern_width > jumbo_roll_width:
                pattern_issues.append(f"Pattern {i+1}: Total width ({pattern_width}) exceeds jumbo roll width ({jumbo_roll_width})")
            
            if waste_percentage > 20:
                pattern_issues.append(f"Pattern {i+1}: High waste percentage ({waste_percentage:.1f}%)")
            elif waste_percentage < 0:
                pattern_issues.append(f"Pattern {i+1}: Invalid negative waste ({waste_percentage:.1f}%)")
            
            # Check roll count
            if len(rolls) > 5:  # MAX_ROLLS_PER_JUMBO
                pattern_issues.append(f"Pattern {i+1}: Too many rolls ({len(rolls)}) per jumbo (max 5)")
            
            # Check for mixed specifications
            if rolls:
                first_spec = (rolls[0].get('gsm'), rolls[0].get('shade'), rolls[0].get('bf'))
                for j, roll in enumerate(rolls[1:], 1):
                    roll_spec = (roll.get('gsm'), roll.get('shade'), roll.get('bf'))
                    if roll_spec != first_spec:
                        pattern_issues.append(f"Pattern {i+1}: Mixed paper specifications in same jumbo roll")
                        break
            
            if pattern_issues:
                validation_result["issues"].extend(pattern_issues)
                validation_result["valid"] = False
        
        # Calculate summary statistics
        avg_waste = total_waste / total_patterns if total_patterns > 0 else 0
        validation_result["summary"].update({
            "total_patterns": total_patterns,
            "total_requirements": len(requirements),
            "average_waste_percentage": round(avg_waste, 2),
            "total_jumbo_rolls": total_patterns,
            "validation_passed": validation_result["valid"]
        })
        
        # Generate recommendations
        if avg_waste > 15:
            validation_result["recommendations"].append("Consider reoptimizing patterns to reduce average waste")
        elif avg_waste < 5:
            validation_result["recommendations"].append("Excellent waste optimization achieved")
        
        if total_patterns > 10:
            validation_result["recommendations"].append("Large number of patterns - consider batching for efficiency")
        
        # Check for optimization opportunities
        if validation_result["valid"]:
            validation_result["recommendations"].append("Plan passes all validation checks")
        
        return validation_result
        
    except Exception as e:
        logger.error(f"Error validating cutting plan: {e}")
        raise HTTPException(status_code=500, detail=f"Error validating cutting plan: {str(e)}")

@router.get("/optimizer/algorithms", tags=["Cutting Optimizer"])
def get_optimizer_algorithms():
    """Get information about available optimization algorithms and their parameters."""
    return {
        "algorithms": [
            {
                "name": "specification_grouping",
                "description": "Groups orders by paper specifications (GSM, Shade, BF) to prevent mixing",
                "default": True,
                "parameters": {
                    "jumbo_width": 118,
                    "min_trim": 1,
                    "max_trim": 6,
                    "max_trim_with_confirmation": 20,
                    "max_rolls_per_jumbo": 5
                }
            }
        ],
        "constraints": {
            "jumbo_roll_width": {
                "default": 118,
                "min": 50,
                "max": 200,
                "unit": "inches"
            },
            "trim_limits": {
                "min_acceptable": 1,
                "max_acceptable": 6,
                "max_with_confirmation": 20,
                "unit": "inches"
            },
            "rolls_per_jumbo": {
                "max": 5,
                "recommended_max": 3
            }
        },
        "optimization_objectives": [
            "minimize_waste",
            "minimize_jumbo_rolls",
            "maximize_roll_utilization"
        ]
    }

@router.get("/debug/pending-orders", tags=["Debug"])
def debug_pending_orders(db: Session = Depends(get_db)):
    """Debug endpoint to check what pending orders exist in the database."""
    try:
        # Check both PendingOrderMaster and PendingOrderItem
        pending_masters = db.query(models.PendingOrderMaster).all()
        pending_items = db.query(models.PendingOrderItem).all()
        
        return {
            "pending_order_masters": {
                "count": len(pending_masters),
                "items": [
                    {
                        "id": str(pm.id),
                        "paper_id": str(pm.paper_id) if pm.paper_id else None,
                        "width": pm.width,
                        "quantity": pm.quantity,
                        "status": pm.status,
                        "reason": pm.reason
                    } for pm in pending_masters
                ]
            },
            "pending_order_items": {
                "count": len(pending_items),
                "items": [
                    {
                        "id": str(pi.id),
                        "original_order_id": str(pi.original_order_id),
                        "width_inches": pi.width_inches,
                        "gsm": pi.gsm,
                        "bf": float(pi.bf),
                        "shade": pi.shade,
                        "quantity_pending": pi.quantity_pending,
                        "status": pi.status,
                        "reason": pi.reason,
                        "created_at": pi.created_at.isoformat() if pi.created_at else None
                    } for pi in pending_items
                ]
            }
        }
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# CUT ROLL PRODUCTION & SELECTION ENDPOINTS
# ============================================================================

@router.post("/cut-rolls/select-for-production", response_model=List[schemas.CutRollProduction], tags=["Cut Roll Production"])
def select_cut_rolls_for_production(
    selection_request: schemas.CutRollSelectionRequest,
    db: Session = Depends(get_db)
):
    """
    Select cut rolls from plan generation results for production.
    Creates CutRollProduction records with QR codes.
    """
    try:
        created_cut_rolls = crud.select_cut_rolls_for_production(db, selection_request)
        return created_cut_rolls
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error selecting cut rolls for production: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cut-rolls/plan/{plan_id}", response_model=Dict[str, Any], tags=["Cut Roll Production"])
def get_cut_roll_production_summary(
    plan_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get summary of cut roll production for a specific plan"""
    try:
        import uuid
        
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {plan_id}")
        
        summary = crud.get_cut_roll_production_summary(db, plan_uuid)
        return summary
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting cut roll production summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/qr-scan/{qr_code}", response_model=schemas.QRCodeScanResult, tags=["QR Code Management"])
def scan_qr_code(
    qr_code: str,
    db: Session = Depends(get_db)
):
    """
    Scan QR code and return cut roll details.
    Used for weight input and production tracking.
    """
    try:
        # Get cut roll by QR code
        cut_roll = crud.get_cut_roll_production_by_qr(db, qr_code)
        if not cut_roll:
            raise HTTPException(status_code=404, detail="QR code not found")
        
        # Create QR data
        qr_data = schemas.QRCodeData(
            qr_code=qr_code,
            cut_roll_id=cut_roll.id,
            width_inches=float(cut_roll.width_inches),
            gsm=cut_roll.gsm,
            bf=float(cut_roll.bf),
            shade=cut_roll.shade,
            client_name=cut_roll.client.company_name if cut_roll.client else None,
            order_details=f"Order #{cut_roll.order_id}" if cut_roll.order_id else None,
            production_date=cut_roll.selected_at
        )
        
        # Check if weight can be updated
        can_update_weight = cut_roll.status in ["selected", "in_production"]
        
        return schemas.QRCodeScanResult(
            cut_roll=cut_roll,
            qr_data=qr_data,
            can_update_weight=can_update_weight,
            current_status=cut_roll.status
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scanning QR code: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/qr-scan/update-weight", tags=["QR Code Management"])
def update_weight_via_qr_scan(
    weight_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    NEW FLOW: Update cut roll weight via QR code scan.
    1. Update inventory status: cutting → available
    2. Update order item status: in_process → in_warehouse
    3. Add moved_to_warehouse_at timestamp
    """
    try:
        from datetime import datetime
        
        qr_code = weight_data.get('qr_code')
        weight = weight_data.get('weight')
        user_id = weight_data.get('user_id')
        
        if not qr_code:
            raise HTTPException(status_code=400, detail="qr_code is required")
        if not weight or weight <= 0:
            raise HTTPException(status_code=400, detail="Valid weight is required")
        
        # Find inventory item by QR code
        inventory_item = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.qr_code == qr_code
        ).first()
        
        if not inventory_item:
            raise HTTPException(status_code=404, detail="QR code not found")
        
        current_time = datetime.utcnow()
        
        # Validate current inventory status before updating
        if inventory_item.status != models.InventoryStatus.CUTTING:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid status transition. Current status: {inventory_item.status}, expected: cutting"
            )
        
        # 1. Update inventory status: cutting → available (with validation)
        inventory_item.weight_kg = float(weight)
        inventory_item.status = models.InventoryStatus.AVAILABLE
        inventory_item.updated_at = current_time
        logger.info(f"Inventory {inventory_item.id} status updated: CUTTING → AVAILABLE, weight: {weight}kg")
        
        # 2. Find related order items and update their status: in_process → in_warehouse
        # Find order items that match this inventory item's specifications
        order_items = db.query(models.OrderItem).join(
            models.PaperMaster
        ).filter(
            models.OrderItem.width_inches == inventory_item.width_inches,
            models.PaperMaster.id == inventory_item.paper_id,
            models.OrderItem.item_status == models.OrderItemStatus.IN_PROCESS
        ).all()
        
        updated_order_items = []
        for order_item in order_items:
            # Validate status transition and quantity constraints
            if order_item.quantity_fulfilled < order_item.quantity_rolls:
                # Update status with validation
                if order_item.item_status == models.OrderItemStatus.IN_PROCESS:
                    order_item.item_status = models.OrderItemStatus.IN_WAREHOUSE
                    order_item.moved_to_warehouse_at = current_time
                    order_item.updated_at = current_time
                    updated_order_items.append(str(order_item.id))
                    logger.info(f"Order item {order_item.id} status updated: IN_PROCESS → IN_WAREHOUSE")
                    
                    # Increment fulfilled quantity with bounds checking
                    old_fulfilled = order_item.quantity_fulfilled
                    order_item.quantity_fulfilled = min(
                        order_item.quantity_fulfilled + 1,
                        order_item.quantity_rolls
                    )
                    logger.info(f"Order item {order_item.id} quantity fulfilled: {old_fulfilled} → {order_item.quantity_fulfilled}")
                else:
                    logger.warning(f"Order item {order_item.id} not in IN_PROCESS status, current: {order_item.item_status}")
            else:
                logger.info(f"Order item {order_item.id} already fully fulfilled ({order_item.quantity_fulfilled}/{order_item.quantity_rolls})")
        
        # 3. Check if any orders can be updated to completed status
        updated_orders = []
        processed_orders = set()
        
        for order_item in order_items:
            if order_item.order_id not in processed_orders:
                order = order_item.order
                processed_orders.add(order_item.order_id)
                
                # Check if all order items are completed
                all_items_completed = all(
                    item.quantity_fulfilled >= item.quantity_rolls 
                    for item in order.order_items
                )
                
                if all_items_completed and order.status != models.OrderStatus.COMPLETED:
                    order.status = models.OrderStatus.COMPLETED
                    order.moved_to_warehouse_at = current_time
                    order.updated_at = current_time
                    updated_orders.append(str(order.id))
        
        db.commit()
        
        return {
            "message": "Weight updated successfully",
            "qr_code": qr_code,
            "weight": weight,
            "inventory_status": "available",
            "timestamp": current_time.isoformat(),
            "summary": {
                "order_items_moved_to_warehouse": len(updated_order_items),
                "orders_completed": len(updated_orders)
            },
            "details": {
                "inventory_item": {
                    "id": str(inventory_item.id),
                    "width": float(inventory_item.width_inches),
                    "weight": float(inventory_item.weight_kg),
                    "status": inventory_item.status,
                    "paper_spec": {
                        "gsm": inventory_item.paper.gsm,
                        "shade": inventory_item.paper.shade,
                        "bf": float(inventory_item.paper.bf)
                    } if inventory_item.paper else None
                },
                "updated_order_items": updated_order_items,
                "updated_orders": updated_orders
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating weight via QR scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Keep the old endpoint for backward compatibility
# OLD FLOW REMOVED: Legacy QR weight update endpoint
# Use /qr-scan/update-weight instead

# ============================================================================
# DISPATCH/WAREHOUSE ENDPOINTS
# ============================================================================

@router.get("/dispatch/warehouse-items", tags=["Dispatch/Warehouse"])
def get_warehouse_items(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Get all order items with 'in_warehouse' status for dispatch management.
    NEW FLOW: Only shows items ready for dispatch.
    """
    try:
        # Get order items with in_warehouse status
        warehouse_items = db.query(models.OrderItem).join(
            models.OrderMaster
        ).join(
            models.PaperMaster
        ).join(
            models.ClientMaster
        ).filter(
            models.OrderItem.item_status == models.OrderItemStatus.IN_WAREHOUSE
        ).offset(skip).limit(limit).all()
        
        result = []
        for item in warehouse_items:
            result.append({
                "order_item_id": str(item.id),
                "order_id": str(item.order_id),
                "width_inches": float(item.width_inches),
                "quantity_rolls": item.quantity_rolls,
                "quantity_fulfilled": item.quantity_fulfilled,
                "moved_to_warehouse_at": item.moved_to_warehouse_at.isoformat() if item.moved_to_warehouse_at else None,
                "paper_spec": {
                    "gsm": item.paper.gsm,
                    "shade": item.paper.shade,
                    "bf": float(item.paper.bf)
                } if item.paper else None,
                "client": {
                    "id": str(item.order.client_id),
                    "company_name": item.order.client.company_name
                } if item.order and item.order.client else None,
                "order_priority": item.order.priority if item.order else None
            })
        
        return {
            "warehouse_items": result,
            "total_count": len(result),
            "status_filter": "in_warehouse"
        }
        
    except Exception as e:
        logger.error(f"Error getting warehouse items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/dispatch/complete-items", tags=["Dispatch/Warehouse"])
def complete_order_items(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    NEW FLOW: Mark multiple order items as completed (batch completion).
    1. Update item status: in_warehouse → completed
    2. Add dispatched_at timestamp
    3. Check if all order items completed → update order status
    """
    try:
        from datetime import datetime
        import uuid
        
        item_ids = request_data.get('item_ids', [])
        user_id = request_data.get('user_id')
        
        if not item_ids:
            raise HTTPException(status_code=400, detail="item_ids list is required")
        
        # Convert string IDs to UUIDs
        uuid_item_ids = []
        for item_id in item_ids:
            try:
                uuid_item_ids.append(uuid.UUID(item_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {item_id}")
        
        current_time = datetime.utcnow()
        completed_items = []
        updated_orders = []
        processed_orders = set()
        
        # Get order items to update
        order_items = db.query(models.OrderItem).filter(
            models.OrderItem.id.in_(uuid_item_ids),
            models.OrderItem.item_status == models.OrderItemStatus.IN_WAREHOUSE
        ).all()
        
        if not order_items:
            raise HTTPException(status_code=404, detail="No warehouse items found with provided IDs")
        
        # 1. Update item statuses to completed (with validation)
        for order_item in order_items:
            # Validate status transition
            if order_item.item_status == models.OrderItemStatus.IN_WAREHOUSE:
                order_item.item_status = models.OrderItemStatus.COMPLETED
                order_item.dispatched_at = current_time
                order_item.updated_at = current_time
                completed_items.append({
                    "item_id": str(order_item.id),
                    "order_id": str(order_item.order_id),
                    "width": float(order_item.width_inches),
                    "quantity": order_item.quantity_rolls,
                    "quantity_fulfilled": order_item.quantity_fulfilled
                })
                logger.info(f"Order item {order_item.id} status updated: IN_WAREHOUSE → COMPLETED")
            else:
                logger.warning(f"Order item {order_item.id} not in IN_WAREHOUSE status, current: {order_item.item_status}")
        
        # 2. Check if orders can be marked as completed (with comprehensive validation)
        for order_item in order_items:
            if order_item.order_id not in processed_orders:
                order = order_item.order
                processed_orders.add(order_item.order_id)
                
                # Check if all order items are completed
                all_items_completed = all(
                    item.item_status == models.OrderItemStatus.COMPLETED 
                    for item in order.order_items
                )
                
                # Additional check: verify all quantities are fulfilled
                all_quantities_fulfilled = all(
                    item.quantity_fulfilled >= item.quantity_rolls
                    for item in order.order_items
                )
                
                if all_items_completed and all_quantities_fulfilled and order.status != models.OrderStatus.COMPLETED:
                    order.status = models.OrderStatus.COMPLETED
                    order.dispatched_at = current_time
                    order.updated_at = current_time
                    updated_orders.append({
                        "order_id": str(order.id),
                        "client": order.client.company_name if order.client else "Unknown",
                        "completed_at": current_time.isoformat()
                    })
                    logger.info(f"Order {order.id} status updated: IN_PROCESS → COMPLETED")
        
        # 3. Resolve related pending orders that were included in production
        resolved_pending_orders = []
        for order_item in order_items:
            if order_item.item_status == models.OrderItemStatus.COMPLETED:
                # Find pending orders with matching specifications that were included in plan
                matching_pending = db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.width_inches == order_item.width_inches,
                    models.PendingOrderItem.gsm == order_item.paper.gsm,
                    models.PendingOrderItem.shade == order_item.paper.shade,
                    models.PendingOrderItem.bf == order_item.paper.bf,
                    models.PendingOrderItem.status == models.PendingOrderStatus.INCLUDED_IN_PLAN
                ).all()
                
                for pending_item in matching_pending:
                    # Resolve the pending order since the item has been dispatched
                    pending_item.status = models.PendingOrderStatus.RESOLVED
                    pending_item.resolved_at = current_time
                    resolved_pending_orders.append(str(pending_item.id))
                    logger.info(f"Pending order {pending_item.id} resolved due to dispatch completion")
        
        db.commit()
        
        return {
            "message": "Order items completed successfully",
            "completed_at": current_time.isoformat(),
            "summary": {
                "items_completed": len(completed_items),
                "orders_completed": len(updated_orders),
                "pending_orders_resolved": len(resolved_pending_orders)
            },
            "details": {
                "completed_items": completed_items,
                "completed_orders": updated_orders,
                "resolved_pending_orders": resolved_pending_orders
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error completing order items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# STATUS MONITORING ENDPOINTS
# ============================================================================

@router.get("/status/summary", tags=["System Monitoring"])
def get_system_status_summary(db: Session = Depends(get_db)):
    """
    Get comprehensive status summary for all entities in the system.
    Useful for monitoring workflow progress and debugging status issues.
    """
    try:
        return get_status_summary(db)
    except Exception as e:
        logger.error(f"Error getting status summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/validate", tags=["System Monitoring"])
def validate_system_status_integrity(db: Session = Depends(get_db)):
    """
    Validate status integrity across the system.
    Identifies any data inconsistencies or invalid status combinations.
    """
    try:
        issues = []
        
        # Check for orders with inconsistent item statuses
        orders_with_issues = db.query(models.OrderMaster).all()
        for order in orders_with_issues:
            if order.status == models.OrderStatus.COMPLETED:
                incomplete_items = [
                    item for item in order.order_items 
                    if item.item_status != models.OrderItemStatus.COMPLETED
                ]
                if incomplete_items:
                    issues.append({
                        "type": "order_item_mismatch",
                        "order_id": str(order.id),
                        "issue": f"Order marked as COMPLETED but has {len(incomplete_items)} incomplete items",
                        "incomplete_items": [str(item.id) for item in incomplete_items]
                    })
            
            # Check for unfulfilled quantities
            for item in order.order_items:
                if item.item_status == models.OrderItemStatus.COMPLETED and item.quantity_fulfilled < item.quantity_rolls:
                    issues.append({
                        "type": "quantity_mismatch",
                        "order_item_id": str(item.id),
                        "issue": f"Item marked as COMPLETED but quantity not fully fulfilled ({item.quantity_fulfilled}/{item.quantity_rolls})"
                    })
        
        # Check for inventory items without proper status progression
        cutting_inventory = db.query(models.InventoryMaster).filter(
            models.InventoryMaster.status == models.InventoryStatus.CUTTING,
            models.InventoryMaster.weight_kg > 0
        ).all()
        
        for inv_item in cutting_inventory:
            issues.append({
                "type": "inventory_status_issue",
                "inventory_id": str(inv_item.id),
                "issue": f"Inventory has weight ({inv_item.weight_kg}kg) but still in CUTTING status"
            })
        
        return {
            "validation_completed_at": datetime.utcnow().isoformat(),
            "issues_found": len(issues),
            "issues": issues,
            "status": "healthy" if len(issues) == 0 else "issues_detected"
        }
        
    except Exception as e:
        logger.error(f"Error validating status integrity: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/status/auto-update", tags=["System Monitoring"])
def trigger_auto_status_update(db: Session = Depends(get_db)):
    """
    Trigger automatic status updates to ensure data consistency.
    This endpoint can be called periodically or manually to fix any
    status inconsistencies that might have occurred.
    """
    try:
        result = auto_update_order_statuses(db)
        return {
            "message": "Auto status update completed",
            "result": result
        }
    except Exception as e:
        logger.error(f"Error triggering auto status update: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dispatch/pending-items", tags=["Dispatch/Warehouse"])
def get_pending_dispatch_items(
    db: Session = Depends(get_db)
):
    """
    Get pending order items that were from pending orders but are now ready for dispatch.
    These items originated from PendingOrderItem but are now in production.
    """
    try:
        # Find pending order items that are included in plans and might be in warehouse
        pending_items = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.status == models.PendingOrderStatus.INCLUDED_IN_PLAN
        ).all()
        
        result = []
        for pending_item in pending_items:
            # Check if there's corresponding inventory in warehouse
            matching_inventory = db.query(models.InventoryMaster).join(
                models.PaperMaster
            ).filter(
                models.InventoryMaster.width_inches == pending_item.width_inches,
                models.PaperMaster.gsm == pending_item.gsm,
                models.PaperMaster.shade == pending_item.shade,
                models.PaperMaster.bf == pending_item.bf,
                models.InventoryMaster.status == models.InventoryStatus.AVAILABLE
            ).first()
            
            if matching_inventory:
                result.append({
                    "pending_item_id": str(pending_item.id),
                    "original_order_id": str(pending_item.original_order_id),
                    "width_inches": float(pending_item.width_inches),
                    "quantity_pending": pending_item.quantity_pending,
                    "paper_spec": {
                        "gsm": pending_item.gsm,
                        "shade": pending_item.shade,
                        "bf": float(pending_item.bf)
                    },
                    "inventory_available": {
                        "id": str(matching_inventory.id),
                        "weight": float(matching_inventory.weight_kg),
                        "qr_code": matching_inventory.qr_code
                    },
                    "reason": pending_item.reason,
                    "created_at": pending_item.created_at.isoformat() if pending_item.created_at else None
                })
        
        return {
            "pending_dispatch_items": result,
            "total_count": len(result),
            "note": "These items originated from pending orders but are now available for dispatch"
        }
        
    except Exception as e:
        logger.error(f"Error getting pending dispatch items: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/dispatch/complete-pending-item", tags=["Dispatch/Warehouse"])
def complete_pending_item(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Complete a pending order item by marking it as resolved and dispatched.
    """
    try:
        from datetime import datetime
        import uuid
        
        pending_item_id = request_data.get('pending_item_id')
        user_id = request_data.get('user_id')
        
        if not pending_item_id:
            raise HTTPException(status_code=400, detail="pending_item_id is required")
        
        try:
            pending_uuid = uuid.UUID(pending_item_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {pending_item_id}")
        
        # Get the pending item
        pending_item = db.query(models.PendingOrderItem).filter(
            models.PendingOrderItem.id == pending_uuid,
            models.PendingOrderItem.status == models.PendingOrderStatus.INCLUDED_IN_PLAN
        ).first()
        
        if not pending_item:
            raise HTTPException(status_code=404, detail="Pending item not found or not ready for dispatch")
        
        current_time = datetime.utcnow()
        
        # Mark pending item as resolved
        pending_item.status = models.PendingOrderStatus.RESOLVED
        pending_item.resolved_at = current_time
        
        db.commit()
        
        return {
            "message": "Pending item completed and dispatched successfully",
            "pending_item_id": pending_item_id,
            "resolved_at": current_time.isoformat(),
            "original_order_id": str(pending_item.original_order_id),
            "details": {
                "width": float(pending_item.width_inches),
                "quantity": pending_item.quantity_pending,
                "paper_spec": {
                    "gsm": pending_item.gsm,
                    "shade": pending_item.shade,
                    "bf": float(pending_item.bf)
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error completing pending item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/plans/generate-with-selection", tags=["Plan Generation"])
def generate_plan_with_cut_roll_selection(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    NEW FLOW: Generate cutting plan and return cut rolls for user selection.
    Shows cut rolls, pending orders, and inventory items.
    User can then select which cut rolls to move to production.
    """
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        from . import crud
        import uuid
        
        # Extract data from request
        order_ids = request_data.get('order_ids', [])
        created_by_id = request_data.get('created_by_id')
        
        if not order_ids:
            raise HTTPException(status_code=400, detail="order_ids is required")
        if not created_by_id:
            raise HTTPException(status_code=400, detail="created_by_id is required")
        
        # Convert string IDs to UUIDs
        uuid_order_ids = []
        for order_id in order_ids:
            try:
                uuid_order_ids.append(uuid.UUID(order_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {order_id}")
        
        try:
            created_by_uuid = uuid.UUID(created_by_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format for created_by_id: {created_by_id}")
        
        # Get order requirements with paper specs
        order_requirements = crud.get_orders_with_paper_specs(db, uuid_order_ids)
        
        if not order_requirements:
            raise HTTPException(status_code=404, detail="No valid orders found with provided IDs")
        
        # Get paper specifications from orders
        paper_specs = []
        for req in order_requirements:
            spec = {'gsm': req['gsm'], 'bf': req['bf'], 'shade': req['shade']}
            if spec not in paper_specs:
                paper_specs.append(spec)
        
        # Fetch pending orders for same specifications
        logger.info(f"🔍 DEBUG: Fetching pending orders for paper specs: {paper_specs}")
        pending_orders_db = crud.get_pending_orders_by_paper_specs(db, paper_specs)
        logger.info(f"📋 DEBUG: Found {len(pending_orders_db)} pending orders from database")
        
        pending_requirements = []
        for i, pending in enumerate(pending_orders_db):
            logger.info(f"  Processing pending order item {i+1}: ID={pending.id}, width={pending.width_inches}\"")
            # PendingOrderItem has paper specs directly embedded, no need to check pending.paper
            pending_req = {
                'width': float(pending.width_inches),
                'quantity': pending.quantity_pending,
                'gsm': pending.gsm,
                'bf': float(pending.bf),
                'shade': pending.shade,
                'pending_id': str(pending.id),
                'reason': pending.reason
            }
            pending_requirements.append(pending_req)
            logger.info(f"  ✅ Added pending requirement: {pending_req}")
        
        logger.info(f"📊 DEBUG: Final pending_requirements: {pending_requirements}")
        
        # Fetch available inventory (20-25" waste rolls)
        available_inventory_db = crud.get_available_inventory_by_paper_specs(db, paper_specs)
        available_inventory = []
        for inv_item in available_inventory_db:
            if inv_item.paper:
                available_inventory.append({
                    'id': str(inv_item.id),
                    'width': float(inv_item.width_inches),
                    'gsm': inv_item.paper.gsm,
                    'bf': float(inv_item.paper.bf),
                    'shade': inv_item.paper.shade,
                    'weight': float(inv_item.weight_kg) if inv_item.weight_kg else 0
                })
        
        # Run optimization
        optimizer = CuttingOptimizer()
        optimization_result = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=pending_requirements,
            available_inventory=available_inventory,
            interactive=False
        )
        
        # Calculate jumbo roll sets needed based on individual 118" rolls
        total_individual_118_rolls = len([roll for roll in optimization_result['cut_rolls_generated'] 
                                         if roll['source'] == 'cutting'])
        jumbo_roll_sets_needed = (total_individual_118_rolls + 2) // 3  # Round up
        
        # IMPORTANT: Orders should remain in CREATED status after plan generation
        # Status flow should be:
        # 1. Order Creation: CREATED status
        # 2. Plan Generation: Orders remain CREATED (this endpoint)
        # 3. Start Production: CREATED → IN_PROCESS (separate endpoint)
        # 4. QR Weight Update: IN_PROCESS → IN_WAREHOUSE (items)
        # 5. Dispatch: IN_WAREHOUSE → COMPLETED (items), potentially IN_PROCESS → COMPLETED (orders)
        logger.info(f"Plan generated successfully. Orders remain in CREATED status until production starts.")
        
        # Create pending orders for orders that couldn't be fulfilled
        logger.info(f"Processing {len(optimization_result['pending_orders'])} pending orders")
        logger.info(f"Available order requirements: {len(order_requirements)}")
        
        for pending_order in optimization_result['pending_orders']:
            logger.info(f"Looking for match for pending order: {pending_order}")
            
            # Find corresponding order and create pending order record with more robust matching
            order_match = None
            for req in order_requirements:
                # Use more tolerant matching for floating point values
                if (abs(req['width'] - pending_order['width']) < 0.1 and 
                    req['gsm'] == pending_order['gsm'] and
                    abs(req['bf'] - pending_order['bf']) < 0.1 and
                    req['shade'] == pending_order['shade']):
                    order_match = req
                    logger.info(f"Found matching order requirement: {order_match}")
                    break
            
            if order_match:
                try:
                    # Use PendingOrderService to create PendingOrderItem
                    from .services.pending_order_service import PendingOrderService
                    pending_service = PendingOrderService(db, created_by_uuid)
                    
                    # Create single pending item in the expected format
                    pending_items = [{
                        'width': pending_order['width'],
                        'quantity': pending_order['quantity'],
                        'gsm': pending_order['gsm'],
                        'bf': pending_order['bf'],
                        'shade': pending_order['shade']
                    }]
                    
                    pending_service.create_pending_items(
                        pending_orders=pending_items,
                        original_order_id=uuid.UUID(order_match['order_id']),
                        reason=pending_order['reason']
                    )
                    logger.info(f"Successfully created pending order item for {pending_order['width']}\" width")
                except Exception as e:
                    logger.warning(f"Failed to create pending order item: {e}. Order match: {order_match}")
            else:
                logger.warning(f"No matching order found or missing order_item_id for pending order: {pending_order}")
                # Skip creating pending order if we can't find a proper match
        
        # Create a plan record in the database so it can be referenced by start-production
        plan_id = uuid.uuid4()
        
        # Convert cut rolls to cutting pattern format
        cut_pattern = []
        for i, cut_roll in enumerate(optimization_result['cut_rolls_generated']):
            pattern_entry = {
                "pattern_id": i + 1,
                "width": cut_roll['width'],
                "gsm": cut_roll['gsm'],
                "bf": cut_roll['bf'],
                "shade": cut_roll['shade'],
                "source": cut_roll.get('source', 'cutting'),
                "individual_roll_number": cut_roll.get('individual_roll_number', i + 1),
                "trim_left": cut_roll.get('trim_left', 0)
            }
            cut_pattern.append(pattern_entry)
        
        plan_data = schemas.PlanMasterCreate(
            name=f"Plan for {len(uuid_order_ids)} orders",
            cut_pattern=cut_pattern,
            expected_waste_percentage=5.0,  # Default estimate, will be updated later
            created_by_id=created_by_uuid,
            order_ids=uuid_order_ids
        )
        
        # Create the plan using CRUD function
        plan = crud.create_plan(db=db, plan=plan_data)
        
        # The plan creation should handle order linking automatically via the order_ids field
        # But let's ensure the plan ID is what we expect
        actual_plan_id = plan.id
        
        db.commit()
        db.refresh(plan)
        logger.info(f"Created plan {actual_plan_id} with {len(uuid_order_ids)} linked orders")
        
        # Format response for frontend selection
        return {
            "plan_id": str(actual_plan_id),  # Include actual plan ID in response
            "optimization_result": optimization_result,
            "selection_data": {
                "cut_rolls_available": optimization_result['cut_rolls_generated'],
                "pending_orders": optimization_result['pending_orders'],
                "inventory_items_to_add": optimization_result['inventory_remaining'],
                "summary": {
                    "total_cut_rolls": len(optimization_result['cut_rolls_generated']),
                    "total_individual_118_rolls": total_individual_118_rolls,
                    "jumbo_roll_sets_needed": jumbo_roll_sets_needed,
                    "pending_orders_count": len(optimization_result['pending_orders']),
                    "inventory_items_count": len(optimization_result['inventory_remaining'])
                }
            },
            "next_steps": [
                "1. Review cut rolls available for production",
                "2. Select which cut rolls to move to production",
                "3. Click 'Start Production' to create production records",
                "4. QR codes will be generated for selected cut rolls",
                "5. Use QR scanner for weight tracking during production"
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating plan with cut roll selection: {e}")
        raise HTTPException(status_code=500, detail=str(e))