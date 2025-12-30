from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import Dict
from datetime import datetime
from zoneinfo import ZoneInfo
import logging


logger = logging.getLogger(__name__)

class FrontendIDGenerator:
    """
    Service for generating human-readable frontend IDs for all models.
    Uses year-based sequential format with automatic counter reset.

    Format: PREFIX-00001-25 (where 25 is the year)
    Counter resets to 00001 on January 1st of each year.
    Year suffix updates automatically based on current date.
    """
    
    # ID Patterns for each model - year-based format with annual counter reset
    ID_PATTERNS: Dict[str, Dict[str, str]] = {
        "client_master": {
            "prefix": "CL",
            "column_name": "frontend_id",
            "description": "Client Master IDs (CL-00001, CL-00002, etc.)",
            "no_year_suffix": True
        },
        "user_master": {
            "prefix": "USR",
            "column_name": "frontend_id",
            "description": "User Master IDs (USR-00001, USR-00002, etc.)",
            "no_year_suffix": True
        },
        "paper_master": {
            "prefix": "PAP",
            "column_name": "frontend_id",
            "description": "Paper Master IDs (PAP-00001, PAP-00002, etc.)",
            "no_year_suffix": True
        },
        "manual_cut_roll": {
            "prefix": "CLR",
            "column_name": "frontend_id",
            "description": "Manual Cut Roll IDs (CLR-00001-25, CLR-00002-25, etc.)"
        },
        "order_master": {
            "prefix": "ORD",
            "column_name": "frontend_id",
            "description": "Order Master IDs (ORD-00001-25, ORD-00002-25, etc.)"
        },
        "order_item": {
            "prefix": "ORI",
            "column_name": "frontend_id",
            "description": "Order Item IDs (ORI-00001-25, ORI-00002-25, etc.)"
        },
        "pending_order_master": {
            "prefix": "POM",
            "column_name": "frontend_id",
            "description": "Pending Order Master IDs (POM-00001-25, POM-00002-25, etc.)"
        },
        "pending_order_item": {
            "prefix": "POI",
            "column_name": "frontend_id",
            "description": "Pending Order Item IDs (POI-00001-25, POI-00002-25, etc.)"
        },
        "inventory_master": {
            "prefix": "INV",
            "column_name": "frontend_id",
            "description": "Inventory Master IDs (INV-00001-25, INV-00002-25, etc.)"
        },
        "plan_master": {
            "prefix": "PLN",
            "column_name": "frontend_id",
            "description": "Plan Master IDs (PLN-00001-25, PLN-00002-25, etc.)"
        },
        "production_order_master": {
            "prefix": "PRO",
            "column_name": "frontend_id",
            "description": "Production Order Master IDs (PRO-00001-25, PRO-00002-25, etc.)"
        },
        "plan_order_link": {
            "prefix": "POL",
            "column_name": "frontend_id",
            "description": "Plan Order Link IDs (POL-00001-25, POL-00002-25, etc.)"
        },
        "plan_inventory_link": {
            "prefix": "PIL",
            "column_name": "frontend_id",
            "description": "Plan Inventory Link IDs (PIL-00001-25, PIL-00002-25, etc.)"
        },
        "dispatch_record": {
            "prefix": "DSP",
            "column_name": "frontend_id",
            "description": "Dispatch Record IDs (DSP-00001-25, DSP-00002-25, etc.)"
        },
        "dispatch_item": {
            "prefix": "DSI",
            "column_name": "frontend_id",
            "description": "Dispatch Item IDs (DSI-00001-25, DSI-00002-25, etc.)"
        },
        "wastage_inventory": {
            "prefix": "WS",
            "column_name": "frontend_id",
            "description": "Wastage Inventory IDs (WS-00001-25, WS-00002-25, etc.)"
        },
        "past_dispatch_record": {
            "prefix": "PDR",
            "column_name": "frontend_id",
            "description": "Past Dispatch Record IDs (PDR-00001-25, PDR-00002-25, etc.)"
        },
        "inward_challan": {
            "prefix": "",
            "column_name": "serial_number",
            "description": "Inward Challan Serial Numbers (00001-25, 00002-25, etc.)",
            "serial_only": True
        },
        "outward_challan": {
            "prefix": "",
            "column_name": "serial_number",
            "description": "Outward Challan Serial Numbers (00001-25, 00002-25, etc.)",
            "serial_only": True
        },
        "order_edit_log": {
            "prefix": "OEL",
            "column_name": "frontend_id",
            "description": "Order Edit Log IDs (OEL-00001-25, OEL-00002-25, etc.)"
        },
        "payment_slip_bill": {
            "prefix": "BI",
            "column_name": "frontend_id",
            "table_name": "payment_slip_master",
            "description": "Bill Invoice Payment Slips (BI-00001-25, BI-00002-25, etc.)"
        },
        "payment_slip_cash": {
            "prefix": "CI",
            "column_name": "frontend_id",
            "table_name": "payment_slip_master",
            "description": "Cash Invoice Payment Slips (CI-00001-25, CI-00002-25, etc.)"
        }
    }
    
    @classmethod
    def generate_frontend_id(cls, table_name: str, db: Session) -> str:
        """
        Generate a human-readable frontend ID with year suffix and annual counter reset.

        Args:
            table_name: The database table name
            db: SQLAlchemy database session

        Returns:
            Generated frontend ID string (e.g., "ORD-00001-25")
            Counter resets to 00001 on January 1st each year.

        Raises:
            ValueError: If table_name is not supported
        """
        if table_name not in cls.ID_PATTERNS:
            raise ValueError(f"Unsupported table name: {table_name}. Supported tables: {list(cls.ID_PATTERNS.keys())}")

        config = cls.ID_PATTERNS[table_name]
        prefix = config["prefix"]
        column_name = config["column_name"]
        no_year_suffix = config.get("no_year_suffix", False)

        # Handle custom table name override (e.g., payment_slip_bill and payment_slip_cash both use payment_slip_master)
        actual_table_name = config.get("table_name", table_name)

        # ============================================================
        # For tables WITHOUT year suffix (client, user, paper)
        # ============================================================
        if no_year_suffix:
            try:
                # Simple sequential ID without year suffix: PREFIX-00001, PREFIX-00002, etc.
                pattern = f"{prefix}-%"

                query = text(f"""
                    SELECT {column_name}
                    FROM {actual_table_name}
                    WHERE {column_name} LIKE :pattern
                """)

                result = db.execute(query, {"pattern": pattern}).fetchall()

                # Extract counter values and find max
                max_counter = 0
                for row in result:
                    id_value = row[0]
                    if id_value:
                        try:
                            # Extract counter from format: PREFIX-00123
                            parts = id_value.split("-")
                            if len(parts) >= 2:
                                counter = int(parts[1])
                                max_counter = max(max_counter, counter)
                        except (ValueError, IndexError):
                            continue

                # Increment counter
                next_counter = max_counter + 1
                generated_id = f"{prefix}-{next_counter:05d}"

                logger.debug(f"Generated ID for {table_name}: {generated_id} (no year suffix, counter: {next_counter})")
                return generated_id

            except Exception as e:
                logger.error(f"Error generating frontend ID for {table_name}: {e}")
                raise

        # ============================================================
        # For tables WITH year suffix (orders, dispatch, etc.)
        # ============================================================
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

        try:
            # ============================================================
            # ACQUIRE APPLICATION LOCK to prevent concurrent ID generation
            # This prevents race conditions when multiple requests generate IDs simultaneously
            # ============================================================
            lock_resource = f"generate_id_{table_name}_{current_year}"
            acquire_lock = text("""
                DECLARE @result INT;
                EXEC @result = sp_getapplock
                    @Resource = :resource,
                    @LockMode = 'Exclusive',
                    @LockOwner = 'Transaction',
                    @LockTimeout = 10000;
                SELECT @result as lock_result;
            """)

            lock_result = db.execute(acquire_lock, {"resource": lock_resource}).scalar()

            if lock_result < 0:
                logger.error(f"Failed to acquire lock for {table_name}: {lock_result}")
                raise Exception(f"Could not acquire database lock for ID generation (code: {lock_result})")

            logger.debug(f"Acquired application lock: {lock_resource}")
            # ============================================================

            # Query to find the highest counter for the current year
            # Pattern: PREFIX-XXXXX-YY or XXXXX-YY (for serial_only)
            if config.get("serial_only", False):
                pattern = f"%-{current_year}"
            else:
                pattern = f"{prefix}-%-{current_year}"

            # Get all IDs matching the year pattern with READ UNCOMMITTED to see pending changes
            query = text(f"""
                SELECT {column_name}
                FROM {actual_table_name} WITH (READUNCOMMITTED)
                WHERE {column_name} LIKE :pattern
            """)

            result = db.execute(query, {"pattern": pattern}).fetchall()

            # Extract counter values and find max
            max_counter = 0
            for row in result:
                id_value = row[0]
                if id_value:
                    try:
                        # Extract counter from format: PREFIX-00123-25 or 00123-25
                        parts = id_value.split("-")
                        if config.get("serial_only", False):
                            # Format: 00123-25
                            if len(parts) >= 2:
                                counter = int(parts[-2])  # Second to last part
                                max_counter = max(max_counter, counter)
                        else:
                            # Format: PREFIX-00123-25
                            if len(parts) >= 3:
                                counter = int(parts[-2])  # Second to last part
                                max_counter = max(max_counter, counter)
                    except (ValueError, IndexError):
                        continue

            # Increment counter
            next_counter = max_counter + 1

            # Handle serial-only format for challan tables
            if config.get("serial_only", False):
                # Format: 00001-25
                generated_id = f"{next_counter:05d}-{current_year}"
            else:
                # Format: PREFIX-00001-25
                generated_id = f"{prefix}-{next_counter:05d}-{current_year}"

            logger.debug(f"Generated ID for {table_name}: {generated_id} (year: {current_year}, counter: {next_counter})")
            return generated_id

        except Exception as e:
            logger.error(f"Error generating frontend ID for {table_name}: {e}")
            raise
    
    
    @classmethod
    def get_all_patterns(cls) -> Dict[str, Dict[str, str]]:
        """
        Get all available ID patterns for documentation/reference.
        
        Returns:
            Dictionary of all table patterns and their configurations
        """
        return cls.ID_PATTERNS.copy()
    
    @classmethod
    def validate_frontend_id(cls, table_name: str, frontend_id: str) -> bool:
        """
        Validate if a frontend ID matches the expected pattern for a table.

        Args:
            table_name: The database table name
            frontend_id: The frontend ID to validate (e.g., "ORD-00001-25" or "CL-00001")

        Returns:
            True if valid, False otherwise
        """
        if table_name not in cls.ID_PATTERNS:
            return False

        config = cls.ID_PATTERNS[table_name]
        prefix = config["prefix"]

        try:
            # Handle tables without year suffix (client, user, paper)
            if config.get("no_year_suffix", False):
                # Format: PREFIX-00001 (prefix-counter)
                if not frontend_id.startswith(f"{prefix}-"):
                    return False

                parts = frontend_id.split("-")
                if len(parts) != 2:
                    return False

                counter = int(parts[1])

                # Check counter is exactly 5 digits and positive
                return len(parts[1]) == 5 and counter > 0

            # Handle serial-only format for challan tables
            if config.get("serial_only", False):
                # Format: 00001-25 (counter-year)
                parts = frontend_id.split("-")
                if len(parts) != 2:
                    return False

                counter = int(parts[0])
                year = parts[1]

                # Check counter is 5 digits and year is 2 digits
                return len(parts[0]) == 5 and counter > 0 and len(year) == 2 and year.isdigit()
            else:
                # Standard format: PREFIX-00001-25 (prefix-counter-year)
                if not frontend_id.startswith(f"{prefix}-"):
                    return False

                parts = frontend_id.split("-")
                if len(parts) != 3:
                    return False

                counter = int(parts[1])
                year = parts[2]

                # Check counter is exactly 5 digits, positive, and year is 2 digits
                return len(parts[1]) == 5 and counter > 0 and len(year) == 2 and year.isdigit()
        except (ValueError, IndexError):
            return False
    
    @classmethod
    def get_id_status(cls, db: Session) -> Dict[str, Dict]:
        """
        Get the current status of all ID patterns for the current year.
        Useful for debugging and monitoring.

        Returns:
            Dictionary with table names and their current counter values for this year
        """
        status = {}
        current_year = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")

        for table_name, config in cls.ID_PATTERNS.items():
            try:
                column_name = config["column_name"]
                prefix = config["prefix"]
                no_year_suffix = config.get("no_year_suffix", False)

                # Handle custom table name override (e.g., payment_slip_bill and payment_slip_cash both use payment_slip_master)
                actual_table_name = config.get("table_name", table_name)

                # Handle tables without year suffix (client, user, paper)
                if no_year_suffix:
                    pattern = f"{prefix}-%"

                    query = text(f"""
                        SELECT {column_name}
                        FROM {actual_table_name}
                        WHERE {column_name} LIKE :pattern
                    """)

                    result = db.execute(query, {"pattern": pattern}).fetchall()

                    max_counter = 0
                    for row in result:
                        id_value = row[0]
                        if id_value:
                            try:
                                parts = id_value.split("-")
                                if len(parts) >= 2:
                                    counter = int(parts[1])
                                    max_counter = max(max_counter, counter)
                            except (ValueError, IndexError):
                                continue

                    status[table_name] = {
                        "prefix": prefix,
                        "current_counter": max_counter,
                        "next_id_will_be": f"{prefix}-{max_counter + 1:05d}",
                        "total": len(result),
                        "note": "No year suffix - simple sequential format"
                    }
                    continue

                # Build pattern for current year (for tables with year suffix)
                if config.get("serial_only", False):
                    pattern = f"%-{current_year}"
                else:
                    pattern = f"{prefix}-%-{current_year}"

                # Get all IDs for current year
                query = text(f"""
                    SELECT {column_name}
                    FROM {actual_table_name}
                    WHERE {column_name} LIKE :pattern
                """)

                result = db.execute(query, {"pattern": pattern}).fetchall()

                # Extract counter values and find max
                max_counter = 0
                for row in result:
                    id_value = row[0]
                    if id_value:
                        try:
                            parts = id_value.split("-")
                            if config.get("serial_only", False):
                                if len(parts) >= 2:
                                    counter = int(parts[-2])
                                    max_counter = max(max_counter, counter)
                            else:
                                if len(parts) >= 3:
                                    counter = int(parts[-2])
                                    max_counter = max(max_counter, counter)
                        except (ValueError, IndexError):
                            continue

                status[table_name] = {
                    "prefix": prefix,
                    "current_year": current_year,
                    "current_counter": max_counter,
                    "next_id_will_be": f"{prefix}-{max_counter + 1:05d}-{current_year}" if not config.get("serial_only", False) else f"{max_counter + 1:05d}-{current_year}",
                    "total_this_year": len(result)
                }

            except Exception as e:
                status[table_name] = {
                    "prefix": config["prefix"],
                    "error": str(e)
                }

        return status