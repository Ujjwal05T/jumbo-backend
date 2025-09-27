from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict
import logging


logger = logging.getLogger(__name__)

class FrontendIDGenerator:
    """
    Service for generating human-readable frontend IDs for all models.
    Uses SQL Server sequences for thread-safe, high-performance ID generation.
    
    All IDs now use simple sequential format: PREFIX-00001, PREFIX-00002, etc.
    No more year/month based IDs - everything is sequential for consistency.
    """
    
    # ID Patterns for each model - now all use simple sequential format with sequences
    ID_PATTERNS: Dict[str, Dict[str, str]] = {
        "client_master": {
            "prefix": "CL",
            "sequence_name": "client_master_seq",
            "description": "Client Master IDs (CL-00001, CL-00002, etc.)"
        },
        "user_master": {
            "prefix": "USR", 
            "sequence_name": "user_master_seq",
            "description": "User Master IDs (USR-00001, USR-00002, etc.)"
        },
        "paper_master": {
            "prefix": "PAP",
            "sequence_name": "paper_master_seq",
            "description": "Paper Master IDs (PAP-00001, PAP-00002, etc.)"
        },
        "order_master": {
            "prefix": "ORD",
            "sequence_name": "order_master_seq",
            "description": "Order Master IDs (ORD-00001, ORD-00002, etc.)"
        },
        "order_item": {
            "prefix": "ORI",
            "sequence_name": "order_item_seq",
            "description": "Order Item IDs (ORI-00001, ORI-00002, etc.)"
        },
        "pending_order_master": {
            "prefix": "POM",
            "sequence_name": "pending_order_master_seq",
            "description": "Pending Order Master IDs (POM-00001, POM-00002, etc.)"
        },
        "pending_order_item": {
            "prefix": "POI",
            "sequence_name": "pending_order_item_seq",
            "description": "Pending Order Item IDs (POI-00001, POI-00002, etc.)"
        },
        "inventory_master": {
            "prefix": "INV",
            "sequence_name": "inventory_master_seq",
            "description": "Inventory Master IDs (INV-00001, INV-00002, etc.)"
        },
        "plan_master": {
            "prefix": "PLN",
            "sequence_name": "plan_master_seq",
            "description": "Plan Master IDs (PLN-00001, PLN-00002, etc.)"
        },
        "production_order_master": {
            "prefix": "PRO",
            "sequence_name": "production_order_master_seq",
            "description": "Production Order Master IDs (PRO-00001, PRO-00002, etc.)"
        },
        "plan_order_link": {
            "prefix": "POL",
            "sequence_name": "plan_order_link_seq",
            "description": "Plan Order Link IDs (POL-00001, POL-00002, etc.)"
        },
        "plan_inventory_link": {
            "prefix": "PIL",
            "sequence_name": "plan_inventory_link_seq",
            "description": "Plan Inventory Link IDs (PIL-00001, PIL-00002, etc.)"
        },
        "dispatch_record": {
            "prefix": "DSP",
            "sequence_name": "dispatch_record_seq",
            "description": "Dispatch Record IDs (DSP-00001, DSP-00002, etc.)"
        },
        "dispatch_item": {
            "prefix": "DSI",
            "sequence_name": "dispatch_item_seq",
            "description": "Dispatch Item IDs (DSI-00001, DSI-00002, etc.)"
        },
        "wastage_inventory": {
            "prefix": "WS",
            "sequence_name": "wastage_inventory_seq",
            "description": "Wastage Inventory IDs (WS-00001, WS-00002, etc.)"
        },
        "past_dispatch_record": {
            "prefix": "PDR",
            "sequence_name": "past_dispatch_record_seq",
            "description": "Past Dispatch Record IDs (PDR-00001, PDR-00002, etc.)"
        },
        "inward_challan": {
            "prefix": "",
            "sequence_name": "inward_challan_serial_seq",
            "description": "Inward Challan Serial Numbers (00001, 00002, etc.)",
            "serial_only": True
        },
        "outward_challan": {
            "prefix": "",
            "sequence_name": "outward_challan_serial_seq",
            "description": "Outward Challan Serial Numbers (00001, 00002, etc.)",
            "serial_only": True
        },
        "order_edit_log": {
            "prefix": "OEL",
            "sequence_name": "order_edit_log_seq",
            "description": "Order Edit Log IDs (OEL-00001, OEL-00002, etc.)"
        }
    }
    
    @classmethod
    def generate_frontend_id(cls, table_name: str, db: Session) -> str:
        """
        Generate a human-readable frontend ID using SQL Server sequences.
        
        Args:
            table_name: The database table name
            db: SQLAlchemy database session
            
        Returns:
            Generated frontend ID string (e.g., "ORD-00001")
            
        Raises:
            ValueError: If table_name is not supported
        """
        if table_name not in cls.ID_PATTERNS:
            raise ValueError(f"Unsupported table name: {table_name}. Supported tables: {list(cls.ID_PATTERNS.keys())}")
        
        config = cls.ID_PATTERNS[table_name]
        prefix = config["prefix"]
        sequence_name = config["sequence_name"]
        
        try:
            # Get next value from sequence - this is atomic and thread-safe
            query = text(f"SELECT NEXT VALUE FOR {sequence_name}")
            counter = db.execute(query).scalar()

            # Handle serial-only format for challan tables
            if config.get("serial_only", False):
                # Just the 5-digit number without prefix
                generated_id = f"{counter:05d}"
            else:
                # Format the ID with exactly 5 digits and prefix
                generated_id = f"{prefix}-{counter:05d}"

            logger.debug(f"Generated ID for {table_name}: {generated_id} (sequence: {sequence_name}, counter: {counter})")
            return generated_id
            
        except Exception as e:
            logger.error(f"Error generating frontend ID for {table_name}: {e}")
            logger.error(f"Make sure sequence '{sequence_name}' exists in the database")
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
            frontend_id: The frontend ID to validate

        Returns:
            True if valid, False otherwise
        """
        if table_name not in cls.ID_PATTERNS:
            return False

        config = cls.ID_PATTERNS[table_name]
        prefix = config["prefix"]

        # Handle serial-only format for challan tables
        if config.get("serial_only", False):
            # Should be exactly 5 digits only
            try:
                counter = int(frontend_id)
                return len(frontend_id) == 5 and counter > 0
            except ValueError:
                return False
        else:
            # Standard format: PREFIX-NNNNN (exactly 5 digits)
            if not frontend_id.startswith(f"{prefix}-"):
                return False

            parts = frontend_id.split("-")
            if len(parts) != 2:
                return False

            try:
                counter = int(parts[1])
                # Check if it's exactly 5 digits and positive
                return len(parts[1]) == 5 and counter > 0
            except ValueError:
                return False
    
    @classmethod
    def get_sequence_status(cls, db: Session) -> Dict[str, Dict]:
        """
        Get the current status of all sequences.
        Useful for debugging and monitoring.
        
        Returns:
            Dictionary with sequence names and their current values
        """
        status = {}
        
        for table_name, config in cls.ID_PATTERNS.items():
            sequence_name = config["sequence_name"]
            try:
                # Get current sequence info
                query = text("""
                    SELECT 
                        current_value,
                        start_value,
                        increment
                    FROM sys.sequences 
                    WHERE name = :seq_name
                """)
                result = db.execute(query, {"seq_name": sequence_name}).fetchone()
                
                if result:
                    status[sequence_name] = {
                        "table": table_name,
                        "prefix": config["prefix"],
                        "current_value": result.current_value,
                        "start_value": result.start_value,
                        "increment": result.increment,
                        "exists": True
                    }
                else:
                    status[sequence_name] = {
                        "table": table_name,
                        "prefix": config["prefix"],
                        "exists": False,
                        "error": "Sequence not found"
                    }
                    
            except Exception as e:
                status[sequence_name] = {
                    "table": table_name,
                    "prefix": config["prefix"],
                    "exists": False,
                    "error": str(e)
                }
        
        return status