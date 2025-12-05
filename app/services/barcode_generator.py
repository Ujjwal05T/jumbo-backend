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
        Range: CR_00001 to CR_07999, then skips to CR_09001+
        (CR_08000 to CR_09000 reserved for manual cut rolls)

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

            # Skip the reserved range for manual cut rolls (8000-9000)
            if next_number == 8000:
                logger.info(f"Reached CR_08000, skipping to CR_09001 (manual cut roll range)")
                next_number = 9001
            elif 8000 < next_number <= 9000:
                # Should not happen, but safety check
                logger.warning(f"Next number {next_number} in reserved manual range, jumping to 9001")
                next_number = 9001

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
    def generate_wastage_barcode(db: Session) -> str:
        """
        Generate barcode for wastage inventory in WSB-00001 format.
        
        Args:
            db: Database session
            
        Returns:
            str: Next wastage barcode ID like WSB-00001, WSB-00002, etc.
        """
        try:
            # Get the highest existing wastage barcode number
            result = db.query(func.max(models.WastageInventory.barcode_id)).filter(
                models.WastageInventory.barcode_id.like('WSB-%')
            ).scalar()
            
            if result is None:
                next_number = 1
            else:
                try:
                    if result and result.startswith('WSB-'):
                        current_number = int(result[4:])  # Remove 'WSB-' prefix
                        next_number = current_number + 1
                    else:
                        next_number = 1
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid wastage barcode format: {result}")
                    next_number = 1
            
            # Format as WSB-00001 (5 digits with leading zeros)
            barcode_id = f"WSB-{next_number:05d}"
            
            logger.info(f"Generated wastage barcode: {barcode_id}")
            return barcode_id
            
        except Exception as e:
            logger.error(f"Error generating wastage barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            fallback_id = f"WSB-{int(time.time())}"
            logger.warning(f"Using fallback wastage barcode: {fallback_id}")
            return fallback_id

    @staticmethod
    def generate_manual_cut_roll_barcode(db: Session) -> str:
        """
        Generate barcode for manual cut rolls in CR_08000 to CR_09000 format.
        This is a reserved range within the CR_ series for manually entered rolls.

        Args:
            db: Database session

        Returns:
            str: Next barcode ID like CR_08000, CR_08001, etc.
        """
        try:
            # Get the highest existing manual cut roll barcode number
            result = db.query(func.max(models.ManualCutRoll.barcode_id)).filter(
                models.ManualCutRoll.barcode_id.like('CR_%')
            ).scalar()

            if result is None:
                # No manual cut roll barcodes exist yet, start with 8000
                next_number = 8000
            else:
                # Extract number from CR_08000 format
                try:
                    if result and result.startswith('CR_'):
                        current_number = int(result[3:])  # Remove 'CR_' prefix
                        next_number = current_number + 1
                    else:
                        next_number = 8000
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid manual cut roll barcode format found: {result}, starting from 8000")
                    next_number = 8000

            # Check if we've exceeded the reserved range
            if next_number > 9000:
                logger.error(f"Manual cut roll range exhausted! Attempted to generate CR_{next_number:05d}")
                raise ValueError("Manual cut roll barcode range (CR_08000 to CR_09000) is exhausted. Maximum 1001 manual rolls reached.")

            # Format as CR_08000 (5 digits with leading zeros)
            barcode_id = f"CR_{next_number:05d}"

            logger.info(f"Generated manual cut roll barcode: {barcode_id}")
            return barcode_id

        except ValueError:
            # Re-raise the exhaustion error
            raise
        except Exception as e:
            logger.error(f"Error generating manual cut roll barcode: {e}")
            # Fallback to timestamp-based ID (still in format but with timestamp)
            import time
            fallback_id = f"CR_{int(time.time()) % 1000 + 8000:05d}"
            logger.warning(f"Using fallback manual cut roll barcode: {fallback_id}")
            return fallback_id

    @staticmethod
    def generate_scrap_cut_roll_barcode(db: Session) -> str:
        """
        Generate barcode for scrap cut rolls (from wastage) in SCR-00001 format.

        Args:
            db: Database session

        Returns:
            str: Next SCR barcode ID like SCR-00001, SCR-00002, etc.
        """
        try:
            # Get the highest existing SCR barcode number from inventory
            result = db.query(func.max(models.InventoryMaster.barcode_id)).filter(
                models.InventoryMaster.barcode_id.like('SCR-%')
            ).scalar()

            if result is None:
                # No SCR barcodes exist yet, start with 1
                next_number = 1
            else:
                # Extract number from SCR-00123 format
                try:
                    if result and result.startswith('SCR-'):
                        current_number = int(result[4:])  # Remove 'SCR-' prefix
                        next_number = current_number + 1
                    else:
                        next_number = 1
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid SCR barcode format found: {result}, starting from 1")
                    next_number = 1

            # Format as SCR-00001 (5 digits with leading zeros)
            barcode_id = f"SCR-{next_number:05d}"

            logger.info(f"Generated scrap cut roll barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating scrap cut roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            fallback_id = f"SCR-{int(time.time())}"
            logger.warning(f"Using fallback SCR barcode: {fallback_id}")
            return fallback_id

    @staticmethod
    def validate_barcode_format(barcode_id: str, barcode_type: str = "cut_roll") -> bool:
        """
        Validate barcode format.

        Args:
            barcode_id: Barcode to validate
            barcode_type: Type - "cut_roll", "manual_cut_roll", "inventory", "jumbo", "118_roll", "wastage", or "scrap_cut_roll"

        Returns:
            bool: True if valid format
        """
        if not barcode_id:
            return False

        try:
            if barcode_type == "cut_roll":
                # Validates CR_XXXXX format (both production and manual use same format)
                if not (barcode_id.startswith("CR_") and len(barcode_id) == 8 and barcode_id[3:].isdigit()):
                    return False
                # Optional: Check range - production (1-7999, 9001+), manual (8000-9000)
                return True
            elif barcode_type == "manual_cut_roll":
                # Validates CR_08000 to CR_09000 range specifically
                if not (barcode_id.startswith("CR_") and len(barcode_id) == 8 and barcode_id[3:].isdigit()):
                    return False
                try:
                    barcode_num = int(barcode_id[3:])
                    return 8000 <= barcode_num <= 9000
                except ValueError:
                    return False
            elif barcode_type == "inventory":
                return barcode_id.startswith("INV_") and len(barcode_id) == 9 and barcode_id[4:].isdigit()
            elif barcode_type == "jumbo":
                return barcode_id.startswith("JR_") and len(barcode_id) == 8 and barcode_id[3:].isdigit()
            elif barcode_type == "118_roll":
                return barcode_id.startswith("SET_") and len(barcode_id) == 9 and barcode_id[4:].isdigit()
            elif barcode_type == "wastage":
                return barcode_id.startswith("WSB-") and len(barcode_id) == 9 and barcode_id[4:].isdigit()
            elif barcode_type == "scrap_cut_roll":
                return barcode_id.startswith("SCR-") and len(barcode_id) == 9 and barcode_id[4:].isdigit()
            else:
                return False
        except:
            return False
    
    @staticmethod
    def generate_118_roll_barcode(db: Session) -> str:
        """
        Generate barcode for 118" rolls in SET_00001 format.

        Args:
            db: Database session

        Returns:
            str: Next barcode ID like SET_00001, SET_00002, etc.
        """
        try:
            # Get the highest existing barcode number from inventory
            result = db.query(func.max(models.InventoryMaster.barcode_id)).filter(
                models.InventoryMaster.barcode_id.like('SET_%')
            ).scalar()

            if result is None:
                # No barcodes exist yet, start with 1
                next_number = 1
            else:
                # Extract number from SET_00123 format
                try:
                    if result and result.startswith('SET_'):
                        current_number = int(result[4:])  # Remove 'SET_' prefix
                        next_number = current_number + 1
                    else:
                        next_number = 1
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid 118 roll barcode format found: {result}, starting from 1")
                    next_number = 1

            # Format as SET_00001 (5 digits with leading zeros)
            barcode_id = f"SET_{next_number:05d}"

            logger.info(f"Generated 118 roll barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating 118 roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            fallback_id = f"SET_{int(time.time())}"
            logger.warning(f"Using fallback 118 roll barcode: {fallback_id}")
            return fallback_id

    @staticmethod
    def generate_jumbo_roll_barcode(db: Session) -> str:
        """
        Generate barcode for jumbo rolls in JR_00001 format.

        Args:
            db: Database session

        Returns:
            str: Next barcode ID like JR_00001, JR_00002, etc.
        """
        try:
            # Get the highest existing barcode number from inventory
            result = db.query(func.max(models.InventoryMaster.barcode_id)).filter(
                models.InventoryMaster.barcode_id.like('JR_%')
            ).scalar()

            if result is None:
                # No barcodes exist yet, start with 1
                next_number = 1
            else:
                # Extract number from JR_00123 format
                try:
                    if result and result.startswith('JR_'):
                        current_number = int(result[3:])  # Remove 'JR_' prefix
                        next_number = current_number + 1
                    else:
                        next_number = 1
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid jumbo roll barcode format found: {result}, starting from 1")
                    next_number = 1

            # Format as JR_00001 (5 digits with leading zeros)
            barcode_id = f"JR_{next_number:05d}"

            logger.info(f"Generated jumbo roll barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating jumbo roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            fallback_id = f"JR_{int(time.time())}"
            logger.warning(f"Using fallback jumbo roll barcode: {fallback_id}")
            return fallback_id

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