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
        raise HTTPException(status_code=500, detail=str(e))# 
# ============================================================================
# ORDER MASTER ENDPOINTS
# ============================================================================

@router.post("/orders", response_model=schemas.OrderMaster, tags=["Order Master"])
def create_order(order: schemas.OrderMasterCreate, db: Session = Depends(get_db)):
    """Create a new order in Order Master"""
    try:
        return crud.create_order(db=db, order=order)
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

# Legacy endpoint for backward compatibility
@router.post("/orders/legacy", response_model=schemas.OrderMaster, tags=["Order Master"])
def create_order_legacy(order: schemas.OrderCreate, db: Session = Depends(get_db)):
    """Create order using legacy format (backward compatibility)"""
    try:
        return crud.create_order_legacy(db=db, order=order)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating legacy order: {e}")
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
        raise HTTPException(status_code=500, detail=str(e))# =
# ===========================================================================
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
    """Test the cutting optimizer algorithm with sample data without affecting the database"""
    try:
        from .services.cutting_optimizer import CuttingOptimizer
        
        optimizer = CuttingOptimizer()
        result = optimizer.test_algorithm_with_sample_data()
        
        return {
            "message": "Cutting optimizer test completed successfully",
            "test_data": "Sample orders with mixed specifications (GSM, Shade, BF)",
            "optimization_result": result
        }
    except Exception as e:
        logger.error(f"Error testing cutting optimizer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/optimizer/test-with-orders", tags=["Cutting Optimizer"])
def test_optimizer_with_orders(
    order_ids: List[str],
    db: Session = Depends(get_db)
):
    """Test the cutting optimizer with actual order IDs from the database"""
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
        
        optimizer = CuttingOptimizer()
        order_requirements = optimizer.get_order_requirements_from_db(db, uuid_order_ids)
        
        if not order_requirements:
            raise HTTPException(status_code=404, detail="No valid orders found with provided IDs")
        
        result = optimizer.optimize_with_new_algorithm(order_requirements, interactive=False)
        
        return {
            "message": "Cutting optimizer test with database orders completed successfully",
            "orders_processed": len(order_requirements),
            "order_details": order_requirements,
            "optimization_result": result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing cutting optimizer with orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/optimizer/create-plan", response_model=schemas.PlanMaster, tags=["Cutting Optimizer"])
def create_cutting_plan(
    order_ids: List[str],
    created_by_id: str,
    plan_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Create a cutting plan from order IDs using the optimizer"""
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
        
        try:
            created_by_uuid = uuid.UUID(created_by_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format for created_by_id: {created_by_id}")
        
        optimizer = CuttingOptimizer()
        plan = optimizer.create_plan_from_orders(
            db=db,
            order_ids=uuid_order_ids,
            created_by_id=created_by_uuid,
            plan_name=plan_name,
            interactive=False
        )
        
        return plan
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating cutting plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))@r
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

# ============================================================================
# WORKFLOW MANAGEMENT ROUTES
# ============================================================================

@router.post("/workflow/generate-plan", response_model=schemas.PlanMaster, tags=["Workflow Management"])
def generate_cutting_plan_from_workflow(
    order_ids: List[str],
    created_by_id: str,
    plan_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Generate a cutting plan from multiple orders using workflow manager"""
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
        
        try:
            created_by_uuid = uuid.UUID(created_by_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format for created_by_id: {created_by_id}")
        
        # Initialize workflow manager
        workflow_manager = WorkflowManager(db=db, user_id=created_by_uuid)
        
        # Create cutting plan
        plan = workflow_manager.create_cutting_plan_from_orders(
            order_ids=uuid_order_ids,
            plan_name=plan_name
        )
        
        return plan
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating cutting plan from workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/workflow/process-orders", tags=["Workflow Management"])
def process_multiple_orders(
    order_ids: List[str],
    user_id: str,
    db: Session = Depends(get_db)
):
    """Process multiple orders together for optimal cutting plans"""
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
        valid_statuses = ["planned", "in_progress", "completed", "cancelled"]
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
        valid_statuses = ["available", "reserved", "used", "damaged"]
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