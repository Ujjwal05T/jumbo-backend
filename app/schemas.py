from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum
from uuid import UUID

# ============================================================================
# STATUS ENUMS - Validation for status fields
# ============================================================================

class OrderStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class InventoryStatus(str, Enum):
    AVAILABLE = "available"
    ALLOCATED = "allocated"
    CUTTING = "cutting"
    USED = "used"
    DAMAGED = "damaged"

class ProductionOrderStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PlanStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class PendingOrderStatus(str, Enum):
    PENDING = "pending"
    IN_PRODUCTION = "in_production"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"

class RollType(str, Enum):
    JUMBO = "jumbo"
    CUT = "cut"

class ClientStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"

class UserRole(str, Enum):
    SALES = "sales"
    PLANNER = "planner"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"

class PaperType(str, Enum):
    STANDARD = "standard"
    PREMIUM = "premium"
    RECYCLED = "recycled"
    SPECIALTY = "specialty"

class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

# ============================================================================
# MASTER SCHEMAS - Core reference data
# ============================================================================

# Client Master Schemas
class ClientMasterBase(BaseModel):
    company_name: str = Field(..., max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    status: ClientStatus = Field(default=ClientStatus.ACTIVE)

class ClientMasterCreate(ClientMasterBase):
    created_by_id: UUID

class ClientMasterUpdate(BaseModel):
    company_name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    status: Optional[ClientStatus] = None

class ClientMaster(ClientMasterBase):
    id: UUID
    created_by_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# User Master Schemas
class UserMasterBase(BaseModel):
    name: str = Field(..., max_length=255)
    username: str = Field(..., max_length=50)
    role: UserRole = Field(..., description="User role: sales, planner, supervisor, admin")
    contact: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=100)
    status: UserStatus = Field(default=UserStatus.ACTIVE)

class UserMasterCreate(UserMasterBase):
    password: str = Field(..., min_length=6)  # Plain password for hashing

class UserMasterLogin(BaseModel):
    username: str = Field(..., max_length=50)
    password: str = Field(..., min_length=6)

class UserMasterUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    role: Optional[UserRole] = None
    contact: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=100)
    status: Optional[UserStatus] = None

class UserMaster(UserMasterBase):
    id: UUID
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

# Paper Master Schemas
class PaperMasterBase(BaseModel):
    name: str = Field(..., max_length=255)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    thickness: Optional[float] = Field(None, gt=0)
    type: PaperType = Field(default=PaperType.STANDARD)
    status: ClientStatus = Field(default=ClientStatus.ACTIVE)  # Reusing ClientStatus for consistency

class PaperMasterCreate(PaperMasterBase):
    created_by_id: UUID

class PaperMasterUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    gsm: Optional[int] = Field(None, gt=0)
    bf: Optional[float] = Field(None, gt=0)
    shade: Optional[str] = Field(None, max_length=50)
    thickness: Optional[float] = Field(None, gt=0)
    type: Optional[PaperType] = None
    status: Optional[ClientStatus] = None

class PaperMaster(PaperMasterBase):
    id: UUID
    created_by_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# TRANSACTION SCHEMAS - Business operations
# ============================================================================

# Order Master Schemas
class OrderMasterBase(BaseModel):
    client_id: UUID
    paper_id: UUID
    width_inches: int = Field(..., gt=0)
    quantity_rolls: int = Field(..., gt=0)
    priority: Priority = Field(default=Priority.NORMAL)
    delivery_date: Optional[datetime] = None
    notes: Optional[str] = None

class OrderMasterCreate(OrderMasterBase):
    created_by_id: UUID

class OrderMasterUpdate(BaseModel):
    priority: Optional[Priority] = None
    delivery_date: Optional[datetime] = None
    notes: Optional[str] = None
    status: Optional[OrderStatus] = None

class OrderMaster(OrderMasterBase):
    id: UUID
    quantity_fulfilled: int
    status: OrderStatus
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    
    # Include related data
    client: Optional[ClientMaster] = None
    paper: Optional[PaperMaster] = None

    class Config:
        from_attributes = True

# Pending Order Master Schemas
class PendingOrderMasterBase(BaseModel):
    order_id: UUID
    paper_id: UUID
    width_inches: int = Field(..., gt=0)
    quantity_pending: int = Field(..., gt=0)
    reason: str = Field(..., max_length=100)

class PendingOrderMasterCreate(PendingOrderMasterBase):
    pass

class PendingOrderMasterUpdate(BaseModel):
    status: Optional[PendingOrderStatus] = None
    production_order_id: Optional[UUID] = None

class PendingOrderMaster(PendingOrderMasterBase):
    id: UUID
    status: PendingOrderStatus
    production_order_id: Optional[UUID] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    
    # Include related data
    original_order: Optional[OrderMaster] = None
    paper: Optional[PaperMaster] = None

    class Config:
        from_attributes = True

# Inventory Master Schemas
class InventoryMasterBase(BaseModel):
    paper_id: UUID
    width_inches: int = Field(..., gt=0)
    weight_kg: float = Field(..., gt=0)
    roll_type: RollType = Field(..., description="Roll type: jumbo or cut")
    location: Optional[str] = Field(None, max_length=100)
    qr_code: Optional[str] = Field(None, max_length=255)
    production_date: datetime = Field(default_factory=datetime.utcnow)

class InventoryMasterCreate(InventoryMasterBase):
    created_by_id: UUID

class InventoryMasterUpdate(BaseModel):
    location: Optional[str] = Field(None, max_length=100)
    status: Optional[InventoryStatus] = None
    allocated_to_order_id: Optional[UUID] = None

class InventoryMaster(InventoryMasterBase):
    id: UUID
    status: InventoryStatus
    allocated_to_order_id: Optional[UUID] = None
    created_by_id: UUID
    created_at: datetime
    
    # Include related data
    paper: Optional[PaperMaster] = None

    class Config:
        from_attributes = True

# Plan Master Schemas
class PlanMasterBase(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    cut_pattern: List[Dict[str, Any]] = Field(..., description="JSON array of cutting pattern")
    expected_waste_percentage: float = Field(..., ge=0, le=100)

class PlanMasterCreate(PlanMasterBase):
    created_by_id: UUID
    order_ids: List[UUID] = Field(..., min_items=1)
    inventory_ids: List[UUID] = Field(..., min_items=1)

class PlanMasterUpdate(BaseModel):
    status: Optional[PlanStatus] = None
    actual_waste_percentage: Optional[float] = Field(None, ge=0, le=100)

class PlanMaster(PlanMasterBase):
    id: UUID
    status: PlanStatus
    actual_waste_percentage: Optional[float] = None
    created_by_id: UUID
    created_at: datetime
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Production Order Master Schemas
class ProductionOrderMasterBase(BaseModel):
    paper_id: UUID
    quantity: int = Field(default=1, gt=0)
    priority: Priority = Field(default=Priority.NORMAL)

class ProductionOrderMasterCreate(ProductionOrderMasterBase):
    created_by_id: UUID

class ProductionOrderMasterUpdate(BaseModel):
    priority: Optional[Priority] = None
    status: Optional[ProductionOrderStatus] = None

class ProductionOrderMaster(ProductionOrderMasterBase):
    id: UUID
    status: ProductionOrderStatus
    created_by_id: UUID
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Include related data
    paper: Optional[PaperMaster] = None

    class Config:
        from_attributes = True

# ============================================================================
# CUTTING OPTIMIZER SCHEMAS - For cutting optimization
# ============================================================================

class CuttingOptimizationRequest(BaseModel):
    """Request for cutting optimization with order IDs"""
    order_ids: List[UUID] = Field(..., min_items=1)
    include_pending: bool = Field(default=True, description="Include pending orders in optimization")
    interactive: bool = Field(default=False, description="Enable interactive trim decisions")

class CuttingPattern(BaseModel):
    """A single cutting pattern result"""
    rolls: List[Dict[str, Any]] = Field(..., description="Rolls in this pattern")
    trim_left: float = Field(..., ge=0, description="Trim left in inches")
    waste_percentage: float = Field(..., ge=0, le=100, description="Waste percentage")
    paper_spec: Dict[str, Any] = Field(..., description="Paper specification used")

class CuttingOptimizationResult(BaseModel):
    """Result of cutting optimization"""
    jumbo_rolls_used: List[CuttingPattern] = Field(..., description="Cutting patterns generated")
    pending_orders: List[PendingOrderMaster] = Field(default_factory=list, description="Orders that couldn't be fulfilled")
    high_trim_approved: List[Dict[str, Any]] = Field(default_factory=list, description="High trim patterns approved")
    summary: Dict[str, Any] = Field(..., description="Summary statistics")

# ============================================================================
# WORKFLOW SCHEMAS - For workflow operations
# ============================================================================

class WorkflowProcessRequest(BaseModel):
    """Request to process multiple orders through workflow"""
    order_ids: List[UUID] = Field(..., min_items=1)
    auto_approve_high_trim: bool = Field(default=False, description="Auto-approve high trim patterns")

class WorkflowStatus(BaseModel):
    """Current workflow status"""
    orders: Dict[str, int] = Field(..., description="Order counts by status")
    pending_items: Dict[str, int] = Field(..., description="Pending item statistics")
    inventory: Dict[str, int] = Field(..., description="Inventory statistics")
    production: Dict[str, int] = Field(..., description="Production statistics")
    recommendations: List[str] = Field(default_factory=list, description="Workflow recommendations")

# ============================================================================
# RESPONSE SCHEMAS - Common response formats
# ============================================================================

class SuccessResponse(BaseModel):
    """Standard success response"""
    message: str
    data: Optional[Dict[str, Any]] = None

class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None

class PaginatedResponse(BaseModel):
    """Paginated response wrapper"""
    items: List[Any]
    total: int
    page: int
    size: int
    pages: int

# ============================================================================
# LEGACY COMPATIBILITY - For backward compatibility
# ============================================================================

# Keep some old schemas for backward compatibility during transition
class OrderCreate(BaseModel):
    """Legacy order creation - will be deprecated"""
    customer_name: str  # Will map to client lookup/creation
    width_inches: int
    gsm: int
    bf: float
    shade: str
    quantity_rolls: int

class Order(BaseModel):
    """Legacy order response - will be deprecated"""
    id: UUID
    customer_name: str
    width_inches: int
    gsm: int
    bf: float
    shade: str
    quantity_rolls: int
    quantity_fulfilled: int
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True