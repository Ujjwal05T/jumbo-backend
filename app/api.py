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

@router.post("/users/register", response_model=schemas.UserMaster, tags=["User Master"])
def register_user(user: schemas.UserMasterCreate, db: Session = Depends(get_db)):
    """Register a new user (no authentication, just registration)"""
    try:
        return crud.create_user(db=db, user=user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users/login", tags=["User Master"])
def login_user(credentials: schemas.UserMasterLogin, db: Session = Depends(get_db)):
    """Simple user login (updates last_login, no token generation)"""
    user = crud.authenticate_user(
        db=db,
        username=credentials.username,
        password=credentials.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    return {
        "message": "Login successful",
        "user_id": str(user.id),
        "username": user.username,
        "role": user.role
    }

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
            order.status = "partially_fulfilled"
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
                    order.status = "partially_fulfilled"
                db.commit()
        
        result = {"fulfilled_items": results, "updated_orders": len(updated_orders)}
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk fulfilling orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/pending", response_model=List[schemas.OrderMaster], tags=["Order Master"])
def get_pending_orders(
    paper_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """Get orders that need fulfillment"""
    try:
        return crud.get_pending_orders(db=db, paper_id=paper_id)
    except Exception as e:
        logger.error(f"Error getting pending orders: {e}")
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
# PENDING ORDER MASTER ENDPOINTS
# ============================================================================

@router.post("/pending-orders", response_model=schemas.PendingOrderMaster, tags=["Pending Orders"])
def create_pending_order(pending: schemas.PendingOrderMasterCreate, db: Session = Depends(get_db)):
    """Create a new pending order"""
    try:
        return crud.create_pending_order(db=db, pending=pending)
    except Exception as e:
        logger.error(f"Error creating pending order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-orders", response_model=List[schemas.PendingOrderMaster], tags=["Pending Orders"])
def get_pending_orders_list(
    skip: int = 0,
    limit: int = 100,
    status: str = "pending",
    db: Session = Depends(get_db)
):
    """Get all pending orders with pagination"""
    try:
        return crud.get_pending_orders_list(db=db, skip=skip, limit=limit, status=status)
    except Exception as e:
        logger.error(f"Error getting pending orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-orders/{pending_id}", response_model=schemas.PendingOrderMaster, tags=["Pending Orders"])
def get_pending_order(pending_id: UUID, db: Session = Depends(get_db)):
    """Get pending order by ID"""
    pending = crud.get_pending_order(db=db, pending_id=pending_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Pending order not found")
    return pending

@router.put("/pending-orders/{pending_id}", response_model=schemas.PendingOrderMaster, tags=["Pending Orders"])
def update_pending_order(
    pending_id: UUID,
    pending_update: schemas.PendingOrderMasterUpdate,
    db: Session = Depends(get_db)
):
    """Update pending order status"""
    try:
        pending = crud.update_pending_order(db=db, pending_id=pending_id, pending_update=pending_update)
        if not pending:
            raise HTTPException(status_code=404, detail="Pending order not found")
        return pending
    except Exception as e:
        logger.error(f"Error updating pending order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-orders/by-paper/{paper_id}", response_model=List[schemas.PendingOrderMaster], tags=["Pending Orders"])
def get_pending_by_specification(paper_id: UUID, db: Session = Depends(get_db)):
    """Get pending orders by paper specification for consolidation"""
    try:
        return crud.get_pending_by_specification(db=db, paper_id=paper_id)
    except Exception as e:
        logger.error(f"Error getting pending orders by specification: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
    width_inches: Optional[int] = None,
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
# CUTTING OPTIMIZER TEST ROUTES
# ============================================================================

@router.get("/optimizer/test", tags=["Cutting Optimizer"])
def test_cutting_optimizer():
    """NEW FLOW: Test the cutting optimizer algorithm with 3-input/4-output sample data"""
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        
        optimizer = CuttingOptimizer()
        result = optimizer.test_algorithm_with_sample_data()
        
        return {
            "message": "NEW FLOW: Cutting optimizer test completed successfully",
            "test_data": "Sample data with 3 inputs: new orders, pending orders, available inventory",
            "optimization_result": result,
            "flow_explanation": {
                "inputs": {
                    "new_orders": "Fresh customer orders",
                    "pending_orders": "Orders from previous cycles that couldn't be fulfilled",
                    "available_inventory": "20-25\" waste rolls available for reuse"
                },
                "outputs": {
                    "cut_rolls_generated": "Rolls that can be fulfilled (from cutting or inventory)",
                    "jumbo_rolls_needed": "Number of jumbo rolls to procure",
                    "pending_orders": "Orders that still cannot be fulfilled",
                    "inventory_remaining": "20-25\" waste rolls for future cycles"
                }
            }
        }
    except Exception as e:
        logger.error(f"Error testing cutting optimizer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/optimizer/test-with-orders", tags=["Cutting Optimizer"])
def test_optimizer_with_orders(
    request: schemas.CreatePlanRequest,
    db: Session = Depends(get_db)
):
    """Test the cutting optimizer with real order data without saving to database
    
    Fetches order details from database using the provided order IDs,
    runs the cutting optimization algorithm, and returns the result.
    Does not create any database records - for testing/preview purposes only.
    """
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        import uuid
        
        # Convert string IDs to UUIDs
        uuid_order_ids = []
        for order_id in request.order_ids:
            try:
                uuid_order_ids.append(uuid.UUID(order_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {order_id}")
        
        # Use the existing method to get order requirements from database
        optimizer = CuttingOptimizer()
        order_requirements = optimizer.get_order_requirements_from_db(db, uuid_order_ids)
        
        if not order_requirements:
            raise HTTPException(status_code=404, detail="No valid orders found with provided IDs")
        
        # Run optimization without saving
        optimization_result = optimizer.optimize_with_new_algorithm(order_requirements, interactive=False)
        
        # Return result in the same format as the test method
        return {
            "message": "Cutting optimizer test completed successfully",
            "test_data": f"Real orders from database - {len(order_requirements)} orders processed",
            "optimization_result": optimization_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing cutting optimizer with orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
@router.post("/optimizer/test-frontend", tags=["Cutting Optimizer"])
def test_optimizer_frontend(
    request_data: Dict[str, Any]
):
    """Test the cutting optimizer with data from the HTML frontend"""
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        
        # Extract rolls data from frontend format
        rolls_data = request_data.get('rolls', [])
        
        if not rolls_data:
            raise HTTPException(status_code=400, detail="No rolls data provided")
        
        # Convert frontend format to optimizer format
        order_requirements = []
        for roll in rolls_data:
            order_requirements.append({
                'width': float(roll['width']),
                'quantity': int(roll['quantity']),
                'gsm': int(roll['gsm']),
                'bf': float(roll['bf']),
                'shade': roll['shade'],
                'min_length': roll.get('min_length', 1000)
            })
        
        # Run optimization
        optimizer = CuttingOptimizer()
        result = optimizer.optimize_with_new_algorithm(order_requirements, interactive=False)
        
        # Convert result to frontend-expected format
        frontend_result = {
            "success": True,
            "total_rolls_needed": result['summary']['total_jumbos_used'],
            "total_waste_percentage": result['summary']['overall_waste_percentage'],
            "total_waste_inches": result['summary']['total_trim_inches'],
            "patterns": [],
            "unfulfilled_orders": []
        }
        
        # Convert jumbo rolls to patterns
        for jumbo in result['jumbo_rolls_used']:
            pattern = {
                "rolls": [
                    {
                        "width": roll['width'],
                        "shade": roll['shade'],
                        "gsm": roll['gsm'],
                        "bf": roll['bf']
                    }
                    for roll in jumbo['rolls']
                ],
                "waste_inches": jumbo['trim_left'],
                "waste_percentage": jumbo['waste_percentage']
            }
            frontend_result["patterns"].append(pattern)
        
        # Convert pending orders to unfulfilled orders
        for pending in result['pending_orders']:
            unfulfilled = {
                "width": pending['width'],
                "quantity": pending['quantity'],
                "gsm": pending['gsm'],
                "bf": pending['bf'],
                "shade": pending['shade']
            }
            frontend_result["unfulfilled_orders"].append(unfulfilled)
        
        return frontend_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing cutting optimizer with frontend data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/optimizer/test-full-cycle", tags=["Cutting Optimizer"])
def test_full_cycle_workflow(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """NEW FLOW: Test complete cycle - 3-input optimization + 4-output processing"""
    try:
        from .services.workflow_manager import WorkflowManager
        import uuid
        
        # Extract data
        order_ids = request_data.get('order_ids', [])
        created_by_id = request_data.get('created_by_id')
        
        if not order_ids:
            # Use test order IDs or create sample data
            return {
                "message": "NEW FLOW: Full cycle test requires order_ids",
                "example_request": {
                    "order_ids": ["uuid1", "uuid2", "uuid3"],
                    "created_by_id": "user_uuid"
                },
                "flow_steps": [
                    "1. Fetch orders with paper specifications",
                    "2. Find matching pending orders",
                    "3. Get available inventory (20-25\" waste)",
                    "4. Run 3-input optimization",
                    "5. Process 4 outputs into database",
                    "6. Update order statuses to 'processing'"
                ]
            }
        
        # Convert to UUIDs
        uuid_order_ids = []
        for order_id in order_ids:
            try:
                uuid_order_ids.append(uuid.UUID(order_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {order_id}")
        
        user_uuid = uuid.UUID(created_by_id) if created_by_id else None
        
        # Initialize workflow manager
        workflow_manager = WorkflowManager(db=db, user_id=user_uuid)
        
        # Run full cycle
        result = workflow_manager.process_multiple_orders(uuid_order_ids)
        
        return {
            "message": "NEW FLOW: Full cycle test completed",
            "result": result,
            "cycle_explanation": {
                "what_happened": [
                    "Orders were fetched with paper specifications",
                    "Matching pending orders were found and included",
                    "Available waste inventory (20-25\") was retrieved",
                    "3-input optimization was executed",
                    "4 outputs were processed into database records",
                    "Order statuses updated to 'processing'"
                ],
                "database_changes": {
                    "plans_created": len(result.get('details', {}).get('plan_ids', [])),
                    "production_orders": len(result.get('details', {}).get('production_order_ids', [])),
                    "pending_orders": len(result.get('details', {}).get('pending_order_ids', [])),
                    "inventory_items": len(result.get('details', {}).get('inventory_ids', [])),
                    "orders_updated": len(result.get('details', {}).get('updated_order_ids', []))
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing full cycle workflow: {e}")
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

@router.post("/optimizer/from-orders", tags=["Cutting Optimizer"])
def generate_cutting_plan_from_orders_advanced(
    order_ids: List[str],
    consider_inventory: bool = True,
    created_by_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Generate an optimized cutting plan for specified orders using master-based architecture.
    
    This endpoint creates a cutting plan by considering existing inventory and optimizing
    for minimum waste, speed, or material usage.
    """
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        import uuid
        
        # Convert string IDs to UUIDs
        uuid_order_ids = []
        for order_id in order_ids:
            try:
                uuid_order_ids.append(uuid.UUID(order_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid UUID format: {order_id}")
        
        # Get orders using master-based architecture
        orders = db.query(models.OrderMaster).options(
            joinedload(models.OrderMaster.client),
            joinedload(models.OrderMaster.paper),
            joinedload(models.OrderMaster.created_by)
        ).filter(
            models.OrderMaster.id.in_(uuid_order_ids),
            models.OrderMaster.status.in_(["pending", "processing"])
        ).all()
        
        if not orders:
            raise HTTPException(
                status_code=404,
                detail="No valid orders found with the provided IDs"
            )
        
        # Convert orders to optimizer format using master relationships
        order_requirements = []
        for order in orders:
            if not order.paper:
                continue
                
            order_requirements.append({
                'order_id': str(order.id),
                'width': float(order.width),
                'quantity': order.quantity - (order.quantity_fulfilled or 0),
                'gsm': order.paper.gsm,
                'bf': float(order.paper.bf),
                'shade': order.paper.shade,
                'min_length': order.min_length or 1000,
                'client_name': order.client.name if order.client else 'Unknown'
            })
        
        if not order_requirements:
            raise HTTPException(status_code=400, detail="No valid order requirements found")
        
        # Get available inventory if requested
        available_inventory = []
        if consider_inventory:
            inventory_items = db.query(models.InventoryMaster).options(
                joinedload(models.InventoryMaster.paper)
            ).filter(
                models.InventoryMaster.status == "available",
                models.InventoryMaster.roll_type == "jumbo"
            ).all()
            
            for item in inventory_items:
                if item.paper:
                    available_inventory.append({
                        'id': str(item.id),
                        'width': float(item.width),
                        'length': float(item.length) if item.length else 1000,
                        'gsm': item.paper.gsm,
                        'bf': float(item.paper.bf),
                        'shade': item.paper.shade,
                        'status': item.status,
                        'weight': float(item.weight) if item.weight else 0
                    })
        
        # Generate the optimized plan
        optimizer = CuttingOptimizer()
        plan = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            interactive=False
        )
        
        # Create plan in database if created_by_id is provided
        plan_created = None
        if created_by_id:
            try:
                created_by_uuid = uuid.UUID(created_by_id)
                plan_data = schemas.PlanMasterCreate(
                    name=f"Auto Plan from Orders {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    cut_pattern=plan['jumbo_rolls_used'],
                    expected_waste_percentage=plan['summary']['overall_waste_percentage'],
                    created_by_id=created_by_uuid,
                    order_ids=uuid_order_ids,
                    inventory_ids=[]
                )
                plan_created = crud.create_plan(db, plan_data)
            except Exception as e:
                logger.warning(f"Could not create plan in database: {e}")
        
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
            'fulfilled_orders': len(order_requirements) - len(plan['pending_orders']),
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
            'plan_created': str(plan_created.id) if plan_created else None,
            'available_inventory_considered': len(available_inventory),
            'specification_groups_processed': plan['summary']['specification_groups_processed']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating cutting plan from orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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