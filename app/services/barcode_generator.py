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
        Generate next sequential cut roll barcode in CR_XXXXX-YY format.

        Year-based reserved ranges for manual cut rolls:
        - Year 25: CR_08000-25 to CR_09000-25 (8000-9000 reserved)
          Regular rolls: 1-7999, then 9001+
        - Year 26+: CR_00000-26 to CR_01000-26 (0-1000 reserved)
          Regular rolls: Start from 1001+

        Counter resets on January 1st each year.

        Args:
            db: Database session

        Returns:
            str: Next barcode ID like CR_00001-25, CR_01001-26, etc.
        """
        try:
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Get all barcodes for the current year
            pattern = f"CR_%-{current_year}"
            result = db.query(models.InventoryMaster.barcode_id).filter(
                models.InventoryMaster.barcode_id.like(pattern)
            ).all()

            # Extract counter values and find max (excluding manual ranges)
            max_number = 0
            for row in result:
                barcode_id = row[0]
                if barcode_id:
                    try:
                        # Extract number from CR_00123-25 format
                        parts = barcode_id.split("-")
                        if len(parts) >= 2 and parts[0].startswith('CR_'):
                            current_number = int(parts[0][3:])  # Remove 'CR_' prefix

                            # Skip manual cut roll ranges based on year
                            if current_year == "25":
                                # Year 25: Skip 8000-9000 range
                                if current_number < 8000 or current_number > 9000:
                                    max_number = max(max_number, current_number)
                            else:
                                # Year 26+: Skip 0-1000 range
                                if current_number > 1000:
                                    max_number = max(max_number, current_number)
                    except (ValueError, AttributeError, IndexError):
                        continue

            # Determine starting number based on year
            if current_year == "25":
                # Year 25: Start from 1 if no existing rolls
                if max_number == 0:
                    next_number = 1
                else:
                    next_number = max_number + 1

                # Skip the reserved range for manual cut rolls (8000-9000)
                if next_number == 8000:
                    logger.info(f"Reached CR_08000-{current_year}, skipping to CR_09001-{current_year} (manual cut roll range)")
                    next_number = 9001
                elif 8000 < next_number <= 9000:
                    logger.warning(f"Next number {next_number} in reserved manual range, jumping to 9001")
                    next_number = 9001
            else:
                # Year 26+: Start from 1001 to skip manual range (0-1000)
                if max_number == 0 or max_number < 1001:
                    next_number = 1001
                else:
                    next_number = max_number + 1

                # Safety check: ensure we never use the manual range (0-1000)
                if next_number <= 1000:
                    logger.warning(f"Next number {next_number} in reserved manual range (0-1000), jumping to 1001")
                    next_number = 1001

            # Format as CR_00001-25 (5 digits with leading zeros and year)
            barcode_id = f"CR_{next_number:05d}-{current_year}"

            logger.info(f"Generated cut roll barcode: {barcode_id}")
            return barcode_id

        except Exception as e:
            logger.error(f"Error generating cut roll barcode: {e}")
            # Fallback to timestamp-based ID
            import time
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")
            # Use timestamp in safe range (avoid reserved ranges)
            fallback_number = (int(time.time()) % 90000) + 10000  # Range: 10000-99999
            fallback_id = f"CR_{fallback_number:05d}-{current_year}"
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
    def generate_manual_cut_roll_barcode(db: Session, reel_no: int) -> str:
        """
        Generate barcode for manual cut rolls using reel number directly.
        Format: CR_{reel_no:05d}-{year}

        Year-based reel number ranges:
        - Year 25: reel_no must be 8000-9000 (legacy range)
        - Year 26+: reel_no must be 0-1000 (new range)

        Args:
            db: Database session
            reel_no: The reel number to use in the barcode

        Returns:
            str: Barcode like CR_08001-25 or CR_00500-26, etc.
        """
        try:
            current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

            # Validate reel_no based on year
            if current_year == "25":
                # Year 25: must be in range 8000-9000
                if not (8000 <= reel_no <= 9000):
                    raise ValueError(f"For year 25, reel number must be between 8000-9000. Got: {reel_no}")
            else:
                # Year 26+: must be in range 0-1000
                if not (0 <= reel_no <= 1000):
                    raise ValueError(f"For year {current_year}, reel number must be between 0-1000. Got: {reel_no}")

            # Format as CR_{reel_no:05d}-{year}
            barcode_id = f"CR_{reel_no:05d}-{current_year}"

            # Check if barcode already exists
            existing = db.query(models.ManualCutRoll).filter(
                models.ManualCutRoll.barcode_id == barcode_id
            ).first()

            if existing:
                raise ValueError(f"Barcode {barcode_id} already exists for reel number {reel_no}")

            logger.info(f"Generated manual cut roll barcode: {barcode_id} (reel_no: {reel_no})")
            return barcode_id

        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Error generating manual cut roll barcode: {e}")
            raise

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