from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Dict, Any
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
            joinedload(models.InventoryMaster.allocated_order).joinedload(models.OrderMaster.client)
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
        if matching_item.paper and matching_item.weight_kg > 0.1:  # Real weight added
            paper = matching_item.paper
            
            # Find order items with matching paper and width that are still "in_process"
            order_items = db.query(models.OrderItem).join(models.OrderMaster).filter(
                models.OrderItem.paper_id == paper.id,
                models.OrderItem.width_inches == float(matching_item.width_inches),
                models.OrderMaster.status == "in_process",
                models.OrderItem.item_status == "in_process"
            ).all()
            
            # Update the first matching order item to "in_warehouse"
            if order_items:
                order_item = order_items[0]
                order_item.item_status = "in_warehouse"
                order_item.moved_to_warehouse_at = func.now()
                logger.info(f"✅ Updated order item {order_item.id} item_status to 'in_warehouse' (Step 4: QR Weight Added)")
        
        db.commit()
        db.refresh(matching_item)
        
        return {
            "inventory_id": str(matching_item.id),
            "qr_code": matching_item.qr_code,
            "barcode_id": matching_item.barcode_id,
            "weight_update": {
                "old_weight_kg": float(old_weight),
                "new_weight_kg": float(matching_item.weight_kg),
                "weight_difference": float(matching_item.weight_kg - old_weight)
            },
            "current_status": matching_item.status,
            "current_location": matching_item.location,
            "updated_at": matching_item.created_at.isoformat(),
            "message": f"Weight updated successfully from {old_weight}kg to {matching_item.weight_kg}kg"
        }
        
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
    """Scan barcode and return cut roll details"""
    try:
        # Find inventory item by barcode ID with relationships loaded
        matching_item = db.query(models.InventoryMaster).options(
            joinedload(models.InventoryMaster.paper),
            joinedload(models.InventoryMaster.created_by),
            joinedload(models.InventoryMaster.allocated_order).joinedload(models.OrderMaster.client)
        ).filter(models.InventoryMaster.barcode_id == barcode_id).first()
        
        if not matching_item:
            raise HTTPException(status_code=404, detail="Barcode not found in inventory")
        
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