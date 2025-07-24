from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import router after logging is configured
from .api import router
from . import database, init_db

app = FastAPI(
    title="Paper Roll Management System",
    description="Simple API for paper roll management",
)

# Set up CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(router, prefix="/api")

@app.on_event("startup")
async def startup_event():
    """
    Initialize the database on startup.
    """
    logger.info("Initializing database...")
    try:
        # Create tables if they don't exist
        if database.engine is not None:
            from . import models
            models.Base.metadata.create_all(bind=database.engine)
            logger.info("Database tables created successfully")
            
            # Initialize default data
            init_db.init_db()
    except SQLAlchemyError as e:
        logger.error(f"Failed to initialize database: {e}")

@app.get("/")
async def root():
    return {"message": "Paper Roll Management System API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}