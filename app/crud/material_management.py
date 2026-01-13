from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, text
from uuid import UUID
import logging
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import models, schemas

logger = logging.getLogger(__name__)

# ============================================================================
# MATERIAL MASTER CRUD
# ============================================================================

def create_material(db: Session, material: schemas.MaterialMasterCreate) -> models.MaterialMaster:
    """Create a new material"""
    db_material = models.MaterialMaster(**material.dict())
    db.add(db_material)
    db.commit()
    db.refresh(db_material)
    logger.info(f"Created material: {db_material.name}")
    return db_material

def get_materials(
    db: Session, 
    skip: int = 0, 
    limit: int = 100
) -> List[models.MaterialMaster]:
    """Get all materials with pagination"""
    return db.query(models.MaterialMaster).order_by(models.MaterialMaster.name).offset(skip).limit(limit).all()

def get_material(db: Session, material_id: UUID) -> Optional[models.MaterialMaster]:
    """Get material by ID"""
    return db.query(models.MaterialMaster).filter(models.MaterialMaster.id == material_id).first()

def update_material(
    db: Session, 
    material_id: UUID, 
    material_update: schemas.MaterialMasterUpdate
) -> Optional[models.MaterialMaster]:
    """Update material information"""
    db_material = get_material(db, material_id)
    if not db_material:
        return None
    
    update_data = material_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_material, field, value)
    
    db.commit()
    db.refresh(db_material)
    logger.info(f"Updated material: {db_material.name}")
    return db_material

def delete_material(db: Session, material_id: UUID) -> bool:
    """Delete material"""
    db_material = get_material(db, material_id)
    if not db_material:
        return False
    
    db.delete(db_material)
    db.commit()
    logger.info(f"Deleted material: {db_material.name}")
    return True

# ============================================================================
# INWARD CHALLAN CRUD
# ============================================================================

def create_inward_challan(db: Session, challan: schemas.InwardChallanCreate) -> models.InwardChallan:
    """Create a new inward challan with year suffix (format: 00001-25)"""
    challan_data = challan.dict()

    # Generate serial number with year suffix
    try:
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

        # Get all serial numbers for the current year
        pattern = f"%-{current_year}"
        result = db.query(models.InwardChallan.serial_no).filter(
            models.InwardChallan.serial_no.like(pattern)
        ).all()

        # Extract counter values and find max
        max_counter = 0
        for row in result:
            serial_no = row[0]
            if serial_no:
                try:
                    # Extract counter from format: 00123-25
                    parts = serial_no.split("-")
                    if len(parts) >= 2:
                        counter = int(parts[0])  # First part is the counter
                        max_counter = max(max_counter, counter)
                except (ValueError, IndexError):
                    continue

        # Increment counter
        next_counter = max_counter + 1

        # Format: 00001-25
        serial_no = f"{next_counter:05d}-{current_year}"
        challan_data['serial_no'] = serial_no
        logger.info(f"Generated inward challan serial number: {serial_no} (year: {current_year}, counter: {next_counter})")
    except Exception as e:
        logger.error(f"Error generating inward challan serial number: {e}")
        # Fallback: use current year with counter 1
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
        challan_data['serial_no'] = f"00001-{current_year}"

    # Calculate final_weight if not provided but net_weight and report are available
    if challan_data.get('final_weight') is None and challan_data.get('net_weight') is not None:
        net_weight = challan_data.get('net_weight', 0)
        report = challan_data.get('report', 0)
        challan_data['final_weight'] = net_weight - report

    db_challan = models.InwardChallan(**challan_data)
    db.add(db_challan)
    db.commit()
    db.refresh(db_challan)

    # Update material quantity using final_weight instead of net_weight
    if db_challan.final_weight and db_challan.final_weight > 0:
        material = get_material(db, challan.material_id)
        if material:
            material.current_quantity += Decimal(str(db_challan.final_weight))
            db.commit()
            logger.info(f"Updated material {material.name} quantity by +{db_challan.final_weight} (final_weight)")

    logger.info(f"Created inward challan with serial number: {challan_data['serial_no']} for material_id: {challan.material_id}")
    return db_challan

def get_inward_challans(
    db: Session, 
    skip: int = 0, 
    limit: int = 100,
    material_id: Optional[UUID] = None
) -> List[models.InwardChallan]:
    """Get all inward challans with pagination and optional material filter"""
    query = db.query(models.InwardChallan).order_by(desc(models.InwardChallan.created_at))
    
    if material_id:
        query = query.filter(models.InwardChallan.material_id == material_id)
    
    return query.offset(skip).limit(limit).all()

def get_inward_challan(db: Session, challan_id: UUID) -> Optional[models.InwardChallan]:
    """Get inward challan by ID"""
    return db.query(models.InwardChallan).filter(models.InwardChallan.id == challan_id).first()

def update_inward_challan(
    db: Session, 
    challan_id: UUID, 
    challan_update: schemas.InwardChallanUpdate
) -> Optional[models.InwardChallan]:
    """Update inward challan information"""
    db_challan = get_inward_challan(db, challan_id)
    if not db_challan:
        return None
    
    # Store old net_weight for quantity adjustment
    old_net_weight = db_challan.net_weight or 0
    
    update_data = challan_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_challan, field, value)
    
    # Adjust material quantity if net_weight changed
    new_net_weight = db_challan.net_weight or 0
    if old_net_weight != new_net_weight:
        material = get_material(db, db_challan.material_id)
        if material:
            quantity_difference = Decimal(str(new_net_weight)) - Decimal(str(old_net_weight))
            material.current_quantity += quantity_difference
            logger.info(f"Adjusted material {material.name} quantity by {quantity_difference}")
    
    db.commit()
    db.refresh(db_challan)
    logger.info(f"Updated inward challan: {challan_id}")
    return db_challan

def delete_inward_challan(db: Session, challan_id: UUID) -> bool:
    """Delete inward challan and adjust material quantity"""
    db_challan = get_inward_challan(db, challan_id)
    if not db_challan:
        return False
    
    # Reverse the quantity addition
    if db_challan.net_weight and db_challan.net_weight > 0:
        material = get_material(db, db_challan.material_id)
        if material:
            material.current_quantity -= Decimal(str(db_challan.net_weight))
            logger.info(f"Reversed material {material.name} quantity by -{db_challan.net_weight}")
    
    db.delete(db_challan)
    db.commit()
    logger.info(f"Deleted inward challan: {challan_id}")
    return True

# ============================================================================
# OUTWARD CHALLAN CRUD
# ============================================================================

def create_outward_challan(db: Session, challan: schemas.OutwardChallanCreate) -> models.OutwardChallan:
    """Create a new outward challan with year suffix (format: 00001-25)"""
    from fastapi import HTTPException

    challan_data = challan.dict()

    # Check for duplicate rst_no (if rst_no is provided and not empty)
    rst_no = challan_data.get('rst_no')
    if rst_no and rst_no.strip():
        existing_challan = db.query(models.OutwardChallan).filter(
            models.OutwardChallan.rst_no == rst_no.strip()
        ).first()

        if existing_challan:
            logger.warning(f"Duplicate rst_no attempted: {rst_no}")
            raise HTTPException(
                status_code=400,
                detail=f"RST No. '{rst_no}' is already in use. Please use a unique RST number."
            )

    # Generate serial number with year suffix
    try:
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

        # Get all serial numbers for the current year
        pattern = f"%-{current_year}"
        result = db.query(models.OutwardChallan.serial_no).filter(
            models.OutwardChallan.serial_no.like(pattern)
        ).all()

        # Extract counter values and find max
        max_counter = 0
        for row in result:
            serial_no = row[0]
            if serial_no:
                try:
                    # Extract counter from format: 00123-25
                    parts = serial_no.split("-")
                    if len(parts) >= 2:
                        counter = int(parts[0])  # First part is the counter
                        max_counter = max(max_counter, counter)
                except (ValueError, IndexError):
                    continue

        # Increment counter
        next_counter = max_counter + 1

        # Format: 00001-25
        serial_no = f"{next_counter:05d}-{current_year}"
        challan_data['serial_no'] = serial_no
        logger.info(f"Generated outward challan serial number: {serial_no} (year: {current_year}, counter: {next_counter})")
    except Exception as e:
        logger.error(f"Error generating outward challan serial number: {e}")
        # Fallback: use current year with counter 1
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
        challan_data['serial_no'] = f"00001-{current_year}"

    db_challan = models.OutwardChallan(**challan_data)
    db.add(db_challan)
    db.commit()
    db.refresh(db_challan)
    logger.info(f"Created outward challan with serial number: {challan_data['serial_no']} and vehicle: {challan.vehicle_number}")
    return db_challan

def get_outward_challans(
    db: Session, 
    skip: int = 0, 
    limit: int = 100
) -> List[models.OutwardChallan]:
    """Get all outward challans with pagination"""
    return db.query(models.OutwardChallan).order_by(desc(models.OutwardChallan.created_at)).offset(skip).limit(limit).all()

def get_outward_challan(db: Session, challan_id: UUID) -> Optional[models.OutwardChallan]:
    """Get outward challan by ID"""
    return db.query(models.OutwardChallan).filter(models.OutwardChallan.id == challan_id).first()

def update_outward_challan(
    db: Session,
    challan_id: UUID,
    challan_update: schemas.OutwardChallanUpdate
) -> Optional[models.OutwardChallan]:
    """Update outward challan information"""
    from fastapi import HTTPException

    db_challan = get_outward_challan(db, challan_id)
    if not db_challan:
        return None

    update_data = challan_update.dict(exclude_unset=True)

    # Check for duplicate rst_no (if rst_no is being updated and not empty)
    if 'rst_no' in update_data:
        rst_no = update_data.get('rst_no')
        if rst_no and rst_no.strip():
            # Check if another challan (not this one) is using this rst_no
            existing_challan = db.query(models.OutwardChallan).filter(
                models.OutwardChallan.rst_no == rst_no.strip(),
                models.OutwardChallan.id != challan_id
            ).first()

            if existing_challan:
                logger.warning(f"Duplicate rst_no attempted in update: {rst_no}")
                raise HTTPException(
                    status_code=400,
                    detail=f"RST No. '{rst_no}' is already in use. Please use a unique RST number."
                )

    for field, value in update_data.items():
        setattr(db_challan, field, value)

    db.commit()
    db.refresh(db_challan)
    logger.info(f"Updated outward challan: {challan_id}")
    return db_challan

def delete_outward_challan(db: Session, challan_id: UUID) -> bool:
    """Delete outward challan"""
    db_challan = get_outward_challan(db, challan_id)
    if not db_challan:
        return False
    
    db.delete(db_challan)
    db.commit()
    logger.info(f"Deleted outward challan: {challan_id}")
    return True

# ============================================================================
# SERIAL NUMBER GENERATION CRUD
# ============================================================================

def get_next_inward_serial(db: Session) -> str:
    """
    Get next available serial number for inward challans as preview
    Format: 00001-25, 00002-25, etc. (with year suffix)
    """

    try:
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

        # Get all serial numbers for the current year
        pattern = f"%-{current_year}"
        result = db.query(models.InwardChallan.serial_no).filter(
            models.InwardChallan.serial_no.like(pattern)
        ).all()

        # Extract counter values and find max
        max_counter = 0
        for row in result:
            serial_no = row[0]
            if serial_no:
                try:
                    # Extract counter from format: 00123-25
                    parts = serial_no.split("-")
                    if len(parts) >= 2:
                        counter = int(parts[0])  # First part is the counter
                        max_counter = max(max_counter, counter)
                except (ValueError, IndexError):
                    continue

        # Preview will be max_counter + 1
        next_counter = max_counter + 1
        next_serial = f"{next_counter:05d}-{current_year}"
        logger.info(f"Preview next inward serial: {next_serial} (year: {current_year}, counter: {next_counter})")
        return next_serial

    except Exception as e:
        logger.error(f"Error getting next inward serial preview: {e}")
        # Fallback: use current year with counter 1
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
        return f"00001-{current_year}"

def get_next_outward_serial(db: Session) -> str:
    """
    Get next available serial number for outward challans as preview
    Format: 00001-25, 00002-25, etc. (with year suffix)
    """

    try:
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

        # Get all serial numbers for the current year
        pattern = f"%-{current_year}"
        result = db.query(models.OutwardChallan.serial_no).filter(
            models.OutwardChallan.serial_no.like(pattern)
        ).all()

        # Extract counter values and find max
        max_counter = 0
        for row in result:
            serial_no = row[0]
            if serial_no:
                try:
                    # Extract counter from format: 00123-25
                    parts = serial_no.split("-")
                    if len(parts) >= 2:
                        counter = int(parts[0])  # First part is the counter
                        max_counter = max(max_counter, counter)
                except (ValueError, IndexError):
                    continue

        # Preview will be max_counter + 1
        next_counter = max_counter + 1
        next_serial = f"{next_counter:05d}-{current_year}"
        logger.info(f"Preview next outward serial: {next_serial} (year: {current_year}, counter: {next_counter})")
        return next_serial

    except Exception as e:
        logger.error(f"Error getting next outward serial preview: {e}")
        # Fallback: use current year with counter 1
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
        return f"00001-{current_year}"
        