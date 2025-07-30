from fastapi import APIRouter
from .api import clients, users, papers, orders, inventory, plans, workflow, pending_orders, auth, cutting, qr_codes, cut_rolls

# Create main API router
api_router = APIRouter()

# Include all sub-routers
api_router.include_router(clients.router, prefix="/api", tags=["Clients"])
api_router.include_router(users.router, prefix="/api", tags=["Users"]) 
api_router.include_router(papers.router, prefix="/api", tags=["Papers"])
api_router.include_router(orders.router, prefix="/api", tags=["Orders"])
api_router.include_router(inventory.router, prefix="/api", tags=["Inventory"])
api_router.include_router(plans.router, prefix="/api", tags=["Plans"])
api_router.include_router(workflow.router, prefix="/api", tags=["Workflow"])
api_router.include_router(pending_orders.router, prefix="/api", tags=["Pending Orders"])

# New endpoint modules
api_router.include_router(auth.router, prefix="/api", tags=["Authentication"])
api_router.include_router(cutting.router, prefix="/api", tags=["Cutting Algorithm"])
api_router.include_router(qr_codes.router, prefix="/api", tags=["QR Code Management"])
api_router.include_router(cut_rolls.router, prefix="/api", tags=["Cut Roll Production"])