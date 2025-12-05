from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Dict, Any
from datetime import datetime
import logging

from .base import get_db
from .. import crud_operations, schemas, models

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# QR CODE ENDPOINTS
# ============================================================================

@router.get("/qr/{qr_code}", response_model=Dict[str, Any], tags=["QR Code Management"])
def scan_qr_code(qr_code: str, db: Session = Depends(get_db)):
    """Scan QR code or barcode and return cut roll details"""
    try:
        # Find inventory item by QR code or barcode ID with relationships loaded
        matching_item = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.created_by),
            joinedload(models.InventoryMaster.allocated_order).joinedload(models.OrderMaster.client),
            joinedload(models.InventoryMaster.parent_118_roll).joinedload(models.InventoryMaster.parent_jumbo)
        ).filter(
            (models.InventoryMaster.qr_code == qr_code) |
            (models.InventoryMaster.barcode_id == qr_code)
        ).first()
        
        if not matching_item:
            raise HTTPException(status_code=404, detail="QR code or barcode not found in inventory")
        
        # Paper and created_by are already loaded via relationships
        paper = matching_item.paper
        
        # Get client information from multiple sources
        client_name = None
        
        # Method 1: Check allocated order
        if matching_item.allocated_order and matching_item.allocated_order.client:
            client_name = matching_item.allocated_order.client.company_name
        
        # Method 2: Check if there are any related orders through same paper and width
        if not client_name:
            try:
                # Find orders with matching paper and width that might be related
                related_order = db.query(models.OrderMaster).join(models.OrderItem).filter(
                    models.OrderItem.paper_id == matching_item.paper_id,
                    models.OrderItem.width_inches == float(matching_item.width_inches),
                    models.OrderMaster.status.in_(["in_process", "created"])
                ).first()
                
                if related_order and related_order.client:
                    client_name = f"{related_order.client.company_name} (Inferred)"
            except Exception as e:
                logger.warning(f"Could not infer client from related orders: {e}")

        # Get parent roll information (118" roll and jumbo roll)
        parent_118_barcode = None
        parent_jumbo_barcode = None

        if matching_item.parent_118_roll:
            parent_118_barcode = matching_item.parent_118_roll.barcode_id
            if matching_item.parent_118_roll.parent_jumbo:
                parent_jumbo_barcode = matching_item.parent_118_roll.parent_jumbo.barcode_id

        return {
            "inventory_id": str(matching_item.id),
            "qr_code": matching_item.qr_code,
            "barcode_id": matching_item.barcode_id,
            "roll_details": {
                "width_inches": float(matching_item.width_inches),
                "weight_kg": float(matching_item.weight_kg),
                "roll_type": matching_item.roll_type,
                "status": matching_item.status,
                "location": matching_item.location
            },
            "paper_specifications": {
                "gsm": paper.gsm if paper else None,
                "bf": float(paper.bf) if paper else None,
                "shade": paper.shade if paper else None,
                "paper_type": paper.type if paper else None
            } if paper else None,
            "production_info": {
                "created_at": matching_item.created_at.isoformat(),
                "created_by": matching_item.created_by.name if matching_item.created_by else None
            },
            "parent_rolls": {
                "parent_118_barcode": parent_118_barcode,
                "parent_jumbo_barcode": parent_jumbo_barcode
            },
            "client_info": {
                "client_name": client_name
            },
            "scan_timestamp": matching_item.created_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scanning QR code {qr_code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/qr/update-weight", response_model=Dict[str, Any], tags=["QR Code Management"])
def update_weight_via_qr(
    weight_update: schemas.QRWeightUpdate,
    db: Session = Depends(get_db)
):
    """Update cut roll weight via QR code scan"""
    try:
        # Find inventory item by QR code or barcode ID with paper relationship loaded
        matching_item = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper)
        ).filter(
            (models.InventoryMaster.qr_code == weight_update.qr_code) |
            (models.InventoryMaster.barcode_id == weight_update.qr_code)
        ).first()
        
        if not matching_item:
            raise HTTPException(status_code=404, detail="QR code or barcode not found in inventory")
        
        # Update weight
        old_weight = matching_item.weight_kg
        matching_item.weight_kg = weight_update.weight_kg
        matching_item.updated_at = datetime.utcnow()

        # If provided, update location
        if weight_update.location:
            matching_item.location = weight_update.location
        
        # AUTOMATIC STATUS UPDATE: When weight is added, automatically set status to 'available'
        # This means the cut roll is now ready for dispatch
        if matching_item.weight_kg > 0.1:  # Real weight added
            matching_item.status = "available"
            logger.info(f"🔄 Auto-updated inventory {matching_item.id} status to 'available' after weight update")
        
        # STEP 4: When weight is added, find related order items and set them to "in_warehouse"
        # Find order items that match this cut roll's specifications
        order_items = []  # Initialize to avoid scope issues
        logger.info(f"🔍 Inventory item paper relationship: {matching_item.paper is not None}, weight: {matching_item.weight_kg}")
        if matching_item.paper and matching_item.weight_kg > 0.1:  # Real weight added
            paper = matching_item.paper
            logger.info(f"🔍 Looking for order items with paper_id={paper.id}, width={matching_item.width_inches}")
            
            # Find order items with matching paper and width that are still "in_process"
            order_items = db.query(models.OrderItem).join(models.OrderMaster).filter(
                models.OrderItem.paper_id == paper.id,
                models.OrderItem.width_inches == float(matching_item.width_inches),
                models.OrderMaster.status == "in_process",
                models.OrderItem.item_status == "in_process"
            ).all()
            
            logger.info(f"🔍 Found {len(order_items)} matching order items in 'in_process' status")
            
            # Update the first matching order item with quantity fulfillment logic
            if order_items:
                order_item = order_items[0]
                
                # STEP 5: Increment quantity_fulfilled for first-time weight updates
                if old_weight <= 0.1 and matching_item.weight_kg > 0.1:  # First time getting real weight
                    if order_item.quantity_fulfilled < order_item.quantity_rolls:
                        order_item.quantity_fulfilled += 1
                        logger.info(f"📈 Incremented quantity_fulfilled for order item {order_item.id}: {order_item.quantity_fulfilled}/{order_item.quantity_rolls}")
                        
                        # Only change status when ALL required rolls are fulfilled
                        if order_item.quantity_fulfilled >= order_item.quantity_rolls:
                            order_item.item_status = "in_warehouse"
                            order_item.moved_to_warehouse_at = func.now()
                            logger.info(f"🏭 Order item {order_item.id} moved to 'in_warehouse' - ALL rolls fulfilled!")
                        else:
                            # Keep in "in_process" until all rolls are weighed
                            logger.info(f"⏳ Order item {order_item.id} remains 'in_process' - needs {order_item.quantity_rolls - order_item.quantity_fulfilled} more rolls")
                
                logger.info(f"Updated order item {order_item.id} - status: '{order_item.item_status}', fulfilled: {order_item.quantity_fulfilled}/{order_item.quantity_rolls}")
                
                # STEP 6: Check if entire order is now completed based on quantity fulfillment
                order = order_item.order
                if order and old_weight <= 0.1 and matching_item.weight_kg > 0.1:  # Only check on first-time weight update
                    # Check if all order items are fully fulfilled by quantity (in "in_warehouse" status)
                    all_items_fulfilled = all(
                        oi.quantity_fulfilled >= oi.quantity_rolls 
                        for oi in order.order_items
                    )
                    
                    # Check if all order items are now in warehouse (ready for dispatch)
                    all_items_in_warehouse = all(
                        oi.item_status == "in_warehouse"
                        for oi in order.order_items
                    )
                    
                    if all_items_fulfilled and all_items_in_warehouse and order.status != "completed":
                        order.status = "in_process"  # Keep as in_process until actually dispatched
                        order.updated_at = func.now()
                        logger.info(f"🏭 Order {order.id} - all items in warehouse, ready for dispatch!")
        
        db.commit()
        db.refresh(matching_item)
        
        # Build response with fulfillment information
        response_data = {
            "inventory_id": str(matching_item.id),
            "qr_code": matching_item.qr_code,
            "barcode_id": matching_item.barcode_id,
            "weight_update": {
                "old_weight_kg": float(old_weight),
                "new_weight_kg": float(matching_item.weight_kg),
                "weight_difference": float(matching_item.weight_kg - old_weight),
                "is_first_time_weight": old_weight <= 0.1 and matching_item.weight_kg > 0.1
            },
            "current_status": matching_item.status,
            "current_location": matching_item.location,
            "updated_at": matching_item.created_at.isoformat(),
            "message": f"Weight updated successfully from {old_weight}kg to {matching_item.weight_kg}kg"
        }
        
        # Add fulfillment information if order items were updated
        if matching_item.paper and matching_item.weight_kg > 0.1 and order_items:
            order_item = order_items[0]
            response_data["fulfillment_update"] = {
                "order_item_id": str(order_item.id),
                "order_id": str(order_item.order_id),
                "quantity_fulfilled": order_item.quantity_fulfilled,
                "quantity_required": order_item.quantity_rolls,
                "item_status": order_item.item_status,
                "is_item_completed": order_item.quantity_fulfilled >= order_item.quantity_rolls,
                "order_status": order_item.order.status if order_item.order else None,
                "is_order_completed": order_item.order.status == "completed" if order_item.order else False
            }
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating weight for QR code {weight_update.qr_code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/qr/generate", response_model=Dict[str, Any], tags=["QR Code Management"])
def generate_qr_code(
    qr_request: schemas.QRGenerateRequest,
    db: Session = Depends(get_db)
):
    """Generate QR code for inventory item"""
    try:
        import uuid
        from datetime import datetime
        
        # Generate unique QR code
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        qr_code = f"JR_{timestamp}_{unique_id}"
        
        # Update inventory item with QR code if inventory_id provided
        if qr_request.inventory_id:
            inventory_item = crud_operations.get_inventory_item(db=db, inventory_id=qr_request.inventory_id)
            if not inventory_item:
                raise HTTPException(status_code=404, detail="Inventory item not found")
            
            inventory_item.qr_code = qr_code
            db.commit()
            db.refresh(inventory_item)
            
            return {
                "qr_code": qr_code,
                "inventory_id": str(inventory_item.id),
                "roll_info": {
                    "width_inches": float(inventory_item.width_inches),
                    "roll_type": inventory_item.roll_type,
                    "status": inventory_item.status
                },
                "generated_at": datetime.now().isoformat(),
                "message": "QR code generated and linked to inventory item"
            }
        else:
            # Just generate QR code without linking
            return {
                "qr_code": qr_code,
                "generated_at": datetime.now().isoformat(),
                "message": "QR code generated successfully"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/barcode/{barcode_id}", response_model=Dict[str, Any], tags=["Barcode Management"])
def scan_barcode(barcode_id: str, db: Session = Depends(get_db)):
    """Scan barcode and return cut roll details (checks both InventoryMaster and ManualCutRoll tables)"""
    try:
        # First try InventoryMaster (production rolls)
        matching_item = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.created_by),
            joinedload(models.InventoryMaster.allocated_order).joinedload(models.OrderMaster.client),
            joinedload(models.InventoryMaster.parent_118_roll).joinedload(models.InventoryMaster.parent_jumbo)
        ).filter(models.InventoryMaster.barcode_id == barcode_id).first()

        # If not found in InventoryMaster, check ManualCutRoll table
        manual_roll = None
        if not matching_item:
            manual_roll = db.query(models.ManualCutRoll).options(
                joinedload(models.ManualCutRoll.paper),
                joinedload(models.ManualCutRoll.client),
                joinedload(models.ManualCutRoll.created_by)
            ).filter(models.ManualCutRoll.barcode_id == barcode_id).first()

        if not matching_item and not manual_roll:
            raise HTTPException(status_code=404, detail="Barcode not found in inventory or manual cut rolls")

        # Handle manual cut roll response
        if manual_roll:
            paper = manual_roll.paper
            client_name = manual_roll.client.company_name if manual_roll.client else None

            return {
                "inventory_id": str(manual_roll.id),
                "qr_code": None,
                "barcode_id": manual_roll.barcode_id,
                "roll_type": "manual_cut",
                "is_manual": True,
                "roll_details": {
                    "width_inches": float(manual_roll.width_inches),
                    "weight_kg": float(manual_roll.weight_kg),
                    "roll_type": "manual_cut",
                    "status": manual_roll.status,
                    "location": manual_roll.location,
                    "reel_number": manual_roll.reel_number
                },
                "paper_specifications": {
                    "gsm": paper.gsm if paper else None,
                    "bf": float(paper.bf) if paper else None,
                    "shade": paper.shade if paper else None,
                    "paper_type": paper.type if paper else None
                } if paper else None,
                "production_info": {
                    "created_at": manual_roll.created_at.isoformat() if manual_roll.created_at else None,
                    "created_by": manual_roll.created_by.name if manual_roll.created_by else None
                },
                "parent_rolls": {
                    "parent_118_barcode": None,
                    "parent_jumbo_barcode": None
                },
                "client_info": {
                    "client_name": client_name
                },
                "scan_timestamp": manual_roll.created_at.isoformat() if manual_roll.created_at else None
            }

        # Handle production roll response (existing logic continues below)
        
        # Paper and created_by are already loaded via relationships
        paper = matching_item.paper
        
        # Get client information from multiple sources
        client_name = None
        
        # Method 1: Check allocated order
        if matching_item.allocated_order and matching_item.allocated_order.client:
            client_name = matching_item.allocated_order.client.company_name
        
        # Method 2: Check if there are any related orders through same paper and width
        if not client_name:
            try:
                # Find orders with matching paper and width that might be related
                related_order = db.query(models.OrderMaster).join(models.OrderItem).filter(
                    models.OrderItem.paper_id == matching_item.paper_id,
                    models.OrderItem.width_inches == float(matching_item.width_inches),
                    models.OrderMaster.status.in_(["in_process", "created"])
                ).first()
                
                if related_order and related_order.client:
                    client_name = f"{related_order.client.company_name} (Inferred)"
            except Exception as e:
                logger.warning(f"Could not infer client from related orders: {e}")

        # Get parent roll information (118" roll and jumbo roll)
        parent_118_barcode = None
        parent_jumbo_barcode = None

        if matching_item.parent_118_roll:
            parent_118_barcode = matching_item.parent_118_roll.barcode_id
            if matching_item.parent_118_roll.parent_jumbo:
                parent_jumbo_barcode = matching_item.parent_118_roll.parent_jumbo.barcode_id

        return {
            "inventory_id": str(matching_item.id),
            "qr_code": matching_item.qr_code,
            "barcode_id": matching_item.barcode_id,
            "roll_details": {
                "width_inches": float(matching_item.width_inches),
                "weight_kg": float(matching_item.weight_kg),
                "roll_type": matching_item.roll_type,
                "status": matching_item.status,
                "location": matching_item.location
            },
            "paper_specifications": {
                "gsm": paper.gsm if paper else None,
                "bf": float(paper.bf) if paper else None,
                "shade": paper.shade if paper else None,
                "paper_type": paper.type if paper else None
            } if paper else None,
            "production_info": {
                "created_at": matching_item.created_at.isoformat(),
                "created_by": matching_item.created_by.name if matching_item.created_by else None
            },
            "parent_rolls": {
                "parent_118_barcode": parent_118_barcode,
                "parent_jumbo_barcode": parent_jumbo_barcode
            },
            "client_info": {
                "client_name": client_name
            },
            "scan_timestamp": matching_item.created_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scanning barcode {barcode_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))