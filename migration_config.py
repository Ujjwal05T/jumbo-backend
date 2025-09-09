"""
Migration Configuration
======================

Configuration settings for frontend ID migration.
Update this file with your database connection details.
"""

import os
from typing import Optional

class MigrationConfig:
    """Configuration for database migration."""
    
    # Database connection settings
    # Option 1: Direct connection string
    DATABASE_URL: Optional[str] = r"mssql+pyodbc:///?odbc_connect=DRIVER={ODBC Driver 17 for SQL Server};SERVER=157.20.215.187,1433;DATABASE=JumboRollDB;UID=Indus;PWD=Param@99811;Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30"
    
    # Migration settings
    BATCH_SIZE: int = 100  # Process records in batches of this size
    DRY_RUN_FIRST: bool = True  # Always run dry run before actual migration
    CREATE_BACKUP_PROMPT: bool = True  # Prompt user to confirm backup exists
    
    # Logging settings
    LOG_LEVEL: str = "INFO"
    LOG_TO_FILE: bool = True
    LOG_TO_CONSOLE: bool = True
    
    @classmethod
    def get_connection_string(cls) -> str:
        """Get the database connection string."""
        
        # Use direct DATABASE_URL if provided
        if cls.DATABASE_URL:
            return cls.DATABASE_URL
        
        # Check environment variables first
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            return db_url
        
        # Build from individual components
        server = os.getenv("DB_SERVER", cls.DB_SERVER)
        database = os.getenv("DB_NAME", cls.DB_NAME)
        username = os.getenv("DB_USERNAME", cls.DB_USERNAME)
        password = os.getenv("DB_PASSWORD", cls.DB_PASSWORD)
        driver = os.getenv("DB_DRIVER", cls.DB_DRIVER)
        
        return f"mssql+pyodbc://{username}:{password}@{server}/{database}?driver={driver}"
    
    @classmethod
    def validate_config(cls) -> bool:
        """Validate that configuration is properly set."""
        connection_string = cls.get_connection_string()
        
        # Check for placeholder values (but allow localhost for local development)
        if any(placeholder in connection_string for placeholder in 
               ["your_username", "your_password", "username:password@server"]):
            print("❌ Please update migration_config.py with your actual database details")
            return False
        
        return True

# Example usage patterns:

# Option 1: Set direct connection string
# MigrationConfig.DATABASE_URL = "mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server"

# Option 2: Set individual components
# MigrationConfig.DB_SERVER = "your-sql-server.database.windows.net"
# MigrationConfig.DB_NAME = "JumboReelApp"
# MigrationConfig.DB_USERNAME = "sa"
# MigrationConfig.DB_PASSWORD = "YourPassword123"

# Option 3: Use environment variables (recommended for production)
# Set these in your environment:
# export DATABASE_URL="mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server"
# Or individual components:
# export DB_SERVER="your-server"
# export DB_NAME="JumboReelApp"
# export DB_USERNAME="username"
# export DB_PASSWORD="password"