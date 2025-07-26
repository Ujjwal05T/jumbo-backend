from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator
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

class PaymentType(str, Enum):
    BILL = "bill"
    CASH = "cash"

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

# Order Item Schemas
class OrderItemBase(BaseModel):
    paper_id: UUID
    width_inches: int = Field(..., gt=0)
    quantity_rolls: Optional[int] = Field(None, gt=0)
    quantity_kg: Optional[float] = Field(None, gt=0)
    rate: float = Field(..., gt=0)
    amount: Optional[float] = Field(None, gt=0)
    
    # Note: Auto-calculation is handled in CRUD layer to avoid Pydantic V2 issues

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemUpdate(BaseModel):
    paper_id: Optional[UUID] = None
    width_inches: Optional[int] = Field(None, gt=0)
    quantity_rolls: Optional[int] = Field(None, gt=0)
    quantity_kg: Optional[float] = Field(None, gt=0)
    rate: Optional[float] = Field(None, gt=0)
    amount: Optional[float] = Field(None, gt=0)
    quantity_fulfilled: Optional[int] = Field(None, ge=0)

class OrderItem(OrderItemBase):
    id: UUID
    order_id: UUID
    quantity_fulfilled: int
    created_at: datetime
    updated_at: datetime
    
    # Include related data
    paper: Optional['PaperMaster'] = None

    class Config:
        from_attributes = True

# Order Master Schemas - Updated for multiple order items
class OrderMasterBase(BaseModel):
    client_id: UUID
    priority: Priority = Field(default=Priority.NORMAL)
    payment_type: PaymentType = Field(default=PaymentType.BILL)
    delivery_date: Optional[datetime] = None
    notes: Optional[str] = None

class OrderMasterCreate(OrderMasterBase):
    created_by_id: UUID
    order_items: List[OrderItemCreate] = Field(..., min_items=1, description="List of order items with different papers, widths and quantities")

class OrderMasterUpdate(BaseModel):
    priority: Optional[Priority] = None
    payment_type: Optional[PaymentType] = None
    delivery_date: Optional[datetime] = None
    notes: Optional[str] = None
    status: Optional[OrderStatus] = None

class OrderMaster(OrderMasterBase):
    id: UUID
    status: OrderStatus
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    
    # Include related data
    client: Optional['ClientMaster'] = None
    order_items: List[OrderItem] = Field(default_factory=list)

    class Config:
        from_attributes = True

# Pending Order Master Schemas
class PendingOrderMasterBase(BaseModel):
    order_id: UUID
    order_item_id: UUID
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
    order_item: Optional[OrderItem] = None
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
    inventory_ids: Optional[List[UUID]] = Field(default_factory=list, description="Optional inventory IDs for plan")

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

    @field_validator('cut_pattern', mode='before')
    @classmethod
    def parse_cut_pattern(cls, v):
        """Parse cut_pattern from JSON string if needed"""
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v

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
# CUTTING OPTIMIZER SCHEMAS - NEW FLOW: 3-input/4-output
# ============================================================================

class OptimizerInventoryItem(BaseModel):
    """Individual inventory item for optimization input"""
    id: Optional[str] = None
    width: float = Field(..., gt=0, description="Width in inches")
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    weight: Optional[float] = Field(None, ge=0)
    location: Optional[str] = None

class OptimizerInput(BaseModel):
    """NEW FLOW: Complete input for 3-input optimization"""
    orders: List[Dict[str, Any]] = Field(..., min_items=1, description="New orders to process")
    pending_orders: List[Dict[str, Any]] = Field(default_factory=list, description="Pending orders from previous cycles")
    available_inventory: List[OptimizerInventoryItem] = Field(default_factory=list, description="Available 20-25\" waste rolls")

class CutRollGenerated(BaseModel):
    """Individual cut roll that was generated"""
    width: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    source: str = Field(..., description="'inventory' or 'cutting'")
    inventory_id: Optional[str] = None
    jumbo_number: Optional[int] = None
    trim_left: Optional[float] = None

class PendingOrderOutput(BaseModel):
    """Pending order that couldn't be fulfilled"""
    width: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    reason: str = Field(..., description="Reason why it's pending")

class InventoryRemaining(BaseModel):
    """Inventory item remaining after optimization"""
    width: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    source: str = Field(..., description="'waste', 'unused_inventory'")
    inventory_id: Optional[str] = None
    from_jumbo: Optional[int] = None

class OptimizerOutput(BaseModel):
    """NEW FLOW: Complete output for 4-output optimization"""
    cut_rolls_generated: List[CutRollGenerated] = Field(..., description="Rolls that can be fulfilled")
    jumbo_rolls_needed: int = Field(..., ge=0, description="Number of jumbo rolls to procure")
    pending_orders: List[PendingOrderOutput] = Field(..., description="Orders that cannot be fulfilled")
    inventory_remaining: List[InventoryRemaining] = Field(..., description="20-25\" waste rolls for future use")
    summary: Dict[str, Any] = Field(..., description="Summary statistics")

class CuttingOptimizationRequest(BaseModel):
    """Request for cutting optimization with order IDs - UPDATED for new flow"""
    order_ids: List[UUID] = Field(..., min_items=1)
    include_pending: bool = Field(default=True, description="Include pending orders in optimization")
    include_inventory: bool = Field(default=True, description="Include available waste inventory")
    interactive: bool = Field(default=False, description="Enable interactive trim decisions")

class CreatePlanRequest(BaseModel):
    """Request to create a cutting plan from order IDs"""
    order_ids: List[str] = Field(..., min_items=1, description="List of order IDs to include in plan")
    created_by_id: str = Field(..., description="ID of user creating the plan")
    plan_name: Optional[str] = Field(None, description="Optional name for the plan")

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
    """NEW FLOW: Request to process multiple orders through workflow"""
    order_ids: List[UUID] = Field(..., min_items=1)
    auto_approve_high_trim: bool = Field(default=False, description="Auto-approve high trim patterns")
    skip_inventory_check: bool = Field(default=True, description="NEW FLOW: Skip inventory checking, go directly to planning")

class WorkflowResult(BaseModel):
    """NEW FLOW: Result of workflow processing with 4 outputs"""
    status: str = Field(..., description="Overall workflow status")
    cut_rolls_generated: List[CutRollGenerated] = Field(..., description="Rolls ready for fulfillment")
    jumbo_rolls_needed: int = Field(..., ge=0, description="Jumbo rolls to procure")
    pending_orders_created: List[PendingOrderOutput] = Field(..., description="New pending orders created")
    inventory_created: List[InventoryRemaining] = Field(..., description="Waste inventory created")
    orders_updated: List[str] = Field(..., description="Order IDs that were updated")
    plans_created: List[str] = Field(..., description="Plan IDs that were created")
    production_orders_created: List[str] = Field(..., description="Production order IDs created")

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

