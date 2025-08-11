from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models
import logging

logger = logging.getLogger(__name__)

class BarcodeGenerator:
    """
    Service for generating unique barcode IDs in CR_00001 format for cut rolls
    and other barcode IDs for inventory items.
    """
    
    @staticmethod
    def generate_cut_roll_barcode(db: Session) -> str:
        """
        Generate next sequential cut roll barcode in CR_00001 format.
        
        Args:
            db: Database session
            
        Returns:
            str: Next barcode ID like CR_00001, CR_00002, etc.
        """
        try:
            # Get the highest existing barcode number from inventory (where cut rolls are stored)
            result = db.query(func.max(models.InventoryMaster.barcode_id)).filter(
                models.InventoryMaster.barcode_id.like('CR_%')
            ).scalar()
            
            if result is None:
                # No barcodes exist yet, start with 1
                next_number = 1
            else:
                # Extract number from CR_00123 format
                try:
                    if result and result.startswith('CR_'):
                        current_number = int(result[3:])  # Remove 'CR_' prefix
                        next_number = current_number + 1
                    else:
                        next_number = 1
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid barcode format found: {result}, starting from 1")
                    next_number = 1
            
            # Format as CR_00001 (5 digits with leading zeros)
            barcode_id = f"CR_{next_number:05d}"
            
            logger.info(f"Generated cut roll barcode: {barcode_id}")
            return barcode_id
            
        except Exception as e:
            logger.error(f"Error generating cut roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            fallback_id = f"CR_{int(time.time())}"
            logger.warning(f"Using fallback barcode: {fallback_id}")
            return fallback_id
    
    @staticmethod
    def generate_inventory_barcode(db: Session, roll_type: str = "INV") -> str:
        """
        Generate barcode for inventory items in INV_00001 or JMB_00001 format.
        
        Args:
            db: Database session
            roll_type: Type of roll ("INV" for general, "JMB" for jumbo)
            
        Returns:
            str: Next barcode ID
        """
        try:
            prefix = "JMB" if roll_type.lower() == "jumbo" else "INV"
            
            # Get the highest existing barcode number for this prefix
            pattern = f"{prefix}_%"
            result = db.query(func.max(models.InventoryMaster.barcode_id)).filter(
                models.InventoryMaster.barcode_id.like(pattern)
            ).scalar()
            
            if result is None:
                next_number = 1
            else:
                try:
                    if result and result.startswith(f'{prefix}_'):
                        current_number = int(result[4:])  # Remove prefix
                        next_number = current_number + 1
                    else:
                        next_number = 1
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid inventory barcode format: {result}")
                    next_number = 1
            
            barcode_id = f"{prefix}_{next_number:05d}"
            logger.info(f"Generated inventory barcode: {barcode_id}")
            return barcode_id
            
        except Exception as e:
            logger.error(f"Error generating inventory barcode: {e}")
            import time
            fallback_id = f"{roll_type.upper()}_{int(time.time())}"
            return fallback_id
    
    @staticmethod
    def validate_barcode_format(barcode_id: str, barcode_type: str = "cut_roll") -> bool:
        """
        Validate barcode format.
        
        Args:
            barcode_id: Barcode to validate
            barcode_type: Type - "cut_roll", "inventory", or "jumbo"
            
        Returns:
            bool: True if valid format
        """
        if not barcode_id:
            return False
            
        try:
            if barcode_type == "cut_roll":
                return barcode_id.startswith("CR_") and len(barcode_id) == 8 and barcode_id[3:].isdigit()
            elif barcode_type == "inventory":
                return barcode_id.startswith("INV_") and len(barcode_id) == 9 and barcode_id[4:].isdigit()
            elif barcode_type == "jumbo":
                return barcode_id.startswith("JMB_") and len(barcode_id) == 9 and barcode_id[4:].isdigit()
            else:
                return False
        except:
            return False
    
    @staticmethod
    def is_barcode_unique(db: Session, barcode_id: str, table: str = "inventory") -> bool:
        """
        Check if barcode is unique in the inventory table.
        
        Args:
            db: Database session
            barcode_id: Barcode to check
            table: Table to check - only "inventory" supported now
            
        Returns:
            bool: True if unique
        """
        try:
            # All barcodes are now stored in inventory_master table
            existing = db.query(models.InventoryMaster).filter(
                models.InventoryMaster.barcode_id == barcode_id
            ).first()
                
            return existing is None
            
        except Exception as e:
            logger.error(f"Error checking barcode uniqueness: {e}")
            return False