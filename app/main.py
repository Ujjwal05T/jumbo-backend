from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import router after logging is configured
from .api_router import api_router
from . import database, init_db

app = FastAPI(
    title="Paper Roll Management System",
    description="Simple API for paper roll management",
)

# Global exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"❌ VALIDATION ERROR on {request.method} {request.url}: {exc}")
    logger.error(f"❌ VALIDATION DETAILS: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": f"Validation error: {exc.errors()}"}
    )

# Set up CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","http://192.168.1.96:3000","https://satguru-test.vercel.app","https://satguru-reels.vercel.app","https://522c58a6cd19.ngrok-free.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router)

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
    return {"message": "Paper Roll Management System API is Live"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}