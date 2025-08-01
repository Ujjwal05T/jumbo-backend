from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Callable
import threading
import logging


logger = logging.getLogger(__name__)

class FrontendIDGenerator:
    """
    Service for generating human-readable frontend IDs for all models.
    Each model has a unique prefix and pattern.
    
    Thread-safe implementation to prevent duplicate ID generation in concurrent scenarios.
    """
    
    # Thread lock to ensure atomic ID generation
    _id_generation_lock = threading.Lock()
    
    # In-memory counter cache to avoid repeated database queries
    _counter_cache = {}
    
    # ID Patterns for each model
    ID_PATTERNS: Dict[str, Dict[str, str]] = {
        "client_master": {
            "prefix": "CL",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Client Master IDs (CL-001, CL-002, etc.)"
        },
        "user_master": {
            "prefix": "USR", 
            "pattern": "{prefix}-{counter:03d}",
            "description": "User Master IDs (USR-001, USR-002, etc.)"
        },
        "paper_master": {
            "prefix": "PAP",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Paper Master IDs (PAP-001, PAP-002, etc.)"
        },
        "order_master": {
            "prefix": "ORD",
            "pattern": "{prefix}-{year}-{counter:03d}",
            "description": "Order Master IDs (ORD-2025-001, etc.)",
            "uses_year": True
        },
        "order_item": {
            "prefix": "ORI",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Order Item IDs (ORI-001, ORI-002, etc.)"
        },
        "pending_order_master": {
            "prefix": "POM",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Pending Order Master IDs (POM-001, POM-002, etc.)"
        },
        "pending_order_item": {
            "prefix": "POI",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Pending Order Item IDs (POI-001, POI-002, etc.)"
        },
        "inventory_master": {
            "prefix": "INV",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Inventory Master IDs (INV-001, INV-002, etc.)"
        },
        "plan_master": {
            "prefix": "PLN",
            "pattern": "{prefix}-{year}-{counter:03d}",
            "description": "Plan Master IDs (PLN-2025-001, etc.)",
            "uses_year": True
        },
        "production_order_master": {
            "prefix": "PRO",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Production Order Master IDs (PRO-001, PRO-002, etc.)"
        },
        "plan_order_link": {
            "prefix": "POL",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Plan Order Link IDs (POL-001, POL-002, etc.)"
        },
        "plan_inventory_link": {
            "prefix": "PIL",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Plan Inventory Link IDs (PIL-001, PIL-002, etc.)"
        },
        "cut_roll_production": {
            "prefix": "CRP",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Cut Roll Production IDs (CRP-001, CRP-002, etc.)"
        },
        "dispatch_record": {
            "prefix": "DSP",
            "pattern": "{prefix}-{year}-{counter:03d}",
            "description": "Dispatch Record IDs (DSP-2025-001, etc.)",
            "uses_year": True
        },
        "dispatch_item": {
            "prefix": "DSI",
            "pattern": "{prefix}-{counter:03d}",
            "description": "Dispatch Item IDs (DSI-001, DSI-002, etc.)"
        }
    }
    
    @classmethod
    def generate_frontend_id(cls, table_name: str, db: Session) -> str:
        """
        Generate a human-readable frontend ID for the given table.
        Thread-safe implementation to prevent duplicate IDs in concurrent scenarios.
        
        Args:
            table_name: The database table name
            db: SQLAlchemy database session
            
        Returns:
            Generated frontend ID string
            
        Raises:
            ValueError: If table_name is not supported
        """
        # Use thread lock to ensure atomic ID generation
        with cls._id_generation_lock:
            logger.debug(f"Acquiring lock for ID generation: {table_name}")
            
            if table_name not in cls.ID_PATTERNS:
                raise ValueError(f"Unsupported table name: {table_name}")
            
            config = cls.ID_PATTERNS[table_name]
            prefix = config["prefix"]
            pattern = config["pattern"]
            uses_year = config.get("uses_year", False)
            
            # Get current year if needed
            year = datetime.now().year if uses_year else None
            
            # Get next counter value
            counter = cls._get_next_counter(table_name, db, year)
            
            # Generate the ID
            if uses_year:
                generated_id = pattern.format(prefix=prefix, year=year, counter=counter)
            else:
                generated_id = pattern.format(prefix=prefix, counter=counter)
            
            logger.debug(f"Generated ID for {table_name}: {generated_id}")
            return generated_id
    
    @classmethod
    def _get_next_counter(cls, table_name: str, db: Session, year: int = None) -> int:
        """
        Get the next counter value for the given table.
        Uses database queries to find the highest existing counter.
        
        Args:
            table_name: The database table name
            db: SQLAlchemy database session
            year: Year filter for year-based IDs
            
        Returns:
            Next counter value (starting from 1)
        """
        config = cls.ID_PATTERNS[table_name]
        prefix = config["prefix"]
        uses_year = config.get("uses_year", False)
        
        try:
            # Create cache key
            cache_key = f"{table_name}_{year}" if uses_year and year else table_name
            
            # Check if we have a cached counter
            if cache_key in cls._counter_cache:
                # Use cached counter and increment it
                cls._counter_cache[cache_key] += 1
                next_counter = cls._counter_cache[cache_key]
                logger.debug(f"Using cached counter for {cache_key}: {next_counter}")
                return next_counter
            
            # No cache, query database
            if uses_year and year:
                # For year-based IDs, find max counter for this year
                pattern_prefix = f"{prefix}-{year}-"
                query = text(f"""
                    SELECT MAX(CAST(RIGHT(frontend_id, 3) AS INT)) as max_counter 
                    FROM {table_name} WITH (UPDLOCK)
                    WHERE frontend_id LIKE :pattern_prefix AND frontend_id IS NOT NULL
                """)
                result = db.execute(query, {"pattern_prefix": f"{pattern_prefix}%"}).scalar()
                logger.debug(f"Year-based counter query for {table_name} ({year}): max_counter = {result}")
            else:
                # For simple counters, find max counter overall
                pattern_prefix = f"{prefix}-"
                query = text(f"""
                    SELECT MAX(CAST(RIGHT(frontend_id, 3) AS INT)) as max_counter 
                    FROM {table_name} WITH (UPDLOCK)
                    WHERE frontend_id LIKE :pattern_prefix AND frontend_id IS NOT NULL
                """)
                result = db.execute(query, {"pattern_prefix": f"{pattern_prefix}%"}).scalar()
                logger.debug(f"Simple counter query for {table_name}: max_counter = {result}")
            
            # Calculate next counter and cache it
            next_counter = (result or 0) + 1
            cls._counter_cache[cache_key] = next_counter
            logger.debug(f"Cached new counter for {cache_key}: {next_counter}")
            return next_counter
            
        except Exception as e:
            logger.error(f"Error getting next counter for {table_name}: {e}")
            raise
    
    @classmethod
    def clear_counter_cache(cls, table_name: str = None):
        """
        Clear the counter cache for a specific table or all tables.
        Useful for testing or when database state changes externally.
        
        Args:
            table_name: Optional table name to clear. If None, clears all cache.
        """
        with cls._id_generation_lock:
            if table_name:
                # Clear specific table entries (including year-based variants)
                keys_to_remove = [key for key in cls._counter_cache.keys() if key.startswith(table_name)]
                for key in keys_to_remove:
                    del cls._counter_cache[key]
                logger.info(f"Cleared counter cache for {table_name}")
            else:
                # Clear all cache
                cls._counter_cache.clear()
                logger.info("Cleared all counter cache")
    
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
        uses_year = config.get("uses_year", False)
        
        if not frontend_id.startswith(f"{prefix}-"):
            return False
        
        if uses_year:
            # Expected format: PREFIX-YYYY-NNN
            parts = frontend_id.split("-")
            if len(parts) != 3:
                return False
            try:
                year = int(parts[1])
                counter = int(parts[2])
                return 2020 <= year <= 2050 and counter > 0
            except ValueError:
                return False
        else:
            # Expected format: PREFIX-NNN
            parts = frontend_id.split("-")
            if len(parts) != 2:
                return False
            try:
                counter = int(parts[1])
                return counter > 0
            except ValueError:
                return False