import os
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get database URL from environment variable
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "mssql+pyodbc:///?odbc_connect=DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost\\SQLEXPRESS;DATABASE=JumboRollDB;Trusted_Connection=yes"
)

logger.info(f"Using database URL: {DATABASE_URL}")

try:
    # Create engine with optimized connection pooling settings
    # For ODBC connection strings, we need to be more careful with connection args
    if "odbc_connect=" in DATABASE_URL:
        # Using ODBC connection string format
        engine = create_engine(
            DATABASE_URL,
            pool_size=8,          # Compromise: some savings, decent concurrency
            max_overflow=2,       # Allow 2 extra connections for bursts
            pool_pre_ping=True,
            pool_recycle=1800,    # Recycle every 30 min
            echo=False  # Set to True for SQL debugging
        )
    else:
        # Using standard SQLAlchemy format
        engine = create_engine(
            DATABASE_URL,
            pool_size=8,          # Compromise: some savings, decent concurrency
            max_overflow=2,       # Allow 2 extra connections for bursts
            pool_pre_ping=True,
            pool_recycle=1800,    # Recycle every 30 min
            connect_args={"timeout": 30}
        )
    
    # Test connection
    with engine.connect() as connection:
        logger.info("Database connection successful!")
        
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
    
except SQLAlchemyError as e:
    logger.error(f"Database connection error: {e}")
    logger.error("Please check your database configuration in .env file")
    logger.error("The application will continue but database operations will fail")
    
    # Create dummy engine and session for app to start
    # This allows the app to start even if DB is not available
    engine = None
    SessionLocal = None
    Base = declarative_base()

# Dependency to get DB session
def get_db():
    if SessionLocal is None:
        raise SQLAlchemyError("Database connection not available")
        
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()