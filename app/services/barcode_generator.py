from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from zoneinfo import ZoneInfo
from .. import models
import logging

logger = logging.getLogger(__name__)

class BarcodeGenerator:
    """
    Service for generating unique barcode IDs with year suffix and annual counter reset.

    Format: CR_00001-25 (where 25 is the year)
    Counter resets to 00001 on January 1st of each year.
    Year suffix updates automatically based on current date.
    """
    
    @staticmethod
    def generate_cut_roll_barcode(db: Session) -> str:
        """
        Generate next sequential cut roll barcode in CR_00001-25 format.
        Range: CR_00001-25 to CR_07999-25, then skips to CR_09001-25+
        (CR_08000-25 to CR_09000-25 reserved for manual cut rolls)
        Counter resets to 00001 on January 1st each year.

        Args:
            db: Database session

        Returns:
            str: Next barcode ID like CR_00001-25, CR_00002-25, etc.
        """
        try:
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Get all barcodes for the current year
            pattern = f"CR_%-{current_year}"
            result = db.query(models.InventoryMaster.barcode_id).filter(
                models.InventoryMaster.barcode_id.like(pattern)
            ).all()

            # Extract counter values and find max
            max_number = 0
            for row in result:
                barcode_id = row[0]
                if barcode_id:
                    try:
                        # Extract number from CR_00123-25 format
                        parts = barcode_id.split("-")
                        if len(parts) >= 2 and parts[0].startswith('CR_'):
                            current_number = int(parts[0][3:])  # Remove 'CR_' prefix
                            # Skip manual cut roll range (8000-9000) when finding max
                            if current_number < 8000 or current_number > 9000:
                                max_number = max(max_number, current_number)
                    except (ValueError, AttributeError, IndexError):
                        continue

            # Increment counter
            next_number = max_number + 1

            # Skip the reserved range for manual cut rolls (8000-9000)
            if next_number == 8000:
                logger.info(f"Reached CR_08000-{current_year}, skipping to CR_09001-{current_year} (manual cut roll range)")
                next_number = 9001
            elif 8000 < next_number <= 9000:
                # Should not happen, but safety check
                logger.warning(f"Next number {next_number} in reserved manual range, jumping to 9001")
                next_number = 9001

            # Format as CR_00001-25 (5 digits with leading zeros and year)
            barcode_id = f"CR_{next_number:05d}-{current_year}"

            logger.info(f"Generated cut roll barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating cut roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
            fallback_id = f"CR_{int(time.time()) % 100000:05d}-{current_year}"
            logger.warning(f"Using fallback barcode: {fallback_id}")
            return fallback_id
    
    @staticmethod
    def generate_inventory_barcode(db: Session, roll_type: str = "INV") -> str:
        """
        Generate barcode for inventory items in INV_00001-25 or JMB_00001-25 format.
        Counter resets to 00001 on January 1st each year.

        Args:
            db: Database session
            roll_type: Type of roll ("INV" for general, "JMB" for jumbo)

        Returns:
            str: Next barcode ID like INV_00001-25
        """
        try:
            prefix = "JMB" if roll_type.lower() == "jumbo" else "INV"
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Get all barcodes for this prefix and current year
            pattern = f"{prefix}_%-{current_year}"
            result = db.query(models.InventoryMaster.barcode_id).filter(
                models.InventoryMaster.barcode_id.like(pattern)
            ).all()

            # Extract counter values and find max
            max_number = 0
            for row in result:
                barcode_id = row[0]
                if barcode_id:
                    try:
                        # Extract number from INV_00123-25 format
                        parts = barcode_id.split("-")
                        if len(parts) >= 2 and parts[0].startswith(f'{prefix}_'):
                            current_number = int(parts[0][4:])  # Remove prefix
                            max_number = max(max_number, current_number)
                    except (ValueError, AttributeError, IndexError):
                        continue

            next_number = max_number + 1

            barcode_id = f"{prefix}_{next_number:05d}-{current_year}"
            logger.info(f"Generated inventory barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating inventory barcode: {e}")
            import time
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
            fallback_id = f"{roll_type.upper()}_{int(time.time()) % 100000:05d}-{current_year}"
            return fallback_id
    
    @staticmethod
    def generate_wastage_barcode(db: Session) -> str:
        """
        Generate barcode for wastage inventory in WSB-00001-25 format.
        Counter resets to 00001 on January 1st each year.

        Args:
            db: Database session

        Returns:
            str: Next wastage barcode ID like WSB-00001-25, WSB-00002-25, etc.
        """
        try:
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Get all wastage barcodes for the current year
            pattern = f"WSB-%-{current_year}"
            result = db.query(models.WastageInventory.barcode_id).filter(
                models.WastageInventory.barcode_id.like(pattern)
            ).all()

            # Extract counter values and find max
            max_number = 0
            for row in result:
                barcode_id = row[0]
                if barcode_id:
                    try:
                        # Extract number from WSB-00123-25 format
                        parts = barcode_id.split("-")
                        if len(parts) >= 3 and parts[0] == 'WSB':
                            current_number = int(parts[1])
                            max_number = max(max_number, current_number)
                    except (ValueError, AttributeError, IndexError):
                        continue

            next_number = max_number + 1

            # Format as WSB-00001-25 (5 digits with leading zeros and year)
            barcode_id = f"WSB-{next_number:05d}-{current_year}"

            logger.info(f"Generated wastage barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating wastage barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
            fallback_id = f"WSB-{int(time.time()) % 100000:05d}-{current_year}"
            logger.warning(f"Using fallback wastage barcode: {fallback_id}")
            return fallback_id

    @staticmethod
    def generate_manual_cut_roll_barcode(db: Session) -> str:
        """
        Generate barcode for manual cut rolls in CR_08000-25 to CR_09000-25 format.
        This is a reserved range within the CR_ series for manually entered rolls.
        Counter resets to 08000 on January 1st each year.

        Args:
            db: Database session

        Returns:
            str: Next barcode ID like CR_08000-25, CR_08001-25, etc.
        """
        try:
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Get all manual cut roll barcodes for the current year
            pattern = f"CR_%-{current_year}"
            result = db.query(models.ManualCutRoll.barcode_id).filter(
                models.ManualCutRoll.barcode_id.like(pattern)
            ).all()

            # Extract counter values in the 8000-9000 range and find max
            max_number = 7999  # Start before the manual range
            for row in result:
                barcode_id = row[0]
                if barcode_id:
                    try:
                        # Extract number from CR_08000-25 format
                        parts = barcode_id.split("-")
                        if len(parts) >= 2 and parts[0].startswith('CR_'):
                            current_number = int(parts[0][3:])  # Remove 'CR_' prefix
                            # Only consider numbers in the manual range
                            if 8000 <= current_number <= 9000:
                                max_number = max(max_number, current_number)
                    except (ValueError, AttributeError, IndexError):
                        continue

            # If no manual rolls exist this year, start at 8000
            next_number = 8000 if max_number == 7999 else max_number + 1

            # Check if we've exceeded the reserved range
            if next_number > 9000:
                logger.error(f"Manual cut roll range exhausted for year {current_year}! Attempted to generate CR_{next_number:05d}-{current_year}")
                raise ValueError(f"Manual cut roll barcode range (CR_08000-{current_year} to CR_09000-{current_year}) is exhausted. Maximum 1001 manual rolls reached for this year.")

            # Format as CR_08000-25 (5 digits with leading zeros and year)
            barcode_id = f"CR_{next_number:05d}-{current_year}"

            logger.info(f"Generated manual cut roll barcode: {barcode_id}")
            return barcode_id

        except ValueError:
            # Re-raise the exhaustion error
            raise
        except Exception as e:
            logger.error(f"Error generating manual cut roll barcode: {e}")
            # Fallback to timestamp-based ID (still in format but with timestamp)
            import time
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
            fallback_id = f"CR_{int(time.time()) % 1000 + 8000:05d}-{current_year}"
            logger.warning(f"Using fallback manual cut roll barcode: {fallback_id}")
            return fallback_id

    @staticmethod
    def generate_scrap_cut_roll_barcode(db: Session) -> str:
        """
        Generate barcode for scrap cut rolls (from wastage) in SCR-00001-25 format.
        Counter resets to 00001 on January 1st each year.

        Args:
            db: Database session

        Returns:
            str: Next SCR barcode ID like SCR-00001-25, SCR-00002-25, etc.
        """
        try:
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Get all SCR barcodes for the current year
            pattern = f"SCR-%-{current_year}"
            result = db.query(models.InventoryMaster.barcode_id).filter(
                models.InventoryMaster.barcode_id.like(pattern)
            ).all()

            # Extract counter values and find max
            max_number = 0
            for row in result:
                barcode_id = row[0]
                if barcode_id:
                    try:
                        # Extract number from SCR-00123-25 format
                        parts = barcode_id.split("-")
                        if len(parts) >= 3 and parts[0] == 'SCR':
                            current_number = int(parts[1])
                            max_number = max(max_number, current_number)
                    except (ValueError, AttributeError, IndexError):
                        continue

            next_number = max_number + 1

            # Format as SCR-00001-25 (5 digits with leading zeros and year)
            barcode_id = f"SCR-{next_number:05d}-{current_year}"

            logger.info(f"Generated scrap cut roll barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating scrap cut roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
            fallback_id = f"SCR-{int(time.time()) % 100000:05d}-{current_year}"
            logger.warning(f"Using fallback SCR barcode: {fallback_id}")
            return fallback_id

    @staticmethod
    def validate_barcode_format(barcode_id: str, barcode_type: str = "cut_roll") -> bool:
        """
        Validate barcode format with year suffix.

        Args:
            barcode_id: Barcode to validate (e.g., "CR_00001-25")
            barcode_type: Type - "cut_roll", "manual_cut_roll", "inventory", "jumbo", "118_roll", "wastage", or "scrap_cut_roll"

        Returns:
            bool: True if valid format
        """
        if not barcode_id:
            return False

        try:
            if barcode_type == "cut_roll":
                # Validates CR_XXXXX-YY format (e.g., CR_00001-25)
                parts = barcode_id.split("-")
                if len(parts) != 2:
                    return False
                if not parts[0].startswith("CR_") or len(parts[0]) != 8 or not parts[0][3:].isdigit():
                    return False
                # Check year is 2 digits
                if len(parts[1]) != 2 or not parts[1].isdigit():
                    return False
                return True
            elif barcode_type == "manual_cut_roll":
                # Validates CR_08000-25 to CR_09000-25 range specifically
                parts = barcode_id.split("-")
                if len(parts) != 2:
                    return False
                if not parts[0].startswith("CR_") or len(parts[0]) != 8 or not parts[0][3:].isdigit():
                    return False
                # Check year is 2 digits
                if len(parts[1]) != 2 or not parts[1].isdigit():
                    return False
                try:
                    barcode_num = int(parts[0][3:])
                    return 8000 <= barcode_num <= 9000
                except ValueError:
                    return False
            elif barcode_type == "inventory":
                # Format: INV_00001-25
                parts = barcode_id.split("-")
                if len(parts) != 2:
                    return False
                if not parts[0].startswith("INV_") or len(parts[0]) != 9 or not parts[0][4:].isdigit():
                    return False
                return len(parts[1]) == 2 and parts[1].isdigit()
            elif barcode_type == "jumbo":
                # Format: JR_00001-25
                parts = barcode_id.split("-")
                if len(parts) != 2:
                    return False
                if not parts[0].startswith("JR_") or len(parts[0]) != 8 or not parts[0][3:].isdigit():
                    return False
                return len(parts[1]) == 2 and parts[1].isdigit()
            elif barcode_type == "118_roll":
                # Format: SET_00001-25
                parts = barcode_id.split("-")
                if len(parts) != 2:
                    return False
                if not parts[0].startswith("SET_") or len(parts[0]) != 9 or not parts[0][4:].isdigit():
                    return False
                return len(parts[1]) == 2 and parts[1].isdigit()
            elif barcode_type == "wastage":
                # Format: WSB-00001-25
                parts = barcode_id.split("-")
                if len(parts) != 3:
                    return False
                if parts[0] != "WSB" or len(parts[1]) != 5 or not parts[1].isdigit():
                    return False
                return len(parts[2]) == 2 and parts[2].isdigit()
            elif barcode_type == "scrap_cut_roll":
                # Format: SCR-00001-25
                parts = barcode_id.split("-")
                if len(parts) != 3:
                    return False
                if parts[0] != "SCR" or len(parts[1]) != 5 or not parts[1].isdigit():
                    return False
                return len(parts[2]) == 2 and parts[2].isdigit()
            else:
                return False
        except:
            return False
    
    @staticmethod
    def generate_118_roll_barcode(db: Session) -> str:
        """
        Generate barcode for 118" rolls in SET_00001-25 format.
        Counter resets to 00001 on January 1st each year.

        Args:
            db: Database session

        Returns:
            str: Next barcode ID like SET_00001-25, SET_00002-25, etc.
        """
        try:
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Get all SET barcodes for the current year
            pattern = f"SET_%-{current_year}"
            result = db.query(models.InventoryMaster.barcode_id).filter(
                models.InventoryMaster.barcode_id.like(pattern)
            ).all()

            # Extract counter values and find max
            max_number = 0
            for row in result:
                barcode_id = row[0]
                if barcode_id:
                    try:
                        # Extract number from SET_00123-25 format
                        parts = barcode_id.split("-")
                        if len(parts) >= 2 and parts[0].startswith('SET_'):
                            current_number = int(parts[0][4:])  # Remove 'SET_' prefix
                            max_number = max(max_number, current_number)
                    except (ValueError, AttributeError, IndexError):
                        continue

            next_number = max_number + 1

            # Format as SET_00001-25 (5 digits with leading zeros and year)
            barcode_id = f"SET_{next_number:05d}-{current_year}"

            logger.info(f"Generated 118 roll barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating 118 roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
            fallback_id = f"SET_{int(time.time()) % 100000:05d}-{current_year}"
            logger.warning(f"Using fallback 118 roll barcode: {fallback_id}")
            return fallback_id

    @staticmethod
    def generate_jumbo_roll_barcode(db: Session) -> str:
        """
        Generate barcode for jumbo rolls in JR_00001-25 format.
        Counter resets to 00001 on January 1st each year.

        Args:
            db: Database session

        Returns:
            str: Next barcode ID like JR_00001-25, JR_00002-25, etc.
        """
        try:
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Get all JR barcodes for the current year
            pattern = f"JR_%-{current_year}"
            result = db.query(models.InventoryMaster.barcode_id).filter(
                models.InventoryMaster.barcode_id.like(pattern)
            ).all()

            # Extract counter values and find max
            max_number = 0
            for row in result:
                barcode_id = row[0]
                if barcode_id:
                    try:
                        # Extract number from JR_00123-25 format
                        parts = barcode_id.split("-")
                        if len(parts) >= 2 and parts[0].startswith('JR_'):
                            current_number = int(parts[0][3:])  # Remove 'JR_' prefix
                            max_number = max(max_number, current_number)
                    except (ValueError, AttributeError, IndexError):
                        continue

            next_number = max_number + 1

            # Format as JR_00001-25 (5 digits with leading zeros and year)
            barcode_id = f"JR_{next_number:05d}-{current_year}"

            logger.info(f"Generated jumbo roll barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating jumbo roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
            fallback_id = f"JR_{int(time.time()) % 100000:05d}-{current_year}"
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