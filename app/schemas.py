from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from enum import Enum
from uuid import UUID

# ============================================================================
# STATUS ENUMS - Validation for status fields
# ============================================================================

class OrderStatus(str, Enum):
    CREATED = "created"
    IN_PROCESS = "in_process"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PaymentType(str, Enum):
    BILL = "bill"
    CASH = "cash"

class OrderItemStatus(str, Enum):
    CREATED = "created"
    IN_PROCESS = "in_process"
    IN_WAREHOUSE = "in_warehouse"
    COMPLETED = "completed"

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
    INCLUDED_IN_PLAN = "included_in_plan"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"

class RollType(str, Enum):
    JUMBO = "jumbo"
    ROLL_118 = "118"
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
    SYSTEM = "system"

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
    gst_number: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    status: ClientStatus = Field(default=ClientStatus.ACTIVE)

class ClientMasterCreate(ClientMasterBase):
    created_by_id: UUID

class ClientMasterUpdate(BaseModel):
    company_name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    gst_number: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    status: Optional[ClientStatus] = None

class ClientMaster(ClientMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable client ID (e.g., CL-001)")
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
    password: Optional[str] = Field(None, min_length=6)  # Optional password for updates
    role: Optional[UserRole] = None
    contact: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=100)
    status: Optional[UserStatus] = None

class UserMaster(UserMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable user ID (e.g., USR-001)")
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
    frontend_id: Optional[str] = Field(None, description="Human-readable paper ID (e.g., PAP-001)")
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
    width_inches: float = Field(..., gt=0)
    quantity_rolls: Optional[int] = Field(None, gt=0)
    quantity_kg: Optional[float] = Field(None, gt=0)
    rate: float = Field(..., gt=0)
    amount: Optional[float] = Field(None, gt=0)
    
    # Note: Auto-calculation is handled in CRUD layer to avoid Pydantic V2 issues

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemUpdate(BaseModel):
    paper_id: Optional[UUID] = None
    width_inches: Optional[float] = Field(None, gt=0)
    quantity_rolls: Optional[int] = Field(None, gt=0)
    quantity_kg: Optional[float] = Field(None, gt=0)
    rate: Optional[float] = Field(None, gt=0)
    amount: Optional[float] = Field(None, gt=0)
    quantity_fulfilled: Optional[int] = Field(None, ge=0)
    quantity_in_pending: Optional[int] = Field(None, ge=0)

class OrderItem(OrderItemBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable order item ID (e.g., ORI-001)")
    order_id: UUID
    quantity_fulfilled: int
    quantity_in_pending: int
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

class OrderMasterCreate(OrderMasterBase):
    created_by_id: UUID
    order_items: List[OrderItemCreate] = Field(..., min_items=1, description="List of order items with different papers, widths and quantities")

class OrderMasterUpdate(BaseModel):
    priority: Optional[Priority] = None
    payment_type: Optional[PaymentType] = None
    delivery_date: Optional[datetime] = None
    status: Optional[OrderStatus] = None

class OrderMasterUpdateWithItems(BaseModel):
    priority: Optional[Priority] = None
    payment_type: Optional[PaymentType] = None
    delivery_date: Optional[datetime] = None
    order_items: List[OrderItemCreate] = Field(..., min_items=1, description="Updated list of order items")

class OrderMaster(OrderMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable order ID (e.g., ORD-2025-001)")
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
    width_inches: float = Field(..., gt=0)
    quantity_pending: int = Field(..., gt=0)
    reason: str = Field(..., max_length=100)

class PendingOrderMasterCreate(PendingOrderMasterBase):
    pass

class PendingOrderMasterUpdate(BaseModel):
    status: Optional[PendingOrderStatus] = None
    production_order_id: Optional[UUID] = None

class PendingOrderMaster(PendingOrderMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable pending order ID (e.g., POM-001)")
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

# Pending Order Item Schemas - New model for service compatibility
class PendingOrderItemBase(BaseModel):
    original_order_id: UUID
    width_inches: float = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    quantity_pending: int = Field(..., gt=0)
    reason: str = Field(default="no_suitable_jumbo", max_length=100)

class PendingOrderItemCreate(PendingOrderItemBase):
    created_by_id: Optional[UUID] = None

class PendingOrderItemUpdate(BaseModel):
    status: Optional[PendingOrderStatus] = None
    production_order_id: Optional[UUID] = None
    resolved_at: Optional[datetime] = None

class PendingOrderItem(PendingOrderItemBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable pending order item ID (e.g., POI-001)")
    status: PendingOrderStatus
    production_order_id: Optional[UUID] = None
    created_by_id: Optional[UUID] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    quantity_fulfilled: Optional[int] = Field(default=0, description="Number of items fulfilled")
    
    # NEW: Plan generation tracking fields
    included_in_plan_generation: Optional[bool] = Field(default=False, description="Was this pending order included in plan generation?")
    generated_cut_rolls_count: Optional[int] = Field(default=0, description="Number of cut rolls generated from this pending order")
    plan_generation_date: Optional[datetime] = Field(None, description="When was this included in plan generation?")
    
    # Include related data
    original_order: Optional[OrderMaster] = None
    created_by: Optional[UserMaster] = None

    class Config:
        from_attributes = True

# Inventory Master Schemas
class InventoryMasterBase(BaseModel):
    paper_id: UUID
    width_inches: float = Field(..., gt=0)
    weight_kg: float = Field(..., gt=0)
    roll_type: RollType = Field(..., description="Roll type: jumbo, 118, or cut")
    location: Optional[str] = Field(None, max_length=100)
    qr_code: Optional[str] = Field(None, max_length=255)
    barcode_id: Optional[str] = Field(None, description="Human-readable barcode ID")
    production_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Jumbo roll hierarchy fields
    parent_jumbo_id: Optional[UUID] = Field(None, description="Parent jumbo roll ID")
    parent_118_roll_id: Optional[UUID] = Field(None, description="Parent 118 inch roll ID")
    roll_sequence: Optional[int] = Field(None, description="Position within jumbo (1, 2, 3)")
    individual_roll_number: Optional[int] = Field(None, description="From optimization algorithm")

class InventoryMasterCreate(InventoryMasterBase):
    created_by_id: UUID

class InventoryMasterUpdate(BaseModel):
    location: Optional[str] = Field(None, max_length=100)
    status: Optional[InventoryStatus] = None
    allocated_to_order_id: Optional[UUID] = None

class InventoryMaster(InventoryMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable inventory ID (e.g., INV-001)")
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
    pending_orders: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Pending orders from algorithm")

class PlanMasterUpdate(BaseModel):
    status: Optional[PlanStatus] = None
    actual_waste_percentage: Optional[float] = Field(None, ge=0, le=100)

class PlanMaster(PlanMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable plan ID (e.g., PLN-2025-001)")
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
    frontend_id: Optional[str] = Field(None, description="Human-readable production order ID (e.g., PRO-001)")
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
    jumbo_roll_width: int = Field(default=118, ge=50, le=300, description="Jumbo roll width in inches")
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


# ============================================================================
# ADDITIONAL SCHEMAS FOR NEW ENDPOINTS
# ============================================================================

class UserLogin(BaseModel):
    """Schema for user login request"""
    username: str
    password: str

class CuttingPlanRequestItem(BaseModel):
    """Individual item in cutting plan request"""
    width: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str
    min_length: int = Field(default=1600, gt=0)

class CuttingPlanRequest(BaseModel):
    """Schema for cutting plan generation request"""
    order_requirements: List[CuttingPlanRequestItem]
    pending_orders: Optional[List[Dict[str, Any]]] = None
    available_inventory: Optional[List[Dict[str, Any]]] = None

class CuttingPlanWithSelectionRequest(CuttingPlanRequest):
    """Schema for cutting plan with selection criteria"""
    selection_criteria: Optional[Dict[str, Any]] = None

class QRWeightUpdate(BaseModel):
    """Schema for updating weight via QR code - status automatically set to 'available'"""
    qr_code: str
    weight_kg: float = Field(..., gt=0)
    location: Optional[str] = None

class BarcodeWeightUpdate(BaseModel):
    """Schema for updating weight via barcode - status automatically set to 'available'"""
    barcode_id: str
    weight_kg: float = Field(..., gt=0)
    location: Optional[str] = None

class QRGenerateRequest(BaseModel):
    """Schema for generating QR code"""
    inventory_id: Optional[UUID] = None

class CutRollSelection(BaseModel):
    """Individual cut roll selection"""
    paper_id: UUID
    width_inches: float
    qr_code: Optional[str] = None
    cutting_pattern: Optional[str] = None

class CutRollSelectionRequest(BaseModel):
    """Schema for selecting cut rolls for production"""
    plan_id: Optional[UUID] = None
    selected_rolls: List[CutRollSelection]
    created_by_id: UUID

class PlanStatusUpdate(BaseModel):
    """Schema for updating plan status"""
    status: str
    actual_waste_percentage: Optional[float] = None

class PlanInventoryLinkRequest(BaseModel):
    """Schema for linking inventory to plans"""
    inventory_ids: List[UUID]

class InventoryStatusUpdate(BaseModel):
    """Schema for updating inventory status"""
    new_status: str
    location: Optional[str] = None

# ============================================================================
# DISPATCH SCHEMAS
# ============================================================================

class DispatchFormData(BaseModel):
    """Schema for dispatch form data"""
    vehicle_number: str = Field(..., max_length=50)
    driver_name: str = Field(..., max_length=255)
    driver_mobile: str = Field(..., max_length=20)
    payment_type: str = Field(default="bill")  # bill/cash
    dispatch_date: datetime = Field(default_factory=datetime.utcnow)
    dispatch_number: str = Field(..., max_length=100)
    reference_number: Optional[str] = Field(None, max_length=100)
    client_id: UUID
    primary_order_id: Optional[UUID] = None
    order_date: Optional[datetime] = None
    inventory_ids: List[UUID] = Field(..., min_items=1)
    created_by_id: UUID

class DispatchRecordCreate(BaseModel):
    """Schema for creating dispatch record"""
    vehicle_number: str
    driver_name: str
    driver_mobile: str
    payment_type: str
    dispatch_date: datetime
    dispatch_number: str
    reference_number: Optional[str] = None
    client_id: UUID
    primary_order_id: Optional[UUID] = None
    order_date: Optional[datetime] = None
    total_items: int
    total_weight_kg: float
    created_by_id: UUID

class DispatchItem(BaseModel):
    """Schema for dispatch item"""
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable dispatch item ID (e.g., DIT-001)")
    dispatch_record_id: UUID
    inventory_id: UUID
    qr_code: str
    width_inches: float
    weight_kg: float
    paper_spec: str
    status: str
    dispatched_at: datetime
    
    class Config:
        from_attributes = True

class DispatchRecord(BaseModel):
    """Schema for dispatch record with items"""
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable dispatch record ID (e.g., DSP-001)")
    vehicle_number: str
    driver_name: str
    driver_mobile: str
    payment_type: str
    dispatch_date: datetime
    dispatch_number: str
    reference_number: Optional[str] = None
    client_id: UUID
    primary_order_id: Optional[UUID] = None
    order_date: Optional[datetime] = None
    status: str
    total_items: int
    total_weight_kg: float
    created_by_id: UUID
    created_at: datetime
    delivered_at: Optional[datetime] = None
    
    # Include related data
    client: Optional[ClientMaster] = None
    primary_order: Optional[OrderMaster] = None
    created_by: Optional[UserMaster] = None
    dispatch_items: List[DispatchItem] = Field(default_factory=list)
    
    class Config:
        from_attributes = True

# ============================================================================
# PRODUCTION START SCHEMAS - NEW FLOW
# ============================================================================

class SelectedCutRoll(BaseModel):
    """Individual cut roll selected for production"""
    paper_id: str = Field(..., description="Paper ID for this cut roll")
    width_inches: float = Field(..., gt=0, description="Width in inches")
    qr_code: str = Field(..., description="QR code for tracking")
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    individual_roll_number: Optional[int] = Field(None, description="Roll number within jumbo")
    trim_left: Optional[float] = Field(None, ge=0, description="Trim left in inches")
    order_id: Optional[str] = Field(None, description="Source order ID")
    # CRITICAL: Add source tracking fields for pending order resolution
    source_type: Optional[str] = Field(None, description="Source type: 'regular_order' or 'pending_order'")
    source_pending_id: Optional[str] = Field(None, description="ID of source pending order if applicable")

class StartProductionRequest(BaseModel):
    """Request to start production with comprehensive roll handling"""
    selected_cut_rolls: List[SelectedCutRoll] = Field(..., min_items=1, description="Cut rolls selected for production")
    all_available_cuts: List[SelectedCutRoll] = Field(..., description="All cuts that were available for selection")
    created_by_id: str = Field(..., description="ID of user starting production")
    jumbo_roll_width: int = Field(default=118, ge=50, le=300, description="Dynamic jumbo roll width in inches")

class ProductionStartSummary(BaseModel):
    """Summary of production start operation"""
    orders_updated: int = Field(..., ge=0)
    order_items_updated: int = Field(..., ge=0)
    pending_orders_resolved: int = Field(..., ge=0, description="Number of pending orders resolved (PHASE 1 -> included_in_plan)")
    inventory_created: int = Field(..., ge=0)
    pending_orders_created_phase2: int = Field(default=0, ge=0, description="Number of PHASE 2 pending orders created from unselected cuts")
    jumbo_rolls_created: int = Field(default=0, ge=0, description="Number of virtual jumbo rolls created")
    intermediate_118_rolls_created: int = Field(default=0, ge=0, description="Number of intermediate 118\" rolls created")

class InventoryDetail(BaseModel):
    """Inventory item details for production response"""
    id: str
    barcode_id: str
    qr_code: str
    width_inches: float
    paper_id: str
    status: str
    created_at: Optional[str] = None

class StartProductionResponse(BaseModel):
    """Response from start production operation"""
    plan_id: str
    status: str
    executed_at: Optional[str] = None
    summary: ProductionStartSummary
    details: Dict[str, List[str]]
    created_inventory_details: List[InventoryDetail] = Field(default_factory=list)
    message: str

