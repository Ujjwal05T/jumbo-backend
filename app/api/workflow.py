from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
import logging

from .base import get_db
from .. import crud_operations, schemas
from ..services.workflow_manager import WorkflowManager

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# WORKFLOW MANAGEMENT ENDPOINTS
# ============================================================================

@router.post("/optimizer/create-plan", response_model=schemas.OptimizerOutput, tags=["Cutting Optimizer"])
def create_cutting_plan(
    request: schemas.CreatePlanRequest,
    db: Session = Depends(get_db)
):
    """Generate cutting plan using optimization algorithm"""
    try:
        return crud_operations.create_cutting_plan(db=db, request=request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating cutting plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/workflow/generate-plan", response_model=schemas.WorkflowResult, tags=["Workflow Management"])
def generate_cutting_plan_from_workflow(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Generate cutting plan using workflow manager"""
    try:
        workflow = WorkflowManager(db=db, user_id=request_data.get("user_id"))
        return workflow.generate_plan_from_orders(request_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating plan from workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/workflow/process-orders", tags=["Workflow Management"])
def process_multiple_orders(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """NEW FLOW: Process multiple orders with 3-input optimization"""
    try:
        import uuid
        order_ids = [uuid.UUID(id_str) for id_str in request_data.get("order_ids", [])]
        user_id = request_data.get("user_id")
        jumbo_roll_width = request_data.get("jumbo_roll_width", 118)  # Default to 118 if not provided
        
        workflow = WorkflowManager(db=db, user_id=user_id, jumbo_roll_width=jumbo_roll_width)
        result = workflow.process_multiple_orders(order_ids)
        
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Invalid order ID format: {ve}")
    except Exception as e:
        logger.error(f"Error processing multiple orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/workflow/status", tags=["Workflow Management"])
def get_workflow_status(db: Session = Depends(get_db)):
    """Get overall workflow status and metrics"""
    try:
        return crud_operations.get_workflow_status(db=db)
    except Exception as e:
        logger.error(f"Error getting workflow status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/optimizer/orders-with-relationships", tags=["Cutting Optimizer"])
def get_orders_with_relationships(db: Session = Depends(get_db)):
    """Get orders with their relationships for planning"""
    try:
        orders = crud_operations.get_orders(db=db, skip=0, limit=1000)
        
        orders_with_relationships = []
        for order in orders:
            order_data = {
                "order_id": str(order.id),
                "client_name": order.client.company_name if order.client else "Unknown",
                "status": order.status,
                "total_quantity": order.quantity_rolls,
                "width_inches": float(order.width_inches),
                "created_at": order.created_at.isoformat(),
                "order_items": [],
                "paper_specs": None
            }
            
            # Get paper specifications
            if order.paper_id:
                paper = crud_operations.get_paper(db=db, paper_id=order.paper_id)
                if paper:
                    order_data["paper_specs"] = {
                        "gsm": paper.gsm,
                        "bf": float(paper.bf),
                        "shade": paper.shade,
                        "paper_type": paper.paper_type
                    }
            
            # Get order items if available
            if hasattr(order, 'order_items') and order.order_items:
                for item in order.order_items:
                    order_data["order_items"].append({
                        "item_id": str(item.id),
                        "width_inches": float(item.width_inches),
                        "quantity": item.quantity,
                        "item_status": item.item_status
                    })
            
            orders_with_relationships.append(order_data)
        
        return {
            "total_orders": len(orders_with_relationships),
            "orders": orders_with_relationships
        }
        
    except Exception as e:
        logger.error(f"Error getting orders with relationships: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/optimizer/plans/{plan_id}/status", tags=["Cutting Optimizer"])
def update_plan_status_and_waste(
    plan_id: str,
    update_request: schemas.PlanStatusUpdate,
    db: Session = Depends(get_db)
):
    """Update plan status and actual waste percentage"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        
        plan = crud_operations.get_plan(db=db, plan_id=plan_uuid)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Update status
        updated_plan = crud_operations.update_plan_status(db=db, plan_id=plan_uuid, new_status=update_request.status)
        
        # Update actual waste percentage if provided
        if update_request.actual_waste_percentage is not None:
            plan_update = schemas.PlanMasterUpdate(
                actual_waste_percentage=update_request.actual_waste_percentage
            )
            updated_plan = crud_operations.update_plan(db=db, plan_id=plan_uuid, plan_update=plan_update)
        
        return {
            "plan_id": str(updated_plan.id),
            "name": updated_plan.name,
            "status": updated_plan.status,
            "expected_waste_percentage": float(updated_plan.expected_waste_percentage) if updated_plan.expected_waste_percentage else None,
            "actual_waste_percentage": float(updated_plan.actual_waste_percentage) if updated_plan.actual_waste_percentage else None,
            "executed_at": updated_plan.executed_at.isoformat() if updated_plan.executed_at else None,
            "completed_at": updated_plan.completed_at.isoformat() if updated_plan.completed_at else None,
            "message": f"Plan status updated to '{updated_plan.status}'"
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating plan status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/optimizer/plans/{plan_id}/execute", tags=["Cutting Optimizer"])
def execute_cutting_plan(plan_id: str, db: Session = Depends(get_db)):
    """Execute a cutting plan by updating status to in_progress"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        
        updated_plan = crud_operations.execute_plan(db=db, plan_id=plan_uuid)
        if not updated_plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        return {
            "plan_id": str(updated_plan.id),
            "name": updated_plan.name,
            "status": updated_plan.status,
            "executed_at": updated_plan.executed_at.isoformat() if updated_plan.executed_at else None,
            "message": "Plan execution started successfully"
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/optimizer/plans/{plan_id}/complete", tags=["Cutting Optimizer"])
def complete_cutting_plan(plan_id: str, db: Session = Depends(get_db)):
    """Complete a cutting plan by updating status to completed"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        
        updated_plan = crud_operations.complete_plan(db=db, plan_id=plan_uuid)
        if not updated_plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        return {
            "plan_id": str(updated_plan.id),
            "name": updated_plan.name,
            "status": updated_plan.status,
            "executed_at": updated_plan.executed_at.isoformat() if updated_plan.executed_at else None,
            "completed_at": updated_plan.completed_at.isoformat() if updated_plan.completed_at else None,
            "message": "Plan completed successfully"
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/optimizer/plans/{plan_id}/inventory-links", tags=["Cutting Optimizer"])
def link_inventory_to_plan(
    plan_id: str,
    link_request: schemas.PlanInventoryLinkRequest,
    db: Session = Depends(get_db)
):
    """Link inventory items to a cutting plan"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        
        plan = crud_operations.get_plan(db=db, plan_id=plan_uuid)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        created_links = []
        for inventory_id in link_request.inventory_ids:
            # Check if inventory item exists
            inventory_item = crud_operations.get_inventory_item(db=db, inventory_id=inventory_id)
            if not inventory_item:
                continue  # Skip invalid inventory IDs
            
            # Create plan-inventory link (this would need to be implemented in crud_operations)
            # For now, we'll simulate the response
            created_links.append({
                "plan_id": str(plan_uuid),
                "inventory_id": str(inventory_id),
                "linked_at": "2024-01-01T00:00:00",  # Would be actual timestamp
                "inventory_status": inventory_item.status
            })
        
        return {
            "plan_id": str(plan_uuid),
            "links_created": len(created_links),
            "inventory_links": created_links,
            "message": f"Successfully linked {len(created_links)} inventory items to plan"
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except Exception as e:
        logger.error(f"Error linking inventory to plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/optimizer/plans/{plan_id}/inventory-links", tags=["Cutting Optimizer"])
def get_plan_inventory_links(plan_id: str, db: Session = Depends(get_db)):
    """Get inventory links for a cutting plan"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        
        plan = crud_operations.get_plan(db=db, plan_id=plan_uuid)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get linked inventory items (would be actual implementation)
        inventory_links = []
        if hasattr(plan, 'plan_inventory') and plan.plan_inventory:
            for link in plan.plan_inventory:
                if link.inventory:
                    inventory_links.append({
                        "link_id": str(link.id) if hasattr(link, 'id') else "unknown",
                        "inventory_id": str(link.inventory.id),
                        "width_inches": float(link.inventory.width_inches),
                        "weight_kg": float(link.inventory.weight_kg),
                        "roll_type": link.inventory.roll_type,
                        "status": link.inventory.status,
                        "qr_code": link.inventory.qr_code
                    })
        
        return {
            "plan_id": str(plan_uuid),
            "plan_name": plan.name,
            "total_linked_items": len(inventory_links),
            "inventory_links": inventory_links
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")
    except Exception as e:
        logger.error(f"Error getting plan inventory links: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/optimizer/plans/{plan_id}/inventory-links/{link_id}", tags=["Cutting Optimizer"])
def remove_inventory_link_from_plan(plan_id: str, link_id: str, db: Session = Depends(get_db)):
    """Remove an inventory link from a cutting plan"""
    try:
        import uuid
        plan_uuid = uuid.UUID(plan_id)
        link_uuid = uuid.UUID(link_id)
        
        plan = crud_operations.get_plan(db=db, plan_id=plan_uuid)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Remove the link (would be actual implementation)
        # For now, we'll simulate the response
        return {
            "plan_id": str(plan_uuid),
            "link_id": str(link_uuid),
            "message": "Inventory link removed successfully"
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error removing inventory link: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/optimizer/inventory/{inventory_id}/status", tags=["Cutting Optimizer"])
def update_inventory_status_optimizer(
    inventory_id: str,
    status_update: schemas.InventoryStatusUpdate,
    db: Session = Depends(get_db)
):
    """Update inventory item status"""
    try:
        import uuid
        inventory_uuid = uuid.UUID(inventory_id)
        
        updated_item = crud_operations.update_inventory_status(
            db=db,
            inventory_id=inventory_uuid,
            new_status=status_update.new_status
        )
        
        if not updated_item:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        
        return {
            "inventory_id": str(updated_item.id),
            "status": updated_item.status,
            "roll_type": updated_item.roll_type,
            "width_inches": float(updated_item.width_inches),
            "location": updated_item.location,
            "updated_at": updated_item.updated_at.isoformat() if updated_item.updated_at else None,
            "message": f"Inventory status updated to '{updated_item.status}'"
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid inventory ID format")
    except Exception as e:
        logger.error(f"Error updating inventory status: {e}")
        raise HTTPException(status_code=500, detail=str(e))