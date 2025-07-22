from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import router

app = FastAPI(
    title="Paper Roll Management System",
    description="Simple API for paper roll management",
)

# Set up CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Paper Roll Management System API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}