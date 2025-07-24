"""
Initialize the database with default data.
This script creates an admin user if one doesn't exist.
"""
from sqlalchemy.orm import Session
import logging
from . import models, crud, schemas, database

# Set up logging
logger = logging.getLogger(__name__)

def init_admin_user(db: Session):
    """
    Create an admin user if one doesn't exist.
    """
    admin_username = "admin"
    admin = crud.get_user_by_username(db, admin_username)
    
    if admin:
        logger.info(f"Admin user '{admin_username}' already exists")
        return admin
    
    logger.info(f"Creating admin user '{admin_username}'")
    admin_user = schemas.UserMasterCreate(
        name="Administrator",
        username=admin_username,
        password="admin123",  # Simple password for internal use
        role="admin"
    )
    
    return crud.create_user(db, admin_user)

def init_db():
    """
    Initialize the database with default data.
    """
    if database.SessionLocal is None:
        logger.error("Database connection not available")
        return
    
    db = database.SessionLocal()
    try:
        # Create admin user
        admin = init_admin_user(db)
        logger.info(f"Database initialized with admin user: {admin.username}")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
    finally:
        db.close()